#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from speedrun_solver.importer import DEFAULT_SOURCE_URL, import_cards


def build_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Import and validate the public 82-0 card dataset."
    )
    parser.add_argument(
        "--source-url",
        default=DEFAULT_SOURCE_URL,
        help="Public structured dataset URL.",
    )
    parser.add_argument(
        "--input-json",
        help="Use a local rankings JSON file instead of making network requests.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(project_root / "data"),
        help="Directory for cards.csv, metrics, and the import report.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(project_root / ".cache" / "82-0-guide"),
        help="Local HTTP response cache.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Revalidate the cached dataset with the source.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--min-request-interval", type=float, default=0.25)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    report = import_cards(
        output_dir=arguments.output_dir,
        input_json=arguments.input_json,
        source_url=arguments.source_url,
        cache_dir=arguments.cache_dir,
        refresh=arguments.refresh,
        timeout=arguments.timeout,
        min_request_interval=arguments.min_request_interval,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
