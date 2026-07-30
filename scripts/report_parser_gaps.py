"""Run a small collection sample and print its aggregated parser gaps as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jobpicky.collection.parser_gaps import gaps_from_results
from jobpicky.collection.pipeline import run_pipeline_by_source
from jobpicky.collection.spreadsheet import read_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSV or XLSX recruitment sheet")
    parser.add_argument("--sheet")
    parser.add_argument("--limit-rows", type=int, default=20)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()

    rows = read_rows(args.input, args.sheet)[: max(args.limit_rows, 0)]
    gaps = gaps_from_results(run_pipeline_by_source(rows), sample_limit=args.samples)
    print(json.dumps([gap.as_dict() for gap in gaps], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
