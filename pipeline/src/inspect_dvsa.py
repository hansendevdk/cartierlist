"""Phase 0 reconnaissance for the DVSA MOT zips: row counts, null rates, distinct
value samples, and encoding, without extracting the multi-gigabyte archives to disk.

Uses Python's zipfile (not git-bash's bundled Info-ZIP 6.00, which cannot read
the Zip64 zips DVSA ships for the 2025 extracts) and streams each CSV member
line by line.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from pathlib import Path

# sys.maxsize overflows C long on Windows; this is comfortably larger than any
# legitimate field while still fitting a 32-bit long.
csv.field_size_limit(2**31 - 1)

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "dvsa"

ARCHIVES = {
    "results_2024.zip": "results",
    "results_2025.zip": "results",
    "failure_item_2024.zip": "failure_item",
    "failure_item_2025.zip": "failure_item",
}


def inspect_archive(path: Path, kind: str) -> dict:
    z = zipfile.ZipFile(path)
    members = [n for n in z.namelist() if n.endswith(".csv")]
    total_rows = 0
    header: list[str] | None = None
    null_counts: Counter = Counter()
    make_model_samples: set[tuple[str, str]] = set()
    test_result_values: Counter = Counter()
    rfr_type_values: Counter = Counter()
    test_class_values: Counter = Counter()
    encoding_ok = True

    for name in members:
        with z.open(name) as raw:
            wrapper = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
            try:
                # DVSA escapes literal quote chars in free-text fields (e.g. model
                # names quoting an inch measurement) with a backslash rather than
                # doubling the quote, which is non-standard CSV; escapechar handles it.
                reader = csv.reader(wrapper, escapechar="\\")
                this_header = next(reader)
                if header is None:
                    header = this_header
                elif header != this_header:
                    print(f"  ! header mismatch in {name}: {this_header}")
                for row in reader:
                    total_rows += 1
                    for col, val in zip(header, row):
                        if val == "":
                            null_counts[col] += 1
                    if kind == "results":
                        if len(make_model_samples) < 500:
                            make_model_samples.add((row[header.index("make")], row[header.index("model")]))
                        test_result_values[row[header.index("test_result")]] += 1
                        test_class_values[row[header.index("test_class_id")]] += 1
                    else:
                        rfr_type_values[row[header.index("rfr_type_code")]] += 1
            except UnicodeDecodeError as e:
                encoding_ok = False
                print(f"  ! decode error in {name}: {e}")

    return {
        "path": path.name,
        "members": len(members),
        "header": header,
        "total_rows": total_rows,
        "null_counts": null_counts,
        "make_model_samples": make_model_samples,
        "test_result_values": test_result_values,
        "test_class_values": test_class_values,
        "rfr_type_values": rfr_type_values,
        "encoding_ok": encoding_ok,
    }


def main() -> None:
    for filename, kind in ARCHIVES.items():
        path = RAW / filename
        print(f"=== {filename} ===")
        result = inspect_archive(path, kind)
        print(f"  members: {result['members']}")
        print(f"  header: {result['header']}")
        print(f"  total_rows: {result['total_rows']:,}")
        print(f"  encoding_ok (utf-8 strict): {result['encoding_ok']}")
        if result["header"]:
            print("  null rate by column:")
            for col in result["header"]:
                n = result["null_counts"].get(col, 0)
                pct = n / result["total_rows"] * 100 if result["total_rows"] else 0
                print(f"    {col}: {n:,} ({pct:.3f}%)")
        if result["make_model_samples"]:
            print(f"  sample make/model pairs (20 of {len(result['make_model_samples'])} sampled distinct):")
            for mm in list(result["make_model_samples"])[:20]:
                print(f"    {mm}")
        if result["test_result_values"]:
            print(f"  test_result distinct values: {dict(result['test_result_values'])}")
        if result["test_class_values"]:
            print(f"  test_class_id distinct values: {dict(result['test_class_values'])}")
        if result["rfr_type_values"]:
            print(f"  rfr_type_code distinct values: {dict(result['rfr_type_values'])}")
        print()


if __name__ == "__main__":
    main()
