"""Tests for the HTML report generator."""

from __future__ import annotations

import pytest

from src.report import generate_report, read_metrics

CSV = """timestamp,name,address,kind,status,latency_ms,packet_loss_pct,detail
2026-01-01T00:00:00,web,1.1.1.1,ping,UP,10.0,0.0,3/3 replies
2026-01-01T00:01:00,web,1.1.1.1,ping,UP,12.0,0.0,3/3 replies
2026-01-01T00:02:00,web,1.1.1.1,ping,DOWN,0.0,100.0,0/3 replies
2026-01-01T00:00:00,api,api.local,http,UP,45.0,0.0,HTTP 200
"""


def _write_csv(tmp_path):
    path = tmp_path / "metrics.csv"
    path.write_text(CSV, encoding="utf-8")
    return path


def test_read_metrics_aggregates(tmp_path):
    summaries = read_metrics(_write_csv(tmp_path))

    web = summaries["web"]
    assert web.total == 3
    assert web.up == 2
    assert web.down == 1
    assert round(web.uptime_pct, 1) == 66.7
    assert web.avg_latency == 11.0

    api = summaries["api"]
    assert api.kind == "http"
    assert api.total == 1
    assert api.uptime_pct == 100.0


def test_generate_report_writes_html(tmp_path):
    metrics = _write_csv(tmp_path)
    out = tmp_path / "report.html"

    result = generate_report(metrics, out, title="My Monitor")

    assert result == out
    html = out.read_text(encoding="utf-8")
    assert "My Monitor" in html
    assert "web" in html and "api" in html
    assert "<svg" in html  # sparkline rendered for the host with >1 latency


def test_missing_metrics_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_report(tmp_path / "nope.csv", tmp_path / "out.html")
