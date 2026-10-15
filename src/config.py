"""Load and validate the monitor configuration.

Reads ``config.yaml`` (what to monitor / how) and merges secrets from ``.env``
(Telegram token, SMTP credentials). Returns plain dataclasses so the rest of
the code never has to touch raw dicts or environment variables directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .checks import KINDS


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


# --------------------------------------------------------------------------- #
#  Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class Host:
    """A single host to monitor, with its resolved check settings."""

    name: str
    address: str
    kind: str = "ping"            # ping | tcp | http
    port: int | None = None       # tcp / http
    url: str | None = None        # http (overrides address/port)
    expect_status: int | None = None  # http (default: any 2xx/3xx)
    interval: int = 60
    timeout: float = 2
    count: int = 3
    retries: int = 2
    alert_recovery: bool = True
    renotify_minutes: int = 0  # 0 = disabled; else re-alert while a host stays DOWN


@dataclass
class LoggingConfig:
    log_dir: str = "logs"
    log_file: str = "monitor.log"
    log_level: str = "INFO"
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 5
    metrics_csv: str = "metrics.csv"


@dataclass
class StateConfig:
    enabled: bool = True
    file: str = "logs/state.json"


@dataclass
class AlertConfig:
    telegram_enabled: bool = False
    email_enabled: bool = False
    # Telegram (secrets come from .env)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Email / SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    use_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    from_addr: str = ""
    to_addrs: list[str] = field(default_factory=list)


@dataclass
class Config:
    hosts: list[Host]
    logging: LoggingConfig
    alerts: AlertConfig
    state: StateConfig
    base_dir: Path


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
def load_config(path: str | os.PathLike = "config.yaml") -> Config:
    """Load ``config.yaml`` + ``.env`` and return a validated :class:`Config`."""
    load_dotenv()  # pull .env values into the environment, if present

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    defaults = raw.get("defaults") or {}
    host_entries = raw.get("hosts") or []
    if not host_entries:
        raise ConfigError("No hosts defined under 'hosts:' in config.yaml")

    hosts = [_build_host(entry, defaults) for entry in host_entries]

    return Config(
        hosts=hosts,
        logging=_build_logging(raw.get("logging") or {}),
        alerts=_build_alerts(raw.get("alerts") or {}),
        state=_build_state(raw.get("state") or {}),
        base_dir=config_path.resolve().parent,
    )


# --------------------------------------------------------------------------- #
#  Internal builders
# --------------------------------------------------------------------------- #
def _build_host(entry: dict[str, Any], defaults: dict[str, Any]) -> Host:
    if not isinstance(entry, dict) or "address" not in entry:
        raise ConfigError(f"Each host needs at least an 'address': {entry!r}")

    merged = {**defaults, **entry}  # per-host values override defaults

    kind = str(merged.get("type", merged.get("kind", "ping"))).lower()
    if kind not in KINDS:
        raise ConfigError(
            f"Unknown check type {kind!r} for host "
            f"{merged.get('name') or merged.get('address')!r} (use one of {KINDS})"
        )

    port = merged.get("port")
    expect_status = merged.get("expect_status")
    url = merged.get("url")

    return Host(
        name=str(merged.get("name") or merged["address"]),
        address=str(merged["address"]),
        kind=kind,
        port=int(port) if port is not None else None,
        url=str(url) if url else None,
        expect_status=int(expect_status) if expect_status is not None else None,
        interval=int(merged.get("interval", 60)),
        timeout=float(merged.get("timeout", 2)),
        count=int(merged.get("count", 3)),
        retries=int(merged.get("retries", 2)),
        alert_recovery=bool(merged.get("alert_recovery", True)),
        renotify_minutes=int(merged.get("renotify_minutes", 0)),
    )


def _build_logging(raw: dict[str, Any]) -> LoggingConfig:
    return LoggingConfig(
        log_dir=str(raw.get("log_dir", "logs")),
        log_file=str(raw.get("log_file", "monitor.log")),
        log_level=str(raw.get("log_level", "INFO")),
        max_bytes=int(raw.get("max_bytes", 5 * 1024 * 1024)),
        backup_count=int(raw.get("backup_count", 5)),
        metrics_csv=str(raw.get("metrics_csv", "metrics.csv")),
    )


def _build_state(raw: dict[str, Any]) -> StateConfig:
    return StateConfig(
        enabled=bool(raw.get("enabled", True)),
        file=str(raw.get("file", "logs/state.json")),
    )


def _build_alerts(raw: dict[str, Any]) -> AlertConfig:
    email = raw.get("email") or {}
    telegram = raw.get("telegram") or {}

    to_addrs = email.get("to_addrs") or []
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    if not to_addrs and os.getenv("ALERT_EMAIL_TO"):
        to_addrs = [os.environ["ALERT_EMAIL_TO"]]

    return AlertConfig(
        telegram_enabled=bool(telegram.get("enabled", False)),
        email_enabled=bool(email.get("enabled", False)),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        smtp_host=email.get("smtp_host") or os.getenv("SMTP_HOST", ""),
        smtp_port=int(email.get("smtp_port") or os.getenv("SMTP_PORT", 587)),
        use_tls=bool(email.get("use_tls", True)),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        from_addr=email.get("from_addr") or os.getenv("SMTP_USER", ""),
        to_addrs=[str(addr) for addr in to_addrs],
    )
