"""Logging helpers.

Two responsibilities:

* :func:`setup_logger` - a rotating, formatted application log (file + console).
* :class:`MetricsWriter` - append one CSV row per ping for later analysis.
"""

from __future__ import annotations

import csv
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .pinger import PingResult

# Column order of the metrics CSV file.
CSV_HEADER = [
    "timestamp",
    "name",
    "address",
    "status",
    "packets_sent",
    "packets_received",
    "packet_loss_pct",
    "min_rtt_ms",
    "avg_rtt_ms",
    "max_rtt_ms",
    "jitter_ms",
]


def setup_logger(
    log_dir: str | Path,
    log_file: str = "monitor.log",
    level: str = "INFO",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Create (once) and return the shared monitor logger."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("uptime_monitor")
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False

    if logger.handlers:  # already configured - don't add duplicates
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path / log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


class MetricsWriter:
    """Append per-ping metrics to a CSV file (header written on demand)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, result: PingResult, timestamp: str) -> None:
        """Write one row for ``result`` tagged with ``timestamp``."""
        needs_header = not self.path.exists() or self.path.stat().st_size == 0

        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if needs_header:
                writer.writerow(CSV_HEADER)
            writer.writerow(
                [
                    timestamp,
                    result.name,
                    result.address,
                    "UP" if result.is_alive else "DOWN",
                    result.packets_sent,
                    result.packets_received,
                    f"{result.packet_loss:.1f}",
                    f"{result.min_rtt:.2f}",
                    f"{result.avg_rtt:.2f}",
                    f"{result.max_rtt:.2f}",
                    f"{result.jitter:.2f}",
                ]
            )
