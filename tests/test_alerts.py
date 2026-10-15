"""Tests for the alert channels and the DOWN/UP state machine."""

from __future__ import annotations

from src.alerts import (
    AlertManager,
    EmailChannel,
    TelegramChannel,
    build_channels,
)
from src.config import AlertConfig
from src.pinger import PingResult


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
