"""Second verification pass on the 2022/2023 DVSA back-year files, run after
verify_dvsa_backyears.py found the structural differences (Deflate64
compression, pipe delimiter, missing completed_date, location_id rename --
all per-file parameters that fail loudly if ignored).

This pass checks the dangerous class of difference instead: value-domain
differences in an older publication vintage that would fail SILENTLY and
corrupt the metrics without an error, because the loader would run to
completion and just count the wrong things.

Seven checks, both 2022 and 2023, against the live warehouse's 2024/2025 as
the reference vintage:
  1. rfr_type_code distinct values + counts -- build_phase3_metrics.py
     excludes advisories with rfr_type_code != 'A'; a different code scheme
     would silently reclassify advisories as failures.
  2. test_type distinct values + counts -- the metric filters test_type = 'NT'.
  3. test_result distinct values + counts -- confirms P/F/PRS/ABR/ABA/ABRVE
     appear with the same literal spelling the loader's CASE expressions match on.
  4. location_id value domain vs mot_test_rfr_location_type_id in 2024/2025,
     and against the lookup table (mdr_rfr_location.csv in lookup_tables.zip
     -- see note below on the filename).
  5. make/model string convention: top 200 (make, model) pairs by test count
     in 2022 vs 2025, overlap rate, and pairs unique to each vintage. The
     crosswalk was built against 2024/2025 strings.
  6. first_use_date/test_date format, and a test_mileage distribution
     comparison against 2025 to confirm the older vintage is still miles.
  7. vehicle_id stability across publication years: sampled vehicle_ids
     present in both the 2022 and 2025 files, checked for agreement on
     first_use_date/make/model/cylinder_capacity. The clocking filter in
     build_phase3_metrics.py assumes vehicle_id is a stable identifier for
     the same physical vehicle across years; if DVSA re-anonymises it per
     publication, that filter would misfire at every year boundary.

DEFLATE64: the 2022/2023 results zips use zip compression method 9, which
Python's stdlib zipfile cannot read. This script (and, going forward, the
warehouse loader) uses the `zipfile-deflate64` package, which installed
cleanly (added to pipeline/pyproject.toml) and patches stdlib zipfile in
place on import to add method-9 support -- confirmed by testing that plain
`import zipfile; zipfile.ZipFile(...)` works correctly for these files after
`import zipfile_deflate64` has run first, anywhere in the process. This was
chosen over shelling out to 7-Zip because it keeps the pipeline
reproducible on any machine with the venv installed, not just one with
7-Zip on PATH. If this import ever fails (package removed, wrong venv), the
right fix is reinstalling the dependency (`uv sync` from pipeline/), not a
silent fallback -- so this script fails loudly with an actionable message
rather than falling back to a partial extraction.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import zipfile_deflate64  # noqa: F401  -- patches stdlib zipfile for method 9 (Deflate64)
except ImportError:
    print(
        "FATAL: the 'zipfile-deflate64' package is required to read the 2022/2023 DVSA "
        "results zips (they use zip compression method 9, Deflate64, which Python's stdlib "
        "zipfile cannot decompress). Install it: cd pipeline && uv sync (or: uv add "
        "zipfile-deflate64). Refusing to silently fall back to a partial extraction.",
        file=sys.stderr,
    )
    sys.exit(1)

import duckdb  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dvsa_warehouse import extract_csvs, CSV_DIR  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "dvsa"
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"

YEARS = ["2022", "2023"]
KNOWN_RFR_TYPE_CODES = {"A", "F", "M", "P"}  # from the live 2024/2025 mot_failures table
KNOWN_TEST_RESULTS = {"P", "F", "PRS", "ABR", "ABA", "ABRVE"}


def main() -> None:
    print("extracting 2022/2023 CSVs (pipe-delimited, Deflate64 results) via zipfile_deflate64...")
    results_dir = extract_csvs([f"results_{y}.zip" for y in YEARS], "results")
    failures_dir = extract_csvs([f"failure_item_{y}.zip" for y in YEARS], "failures")

    # 2025 raw extracted CSVs are already on disk from the original Phase 1
    # build (comma-delimited, 15/6 columns) -- used as the reference vintage
    # throughout, since it is verified-good and not itself part of the
    # 2024-alt-vs-2024 confusion compare_dvsa_2024.py resolved.
    ref_results_glob = str(results_dir / "results_2025.zip__*.csv")
    ref_failures_glob = str(failures_dir / "failure_item_2025.zip__*.csv")
    if not list(results_dir.glob("results_2025.zip__*.csv")):
        print(f"FATAL: expected 2025 results CSVs already extracted at {results_dir}, none found.")
        sys.exit(1)

    con = duckdb.connect(":memory:")

    def read_results(glob: str, delim: str, quote: str = '"') -> str:
        # 2022/2023 (pipe-delimited) do NOT use backslash-quote-escaping like
        # 2024/2025 do -- checked, 0 occurrences of a backslash before a
        # quote in either file. They DO contain a handful of literal,
        # unescaped double-quote characters inside model names (32 rows in
        # 2022, 40 in 2023, e.g. a vintage HUPMOBILE model recorded as
        # '"A"  COUPE'), which trips DuckDB's strict quote-matching when
        # quote='"' is set. Since the delimiter is '|' and no field
        # legitimately needs CSV quoting to embed a literal pipe, quote=''
        # (quoting disabled entirely, every quote char read as a literal
        # character) is the correct setting for the pipe-delimited files --
        # passed in by the caller for that case; the comma-delimited 2025
        # reference keeps the original quote='"'/escape='\' behaviour
        # build_dvsa_warehouse.py uses.
        escape_clause = "escape='\\', " if quote else ""
        return (f"read_csv('{glob}', delim='{delim}', {escape_clause}quote='{quote}', "
                f"all_varchar=true, header=true, union_by_name=true)")

    con.execute(f"""
        CREATE TABLE ref_results AS
        SELECT * FROM {read_results(ref_results_glob, ',')}
        WHERE test_result != 'test_result'
    """)
    con.execute(f"""
        CREATE TABLE ref_failures AS
        SELECT * FROM {read_results(ref_failures_glob, ',')}
        WHERE rfr_type_code != 'rfr_type_code'
    """)

    for year in YEARS:
        print(f"\n{'=' * 70}\nYEAR {year} -- value domain checks\n{'=' * 70}")

        r_glob = str(results_dir / f"results_{year}.zip__*.csv")
        f_glob = str(failures_dir / f"failure_item_{year}.zip__*.csv")
        con.execute(f"CREATE OR REPLACE TABLE yr_results AS SELECT * FROM {read_results(r_glob, '|', quote='')} "
                    f"WHERE test_result != 'test_result'")
        con.execute(f"CREATE OR REPLACE TABLE yr_failures AS SELECT * FROM {read_results(f_glob, '|', quote='')} "
                    f"WHERE rfr_type_code != 'rfr_type_code'")

        # --- check 1: rfr_type_code -------------------------------------
        print(f"\n[check 1] rfr_type_code distinct values, {year}:")
        codes = con.execute("SELECT rfr_type_code, COUNT(*) FROM yr_failures GROUP BY 1 ORDER BY 2 DESC").fetchall()
        seen_codes = set()
        for code, n in codes:
            seen_codes.add(code)
            print(f"    {code!r}: {n:,}")
        unknown = seen_codes - KNOWN_RFR_TYPE_CODES
        if unknown:
            print(f"  !! UNKNOWN rfr_type_code values not in 2024/2025's set {KNOWN_RFR_TYPE_CODES}: {unknown}")
        else:
            print(f"  all values are within the known 2024/2025 set {KNOWN_RFR_TYPE_CODES}")

        # --- check 2: test_type -------------------------------------------
        print(f"\n[check 2] test_type distinct values, {year}:")
        for tt, n in con.execute("SELECT test_type, COUNT(*) FROM yr_results GROUP BY 1 ORDER BY 2 DESC").fetchall():
            print(f"    {tt!r}: {n:,}")

        # --- check 3: test_result ------------------------------------------
        print(f"\n[check 3] test_result distinct values, {year}:")
        results_vals = con.execute("SELECT test_result, COUNT(*) FROM yr_results GROUP BY 1 ORDER BY 2 DESC").fetchall()
        seen_results = set()
        for tr, n in results_vals:
            seen_results.add(tr)
            print(f"    {tr!r}: {n:,}")
        missing_known = KNOWN_TEST_RESULTS - seen_results
        unknown_results = seen_results - KNOWN_TEST_RESULTS
        print(f"  known codes present: {KNOWN_TEST_RESULTS & seen_results}")
        if missing_known:
            print(f"  known codes NOT seen in {year} (may just mean zero of that outcome this year): {missing_known}")
        if unknown_results:
            print(f"  !! UNKNOWN test_result values not in the reference set: {unknown_results}")

        # --- check 4: location_id vs mot_test_rfr_location_type_id -------
        print(f"\n[check 4] location_id domain, {year}, vs 2024/2025's mot_test_rfr_location_type_id:")
        yr_locs = set(r[0] for r in con.execute(
            "SELECT DISTINCT location_id FROM yr_failures WHERE location_id != ''"
        ).fetchall())
        ref_locs = set(r[0] for r in con.execute(
            "SELECT DISTINCT mot_test_rfr_location_type_id FROM ref_failures "
            "WHERE mot_test_rfr_location_type_id != ''"
        ).fetchall())
        print(f"  {year} distinct location_id values: {len(yr_locs)}")
        print(f"  2025 distinct mot_test_rfr_location_type_id values: {len(ref_locs)}")
        not_in_ref = yr_locs - ref_locs
        print(f"  {year} values absent from 2025's domain: {len(not_in_ref)} "
              f"{sorted(not_in_ref)[:20] if not_in_ref else ''}")
        lookup_path = ROOT / "data" / "interim" / "dvsa_lookup" / "mdr_rfr_location.csv"
        if lookup_path.exists():
            lookup_ids = set(r[0] for r in con.execute(
                f"SELECT DISTINCT id FROM read_csv('{lookup_path.as_posix()}', delim='|', header=true, all_varchar=true)"
            ).fetchall())
            not_in_lookup = yr_locs - lookup_ids
            print(f"  lookup table (mdr_rfr_location.csv) has {len(lookup_ids)} ids; "
                  f"{year} values absent from it: {len(not_in_lookup)} "
                  f"{sorted(not_in_lookup)[:20] if not_in_lookup else ''}")
        else:
            print(f"  lookup table not found at {lookup_path} -- extract lookup_tables.zip first")

        # --- check 5: make/model string convention -------------------------
        print(f"\n[check 5] top-200 (make, model) overlap, {year} vs 2025 (by test count):")
        top_yr = con.execute(
            "SELECT make, model, COUNT(*) AS n FROM yr_results GROUP BY 1, 2 ORDER BY n DESC LIMIT 200"
        ).fetchall()
        top_ref = con.execute(
            "SELECT make, model, COUNT(*) AS n FROM ref_results GROUP BY 1, 2 ORDER BY n DESC LIMIT 200"
        ).fetchall()
        set_yr = {(m, mo) for m, mo, n in top_yr}
        set_ref = {(m, mo) for m, mo, n in top_ref}
        overlap = set_yr & set_ref
        only_yr = set_yr - set_ref
        only_ref = set_ref - set_yr
        print(f"  overlap: {len(overlap)} / 200 ({len(overlap) / 200 * 100:.1f}%)")
        print(f"  present in {year}'s top 200 but not 2025's: {len(only_yr)}")
        for m, mo in sorted(only_yr):
            print(f"    {m} / {mo}")
        print(f"  present in 2025's top 200 but not {year}'s: {len(only_ref)}")
        for m, mo in sorted(only_ref):
            print(f"    {m} / {mo}")

        # --- check 6: date formats + mileage units --------------------------
        print(f"\n[check 6] date format + test_mileage distribution, {year}:")
        sample_dates = con.execute("SELECT test_date, first_use_date FROM yr_results LIMIT 5").fetchall()
        print(f"  sample (test_date, first_use_date): {sample_dates}")
        yr_mileage = con.execute(
            "SELECT MIN(TRY_CAST(test_mileage AS DOUBLE)), "
            "quantile_cont(TRY_CAST(test_mileage AS DOUBLE), 0.5), "
            "AVG(TRY_CAST(test_mileage AS DOUBLE)), "
            "MAX(TRY_CAST(test_mileage AS DOUBLE)) "
            "FROM yr_results WHERE test_class_id = '4'"
        ).fetchone()
        ref_mileage = con.execute(
            "SELECT MIN(TRY_CAST(test_mileage AS DOUBLE)), "
            "quantile_cont(TRY_CAST(test_mileage AS DOUBLE), 0.5), "
            "AVG(TRY_CAST(test_mileage AS DOUBLE)), "
            "MAX(TRY_CAST(test_mileage AS DOUBLE)) "
            "FROM ref_results WHERE test_class_id = '4'"
        ).fetchone()
        print(f"  {year} test_mileage (class 4): min={yr_mileage[0]:,.0f} median={yr_mileage[1]:,.0f} "
              f"mean={yr_mileage[2]:,.0f} max={yr_mileage[3]:,.0f}")
        print(f"  2025  test_mileage (class 4): min={ref_mileage[0]:,.0f} median={ref_mileage[1]:,.0f} "
              f"mean={ref_mileage[2]:,.0f} max={ref_mileage[3]:,.0f}")
        ratio = yr_mileage[2] / ref_mileage[2] if ref_mileage[2] else None
        print(f"  mean ratio {year}/2025: {ratio:.3f}" if ratio else "  ratio: n/a")

        # --- check 7: vehicle_id stability across vintages ------------------
        print(f"\n[check 7] vehicle_id stability, {year} vs 2025 (class 4 only):")
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE yr_veh AS
            SELECT vehicle_id, ANY_VALUE(make) AS make, ANY_VALUE(model) AS model,
                   ANY_VALUE(first_use_date) AS first_use_date,
                   ANY_VALUE(cylinder_capacity) AS cylinder_capacity,
                   COUNT(DISTINCT make || '|' || model || '|' || first_use_date || '|' || cylinder_capacity) AS n_distinct_combos
            FROM yr_results WHERE test_class_id = '4'
            GROUP BY vehicle_id
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE ref_veh AS
            SELECT vehicle_id, ANY_VALUE(make) AS make, ANY_VALUE(model) AS model,
                   ANY_VALUE(first_use_date) AS first_use_date,
                   ANY_VALUE(cylinder_capacity) AS cylinder_capacity,
                   COUNT(DISTINCT make || '|' || model || '|' || first_use_date || '|' || cylinder_capacity) AS n_distinct_combos
            FROM ref_results WHERE test_class_id = '4'
            GROUP BY vehicle_id
        """)
        within_year_unstable_yr = con.execute("SELECT COUNT(*) FROM yr_veh WHERE n_distinct_combos > 1").fetchone()[0]
        within_year_unstable_ref = con.execute("SELECT COUNT(*) FROM ref_veh WHERE n_distinct_combos > 1").fetchone()[0]
        print(f"  {year}: {within_year_unstable_yr:,} vehicle_ids with inconsistent attributes WITHIN the same year's file")
        print(f"  2025: {within_year_unstable_ref:,} vehicle_ids with inconsistent attributes WITHIN the same year's file")

        joined = con.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN y.make = r.make THEN 1 ELSE 0 END),
                   SUM(CASE WHEN y.model = r.model THEN 1 ELSE 0 END),
                   SUM(CASE WHEN y.first_use_date = r.first_use_date THEN 1 ELSE 0 END),
                   SUM(CASE WHEN y.cylinder_capacity = r.cylinder_capacity THEN 1 ELSE 0 END),
                   SUM(CASE WHEN y.make = r.make AND y.model = r.model
                             AND y.first_use_date = r.first_use_date
                             AND y.cylinder_capacity = r.cylinder_capacity THEN 1 ELSE 0 END)
            FROM yr_veh y JOIN ref_veh r ON y.vehicle_id = r.vehicle_id
        """).fetchone()
        n_joined, n_make, n_model, n_fud, n_cc, n_all = joined
        n_yr_total = con.execute("SELECT COUNT(*) FROM yr_veh").fetchone()[0]
        print(f"  {year} distinct vehicle_ids (class 4): {n_yr_total:,}")
        print(f"  vehicle_ids present in BOTH {year} and 2025: {n_joined:,} "
              f"({n_joined / n_yr_total * 100:.1f}% of {year}'s)")
        if n_joined:
            print(f"    agree on make: {n_make:,} ({n_make / n_joined * 100:.2f}%)")
            print(f"    agree on model: {n_model:,} ({n_model / n_joined * 100:.2f}%)")
            print(f"    agree on first_use_date: {n_fud:,} ({n_fud / n_joined * 100:.2f}%)")
            print(f"    agree on cylinder_capacity: {n_cc:,} ({n_cc / n_joined * 100:.2f}%)")
            print(f"    agree on ALL FOUR: {n_all:,} ({n_all / n_joined * 100:.2f}%)")
            if n_all / n_joined < 0.98:
                print(f"  !! vehicle_id does NOT look stable across vintages for {year} -- "
                      f"clocking filter would need to be applied within test year only")
            else:
                print(f"  vehicle_id looks STABLE across vintages for {year}")

    con.close()


if __name__ == "__main__":
    main()
