"""Alert channels (Telegram / Email) and DOWN->UP state tracking.

The :class:`AlertManager` remembers the last known state of every host so that
a single outage produces exactly one DOWN alert and (optionally) one RECOVERY
alert - instead of a message on every single failed ping.
"""

from __future__ import annotations

import html
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol

import requests

from .checks import CheckResult
from .config import AlertConfig
from .state import HostState, StateStore

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Channels
# --------------------------------------------------------------------------- #
class Channel(Protocol):
    """Anything that can deliver an alert message."""

    def send(self, subject: str, message: str) -> None: ...


class TelegramChannel:
    """Send alerts through the Telegram Bot API."""

    def __init__(self, token: str, chat_id: str, timeout: float = 10):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, subject: str, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        text = f"<b>{html.escape(subject)}</b>\n\n{html.escape(message)}"
        response = requests.post(
            url,
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
            timeout=self.timeout,
        )
        response.raise_for_status()


class EmailChannel:
    """Send alerts through an SMTP server."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        use_tls: bool = True,
        timeout: float = 15,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls
        self.timeout = timeout

    def send(self, subject: str, message: str) -> None:
        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = self.from_addr
        email["To"] = ", ".join(self.to_addrs)
        email.set_content(message)

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(email)


# --------------------------------------------------------------------------- #
#  Manager
# --------------------------------------------------------------------------- #
class AlertManager:
    """Fan out alerts to every channel, but only on meaningful state changes.

    * one **DOWN** alert per outage
    * one **RECOVERED** alert when the host returns (unless disabled)
    * optional **re-notify** while a host stays down (``renotify_minutes``)

    State is kept in a :class:`~src.state.StateStore` when one is supplied, so a
    restart does **not** re-send alerts for hosts that were already down.
    """

    def __init__(
        self,
        channels: list[Channel],
        logger: logging.Logger | None = None,
        state_store: StateStore | None = None,
    ):
        self.channels = channels
        self.log = logger or log
        self.state = state_store
        self._memory: dict[str, HostState] = {}  # fallback when no store is given

    # -- state helpers ---------------------------------------------------- #
    def _get_record(self, name: str) -> HostState | None:
        if self.state is not None:
            return self.state.get(name)
        return self._memory.get(name)

    def _put_record(self, name: str, record: HostState) -> None:
        if self.state is not None:
            self.state.set(name, record)
            self.state.save()
        else:
            self._memory[name] = record

    @staticmethod
    def _cooldown_elapsed(last_alert_at: str, now: datetime, minutes: int) -> bool:
        if not last_alert_at:
            return True
        try:
            last = datetime.fromisoformat(last_alert_at)
        except ValueError:
            return True
        return (now - last).total_seconds() >= minutes * 60

    # -- main entry ------------------------------------------------------- #
    def evaluate(
        self,
        result: CheckResult,
        is_alive: bool,
        alert_recovery: bool = True,
        renotify_minutes: int = 0,
    ) -> None:
        """Update the host's state and alert on DOWN / RECOVERED / re-notify.

        A host that is unknown is assumed to have been UP, so a host that is
        already down on the very first check still raises a DOWN alert.
        """
        now = datetime.now()
        stamp = now.isoformat(timespec="seconds")

        record = self._get_record(result.name)
        previous_alive = record.is_alive if record else True
        if record is None:
            record = HostState(is_alive=is_alive, since=stamp)

        if record.is_alive != is_alive:
            record.is_alive = is_alive
            record.since = stamp

        if previous_alive and not is_alive:
            self._dispatch("DOWN", result)
            record.last_alert_at = stamp
        elif not previous_alive and is_alive:
            if alert_recovery:
                self._dispatch("RECOVERED", result)
                record.last_alert_at = stamp
        elif (
            not previous_alive
            and not is_alive
            and renotify_minutes > 0
            and self._cooldown_elapsed(record.last_alert_at, now, renotify_minutes)
        ):
            self._dispatch("STILL DOWN", result)
            record.last_alert_at = stamp

        self._put_record(result.name, record)

    def _dispatch(self, event: str, result: CheckResult) -> None:
        subject = f"[{event}] {result.name} ({result.address})"

        lines = [
            f"Host: {result.name}",
            f"Address: {result.address}",
            f"Check: {result.kind}",
            f"Status: {'UP' if result.is_alive else 'DOWN'}",
            f"Latency: {result.latency_ms:.1f} ms",
        ]
        if result.kind == "ping":
            lines.append(f"Packet loss: {result.packet_loss:.1f}%")
        if result.detail:
            lines.append(f"Detail: {result.detail}")
        if result.error:
            lines.append(f"Note: {result.error}")
        message = "\n".join(lines)

        if not self.channels:
            self.log.warning("%s alert for %s (no channels configured)", event, result.name)
            return

        self.log.info("Sending %s alert for %s", event, result.name)
        for channel in self.channels:
            try:
                channel.send(subject, message)
            except Exception as exc:  # noqa: BLE001 - one channel must not block others
                self.log.error(
                    "Alert channel %s failed: %s", type(channel).__name__, exc
                )


# --------------------------------------------------------------------------- #
#  Factory
# --------------------------------------------------------------------------- #
def build_channels(
    config: AlertConfig,
    logger: logging.Logger | None = None,
) -> list[Channel]:
    """Create the list of channels that are enabled *and* fully configured."""
    logger = logger or log
    channels: list[Channel] = []

    if config.telegram_enabled:
        if config.telegram_bot_token and config.telegram_chat_id:
            channels.append(
                TelegramChannel(config.telegram_bot_token, config.telegram_chat_id)
            )
        else:
            logger.warning(
                "Telegram is enabled but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
                "are missing in .env - skipping Telegram."
            )

    if config.email_enabled:
        if config.smtp_host and config.to_addrs:
            channels.append(
                EmailChannel(
                    host=config.smtp_host,
                    port=config.smtp_port,
                    user=config.smtp_user,
                    password=config.smtp_password,
                    from_addr=config.from_addr,
                    to_addrs=config.to_addrs,
                    use_tls=config.use_tls,
                )
            )
        else:
            logger.warning(
                "Email is enabled but SMTP host / recipients are missing - "
                "skipping Email."
            )

    return channels
