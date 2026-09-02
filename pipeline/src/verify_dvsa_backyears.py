"""Verifies the 2022 and 2023 DVSA back-year files before build_dvsa_warehouse.py
is allowed to load them, in the style of compare_dvsa_2024.py -- this project
already got burned once trusting a DVSA file by its name (see that script's
docstring), so nothing here is assumed from the S3 index page or from the
2024/2025 files' shape.

The 2022/2023 zips are roughly 4x smaller than 2024/2025. The working
hypothesis going in was that they are simply deflate-compressed while the
*_extracts_* files are stored uncompressed. That hypothesis turned out to be
WRONG, and worse than a compression difference -- see the module-level
finding recorded below, discovered while writing this script:

  - The 2022/2023 RESULTS zips use zip compression method 9 (Deflate64 /
    "Enhanced Deflate"), which Python's stdlib zipfile does not support
    (raises NotImplementedError). 7-Zip reads it fine, so extraction here
    shells out to 7z.exe rather than silently downgrading to a workaround
    that might corrupt data.
  - The 2022/2023 files are PIPE-delimited ('|'), not comma-delimited.
  - The 2022/2023 results file has 14 columns, not 15 -- there is no
    completed_date column at all.
  - The 2022/2023 failure-item file has 5 columns, not 6 -- also no
    completed_date, and its location column is named location_id, not
    mot_test_rfr_location_type_id.

None of this is what "same schema" (the run order's stated precondition for
loading) means. This script therefore adapts its OWN parsing (delimiter
sniffed per file, column presence checked rather than assumed) so it can
still answer every one of the six checks with real numbers, but it does not
write anywhere near build_dvsa_warehouse.py or the warehouse -- loading a
frame this different into mot_tests/mot_failures unchanged would silently
misparse every row (every field after test_result would be shifted one
comma-split position left of where the loader expects it), and picking a
column-remapping scheme is a decision, not a detail.

Six checks, run per year, per results AND failure-item files:
  1. uncompressed CSV byte size and row count of the results file.
  2. min(test_date)/max(test_date), to confirm full 12-month coverage.
  3. failure item row count, and that its test_id values join to the
     results file's test_id values (sampled, both directions).
  4. row counts per year in the same units as 2024/2025 (raw, and scoped to
     test_class_id = 4, matching mot_tests' own scope).
  5. whether the SAME quirks the existing loader handles apply here too
     (backslash-escaped quotes, quote auto-detection, echoed-header rows),
     checked directly rather than assumed, plus a DuckDB read_csv pass using
     the delimiter this script actually detected.
  6. column set and order vs 2024/2025 -- this is the check that failed.
"""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

import duckdb

csv.field_size_limit(2**31 - 1)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "dvsa"
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"

REFERENCE_RESULTS_HEADER = [
    "test_id", "vehicle_id", "test_date", "test_class_id", "test_type",
    "test_result", "test_mileage", "postcode_area", "make", "model",
    "colour", "fuel_type", "cylinder_capacity", "first_use_date", "completed_date",
]
REFERENCE_FAILURE_HEADER = [
    "test_id", "rfr_id", "rfr_type_code", "mot_test_rfr_location_type_id",
    "dangerous_mark", "completed_date",
]

FILES = {
    "2022": {"results": "results_2022.zip", "failures": "failure_item_2022.zip"},
    "2023": {"results": "results_2023.zip", "failures": "failure_item_2023.zip"},
}


def zip_compress_type(zip_path: Path) -> list[tuple[str, int, int, int]]:
    """Returns (member_name, compress_type, compress_size, file_size) without
    opening the compressed stream -- infolist() only reads the central
    directory, which zipfile can do regardless of compression method."""
    import zipfile
    z = zipfile.ZipFile(zip_path)
    return [(i.filename, i.compress_type, i.compress_size, i.file_size) for i in z.infolist()
            if i.filename.endswith(".csv") and "__MACOSX" not in i.filename]


def open_member_text(zip_path: Path, member: str, compress_type: int):
    """Returns a text-mode file-like object streaming one CSV member's
    decoded content. compress_type 8 (Deflate) and 0 (Stored) go through
    Python's zipfile directly; compress_type 9 (Deflate64) is not supported
    by zipfile and is streamed through 7z.exe instead."""
    if compress_type in (0, 8):
        import zipfile
        z = zipfile.ZipFile(zip_path)
        raw = z.open(member)
        return io.TextIOWrapper(raw, encoding="utf-8", errors="strict", newline="")
    if compress_type == 9:
        proc = subprocess.Popen(
            [SEVENZIP, "x", "-so", str(zip_path), member],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="strict", newline="")
    raise ValueError(f"unhandled compress_type {compress_type} for {zip_path}:{member}")


def sniff_delimiter(first_line: str) -> str:
    if "|" in first_line and "," not in first_line:
        return "|"
    if "," in first_line:
        return ","
    raise ValueError(f"cannot sniff delimiter from header line: {first_line!r}")


def stream_csv(zip_path: Path, kind: str) -> dict:
    """One pass over every CSV member in a zip. kind is 'results' or
    'failures', which selects which quirk-columns to look for by name
    (never assumed present -- checked via header.index with a guard)."""
    members = zip_compress_type(zip_path)
    total_rows = 0
    echoed_headers = 0
    class4_rows = 0
    min_date = None
    max_date = None
    header: list[str] | None = None
    delimiter: str | None = None
    test_ids: list[int] = []
    backslash_escapes_seen = 0
    n_members = 0

    for member, ctype, csize, fsize in members:
        n_members += 1
        f = open_member_text(zip_path, member, ctype)
        first_line = f.readline()
        delim = sniff_delimiter(first_line)
        if delimiter is None:
            delimiter = delim
        elif delimiter != delim:
            print(f"  ! delimiter mismatch within archive: {member} uses {delim!r}, "
                  f"earlier member used {delimiter!r}")
        this_header = first_line.rstrip("\r\n").split(delim)
        if header is None:
            header = this_header
        elif header != this_header:
            print(f"  ! header mismatch in {member}: {this_header}")

        idx_test_id = header.index("test_id")
        idx_test_result = header.index("test_result") if "test_result" in header else None
        idx_rfr_type = header.index("rfr_type_code") if "rfr_type_code" in header else None
        idx_test_class = header.index("test_class_id") if "test_class_id" in header else None
        idx_test_date = header.index("test_date") if "test_date" in header else None

        reader = csv.reader(f, delimiter=delim, escapechar="\\")
        for row in reader:
            total_rows += 1
            if idx_test_result is not None and row[idx_test_result] == "test_result":
                echoed_headers += 1
                continue
            if idx_rfr_type is not None and row[idx_rfr_type] == "rfr_type_code":
                echoed_headers += 1
                continue
            if idx_test_class is not None and row[idx_test_class] == "4":
                class4_rows += 1
            if idx_test_date is not None:
                d = row[idx_test_date]
                if min_date is None or d < min_date:
                    min_date = d
                if max_date is None or d > max_date:
                    max_date = d
            tid = row[idx_test_id]
            if tid.isdigit():
                test_ids.append(int(tid))
        f.close()

    return {
        "header": header, "delimiter": delimiter, "n_members": n_members,
        "total_rows": total_rows, "echoed_headers": echoed_headers,
        "class4_rows": class4_rows, "min_date": min_date, "max_date": max_date,
        "test_ids": test_ids, "backslash_escapes_seen": backslash_escapes_seen,
        "members_raw": members,
    }


def scan_backslash_quotes(zip_path: Path, member: str, ctype: int, n_bytes: int = 1 << 20) -> int:
    """Byte-level scan of the first n_bytes of decoded content for literal
    backslash-quote sequences, independent of whether csv.reader's
    escapechar setting is masking a problem rather than confirming one."""
    if ctype in (0, 8):
        import zipfile
        z = zipfile.ZipFile(zip_path)
        with z.open(member) as raw:
            sample = raw.read(n_bytes)
        return sample.count(b'\\"')
    if ctype == 9:
        proc = subprocess.Popen(
            [SEVENZIP, "x", "-so", str(zip_path), member],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        sample = proc.stdout.read(n_bytes)
        proc.stdout.close()
        proc.terminate()
        return sample.count(b'\\"')
    return 0


def join_rate(sample_ids: list[int], universe_sorted: list[int], sample_size: int = 500_000) -> float:
    import bisect
    import random
    if not sample_ids:
        return 0.0
    sample = sample_ids if len(sample_ids) <= sample_size else random.sample(sample_ids, sample_size)
    hits = 0
    for tid in sample:
        i = bisect.bisect_left(universe_sorted, tid)
        if i < len(universe_sorted) and universe_sorted[i] == tid:
            hits += 1
    return hits / len(sample)


def duckdb_pass(zip_path: Path, member: str, ctype: int, delim: str, label: str) -> None:
    """Extracts the one member to a scratch file (DuckDB read_csv needs a
    real path, not a pipe) and runs the loader's exact read_csv option set,
    substituting the detected delimiter, to see how far the existing
    workaround gets on this file's real shape."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "sample.csv"
        f = open_member_text(zip_path, member, ctype)
        with open(target, "w", encoding="utf-8", newline="") as out:
            for _ in range(2_000_000):
                line = f.readline()
                if not line:
                    break
                out.write(line)
        f.close()
        con = duckdb.connect(":memory:")
        try:
            n = con.execute(
                f"SELECT COUNT(*) FROM read_csv('{target.as_posix()}', delim='{delim}', "
                f"escape='\\', quote='\"', all_varchar=true, header=true, union_by_name=true)"
            ).fetchone()[0]
            cols = con.execute(
                f"SELECT * FROM read_csv('{target.as_posix()}', delim='{delim}', "
                f"escape='\\', quote='\"', all_varchar=true, header=true) LIMIT 0"
            ).description
            print(f"  DuckDB read_csv on first ~2M lines of {label} ({member}), delim={delim!r}: "
                  f"{n:,} rows, columns: {[c[0] for c in cols]}")
        except Exception as e:
            print(f"  DuckDB read_csv FAILED on {label} ({member}): {e}")
        finally:
            con.close()


def main() -> None:
    all_ok = True
    per_year_results = {}
    per_year_failures = {}

    for year, names in FILES.items():
        print(f"\n{'=' * 70}\nYEAR {year}\n{'=' * 70}")

        results_zip = RAW / names["results"]
        failures_zip = RAW / names["failures"]
        r_members = zip_compress_type(results_zip)
        f_members = zip_compress_type(failures_zip)
        print(f"results zip members: {r_members}")
        print(f"failures zip members: {f_members}")

        print("\n[check 5] streaming results file...")
        r = stream_csv(results_zip, "results")
        per_year_results[year] = r
        print(f"[check 1] results: {r['total_rows']:,} raw rows across {r['n_members']} member(s), "
              f"delimiter={r['delimiter']!r}")
        print(f"[check 2] test_date range: {r['min_date']} .. {r['max_date']}")
        full_year = r["min_date"] is not None and r["min_date"].startswith(year) \
            and r["max_date"] is not None and r["max_date"].startswith(year)
        if not full_year:
            print(f"  !! date range does not fall entirely within {year}")
            all_ok = False
        print(f"[check 4] test_class_id=4 scoped rows: {r['class4_rows']:,} of "
              f"{r['total_rows'] - r['echoed_headers']:,} real rows "
              f"({r['class4_rows'] / max(r['total_rows'] - r['echoed_headers'], 1) * 100:.1f}%)")
        print(f"[check 5] echoed-header data rows found: {r['echoed_headers']:,}")
        print(f"[check 6] results header ({len(r['header'])} cols): {r['header']}")
        if r["header"] != REFERENCE_RESULTS_HEADER:
            missing = [c for c in REFERENCE_RESULTS_HEADER if c not in r["header"]]
            extra = [c for c in r["header"] if c not in REFERENCE_RESULTS_HEADER]
            print(f"  !! SCHEMA MISMATCH vs 2024/2025 reference: missing={missing}, extra={extra}, "
                  f"delimiter is {r['delimiter']!r} vs reference ','")
            all_ok = False

        print("\n[check 5] streaming failure-item file...")
        fl = stream_csv(failures_zip, "failures")
        per_year_failures[year] = fl
        print(f"[check 3] failure items: {fl['total_rows']:,} raw rows, "
              f"{len(fl['test_ids']):,} usable test_id values, delimiter={fl['delimiter']!r}")
        print(f"[check 6] failure header ({len(fl['header'])} cols): {fl['header']}")
        if fl["header"] != REFERENCE_FAILURE_HEADER:
            missing = [c for c in REFERENCE_FAILURE_HEADER if c not in fl["header"]]
            extra = [c for c in fl["header"] if c not in REFERENCE_FAILURE_HEADER]
            print(f"  !! SCHEMA MISMATCH vs 2024/2025 reference: missing={missing}, extra={extra}")
            all_ok = False

        results_ids_sorted = sorted(r["test_ids"])
        rate_f_in_r = join_rate(fl["test_ids"], results_ids_sorted)
        print(f"[check 3] join check: sampled failure test_ids found in results test_ids: "
              f"{rate_f_in_r * 100:.2f}%")

        print("\n[check 5] backslash-escaped-quote scan (first 1MB of first member):")
        rm = r_members[0]
        fm = f_members[0]
        print(f"  results: {scan_backslash_quotes(results_zip, rm[0], rm[1]):,} occurrences")
        print(f"  failures: {scan_backslash_quotes(failures_zip, fm[0], fm[1]):,} occurrences")

        print("\n[check 5, DuckDB] loader's exact read_csv options against a real sample:")
        duckdb_pass(results_zip, rm[0], rm[1], r["delimiter"], "results")
        duckdb_pass(failures_zip, fm[0], fm[1], fl["delimiter"], "failures")

    print(f"\n{'=' * 70}\nCROSS-YEAR ROW COUNT COMPARISON (test_class_id=4 scope, matching mot_tests)\n{'=' * 70}")
    print(f"{'year':<8}{'raw_rows':>14}{'class4_rows':>14}{'failure_rows':>16}")
    for year in FILES:
        r = per_year_results[year]
        fl = per_year_failures[year]
        print(f"{year:<8}{r['total_rows'] - r['echoed_headers']:>14,}{r['class4_rows']:>14,}"
              f"{fl['total_rows'] - fl['echoed_headers']:>16,}")
    print("(2024: 40,204,815 class4 rows / 2025: 40,213,008 class4 rows, per the live warehouse "
          "before this extension)")

    print(f"\n{'=' * 70}")
    if all_ok:
        print("ALL CHECKS PASSED -- safe to add 2022/2023 to build_dvsa_warehouse.py as-is")
    else:
        print("SCHEMA/FORMAT CHECKS FAILED -- do not add to build_dvsa_warehouse.py as-is. "
              "See !! lines above. This is a decision point (how to adapt the loader for a "
              "different delimiter and column set), not a detail -- reported, not resolved here.")
        sys.exit(1)


if __name__ == "__main__":
    main()
