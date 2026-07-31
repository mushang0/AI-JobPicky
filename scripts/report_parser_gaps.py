"""Report parser coverage for the first N CSV data rows without network access."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from itertools import islice
from pathlib import Path

from jobpicky.collection.link_classification import UNKNOWN, classify_link
from jobpicky.collection.link_extraction import extract_links
from jobpicky.collection.pipeline import PARSERS


def _classify_csv(path: Path, limit: int) -> tuple[int, Counter[str]]:
    counts: Counter[str] = Counter()
    rows_scanned = 0
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        next(reader, None)
        for values in islice(reader, max(limit, 0)):
            rows_scanned += 1
            apply_value = values[12] if len(values) > 12 else None
            for link in extract_links(apply_value, None):
                counts[classify_link(link)] += 1
    return rows_scanned, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSV recruitment sheet")
    parser.add_argument("--limit-rows", type=int, default=20)
    args = parser.parse_args()

    rows_scanned, counts = _classify_csv(args.input, args.limit_rows)
    implemented = {kind: counts[kind] for kind in sorted(PARSERS) if counts[kind]}
    unimplemented = {
        kind: count
        for kind, count in sorted(counts.items())
        if kind != UNKNOWN and kind not in PARSERS
    }
    summary = {
        "rows_scanned": rows_scanned,
        "links": sum(counts.values()),
        "implemented": {
            "types": len(PARSERS),
            "links": sum(implemented.values()),
            "counts": implemented,
        },
        "unimplemented": {
            "types": len(unimplemented),
            "links": sum(unimplemented.values()),
            "counts": unimplemented,
        },
        "unknown": {"types": int(bool(counts[UNKNOWN])), "links": counts[UNKNOWN]},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
