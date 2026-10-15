#!/usr/bin/env python3
"""Network Uptime Monitor - entry point.

Wires everything together: load config -> ping hosts -> log metrics -> alert.

Usage
-----
    python monitor.py                 # continuous mode (systemd / manual)
    python monitor.py --once          # one cycle then exit (cron)
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
from datetime import datetime
from types import FrameType

from src.alerts import AlertManager, build_channels
from src.config import Config, ConfigError, Host, load_config
from src.logger import MetricsWriter, setup_logger
from src.pinger import ping_host

_STOP = False


def _handle_stop(signum: int, frame: FrameType | None) -> None:
    """Request a clean shutdown on SIGINT / SIGTERM."""
    global _STOP
    _STOP = True


def check_host(
    host: Host,
    logger,
    metrics: MetricsWriter,
    alerts: AlertManager,
    consecutive_failures: dict[str, int],
) -> None:
    """Ping one host, record the result and raise alerts on state changes."""
    result = ping_host(host.name, host.address, count=host.count, timeout=host.timeout)
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

    alerts.evaluate(result, effective_alive, host.alert_recovery)


def run_once(config: Config, logger, metrics: MetricsWriter, alerts: AlertManager) -> None:
    """Ping every host a single time (cron-friendly)."""
    failures: dict[str, int] = {}
    for host in config.hosts:
        check_host(host, logger, metrics, alerts, failures)


def run_forever(config: Config, logger, metrics: MetricsWriter, alerts: AlertManager) -> None:
    """Loop forever, honouring each host's own interval."""
    failures: dict[str, int] = {}
    last_run: dict[str, float] = {host.name: 0.0 for host in config.hosts}

    while not _STOP:
        now = time.time()
        for host in config.hosts:
            if now - last_run[host.name] >= host.interval:
                check_host(host, logger, metrics, alerts, failures)
                last_run[host.name] = time.time()
        time.sleep(1)  # 1-second tick keeps per-host intervals responsive


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
    alerts = AlertManager(build_channels(config.alerts, logger), logger)

    if not alerts.channels:
        logger.warning("No alert channels are enabled/configured.")

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
