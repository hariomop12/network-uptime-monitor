"""Build a self-contained HTML uptime report from the metrics CSV.

No external templating library is used - the page is a single HTML string with
inline CSS and tiny inline SVG sparklines, so it can be opened directly in a
browser or dropped into a GitHub Pages site.
"""

from __future__ import annotations

import csv
import html
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class HostSummary:
    """Aggregated stats for one host."""

    name: str
    address: str
    kind: str = "ping"
    total: int = 0
    up: int = 0
    down: int = 0
    latency_values: list[float] = field(default_factory=list)
    loss_values: list[float] = field(default_factory=list)
    last_status: str = "?"
    last_seen: str = ""
    last_detail: str = ""

    @property
    def uptime_pct(self) -> float:
        return (self.up / self.total * 100) if self.total else 0.0

    @property
    def avg_latency(self) -> float:
        return sum(self.latency_values) / len(self.latency_values) if self.latency_values else 0.0

    @property
    def avg_loss(self) -> float:
        return sum(self.loss_values) / len(self.loss_values) if self.loss_values else 0.0


def read_metrics(path: str | Path) -> "OrderedDict[str, HostSummary]":
    """Parse the metrics CSV into per-host summaries, preserving order."""
    summaries: "OrderedDict[str, HostSummary]" = OrderedDict()

    with Path(path).open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row.get("name", "")
            if not name:
                continue

            summary = summaries.get(name)
            if summary is None:
                summary = HostSummary(
                    name=name,
                    address=row.get("address", ""),
                    kind=row.get("kind", "ping"),
                )
                summaries[name] = summary

            summary.kind = row.get("kind", summary.kind)
            summary.total += 1
            alive = row.get("status", "") == "UP"
            if alive:
                summary.up += 1
            else:
                summary.down += 1

            summary.last_status = row.get("status", summary.last_status)
            summary.last_seen = row.get("timestamp", summary.last_seen)
            summary.last_detail = row.get("detail", summary.last_detail)

            try:
                latency = float(row.get("latency_ms") or 0)
            except ValueError:
                latency = 0.0
            if alive and latency > 0:
                summary.latency_values.append(latency)

            try:
                summary.loss_values.append(float(row.get("packet_loss_pct") or 0))
            except ValueError:
                summary.loss_values.append(0.0)

    return summaries


def _sparkline(values: list[float], width: int = 260, height: int = 44) -> str:
    """Render a tiny inline SVG line chart for a list of latencies."""
    if len(values) < 2:
        return '<span class="muted">not enough data</span>'

    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = width / (len(values) - 1)

    points = []
    for index, value in enumerate(values):
        x = index * step
        y = height - ((value - low) / span) * (height - 6) - 3
        points.append(f"{x:.1f},{y:.1f}")

    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" role="img">'
        f'<polyline points="{" ".join(points)}" /></svg>'
    )


def _status_badge(status: str) -> str:
    css = "up" if status == "UP" else "down"
    label = status or "?"
    return f'<span class="badge {css}">{html.escape(label)}</span>'


def _uptime_class(pct: float) -> str:
    if pct >= 99:
        return "good"
    if pct >= 95:
        return "warn"
    return "bad"


def generate_report(
    metrics_path: str | Path,
    out_path: str | Path,
    title: str = "Network Uptime Monitor",
) -> Path:
    """Read ``metrics_path`` and write an HTML report to ``out_path``."""
    metrics_path = Path(metrics_path)
    if not metrics_path.is_file():
        raise FileNotFoundError(f"Metrics file not found: {metrics_path}")

    summaries = read_metrics(metrics_path)
    total_checks = sum(s.total for s in summaries.values())
    total_down = sum(s.down for s in summaries.values())
    overall_uptime = (
        (total_checks - total_down) / total_checks * 100 if total_checks else 0.0
    )
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for summary in summaries.values():
        loss_cell = f"{summary.avg_loss:.1f}%" if summary.kind == "ping" else "—"
        rows.append(
            f"""
            <tr>
              <td class="host">
                <div class="host-name">{html.escape(summary.name)}</div>
                <div class="host-addr">{html.escape(summary.address)}</div>
              </td>
              <td><span class="chip">{html.escape(summary.kind)}</span></td>
              <td>{_status_badge(summary.last_status)}</td>
              <td>
                <div class="uptime {_uptime_class(summary.uptime_pct)}">
                  {summary.uptime_pct:.1f}%
                </div>
                <div class="muted small">{summary.up}/{summary.total} checks</div>
              </td>
              <td class="num">{summary.avg_latency:.1f} ms</td>
              <td class="num">{loss_cell}</td>
              <td class="spark-cell">{_sparkline(summary.latency_values)}</td>
              <td class="muted small">{html.escape(summary.last_seen)}</td>
            </tr>"""
        )

    if not rows:
        rows.append(
            '<tr><td colspan="8" class="muted">No metrics found.</td></tr>'
        )

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem 1rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f6f8fa; color: #1f2328;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.5rem; }}
  .sub {{ color: #656d76; margin-bottom: 1.5rem; font-size: .9rem; }}
  .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }}
  .card {{
    background: #fff; border: 1px solid #d0d7de; border-radius: 10px;
    padding: 1rem 1.25rem; min-width: 160px;
  }}
  .card .label {{ color: #656d76; font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }}
  .card .value {{ font-size: 1.6rem; font-weight: 600; margin-top: .25rem; }}
  table {{
    width: 100%; border-collapse: collapse; background: #fff;
    border: 1px solid #d0d7de; border-radius: 10px; overflow: hidden;
  }}
  th, td {{ padding: .7rem .85rem; text-align: left; border-bottom: 1px solid #eaeef2; vertical-align: middle; }}
  th {{ background: #f6f8fa; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; color: #656d76; }}
  tr:last-child td {{ border-bottom: none; }}
  .host-name {{ font-weight: 600; }}
  .host-addr {{ color: #656d76; font-size: .8rem; }}
  .num {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .muted {{ color: #656d76; }}
  .small {{ font-size: .78rem; }}
  .chip {{ background: #eaeef2; border-radius: 6px; padding: .15rem .5rem; font-size: .78rem; }}
  .badge {{ padding: .15rem .55rem; border-radius: 999px; font-size: .78rem; font-weight: 600; color: #fff; }}
  .badge.up {{ background: #1a7f37; }}
  .badge.down {{ background: #cf222e; }}
  .uptime {{ font-weight: 600; }}
  .uptime.good {{ color: #1a7f37; }}
  .uptime.warn {{ color: #9a6700; }}
  .uptime.bad {{ color: #cf222e; }}
  .spark-cell {{ width: 280px; }}
  .spark {{ width: 260px; height: 44px; }}
  .spark polyline {{ fill: none; stroke: #2da44e; stroke-width: 2; stroke-linejoin: round; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0d1117; color: #e6edf3; }}
    .card, table {{ background: #161b22; border-color: #30363d; }}
    th {{ background: #161b22; }}
    th, td {{ border-color: #30363d; }}
    .chip {{ background: #21262d; }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(title)}</h1>
    <div class="sub">Report generated {html.escape(generated)} &middot; source: {html.escape(str(metrics_path))}</div>

    <div class="cards">
      <div class="card"><div class="label">Hosts</div><div class="value">{len(summaries)}</div></div>
      <div class="card"><div class="label">Total checks</div><div class="value">{total_checks}</div></div>
      <div class="card"><div class="label">Failed checks</div><div class="value">{total_down}</div></div>
      <div class="card"><div class="label">Overall uptime</div><div class="value {_uptime_class(overall_uptime)}">{overall_uptime:.1f}%</div></div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Host</th><th>Type</th><th>Last</th><th>Uptime</th>
          <th>Avg latency</th><th>Avg loss</th><th>Latency trend</th><th>Last seen</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</body>
</html>
"""

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    return out_path
