#!/usr/bin/env python3
"""Generate a standalone HTML uptime report from the metrics CSV.

Usage
-----
    python report.py
    python report.py --metrics logs/metrics.csv --out logs/report.html
"""

from __future__ import annotations

import argparse

from src.report import generate_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an HTML uptime report.")
    parser.add_argument("--metrics", default="logs/metrics.csv", help="Path to metrics CSV")
    parser.add_argument("--out", default="logs/report.html", help="Output HTML file")
    parser.add_argument("--title", default="Network Uptime Monitor", help="Report title")
    args = parser.parse_args(argv)

    try:
        path = generate_report(args.metrics, args.out, args.title)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Report written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
