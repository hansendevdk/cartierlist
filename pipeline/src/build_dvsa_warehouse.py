"""Build the DVSA-derived warehouse tables (mot_tests, mot_failures,
failure_categories) as Parquet-backed DuckDB tables.

CSV parsing quirks discovered in Phase 0/1 that this script works around:
  - DVSA escapes literal quote chars with a backslash instead of doubling them
    (non-standard CSV) -- read_csv(escape='\\').
  - DuckDB's quote auto-detection can miss the quote char entirely on files
    where quoted fields are rare in the sample window -- quote='"' is set
    explicitly, not left to auto-detect.
  - The 2024 files contain ~180 rows where the header line is echoed back as a
    literal data row (e.g. a row where test_result='test_result') -- these break
    DuckDB's type auto-detection outright (can't cast the string "test_class_id"
    to BIGINT), so every column is read as VARCHAR first, the echoed-header rows
    are filtered out by value, and only then are real types cast.
  - The 2024 zip has two publications; see compare_dvsa_2024.py / the Phase 1
    report for which one this script points at and why.

FOUR-YEAR EXTENSION (2022/2023 added, see reports/dvsa_backyears_report.md):
the 2022/2023 files are an older DVSA publication vintage with a materially
different physical shape from 2024/2025 -- pipe-delimited instead of comma,
14/5 columns instead of 15/6 (no completed_date column at all), no
quote-escaping convention (a handful of rows carry a literal, unescaped
quote character inside a model name, so quote must be disabled rather than
treated as CSV-quoting), and the failure-item location column is named
location_id rather than mot_test_rfr_location_type_id. Verified this is a
rename onto the SAME 60-value code domain, not a different one, before
mapping it across. All of this is a per-file SHAPE difference, not a
semantic one: two independent verification passes (structural, then
value-domain: rfr_type_code, test_type, test_result, location_id, top-200
make/model overlap, mileage units, and vehicle_id stability across
publication years) came back clean before this script was changed to load
them. RESULTS_FILE_PROPS/FAILURE_FILE_PROPS below is the explicit,
per-zip-filename table those differences are driven from, so adding a future
vintage means adding a dict entry, not a year-number branch in the loading
SQL -- and a zip with no entry there fails loudly (KeyError) rather than
silently falling through to the wrong shape.

DEFLATE64: the 2022/2023 results zips use zip compression method 9
(Deflate64 / "Enhanced Deflate"), which Python's stdlib zipfile cannot
decompress (raises NotImplementedError). This script imports the
`zipfile-deflate64` package (added to pipeline/pyproject.toml) before
`zipfile` itself; importing it patches stdlib zipfile in place to add
method-9 support, so the plain `import zipfile` / `zipfile.ZipFile(...)`
calls below work unchanged for both old- and new-vintage zips. Chosen over
shelling out to 7-Zip because it keeps the pipeline reproducible on any
machine with the venv installed, not one with 7-Zip on PATH specifically.
If the import ever fails, that means the dependency is missing from the
venv, not that Deflate64 support can be silently skipped -- see the loud
FATAL check right after the import below.

Scope decision (Opus review, Phase 1 handover): mot_tests is restricted to
test_class_id = 4 (the passenger-car class, ~94% of rows) at load time, since
that's the project's vehicle scope throughout. mot_failures is implicitly
scoped to the same tests via the join to mot_tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import zipfile_deflate64  # noqa: F401  -- patches stdlib zipfile for method 9 (Deflate64), see module docstring
except ImportError:
    print(
        "FATAL: the 'zipfile-deflate64' package is required to read the 2022/2023 DVSA "
        "results zips (zip compression method 9, Deflate64, unsupported by stdlib zipfile). "
        "Install it: cd pipeline && uv sync",
        file=sys.stderr,
    )
    sys.exit(1)

import zipfile

import duckdb

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "dvsa"
INTERIM = Path(__file__).resolve().parents[2] / "data" / "interim"
CSV_DIR = INTERIM / "dvsa_csv"
WAREHOUSE = Path(__file__).resolve().parents[2] / "data" / "warehouse.duckdb"

# which zips to use -- results_2024_alt/failure_item_2024_alt chosen only after
# compare_dvsa_2024.py confirms the old-naming files are a superseded/duplicated
# publication; flip back to results_2024.zip/failure_item_2024.zip if not.
RESULTS_ZIPS = ["results_2022.zip", "results_2023.zip", "results_2024_alt.zip", "results_2025.zip"]
FAILURE_ZIPS = ["failure_item_2022.zip", "failure_item_2023.zip", "failure_item_2024_alt.zip", "failure_item_2025.zip"]

# Per-zip file-shape properties -- see the FOUR-YEAR EXTENSION docstring note
# above for how each of these was verified. Keyed by zip filename, not year,
# so RESULTS_ZIPS/FAILURE_ZIPS and this table can never silently drift apart:
# every zip named above MUST have an entry here or loading raises a KeyError.
RESULTS_FILE_PROPS = {
    "results_2022.zip": {"delim": "|", "quote": "", "has_completed_date": False},
    "results_2023.zip": {"delim": "|", "quote": "", "has_completed_date": False},
    "results_2024_alt.zip": {"delim": ",", "quote": '"', "has_completed_date": True},
    "results_2025.zip": {"delim": ",", "quote": '"', "has_completed_date": True},
}
FAILURE_FILE_PROPS = {
    "failure_item_2022.zip": {"delim": "|", "quote": "", "has_completed_date": False, "location_col": "location_id"},
    "failure_item_2023.zip": {"delim": "|", "quote": "", "has_completed_date": False, "location_col": "location_id"},
    "failure_item_2024_alt.zip": {"delim": ",", "quote": '"', "has_completed_date": True, "location_col": "mot_test_rfr_location_type_id"},
    "failure_item_2025.zip": {"delim": ",", "quote": '"', "has_completed_date": True, "location_col": "mot_test_rfr_location_type_id"},
}

# Hard assertion, checked right after mot_tests is built: the test_class_id=4
# row count per calendar year, as independently verified by
# verify_dvsa_backyears.py / verify_dvsa_backyears_valuedomain.py before this
# script was pointed at the back years (see reports/dvsa_backyears_report.md).
# A future re-run that silently picks up a different/republished DVSA
# extract for one of these years will fail this loudly instead of producing
# quiet nonsense downstream -- the exact failure mode compare_dvsa_2024.py
# exists to catch for 2024 specifically; this generalises it to every year.
EXPECTED_CLASS4_COUNTS_BY_YEAR = {
    2022: 39_314_756,
    2023: 39_834_324,
    2024: 40_204_815,
    2025: 40_213_008,
}


def extract_csvs(zip_names: list[str], out_subdir: str) -> Path:
    out_dir = CSV_DIR / out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    for zip_name in zip_names:
        z = zipfile.ZipFile(RAW / zip_name)
        for member in z.namelist():
            if not member.endswith(".csv") or "__MACOSX" in member:
                continue
            target = out_dir / f"{zip_name}__{Path(member).name}"
            if target.exists():
                continue
            print(f"  extracting {zip_name}:{member} -> {target.name}")
            with z.open(member) as src, open(target, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
    return out_dir


def _read_csv_expr(glob: str, delim: str, quote: str) -> str:
    # quote='' (verified needed for 2022/2023, see module docstring) disables
    # quote interpretation entirely, so escape is meaningless in that case --
    # only pass escape='\' when a real quote char is in play, matching the
    # comma-delimited 2024/2025 vintage's backslash-escaping convention.
    escape_clause = "escape='\\', " if quote else ""
    return (f"read_csv('{glob}', delim='{delim}', {escape_clause}quote='{quote}', "
            f"all_varchar=true, header=true, union_by_name=true)")


def _results_union_sql(results_dir: Path, zip_names: list[str]) -> str:
    """Reads each results zip's extracted CSVs with ITS OWN verified shape
    (RESULTS_FILE_PROPS), projects every zip onto the same column list
    (synthesizing completed_date as NULL where the vintage doesn't carry
    one), and UNION ALLs them -- so the outer CAST/WHERE layer in main() sees
    one uniform-shaped result set no matter how many publication vintages
    are behind it."""
    parts = []
    for zip_name in zip_names:
        props = RESULTS_FILE_PROPS[zip_name]
        glob = str(results_dir / f"{zip_name}__*.csv")
        completed_date_expr = "completed_date" if props["has_completed_date"] else "CAST(NULL AS VARCHAR) AS completed_date"
        parts.append(f"""
            SELECT test_id, vehicle_id, test_date, test_class_id, test_type, test_result,
                   test_mileage, postcode_area, make, model, colour, fuel_type,
                   cylinder_capacity, first_use_date, {completed_date_expr}
            FROM {_read_csv_expr(glob, props['delim'], props['quote'])}
            WHERE test_result != 'test_result'
        """)
    return " UNION ALL ".join(parts)


def _failures_union_sql(failures_dir: Path, zip_names: list[str]) -> str:
    """Same idea as _results_union_sql, for the failure-item side: also
    aliases each vintage's location column onto the single canonical name
    mot_test_rfr_location_type_id (verified same 60-value code domain across
    vintages, see module docstring -- a rename, not a remap)."""
    parts = []
    for zip_name in zip_names:
        props = FAILURE_FILE_PROPS[zip_name]
        glob = str(failures_dir / f"{zip_name}__*.csv")
        completed_date_expr = "completed_date" if props["has_completed_date"] else "CAST(NULL AS VARCHAR) AS completed_date"
        parts.append(f"""
            SELECT test_id, rfr_id, rfr_type_code,
                   {props['location_col']} AS mot_test_rfr_location_type_id,
                   dangerous_mark, {completed_date_expr}
            FROM {_read_csv_expr(glob, props['delim'], props['quote'])}
            WHERE rfr_type_code != 'rfr_type_code'
        """)
    return " UNION ALL ".join(parts)


def main() -> None:
    INTERIM.mkdir(parents=True, exist_ok=True)

    print("extracting results CSVs...")
    results_dir = extract_csvs(RESULTS_ZIPS, "results")
    print("extracting failure item CSVs...")
    failures_dir = extract_csvs(FAILURE_ZIPS, "failures")

    con = duckdb.connect(str(WAREHOUSE))

    print(f"loading mot_tests from {len(RESULTS_ZIPS)} source zip(s) (test_class_id = 4 only)...")
    results_union = _results_union_sql(results_dir, RESULTS_ZIPS)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE mot_tests AS
        SELECT
            CAST(test_id AS BIGINT) AS test_id,
            CAST(vehicle_id AS BIGINT) AS vehicle_id,
            CAST(test_date AS DATE) AS test_date,
            CAST(test_class_id AS INTEGER) AS test_class_id,
            test_type,
            test_result,
            CAST(test_mileage AS DOUBLE) AS test_mileage,
            postcode_area,
            make,
            model,
            colour,
            fuel_type,
            CAST(cylinder_capacity AS INTEGER) AS cylinder_capacity,
            CAST(first_use_date AS DATE) AS first_use_date,
            CAST(completed_date AS TIMESTAMP) AS completed_date
        FROM ({results_union}) src
        WHERE test_class_id = '4'           -- passenger cars only (Phase 1 scope decision)
        """
    )
    n_tests = con.execute("SELECT COUNT(*) FROM mot_tests").fetchone()[0]
    print(f"mot_tests: {n_tests:,} rows")

    print("checking per-year row counts against verified expectations...")
    year_counts = dict(con.execute(
        "SELECT EXTRACT(year FROM test_date)::INTEGER, COUNT(*) FROM mot_tests GROUP BY 1 ORDER BY 1"
    ).fetchall())
    mismatches = []
    for year, expected in EXPECTED_CLASS4_COUNTS_BY_YEAR.items():
        actual = year_counts.get(year)
        status = "OK" if actual == expected else "MISMATCH"
        print(f"  {year}: expected {expected:,}, got {actual if actual is not None else 0:,} [{status}]")
        if actual != expected:
            mismatches.append((year, expected, actual))
    if mismatches:
        print(f"\nROW COUNT ASSERTION FAILED for {len(mismatches)} year(s): {mismatches}")
        print("This means the loaded DVSA data no longer matches what was independently verified "
              "before this loader was written (a republished/different extract, most likely) -- "
              "stopping rather than building metrics on top of an unverified row count.")
        con.close()
        sys.exit(1)
    print("all years match their independently verified row count.")

    print(f"loading raw failure items from {len(FAILURE_ZIPS)} source zip(s)...")
    failures_union = _failures_union_sql(failures_dir, FAILURE_ZIPS)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE _test_item_raw AS
        SELECT
            CAST(test_id AS BIGINT) AS test_id,
            CAST(rfr_id AS INTEGER) AS rfr_id,
            rfr_type_code,
            CAST(mot_test_rfr_location_type_id AS INTEGER) AS mot_test_rfr_location_type_id,
            dangerous_mark,
            CAST(completed_date AS TIMESTAMP) AS completed_date
        FROM ({failures_union}) src
        """
    )
    n_raw_failures = con.execute("SELECT COUNT(*) FROM _test_item_raw").fetchone()[0]
    print(f"raw failure items (before scoping to class-4 tests): {n_raw_failures:,} rows")

    lookup_dir = INTERIM / "dvsa_lookup"
    lookup_dir.mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(RAW / "lookup_tables.zip")
    for name in ["item_detail.csv", "item_group.csv"]:
        target = lookup_dir / name
        if not target.exists():
            with z.open(name) as src, open(target, "wb") as dst:
                dst.write(src.read())

    print("building failure_categories from item_detail + item_group...")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE failure_categories AS
        SELECT
            CAST(d.rfr_id AS INTEGER) AS rfr_id,
            CAST(d.test_class_id AS INTEGER) AS test_class_id,
            CAST(d.test_item_id AS INTEGER) AS test_item_id,
            d.minor_item,
            d.rfr_deficiency_category,
            d.rfr_desc,
            d.rfr_loc_marker,
            d.rfr_insp_manual_desc,
            d.rfr_advisory_text,
            g.item_name AS component_category
        FROM read_csv('{lookup_dir / "item_detail.csv"}', delim='|', header=true) d
        LEFT JOIN read_csv('{lookup_dir / "item_group.csv"}', delim='|', header=true) g
          ON CAST(d.test_item_id AS INTEGER) = CAST(g.test_item_id AS INTEGER)
         AND CAST(d.test_class_id AS INTEGER) = CAST(g.test_class_id AS INTEGER)
        """
    )
    n_cat = con.execute("SELECT COUNT(*) FROM failure_categories").fetchone()[0]
    print(f"failure_categories: {n_cat:,} rows")

    print("building mot_failures (scoped to class-4 tests, joined to categories)...")
    con.execute(
        """
        CREATE OR REPLACE TABLE mot_failures AS
        SELECT
            ti.test_id,
            ti.rfr_id,
            ti.rfr_type_code,
            ti.mot_test_rfr_location_type_id,
            ti.dangerous_mark,
            ti.completed_date,
            fc.component_category,
            fc.rfr_desc,
            fc.rfr_deficiency_category,
            fc.minor_item
        FROM _test_item_raw ti
        INNER JOIN mot_tests mt ON mt.test_id = ti.test_id
        LEFT JOIN failure_categories fc
          ON fc.rfr_id = ti.rfr_id AND fc.test_class_id = 4
        """
    )
    con.execute("DROP TABLE _test_item_raw")
    n_failures = con.execute("SELECT COUNT(*) FROM mot_failures").fetchone()[0]
    print(f"mot_failures: {n_failures:,} rows (scoped from {n_raw_failures:,} raw)")

    unmatched = con.execute(
        "SELECT COUNT(*) FROM mot_failures WHERE component_category IS NULL"
    ).fetchone()[0]
    print(f"mot_failures rows with no matching category: {unmatched:,} ({unmatched / n_failures * 100:.2f}%)")

    con.close()


if __name__ == "__main__":
    main()
