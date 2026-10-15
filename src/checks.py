"""Host checks: ICMP ping, TCP port and HTTP(S).

Every check returns the same :class:`CheckResult`, so the logger, alert manager
and reporter stay completely check-type agnostic.
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass

import requests
from icmplib import ping
from icmplib.exceptions import ICMPLibError, SocketPermissionError

log = logging.getLogger(__name__)

KINDS = ("ping", "tcp", "http")


@dataclass
class CheckResult:
    """Normalised outcome of a single check for one host."""

    name: str
    address: str
    kind: str = "ping"        # ping | tcp | http
    is_alive: bool = False
    latency_ms: float = 0.0   # avg RTT (ping) or connect/response time
    packet_loss: float = 0.0  # percent - ping only
    detail: str = ""          # short human summary, e.g. "HTTP 200"
    error: str | None = None  # set only when the check could not run at all


def run_check(host) -> CheckResult:
    """Run the check matching ``host.kind`` and never crash the monitor."""
    kind = (getattr(host, "kind", "ping") or "ping").lower()
    try:
        if kind == "ping":
            return _check_icmp(host)
        if kind == "tcp":
            return _check_tcp(host)
        if kind == "http":
            return _check_http(host)
        return CheckResult(
            name=host.name,
            address=host.address,
            kind=kind,
            is_alive=False,
            error=f"unknown check kind: {kind}",
        )
    except Exception as exc:  # noqa: BLE001 - a check must never crash the loop
        log.exception("Check for %s (%s) crashed", host.name, host.address)
        return CheckResult(
            name=host.name,
            address=host.address,
            kind=kind,
            is_alive=False,
            error=f"{type(exc).__name__}: {exc}",
        )


# --------------------------------------------------------------------------- #
#  ICMP
# --------------------------------------------------------------------------- #
def _check_icmp(host) -> CheckResult:
    """Ping a host. Link failures are results; only real problems set ``error``."""
    last_error: str | None = None

    for privileged in (True, False):
        try:
            reply = ping(
                address=host.address,
                count=host.count,
                timeout=host.timeout,
                privileged=privileged,
            )
        except SocketPermissionError as exc:
            last_error = f"permission denied ({type(exc).__name__})"
            continue
        except ICMPLibError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            break

        return CheckResult(
            name=host.name,
            address=host.address,
            kind="ping",
            is_alive=reply.is_alive,
            # icmplib reports loss as a 0.0-1.0 ratio; store it as a percentage.
            packet_loss=reply.packet_loss * 100.0,
            latency_ms=reply.avg_rtt,
            detail=f"{reply.packets_received}/{reply.packets_sent} replies",
        )

    log.error("Could not ping %s (%s): %s", host.name, host.address, last_error)
    return CheckResult(
        name=host.name, address=host.address, kind="ping", is_alive=False, error=last_error
    )


# --------------------------------------------------------------------------- #
#  TCP
# --------------------------------------------------------------------------- #
def _check_tcp(host) -> CheckResult:
    """Try to open a TCP connection to ``host.address:host.port``."""
    port = int(host.port) if host.port else 80
    start = time.perf_counter()
    try:
        with socket.create_connection((host.address, port), timeout=host.timeout):
            latency = (time.perf_counter() - start) * 1000
    except OSError as exc:
        return CheckResult(
            name=host.name,
            address=host.address,
            kind="tcp",
            is_alive=False,
            detail=f"port {port}",
            error=f"{type(exc).__name__}: {exc}",
        )

    return CheckResult(
        name=host.name,
        address=host.address,
        kind="tcp",
        is_alive=True,
        latency_ms=latency,
        detail=f"port {port} open",
    )


# --------------------------------------------------------------------------- #
#  HTTP
# --------------------------------------------------------------------------- #
def _check_http(host) -> CheckResult:
    """HTTP GET ``host.url`` (or ``http://address:port/``) and check the status."""
    is_https = bool(host.url and host.url.startswith("https"))
    port = host.port or (443 if is_https else 80)
    url = host.url or f"http://{host.address}:{port}/"

    start = time.perf_counter()
    try:
        response = requests.get(url, timeout=host.timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return CheckResult(
            name=host.name,
            address=host.address,
            kind="http",
            is_alive=False,
            detail=url,
            error=f"{type(exc).__name__}: {exc}",
        )

    latency = (time.perf_counter() - start) * 1000
    status = response.status_code
    alive = status == host.expect_status if host.expect_status else 200 <= status < 400

    return CheckResult(
        name=host.name,
        address=host.address,
        kind="http",
        is_alive=alive,
        latency_ms=latency,
        detail=f"HTTP {status}",
    )
