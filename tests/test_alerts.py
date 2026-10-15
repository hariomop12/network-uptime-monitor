"""Tests for the alert channels and the DOWN/UP state machine."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.alerts import (
    AlertManager,
    EmailChannel,
    TelegramChannel,
    build_channels,
)
from src.config import AlertConfig
from src.pinger import PingResult
from src.state import HostState, StateStore


class RecordingChannel:
    """Captures the messages that would have been sent."""

    def __init__(self):
        self.messages = []

    def send(self, subject, message):
        self.messages.append((subject, message))


def result(name="web", alive=True, loss=0.0, error=None):
    return PingResult(
        name=name,
        address="1.1.1.1",
        is_alive=alive,
        packet_loss=loss,
        avg_rtt=5.0,
        error=error,
    )


def test_one_down_and_one_recovery_alert():
    channel = RecordingChannel()
    manager = AlertManager([channel])

    manager.evaluate(result(alive=True), True)
    manager.evaluate(result(alive=True), True)
    manager.evaluate(result(alive=False, loss=100.0), False)
    manager.evaluate(result(alive=False, loss=100.0), False)  # no repeat
    manager.evaluate(result(alive=True), True)

    subjects = [subject for subject, _ in channel.messages]
    assert subjects == ["[DOWN] web (1.1.1.1)", "[RECOVERED] web (1.1.1.1)"]


def test_recovery_alert_can_be_disabled():
    channel = RecordingChannel()
    manager = AlertManager([channel])

    manager.evaluate(result(alive=True), True)
    manager.evaluate(result(alive=False), False)
    manager.evaluate(result(alive=True), True, alert_recovery=False)

    assert [s for s, _ in channel.messages] == ["[DOWN] web (1.1.1.1)"]


def test_already_down_at_startup_alerts_once():
    channel = RecordingChannel()
    manager = AlertManager([channel])

    manager.evaluate(result(name="db", alive=False), False)

    assert len(channel.messages) == 1
    assert channel.messages[0][0].startswith("[DOWN]")


def test_a_failing_channel_does_not_block_others():
    class Broken:
        def send(self, subject, message):
            raise RuntimeError("channel down")

    healthy = RecordingChannel()
    manager = AlertManager([Broken(), healthy])

    manager.evaluate(result(alive=True), True)
    manager.evaluate(result(alive=False), False)

    assert len(healthy.messages) == 1


def test_build_channels_skips_incomplete_telegram():
    assert build_channels(AlertConfig(telegram_enabled=True)) == []

    channels = build_channels(
        AlertConfig(
            telegram_enabled=True,
            telegram_bot_token="token",
            telegram_chat_id="chat",
        )
    )
    assert len(channels) == 1
    assert isinstance(channels[0], TelegramChannel)


def test_build_channels_skips_incomplete_email():
    assert build_channels(AlertConfig(email_enabled=True)) == []

    channels = build_channels(
        AlertConfig(
            email_enabled=True,
            smtp_host="smtp.test",
            to_addrs=["a@b.com"],
            smtp_user="user",
        )
    )
    assert len(channels) == 1
    assert isinstance(channels[0], EmailChannel)


def test_no_channels_does_not_crash():
    manager = AlertManager([])
    manager.evaluate(result(alive=True), True)
    manager.evaluate(result(alive=False), False)  # just logs a warning


def test_state_persists_across_restart(tmp_path):
    path = tmp_path / "state.json"

    first = RecordingChannel()
    manager = AlertManager([first], state_store=StateStore(path))
    manager.evaluate(result(alive=True), True)
    manager.evaluate(result(alive=False, loss=100.0), False)
    assert [s for s, _ in first.messages] == ["[DOWN] web (1.1.1.1)"]

    # Simulate a restart: brand-new manager + channel, same state file.
    second = RecordingChannel()
    restarted = AlertManager([second], state_store=StateStore(path))
    restarted.evaluate(result(alive=False, loss=100.0), False)  # still down
    assert second.messages == []                                # no repeat

    restarted.evaluate(result(alive=True), True)                # recovers
    assert [s for s, _ in second.messages] == ["[RECOVERED] web (1.1.1.1)"]


def test_renotify_fires_after_cooldown(tmp_path):
    store = StateStore(tmp_path / "state.json")
    old = (datetime.now() - timedelta(minutes=31)).isoformat(timespec="seconds")
    store.set("web", HostState(is_alive=False, since=old, last_alert_at=old))

    channel = RecordingChannel()
    manager = AlertManager([channel], state_store=store)

    manager.evaluate(result(alive=False), False, renotify_minutes=30)
    assert [s for s, _ in channel.messages] == ["[STILL DOWN] web (1.1.1.1)"]


def test_renotify_silent_before_cooldown(tmp_path):
    store = StateStore(tmp_path / "state.json")
    recent = datetime.now().isoformat(timespec="seconds")
    store.set("web", HostState(is_alive=False, since=recent, last_alert_at=recent))

    channel = RecordingChannel()
    manager = AlertManager([channel], state_store=store)

    manager.evaluate(result(alive=False), False, renotify_minutes=30)
    assert channel.messages == []


def test_renotify_disabled_by_default(tmp_path):
    store = StateStore(tmp_path / "state.json")
    old = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    store.set("web", HostState(is_alive=False, since=old, last_alert_at=old))

    channel = RecordingChannel()
    manager = AlertManager([channel], state_store=store)

    manager.evaluate(result(alive=False), False)  # renotify_minutes=0
    assert channel.messages == []
