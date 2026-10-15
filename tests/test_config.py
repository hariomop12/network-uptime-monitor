"""Tests for configuration loading and merging."""

from __future__ import annotations

import textwrap

import pytest

from src.config import ConfigError, load_config

SAMPLE = textwrap.dedent(
    """
    defaults:
      interval: 30
      timeout: 1
      count: 2
      retries: 3
      alert_recovery: false

    logging:
      log_dir: mylogs
      log_level: DEBUG

    alerts:
      telegram:
        enabled: true
      email:
        enabled: true
        smtp_host: smtp.test
        to_addrs:
          - a@b.com

    hosts:
      - name: Host A
        address: 1.1.1.1
      - address: 2.2.2.2
        interval: 5
    """
)


def _write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_hosts_inherit_defaults_and_override(tmp_path):
    cfg = load_config(_write(tmp_path, SAMPLE))

    assert len(cfg.hosts) == 2

    first = cfg.hosts[0]
    assert first.name == "Host A"
    assert first.interval == 30
    assert first.retries == 3
    assert first.alert_recovery is False

    second = cfg.hosts[1]
    assert second.name == "2.2.2.2"  # name falls back to the address
    assert second.interval == 5      # per-host override wins


def test_logging_and_alert_config(tmp_path):
    cfg = load_config(_write(tmp_path, SAMPLE))

    assert cfg.logging.log_dir == "mylogs"
    assert cfg.logging.log_level == "DEBUG"
    assert cfg.alerts.telegram_enabled is True
    assert cfg.alerts.email_enabled is True
    assert cfg.alerts.smtp_host == "smtp.test"
    assert cfg.alerts.to_addrs == ["a@b.com"]


def test_secrets_are_read_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("SMTP_USER", "me@test")

    cfg = load_config(_write(tmp_path, SAMPLE))

    assert cfg.alerts.telegram_bot_token == "TOKEN123"
    assert cfg.alerts.telegram_chat_id == "42"
    assert cfg.alerts.smtp_user == "me@test"
    assert cfg.alerts.from_addr == "me@test"  # falls back to SMTP_USER


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_no_hosts_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "hosts: []"))


def test_host_without_address_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "hosts:\n  - name: broken\n"))
