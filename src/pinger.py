"""ICMP ping wrapper around :mod:`icmplib`.

Turns icmplib's rich ``Host`` object into a small, predictable
:class:`PingResult` and never lets an unexpected error crash the monitor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from icmplib import ping
from icmplib.exceptions import ICMPLibError, SocketPermissionError

log = logging.getLogger(__name__)


@dataclass
class PingResult:
    """Normalised outcome of a single ping round for one host."""

    name: str
    address: str
    is_alive: bool
    packets_sent: int = 0
    packets_received: int = 0
    packet_loss: float = 100.0
    min_rtt: float = 0.0
    avg_rtt: float = 0.0
    max_rtt: float = 0.0
    jitter: float = 0.0
    error: str | None = None  # set only when the ping itself could not run


def ping_host(
    name: str,
    address: str,
    count: int = 3,
    timeout: float = 2.0,
) -> PingResult:
    """Ping ``address`` and return a :class:`PingResult`.

    Link failures (host unreachable / packet loss) are *not* errors - they come
    back as ``is_alive=False``. Only real problems (missing permissions, bad
    address, no socket) are reported through ``PingResult.error``.

    Raw ICMP sockets normally require root, so privileged mode is tried first
    and the call transparently falls back to unprivileged mode.
    """
    last_error: str | None = None

    for privileged in (True, False):
        try:
            reply = ping(
                address=address,
                count=count,
                timeout=timeout,
                privileged=privileged,
            )
        except SocketPermissionError as exc:
            # No permission in this mode - try the other one.
            last_error = f"permission denied ({type(exc).__name__})"
            continue
        except ICMPLibError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            break
        except Exception as exc:  # noqa: BLE001 - the monitor must never crash
            last_error = f"{type(exc).__name__}: {exc}"
            break

        return PingResult(
            name=name,
            address=address,
            is_alive=reply.is_alive,
            packets_sent=reply.packets_sent,
            packets_received=reply.packets_received,
            # icmplib reports loss as a 0.0-1.0 ratio; store it as a percentage.
            packet_loss=reply.packet_loss * 100.0,
            min_rtt=reply.min_rtt,
            avg_rtt=reply.avg_rtt,
            max_rtt=reply.max_rtt,
            jitter=reply.jitter,
        )

    log.error("Could not ping %s (%s): %s", name, address, last_error)
    return PingResult(name=name, address=address, is_alive=False, error=last_error)
