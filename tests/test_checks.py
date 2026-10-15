"""Tests for the host checks (network is mocked - nothing real is contacted)."""

from __future__ import annotations

from types import SimpleNamespace

from icmplib.exceptions import ICMPLibError, SocketPermissionError

import src.checks as checks
from src.checks import CheckResult, run_check


class FakeReply:
    is_alive = True
    packets_sent = 3
    packets_received = 3
    packet_loss = 0.0
    min_rtt = 1.0
    avg_rtt = 2.0
    max_rtt = 3.0
    jitter = 0.5


def ping_host(name="web", address="1.1.1.1"):
    return SimpleNamespace(name=name, address=address, kind="ping", count=3, timeout=1)


# --------------------------------------------------------------------------- #
#  ping
# --------------------------------------------------------------------------- #
def test_successful_ping(monkeypatch):
    monkeypatch.setattr(checks, "ping", lambda **kwargs: FakeReply())

    result = run_check(ping_host())

    assert result.kind == "ping"
    assert result.is_alive is True
    assert result.latency_ms == 2.0
    assert result.packet_loss == 0.0
    assert result.error is None


def test_packet_loss_is_scaled_to_percent(monkeypatch):
    class Down(FakeReply):
        is_alive = False
        packets_received = 0
        packet_loss = 1.0  # icmplib ratio -> 100 %

    monkeypatch.setattr(checks, "ping", lambda **kwargs: Down())

    result = run_check(ping_host())
    assert result.is_alive is False
    assert result.packet_loss == 100.0


def test_permission_error_falls_back_to_unprivileged(monkeypatch):
    calls = []

    def fake_ping(**kwargs):
        calls.append(kwargs["privileged"])
        if kwargs["privileged"]:
            raise SocketPermissionError("not root")
        return FakeReply()

    monkeypatch.setattr(checks, "ping", fake_ping)

    result = run_check(ping_host())
    assert calls == [True, False]
    assert result.is_alive is True


def test_icmp_error_is_reported_not_raised(monkeypatch):
    def boom(**kwargs):
        raise ICMPLibError("kaput")

    monkeypatch.setattr(checks, "ping", boom)

    result = run_check(ping_host())
    assert result.is_alive is False
    assert result.error is not None and "ICMPLibError" in result.error


# --------------------------------------------------------------------------- #
#  tcp
# --------------------------------------------------------------------------- #
def test_tcp_open(monkeypatch):
    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(checks.socket, "create_connection", lambda *a, **k: FakeConn())

    host = SimpleNamespace(name="ssh", address="10.0.0.1", kind="tcp", port=22, timeout=1)
    result = run_check(host)

    assert result.kind == "tcp"
    assert result.is_alive is True
    assert "22" in result.detail


def test_tcp_closed(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(checks.socket, "create_connection", refuse)

    host = SimpleNamespace(name="ssh", address="10.0.0.1", kind="tcp", port=22, timeout=1)
    result = run_check(host)

    assert result.is_alive is False
    assert result.error is not None


# --------------------------------------------------------------------------- #
#  http
# --------------------------------------------------------------------------- #
def test_http_ok(monkeypatch):
    monkeypatch.setattr(
        checks.requests, "get", lambda url, **kw: SimpleNamespace(status_code=200)
    )

    host = SimpleNamespace(
        name="site", address="example.org", kind="http", url=None, port=None,
        expect_status=None, timeout=1,
    )
    result = run_check(host)

    assert result.is_alive is True
    assert result.detail == "HTTP 200"


def test_http_expected_status_mismatch(monkeypatch):
    monkeypatch.setattr(
        checks.requests, "get", lambda url, **kw: SimpleNamespace(status_code=500)
    )

    host = SimpleNamespace(
        name="api", address="api.local", kind="http", url=None, port=8080,
        expect_status=200, timeout=1,
    )
    result = run_check(host)

    assert result.is_alive is False
    assert result.detail == "HTTP 500"


def test_http_connection_error(monkeypatch):
    def boom(url, **kw):
        raise checks.requests.RequestException("no route")

    monkeypatch.setattr(checks.requests, "get", boom)

    host = SimpleNamespace(
        name="site", address="down.local", kind="http", url=None, port=None,
        expect_status=None, timeout=1,
    )
    result = run_check(host)

    assert result.is_alive is False
    assert result.error is not None


# --------------------------------------------------------------------------- #
#  dispatcher
# --------------------------------------------------------------------------- #
def test_unknown_kind_is_reported():
    host = SimpleNamespace(name="x", address="1.1.1.1", kind="carrier-pigeon")
    result = run_check(host)

    assert result.is_alive is False
    assert "unknown check kind" in (result.error or "")


def test_check_result_defaults():
    result = CheckResult(name="web", address="1.1.1.1")
    assert result.kind == "ping"
    assert result.is_alive is False
