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

Scope decision (Opus review, Phase 1 handover): mot_tests is restricted to
test_class_id = 4 (the passenger-car class, ~94% of rows) at load time, since
that's the project's vehicle scope throughout. mot_failures is implicitly
scoped to the same tests via the join to mot_tests.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "dvsa"
INTERIM = Path(__file__).resolve().parents[2] / "data" / "interim"
CSV_DIR = INTERIM / "dvsa_csv"
WAREHOUSE = Path(__file__).resolve().parents[2] / "data" / "warehouse.duckdb"

# which zips to use -- results_2024_alt/failure_item_2024_alt chosen only after
# compare_dvsa_2024.py confirms the old-naming files are a superseded/duplicated
# publication; flip back to results_2024.zip/failure_item_2024.zip if not.
RESULTS_ZIPS = ["results_2024_alt.zip", "results_2025.zip"]
FAILURE_ZIPS = ["failure_item_2024_alt.zip", "failure_item_2025.zip"]


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


def main() -> None:
    INTERIM.mkdir(parents=True, exist_ok=True)

    print("extracting results CSVs...")
    results_dir = extract_csvs(RESULTS_ZIPS, "results")
    print("extracting failure item CSVs...")
    failures_dir = extract_csvs(FAILURE_ZIPS, "failures")

    con = duckdb.connect(str(WAREHOUSE))

    results_glob = str(results_dir / "*.csv")
    print(f"loading mot_tests from {results_glob} (test_class_id = 4 only)...")
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
        FROM read_csv('{results_glob}', escape='\\', quote='"', all_varchar=true, header=true, union_by_name=true)
        WHERE test_result != 'test_result'  -- drop embedded header-echo rows
          AND test_class_id = '4'           -- passenger cars only (Phase 1 scope decision)
        """
    )
    n_tests = con.execute("SELECT COUNT(*) FROM mot_tests").fetchone()[0]
    print(f"mot_tests: {n_tests:,} rows")

    failures_glob = str(failures_dir / "*.csv")
    print(f"loading raw failure items from {failures_glob}...")
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
        FROM read_csv('{failures_glob}', escape='\\', quote='"', all_varchar=true, header=true, union_by_name=true)
        WHERE rfr_type_code != 'rfr_type_code'  -- drop embedded header-echo rows
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
