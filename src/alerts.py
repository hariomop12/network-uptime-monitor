"""Alert channels (Telegram / Email) and DOWN->UP state tracking.

The :class:`AlertManager` remembers the last known state of every host so that
a single outage produces exactly one DOWN alert and (optionally) one RECOVERY
alert - instead of a message on every single failed ping.
"""

from __future__ import annotations

import html
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import requests

from .config import AlertConfig
from .pinger import PingResult

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
    """Fan out alerts to every channel, but only on a state *change*."""

    def __init__(self, channels: list[Channel], logger: logging.Logger | None = None):
        self.channels = channels
        self.log = logger or log
        self._states: dict[str, bool] = {}

    def evaluate(
        self,
        result: PingResult,
        is_alive: bool,
        alert_recovery: bool = True,
    ) -> None:
        """Compare the new state with the previous one and alert if it changed.

        A host that is unknown at startup is treated as previously UP, so a
        host that is already down when the monitor starts still raises a
        DOWN alert.
        """
        previous = self._states.get(result.name, True)
        self._states[result.name] = is_alive

        if previous and not is_alive:
            self._dispatch("DOWN", result)
        elif not previous and is_alive and alert_recovery:
            self._dispatch("RECOVERED", result)

    def _dispatch(self, event: str, result: PingResult) -> None:
        subject = f"[{event}] {result.name} ({result.address})"
        message = "\n".join(
            [
                f"Host: {result.name}",
                f"Address: {result.address}",
                f"Status: {'UP' if result.is_alive else 'DOWN'}",
                f"Packet loss: {result.packet_loss:.1f}%",
                f"Latency: {result.avg_rtt:.1f} ms",
                *([f"Note: {result.error}"] if result.error else []),
            ]
        )

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
