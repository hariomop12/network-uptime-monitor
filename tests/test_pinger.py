"""Tests for the pinger wrapper (icmplib is mocked - no real network needed)."""

from __future__ import annotations

import pytest
from icmplib.exceptions import ICMPLibError, SocketPermissionError

import src.pinger as pinger
from src.pinger import ping_host


class FakeReply:
    is_alive = True
    packets_sent = 3
    packets_received = 3
    packet_loss = 0.0
    min_rtt = 1.0
    avg_rtt = 2.0
    max_rtt = 3.0
    jitter = 0.5


def test_successful_ping(monkeypatch):
    monkeypatch.setattr(pinger, "ping", lambda **kwargs: FakeReply())

    result = ping_host("web", "1.1.1.1", count=3, timeout=1)

    assert result.is_alive is True
    assert result.avg_rtt == 2.0
    assert result.packet_loss == 0.0
    assert result.error is None


def test_packet_loss_is_scaled_to_percent(monkeypatch):
    class Down(FakeReply):
        is_alive = False
        packets_received = 0
        packet_loss = 1.0  # icmplib ratio -> 100 %

    monkeypatch.setattr(pinger, "ping", lambda **kwargs: Down())

    result = ping_host("web", "1.1.1.1")

    assert result.is_alive is False
    assert result.packet_loss == 100.0


def test_permission_error_falls_back_to_unprivileged(monkeypatch):
    calls = []

    def fake_ping(**kwargs):
        calls.append(kwargs["privileged"])
        if kwargs["privileged"]:
            raise SocketPermissionError("not root")
        return FakeReply()

    monkeypatch.setattr(pinger, "ping", fake_ping)

    result = ping_host("web", "1.1.1.1")

    assert calls == [True, False]
    assert result.is_alive is True


def test_icmp_error_is_reported_not_raised(monkeypatch):
    def boom(**kwargs):
        raise ICMPLibError("kaput")

    monkeypatch.setattr(pinger, "ping", boom)

    result = ping_host("web", "1.1.1.1")

    assert result.is_alive is False
    assert result.error is not None
    assert "ICMPLibError" in result.error
