#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from speedrun_solver.webapp import run_server


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Run the local 82-0 speedrun browser application."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        choices=["127.0.0.1"],
        help="Security-locked loopback address.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        choices=[8765],
        help="Security-locked loopback port.",
    )
    parser.add_argument("--cards", default=str(root / "data" / "cards.csv"))
    parser.add_argument(
        "--team-era-metrics",
        default=str(root / "data" / "team_era_metrics.json"),
    )
    parser.add_argument(
        "--session",
        default=str(root / "data" / "active_run.json"),
        help="Persistent run-state file.",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--max-lifetime-hours",
        type=float,
        default=6,
        help="Close this solver terminal after this many hours (default: 6).",
    )
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    run_server(
        host=arguments.host,
        port=arguments.port,
        cards_path=arguments.cards,
        metrics_path=arguments.team_era_metrics,
        session_path=arguments.session,
        static_root=root / "web",
        open_browser=not arguments.no_browser,
        max_lifetime_seconds=max(0.0, arguments.max_lifetime_hours) * 3600,
    )


if __name__ == "__main__":
    main()
