"""Tests for the logging helpers and the CSV metrics writer."""

from __future__ import annotations

import logging

from src.logger import CSV_HEADER, MetricsWriter, setup_logger
from src.pinger import PingResult


def test_metrics_writer_writes_header_then_rows(tmp_path):
    path = tmp_path / "metrics.csv"
    writer = MetricsWriter(path)

    writer.write(
        PingResult("web", "1.1.1.1", True, packets_sent=3, packets_received=3, avg_rtt=1.5),
        "2026-01-01T00:00:00",
    )
    writer.write(
        PingResult("web", "1.1.1.1", False, packet_loss=100.0),
        "2026-01-01T00:01:00",
    )

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == ",".join(CSV_HEADER)
    assert len(lines) == 3          # header + 2 rows
    assert "UP" in lines[1]
    assert "DOWN" in lines[2]


def test_metrics_writer_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "deeper" / "metrics.csv"
    MetricsWriter(path).write(PingResult("web", "1.1.1.1", True), "t")
    assert path.exists()


def test_setup_logger_writes_to_file(tmp_path):
    logging.getLogger("uptime_monitor").handlers.clear()  # isolate the test

    logger = setup_logger(tmp_path, "test.log", "DEBUG")
    logger.info("hello from test")
    for handler in logger.handlers:
        handler.flush()

    content = (tmp_path / "test.log").read_text(encoding="utf-8")
    assert "hello from test" in content
