"""CLI entry point: ``python -m fixtures.generator``.

Builds the synthetic dataset and writes it to ``fixtures/data/``. Deterministic given ``--seed``;
re-running with the same arguments reproduces byte-identical files.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from fixtures.generator.build import build_dataset
from fixtures.generator.config import DEFAULT_ANCHOR, DEFAULT_OUTPUT_DIR, GenerationConfig
from fixtures.generator.writer import write_dataset


def _parse_anchor(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fixtures.generator", description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42).")
    parser.add_argument("--customers", type=int, default=3, help="Number of archetypes to emit (default: 3).")
    parser.add_argument("--months", type=int, default=24, help="Transaction history window in months (default: 24).")
    parser.add_argument(
        "--anchor",
        type=_parse_anchor,
        default=DEFAULT_ANCHOR,
        help="Fixed 'as of now' date the window counts back from (ISO 8601).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write JSON into (default: fixtures/data).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, generate the dataset, and persist it. Returns a process exit code."""
    args = _build_parser().parse_args(argv)
    config = GenerationConfig(
        seed=args.seed,
        num_customers=args.customers,
        history_months=args.months,
        anchor_date=args.anchor,
        output_dir=args.output_dir,
    )
    datasets = build_dataset(config)
    paths = write_dataset(datasets, config.output_dir)
    print(f"Generated {len(datasets)} customer(s); wrote {len(paths)} file(s) to {config.output_dir}")
    for path in paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
