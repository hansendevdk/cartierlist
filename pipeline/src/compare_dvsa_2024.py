"""Compare the two 2024 DVSA publications found on the index page:
  - results_2024.zip / failure_item_2024.zip ("MOT+testing+data+results+(2024)"
    naming, deflate-compressed, contains __MACOSX junk and ~180 duplicate
    embedded header rows -- discovered in Phase 0)
  - results_2024_alt.zip / failure_item_2024_alt.zip ("dft_test_result_extracts_2024"
    naming, matching the 2025 convention, stored/uncompressed)

Phase 0 found 66.9M rows in the old-naming 2024 results file vs 42.7M in 2025 --
about 1.57x too large relative to a full 12-month year at 2025's rate. This checks
row counts and test_id overlap to determine whether the old file is a superseded/
duplicated publication.
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

csv.field_size_limit(2**31 - 1)

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "dvsa"


def count_and_sample_ids(zip_path: Path, kind: str) -> tuple[int, set[str]]:
    z = zipfile.ZipFile(zip_path)
    members = [n for n in z.namelist() if n.endswith(".csv") and "__MACOSX" not in n]
    total = 0
    id_sample: set[str] = set()
    id_col = "test_id"
    for name in members:
        with z.open(name) as raw:
            import io

            wrapper = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
            try:
                reader = csv.reader(wrapper, escapechar="\\")
                header = next(reader)
                idx = header.index(id_col)
                for row in reader:
                    total += 1
                    val = row[idx]
                    if val == id_col:
                        continue  # embedded duplicate header row, Phase 0 finding
                    if len(id_sample) < 2_000_000:
                        id_sample.add(val)
            except UnicodeDecodeError:
                pass
    return total, id_sample


def main() -> None:
    print("=== results_2024.zip (old naming) ===")
    old_total, old_ids = count_and_sample_ids(RAW / "results_2024.zip", "results")
    print(f"  total rows: {old_total:,}, sampled distinct test_ids: {len(old_ids):,}")

    print("=== results_2024_alt.zip (new naming) ===")
    alt_total, alt_ids = count_and_sample_ids(RAW / "results_2024_alt.zip", "results")
    print(f"  total rows: {alt_total:,}, sampled distinct test_ids: {len(alt_ids):,}")

    overlap = len(old_ids & alt_ids)
    print(f"\noverlap between sampled id sets: {overlap:,} "
          f"({overlap / max(len(alt_ids), 1) * 100:.1f}% of alt ids also in old)")

    old_only = old_total - len(old_ids)
    print(f"\nold file: {old_total:,} rows, {len(old_ids):,} distinct ids sampled "
          f"-> ~{old_total / len(old_ids):.2f}x rows per distinct id (duplication ratio)")


if __name__ == "__main__":
    main()
