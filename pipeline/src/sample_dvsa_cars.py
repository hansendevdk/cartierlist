"""Pull real passenger-car (test_class_id 4) make/model examples for the Phase 0
schema report, from the cleanest available file (2025, no __MACOSX junk, no
embedded duplicate header rows).
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

csv.field_size_limit(2**31 - 1)

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "dvsa"


def main() -> None:
    z = zipfile.ZipFile(RAW / "results_2025.zip")
    name = "dft_test_result_extracts_2025/dft_test_result_extract_202501.csv"
    seen: set[tuple[str, str]] = set()
    with z.open(name) as raw:
        import io

        wrapper = io.TextIOWrapper(raw, encoding="utf-8")
        reader = csv.reader(wrapper, escapechar="\\")
        header = next(reader)
        idx = {c: i for i, c in enumerate(header)}
        for row in reader:
            if row[idx["test_class_id"]] == "4":
                seen.add((row[idx["make"]], row[idx["model"]]))
            if len(seen) >= 20:
                break
    for pair in sorted(seen):
        print(pair)


if __name__ == "__main__":
    main()
