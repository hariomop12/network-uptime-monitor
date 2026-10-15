#!/usr/bin/env python3
"""Network Uptime Monitor - entry point.

Wires everything together: load config -> ping hosts (in parallel) ->
log metrics -> alert on state changes.

Usage
-----
    python monitor.py                 # continuous mode (systemd / manual)
    python monitor.py --once          # one cycle then exit (cron)
    python monitor.py --test-alert    # send a test alert and exit
    python monitor.py --config my.yaml

Note: raw ICMP needs privileges, so run with sudo or grant CAP_NET_RAW:

    sudo ./.venv/bin/python monitor.py
    # or, once:
    sudo setcap cap_net_raw+ep .venv/bin/python3
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from types import FrameType

from src.alerts import AlertManager, build_channels
from src.config import Config, ConfigError, Host, load_config
from src.logger import MetricsWriter, setup_logger
from src.pinger import PingResult, ping_host
from src.state import StateStore

_STOP = False
_MAX_WORKERS = 32


def _handle_stop(signum: int, frame: FrameType | None) -> None:
    """Request a clean shutdown on SIGINT / SIGTERM."""
    global _STOP
    _STOP = True


# --------------------------------------------------------------------------- #
#  Checking (parallel ping, serial logging/alerting)
# --------------------------------------------------------------------------- #
def _ping_batch(hosts: list[Host]) -> dict[str, PingResult]:
    """Ping every host concurrently and return the results keyed by host name."""
    results: dict[str, PingResult] = {}
    if not hosts:
        return results

    workers = min(len(hosts), _MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                ping_host, host.name, host.address, host.count, host.timeout
            ): host
            for host in hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                results[host.name] = future.result()
            except Exception as exc:  # noqa: BLE001 - defensive, ping_host shouldn't raise
                results[host.name] = PingResult(
                    name=host.name,
                    address=host.address,
                    is_alive=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
    return results


def _process_result(
    host: Host,
    result: PingResult,
    logger,
    metrics: MetricsWriter,
    alerts: AlertManager,
    consecutive_failures: dict[str, int],
) -> None:
    """Record one ping result and raise an alert if the state changed."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    metrics.write(result, timestamp)

    # Count consecutive failures so a single lost packet doesn't page anyone.
    if result.is_alive:
        consecutive_failures[host.name] = 0
    else:
        consecutive_failures[host.name] = consecutive_failures.get(host.name, 0) + 1

    failures = consecutive_failures[host.name]
    effective_alive = result.is_alive or failures < host.retries

    if result.is_alive:
        logger.info(
            "%-16s UP    avg %.1f ms  loss %.1f%%",
            host.name, result.avg_rtt, result.packet_loss,
        )
    elif effective_alive:
        logger.warning(
            "%-16s MISS  %d/%d failed round(s)  loss %.1f%%",
            host.name, failures, host.retries, result.packet_loss,
        )
    else:
        logger.error(
            "%-16s DOWN  loss %.1f%%%s",
            host.name, result.packet_loss,
            f"  ({result.error})" if result.error else "",
        )

    alerts.evaluate(
        result,
        effective_alive,
        host.alert_recovery,
        host.renotify_minutes,
    )


def _run_batch(
    hosts: list[Host],
    logger,
    metrics: MetricsWriter,
    alerts: AlertManager,
    consecutive_failures: dict[str, int],
) -> None:
    """Ping a group of hosts in parallel, then process the results in order."""
    results = _ping_batch(hosts)
    for host in hosts:
        _process_result(
            host, results[host.name], logger, metrics, alerts, consecutive_failures
        )


def run_once(config: Config, logger, metrics: MetricsWriter, alerts: AlertManager) -> None:
    """Ping every host a single time (cron-friendly)."""
    _run_batch(config.hosts, logger, metrics, alerts, {})


def run_forever(config: Config, logger, metrics: MetricsWriter, alerts: AlertManager) -> None:
    """Loop forever, pinging the hosts that are due (respecting each interval)."""
    failures: dict[str, int] = {}
    last_run: dict[str, float] = {host.name: 0.0 for host in config.hosts}

    while not _STOP:
        now = time.time()
        due = [h for h in config.hosts if now - last_run[h.name] >= h.interval]
        if due:
            _run_batch(due, logger, metrics, alerts, failures)
            for host in due:
                last_run[host.name] = time.time()
        time.sleep(1)  # 1-second tick keeps per-host intervals responsive


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _build_state_store(config: Config, logger) -> StateStore | None:
    """Create the persistent state store, unless disabled in the config."""
    if not config.state.enabled:
        logger.info("State persistence is disabled - alerts may repeat after restart.")
        return None

    path = Path(config.state.file)
    if not path.is_absolute():
        path = config.base_dir / path
    logger.info("Persisting host state to %s", path)
    return StateStore(path)


def _send_test_alert(alerts: AlertManager, logger) -> int:
    """Fire a dummy alert through every configured channel (connectivity test)."""
    if not alerts.channels:
        logger.error(
            "No alert channels configured - fill .env and enable a channel "
            "in config.yaml."
        )
        return 1

    subject = "[TEST] Network Uptime Monitor"
    message = "Test alert - if you are reading this, your alert channel works."

    failures = 0
    for channel in alerts.channels:
        try:
            channel.send(subject, message)
            logger.info("Test alert sent via %s", type(channel).__name__)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            failures += 1
            logger.error("Test alert via %s failed: %s", type(channel).__name__, exc)
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated Network Uptime Monitor with alerting."
    )
    parser.add_argument(
        "--config",
        default=os.getenv("MONITOR_CONFIG", "config.yaml"),
        help="Path to config.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single monitoring cycle and exit (good for cron).",
    )
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="Send a test alert through the configured channels and exit.",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    log_dir = config.base_dir / config.logging.log_dir
    logger = setup_logger(
        log_dir,
        config.logging.log_file,
        config.logging.log_level,
        config.logging.max_bytes,
        config.logging.backup_count,
    )
    metrics = MetricsWriter(log_dir / config.logging.metrics_csv)

    state_store = _build_state_store(config, logger)
    alerts = AlertManager(build_channels(config.alerts, logger), logger, state_store)

    if not alerts.channels:
        logger.warning("No alert channels are enabled/configured.")

    if args.test_alert:
        return _send_test_alert(alerts, logger)

    mode = "single cycle" if args.once else "continuous"
    logger.info(
        "Network Uptime Monitor started (%s mode) - watching %d host(s)",
        mode, len(config.hosts),
    )

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    try:
        if args.once:
            run_once(config, logger, metrics, alerts)
            logger.info("Single cycle complete.")
        else:
            run_forever(config, logger, metrics, alerts)
            logger.info("Shutdown requested - exiting.")
    except KeyboardInterrupt:
        logger.info("Interrupted - exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
