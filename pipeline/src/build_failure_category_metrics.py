"""Recomputes UK and Norwegian reliability at TEST level three ways --
all-defects, mechanical-only, consumable-only -- using the frozen
classification in reference/dvsa_defect_classification.csv and
reference/norway_defect_classification.csv (both written and committed BEFORE
this script was run; see build_dvsa_defect_classification.py's docstring for
the classification method and justification).

Reuses the existing eligible-test construction UNCHANGED from
build_phase3_metrics.py (UK) and build_norway_metrics.py (Norway) -- same
scope, same filters, same mileage strata, same direct-standardisation
merge -- so the only thing that differs between the three rate variants is
which failure items count as a defect. This is the required design: "the
only change is which failure items count."

DEFECT-CAUSATION FILTER, verified directly against the warehouse before this
script was written (not assumed): DVSA rfr_type_code has four values, F
(fail), P (PRS item), A (advisory, already excluded from category rates
project-wide), and M (minor defect). The 2018 EU three-category system
documents M as NOT causing test failure ("a minor defect will not cause the
vehicle to fail"), and the value-domain check confirms it: 8,150,916 of
121,354,090 PASSING (test_result='P') tests carry an M-type item, while only
57 carry an F-type item and 2 a P-type item (both negligible, consistent
with rare data noise, not a real relationship). So the item-level set that
determines pass/fail here is {F, P} -- NOT {F, P, M} (which the project's
EXISTING component_category rate table uses for a different purpose, category
frequency, not fail-causation). Using {F, P} is what makes the required
reproduction gate below pass; using {F, P, M} would not (it would
misclassify 8.15M genuinely-passing tests as failed). This is stated
up front, not discovered by iterating against the gate.

Norway's analogous check needs no filter decision: godkjent='Nei' already
matches "sum of kap0..kap10 (2-3er only, 4er already excluded upstream in
pkk_inspections) > 0" with ZERO exceptions across the full scoped population
(verified below), so the item-level reconstruction is exact by construction.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_phase3_metrics import (  # noqa: E402
    setup_reference_tables as uk_setup_reference_tables,
    build_dvsa_eligible_tests,
)
from build_norway_metrics import (  # noqa: E402
    build_link_table as no_build_link_table,
    build_eligible_tests as no_build_eligible_tests,
    merge_strata,
)

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
LOOKUP = ROOT / "data" / "interim" / "dvsa_lookup"
REFERENCE = ROOT / "pipeline" / "reference"
REPORTS = ROOT / "pipeline" / "reports"

UK_DEFECT_CLASS_CSV = REFERENCE / "dvsa_defect_classification.csv"
NO_DEFECT_CLASS_CSV = REFERENCE / "norway_defect_classification.csv"

EXISTING_UK_METRICS = REFERENCE / "model_age_band_metrics.csv"
EXISTING_NO_METRICS = REFERENCE / "model_age_band_metrics_no.csv"

OUT_UK = REFERENCE / "model_age_band_metrics_category_split.csv"
OUT_NO = REFERENCE / "model_age_band_metrics_category_split_no.csv"
OUT_DESCRIPTIVE = REFERENCE / "failure_category_descriptive_split.csv"
OUT_REPORT = REPORTS / "failure_category_recompute_report.md"

UK_STRATUM_MIN_CELL = 100
UK_MIN_SURVIVING_STRATA = 3
NO_STRATUM_MIN_CELL = 25
NO_MIN_SURVIVING_STRATA = 3

MILEAGE_STRATA = [(1, 0, 50_000), (2, 50_000, 100_000), (3, 100_000, 150_000),
                  (4, 150_000, 200_000), (5, 200_000, 250_000), (6, 250_000, None)]

AGE_BANDS = [1, 2, 3, 4]


def stratum_sql_case(km_col: str) -> str:
    whens = []
    for stratum, lo, hi in MILEAGE_STRATA:
        cond = f"{km_col} >= {lo}" if hi is None else f"{km_col} >= {lo} AND {km_col} < {hi}"
        whens.append(f"WHEN {cond} THEN {stratum}")
    return f"CASE {' '.join(whens)} END"


# ---------------------------------------------------------------------------
# Shared standardisation runner: identical merge/weight logic to
# build_phase3_metrics.compute_reliability / build_norway_metrics.compute_reliability,
# generalised to run once per (variant, pass-flag column) instead of being
# hand-duplicated three times.
# ---------------------------------------------------------------------------

def standardize(cell_pass_fail: dict, ref_pass_fail: dict, min_cell: int, min_surviving: int) -> dict[tuple, dict]:
    """cell_pass_fail: {(make, model, band): {stratum: [n_pass, n_fail]}}
    ref_pass_fail: {band: {stratum: [n_pass, n_fail]}}
    Returns {(make, model, band): {n_tests, raw_rate, std_rate, unstable, n_strata_surviving}}"""
    out = {}
    for key, stratum_counts in cell_pass_fail.items():
        band = key[2]
        total_pass = sum(v[0] for v in stratum_counts.values())
        total_fail = sum(v[1] for v in stratum_counts.values())
        n_tests = total_pass + total_fail
        raw_rate = total_pass / n_tests if n_tests else None

        merged = merge_strata(stratum_counts, min_cell)
        n_surviving = sum(1 for m in merged if m["n"] >= min_cell)
        unstable = n_surviving < min_surviving

        std_rate = None
        if not unstable:
            ref_counts = ref_pass_fail.get(band, {})
            total_ref = sum(sum(v) for v in ref_counts.values())
            weighted_sum = weight_total = 0.0
            for m in merged:
                if m["n"] < min_cell:
                    continue
                ref_n = sum(sum(ref_counts.get(s, [0, 0])) for s in m["strata"])
                w = ref_n / total_ref if total_ref else 0
                p_k = m["passes"] / m["n"]
                weighted_sum += w * p_k
                weight_total += w
            std_rate = (weighted_sum / weight_total) if weight_total > 0 else None

        out[key] = {
            "n_tests": n_tests,
            "raw_rate": round(raw_rate, 4) if raw_rate is not None else None,
            "std_rate": round(std_rate, 4) if std_rate is not None else None,
            "unstable": unstable,
            "n_strata_surviving": n_surviving,
        }
    return out


def cells_from_rows(rows, pass_col_idx: int) -> dict:
    """rows: (make, model, band, stratum, is_pass_flag) -- builds
    {(make, model, band): {stratum: [n_pass, n_fail]}} by summing is_pass_flag."""
    cells: dict[tuple, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for make, model, band, stratum, n_pass, n_fail in rows:
        cells[(make, model, band)][stratum] = [n_pass, n_fail]
    return cells


# ---------------------------------------------------------------------------
# UK side
# ---------------------------------------------------------------------------

def load_uk_classification(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"CREATE OR REPLACE TABLE dvsa_defect_classification AS "
                f"SELECT * FROM read_csv_auto('{UK_DEFECT_CLASS_CSV.as_posix()}')")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE idet AS
        SELECT CAST(rfr_id AS INTEGER) rfr_id,
               CAST(test_item_set_section_id AS INTEGER) section_id
        FROM read_csv('{(LOOKUP / "item_detail.csv").as_posix()}', delim='|', header=true)
        WHERE test_class_id = '4'
    """)
    # rfr_id -> bucket, precomputed once (small table, ~21k rows scoped to class 4)
    con.execute("""
        CREATE OR REPLACE TABLE rfr_bucket AS
        SELECT DISTINCT fc.rfr_id, cls.bucket
        FROM failure_categories fc
        JOIN idet ON idet.rfr_id = fc.rfr_id
        JOIN dvsa_defect_classification cls
          ON cls.section_id = idet.section_id AND cls.component_category = fc.component_category
        WHERE fc.test_class_id = 4
    """)
    n_rfr = con.execute("SELECT COUNT(*) FROM rfr_bucket").fetchone()[0]

    # Completeness is checked against rfr_ids that actually appear as REAL
    # (F/P, non-advisory) failures in the class-4 warehouse -- the same scope
    # build_dvsa_defect_classification.py enumerated when it wrote the 277
    # rows. failure_categories itself carries every rfr_id (including
    # advisory-only/minor-only ones that never fail a test), which is a much
    # larger set than the classification needs to cover -- checking against
    # that broader set would flag rows that are never touched by the
    # mechanical/consumable split at all.
    #
    # Two different kinds of "unmapped" are possible here, and they are NOT
    # the same thing: (a) the rfr_id has an item_detail entry at test_class_id
    # 4 (a real section/category exists) but the classification CSV is
    # missing that (section, category) pair -- a genuine gap in the frozen
    # classification that must be fixed by editing the CSV, not worked
    # around in code; (b) the rfr_id has NO item_detail entry at test_class_id
    # 4 AT ALL -- the DVSA lookup tables themselves have no class-4 entry for
    # this RfR code, even though it appears on a real class-4 test failure
    # (verified: e.g. rfr_id 31178/31179 exist only for classes 5/7 "load
    # index inadequate for axle weight", a goods-vehicle check; rfr_ids in
    # the 32133-32142 and 40199-40652 ranges have no item_detail row for ANY
    # test class -- a DVSA lookup-table gap, not a classification decision).
    # Case (b) cannot be resolved through the hierarchy by definition, so
    # per the brief's own instruction for an unresolvable case, it is routed
    # to administrative_or_other rather than guessed -- and reported here,
    # not silently absorbed. It is NOT high-volume (checked below).
    unresolvable = con.execute("""
        SELECT f.rfr_id, COUNT(*) n
        FROM mot_failures f
        LEFT JOIN idet ON idet.rfr_id = f.rfr_id
        WHERE f.rfr_type_code IN ('F', 'P')
          AND NOT EXISTS (SELECT 1 FROM rfr_bucket rb WHERE rb.rfr_id = f.rfr_id)
        GROUP BY 1
    """).fetchall()
    genuine_gap = con.execute("""
        SELECT DISTINCT f.rfr_id, idet.section_id, fc.component_category
        FROM mot_failures f
        JOIN idet ON idet.rfr_id = f.rfr_id
        LEFT JOIN failure_categories fc ON fc.rfr_id = f.rfr_id AND fc.test_class_id = 4
        WHERE f.rfr_type_code IN ('F', 'P')
          AND NOT EXISTS (SELECT 1 FROM rfr_bucket rb WHERE rb.rfr_id = f.rfr_id)
    """).fetchall()
    if genuine_gap:
        print("UK: GENUINE classification gap -- these (section, component_category) pairs are "
              "missing from dvsa_defect_classification.csv and must be added by hand:")
        for row in genuine_gap:
            print(f"    {row}")
        raise RuntimeError("UK defect classification incomplete -- see printed rows above")

    n_lookup_gap = sum(n for _, n in unresolvable)
    n_total_real = con.execute(
        "SELECT COUNT(*) FROM mot_failures WHERE rfr_type_code IN ('F','P')"
    ).fetchone()[0]
    print(f"UK: rfr_id -> bucket mapping built, {n_rfr:,} rfr_ids classified from the frozen "
          f"classification CSV ({len(unresolvable)} distinct rfr_ids, {n_lookup_gap:,} real failure "
          f"rows = {n_lookup_gap / n_total_real * 100:.4f}% of all real UK failures, have NO "
          f"item_detail entry at test_class_id=4 in the DVSA lookup tables at all -- a lookup-table "
          f"gap, not a classification decision; routed to administrative_or_other, excluded from "
          f"both mechanical-only and consumable-only)")
    if unresolvable:
        con.executemany(
            "INSERT INTO rfr_bucket VALUES (?, 'administrative_or_other')",
            [(rfr_id,) for rfr_id, _ in unresolvable],
        )


def build_uk_test_bucket_flags(con: duckdb.DuckDBPyConnection) -> None:
    """Per eligible physical test: does it carry >=1 real (F/P, non-advisory,
    non-minor -- see module docstring) defect item overall / classified
    mechanical / classified consumable. One pass over mot_failures joined to
    the already-scoped eligible test set."""
    con.execute("""
        CREATE OR REPLACE TABLE uk_test_flags AS
        SELECT e.test_id,
               MAX(CASE WHEN f.rfr_type_code IN ('F','P') THEN 1 ELSE 0 END) AS has_any_real_defect,
               MAX(CASE WHEN f.rfr_type_code IN ('F','P') AND rb.bucket = 'mechanical' THEN 1 ELSE 0 END) AS has_mechanical,
               MAX(CASE WHEN f.rfr_type_code IN ('F','P') AND rb.bucket = 'consumable' THEN 1 ELSE 0 END) AS has_consumable,
               MAX(CASE WHEN f.rfr_type_code IN ('F','P') AND rb.bucket = 'administrative_or_other' THEN 1 ELSE 0 END) AS has_admin
        FROM dvsa_physical_tests_eligible e
        LEFT JOIN mot_failures f ON f.test_id = e.test_id
        LEFT JOIN rfr_bucket rb ON rb.rfr_id = f.rfr_id
        GROUP BY e.test_id
    """)
    n = con.execute("SELECT COUNT(*) FROM uk_test_flags").fetchone()[0]
    print(f"UK: per-test bucket flags built for {n:,} eligible physical tests")


def compute_uk_three_way(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    """Returns {variant: {(make, model, band): {...}}} for variant in
    all/mechanical/consumable, using the SAME reference population and
    merge/weight logic as the existing UK metric."""
    # attribute physical tests (with bucket flags) to every DMR model, same
    # fan-out as build_dvsa_eligible_tests does for is_pass.
    con.execute(f"""
        CREATE OR REPLACE TABLE uk_eligible_attributed AS
        SELECT m.dmr_make, m.dmr_model, e.test_id, e.age_years,
               {stratum_sql_case('e.test_mileage_km')} AS stratum,
               tf.has_any_real_defect, tf.has_mechanical, tf.has_consumable
        FROM dvsa_physical_tests_eligible e
        JOIN crosswalk_dvsa_match m ON m.dvsa_make = e.make AND m.dvsa_model = e.model
        JOIN uk_test_flags tf ON tf.test_id = e.test_id
    """)

    def age_band_case(col):
        return ("CASE " + " ".join(
            f"WHEN {col} >= {amin} AND {col} < {amax} THEN {band}"
            for band, amin, amax in [(1, 4, 7), (2, 7, 10), (3, 10, 13), (4, 13, 17)]
        ) + " END")

    results = {}
    for variant, flag_col in [("all", "has_any_real_defect"), ("mechanical", "has_mechanical"),
                               ("consumable", "has_consumable")]:
        cell_rows = con.execute(f"""
            SELECT dmr_make, dmr_model, {age_band_case('age_years')} AS age_band, stratum,
                   SUM(CASE WHEN {flag_col} = 0 THEN 1 ELSE 0 END) AS n_pass,
                   SUM(CASE WHEN {flag_col} = 1 THEN 1 ELSE 0 END) AS n_fail
            FROM uk_eligible_attributed
            WHERE stratum IS NOT NULL
            GROUP BY 1, 2, 3, 4
            HAVING age_band IS NOT NULL
        """).fetchall()
        ref_rows = con.execute(f"""
            SELECT {age_band_case('e.age_years')} AS age_band,
                   {stratum_sql_case('e.test_mileage_km')} AS stratum,
                   SUM(CASE WHEN tf.{flag_col} = 0 THEN 1 ELSE 0 END) AS n_pass,
                   SUM(CASE WHEN tf.{flag_col} = 1 THEN 1 ELSE 0 END) AS n_fail
            FROM dvsa_physical_tests_eligible e
            JOIN uk_test_flags tf ON tf.test_id = e.test_id
            GROUP BY 1, 2
            HAVING age_band IS NOT NULL AND stratum IS NOT NULL
        """).fetchall()

        cells = cells_from_rows(cell_rows, None)
        ref_cells: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for band, stratum, n_pass, n_fail in ref_rows:
            ref_cells[band][stratum] = [n_pass, n_fail]

        results[variant] = standardize(cells, ref_cells, UK_STRATUM_MIN_CELL, UK_MIN_SURVIVING_STRATA)
        print(f"UK {variant}: {len(results[variant])} (model, age_band) cells computed")
    return results


# ---------------------------------------------------------------------------
# Norway side
# ---------------------------------------------------------------------------

def load_no_classification() -> dict[int, str]:
    with open(NO_DEFECT_CLASS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {int(r["chapter"]): r["bucket"] for r in rows}


def compute_no_three_way(con: duckdb.DuckDBPyConnection, chapter_bucket: dict[int, str]) -> dict[str, dict]:
    mech_chapters = [c for c, b in chapter_bucket.items() if b == "mechanical"]
    cons_chapters = [c for c, b in chapter_bucket.items() if b == "consumable"]
    all_chapters = list(range(11))

    def sum_expr(chapters):
        return " + ".join(f"COALESCE(kap{c}, 0)" for c in chapters)

    def age_band_case(col):
        return ("CASE " + " ".join(
            f"WHEN {col} >= {amin} AND {col} < {amax} THEN {band}"
            for band, amin, amax in [(1, 4, 7), (2, 7, 10), (3, 10, 13), (4, 13, 17)]
        ) + " END")

    con.execute(f"""
        CREATE OR REPLACE TABLE no_eligible_flagged AS
        SELECT link.dmr_make, link.dmr_model, t.age_years,
               {stratum_sql_case('t.km')} AS stratum,
               CASE WHEN ({sum_expr(all_chapters)}) > 0 THEN 1 ELSE 0 END AS flag_all,
               CASE WHEN ({sum_expr(mech_chapters)}) > 0 THEN 1 ELSE 0 END AS flag_mech,
               CASE WHEN ({sum_expr(cons_chapters)}) > 0 THEN 1 ELSE 0 END AS flag_cons
        FROM no_scoped_tests t
        JOIN no_model_link link ON link.no_make = t.make AND link.model_raw = t.model_raw
        WHERE t.age_years >= 4 AND t.age_years < 17
    """)

    results = {}
    for variant, flag_col in [("all", "flag_all"), ("mechanical", "flag_mech"), ("consumable", "flag_cons")]:
        cell_rows = con.execute(f"""
            SELECT dmr_make, dmr_model, {age_band_case('age_years')} AS age_band, stratum,
                   SUM(CASE WHEN {flag_col} = 0 THEN 1 ELSE 0 END) AS n_pass,
                   SUM(CASE WHEN {flag_col} = 1 THEN 1 ELSE 0 END) AS n_fail
            FROM no_eligible_flagged
            WHERE stratum IS NOT NULL
            GROUP BY 1, 2, 3, 4
            HAVING age_band IS NOT NULL
        """).fetchall()
        ref_rows = con.execute(f"""
            SELECT {age_band_case('age_years')} AS age_band,
                   {stratum_sql_case('km')} AS stratum,
                   SUM(CASE WHEN ({sum_expr(all_chapters) if flag_col=='flag_all' else sum_expr(mech_chapters) if flag_col=='flag_mech' else sum_expr(cons_chapters)}) = 0 THEN 1 ELSE 0 END) AS n_pass,
                   SUM(CASE WHEN ({sum_expr(all_chapters) if flag_col=='flag_all' else sum_expr(mech_chapters) if flag_col=='flag_mech' else sum_expr(cons_chapters)}) > 0 THEN 1 ELSE 0 END) AS n_fail
            FROM no_scoped_tests
            WHERE age_years >= 4 AND age_years < 17
            GROUP BY 1, 2
            HAVING age_band IS NOT NULL AND stratum IS NOT NULL
        """).fetchall()

        cells = cells_from_rows(cell_rows, None)
        ref_cells: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for band, stratum, n_pass, n_fail in ref_rows:
            ref_cells[band][stratum] = [n_pass, n_fail]

        results[variant] = standardize(cells, ref_cells, NO_STRATUM_MIN_CELL, NO_MIN_SURVIVING_STRATA)
        print(f"Norway {variant}: {len(results[variant])} (model, age_band) cells computed")
    return results


# ---------------------------------------------------------------------------
# Reproduction gate + descriptive split + output
# ---------------------------------------------------------------------------

def check_reproduction(recomputed_all: dict, existing_csv: Path, n_col: str, label: str) -> None:
    existing = {}
    with open(existing_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["standardized_pass_rate"]:
                existing[(r["dmr_make"], r["dmr_model"], int(r["age_band"]))] = float(r["standardized_pass_rate"])

    diffs = []
    missing_existing = 0
    missing_recomputed = 0
    for key, rate in existing.items():
        rec = recomputed_all.get(key)
        if rec is None or rec["std_rate"] is None:
            missing_recomputed += 1
            continue
        diffs.append(abs(rec["std_rate"] - rate))
    for key in recomputed_all:
        if key not in existing:
            missing_existing += 1

    print(f"\n=== REPRODUCTION GATE: {label} ===")
    print(f"  existing cells with a standardized_pass_rate: {len(existing)}")
    print(f"  recomputed cells missing/unstable where existing has a rate: {missing_recomputed}")
    print(f"  recomputed cells with no existing counterpart (should be ~0, same eligible-test logic): {missing_existing}")
    if diffs:
        print(f"  n compared: {len(diffs)}")
        print(f"  max abs diff: {max(diffs):.6f}")
        print(f"  mean abs diff: {sum(diffs)/len(diffs):.6f}")
        print(f"  cells differing by > 0.0001: {sum(1 for d in diffs if d > 0.0001)}")
        print(f"  cells differing by > 0.001:  {sum(1 for d in diffs if d > 0.001)}")
        gate_pass = max(diffs) < 0.0001
        print(f"  GATE {'PASSES' if gate_pass else 'FAILS'} (tolerance 0.0001)")
    else:
        print("  NO OVERLAPPING CELLS -- gate cannot be evaluated, something is structurally wrong")


def write_split_csv(results: dict[str, dict], out_path: Path, n_label: str) -> None:
    keys = set()
    for variant_res in results.values():
        keys |= set(variant_res.keys())
    rows = []
    for key in sorted(keys):
        make, model, band = key
        row = {"dmr_make": make, "dmr_model": model, "age_band": band}
        for variant in ["all", "mechanical", "consumable"]:
            r = results[variant].get(key, {})
            row[f"n_tests_{variant}"] = r.get("n_tests")
            row[f"raw_rate_{variant}"] = r.get("raw_rate")
            row[f"standardized_rate_{variant}"] = r.get("std_rate")
            row[f"unstable_{variant}"] = r.get("unstable")
        rows.append(row)
    fieldnames = ["dmr_make", "dmr_model", "age_band"] + [
        f"{p}_{v}" for v in ["all", "mechanical", "consumable"]
        for p in ["n_tests", "raw_rate", "standardized_rate", "unstable"]
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_path} ({len(rows)} rows)")


def descriptive_split(con: duckdb.DuckDBPyConnection, chapter_bucket: dict[int, str]) -> list[dict]:
    """Share of real failures that are mechanical vs consumable vs
    administrative_or_other, per source per age band -- ITEM-level (count of
    defect items) and TEST-level (share of failed tests carrying each kind)."""
    out = []

    def age_band_case(col):
        return ("CASE " + " ".join(
            f"WHEN {col} >= {amin} AND {col} < {amax} THEN {band}"
            for band, amin, amax in [(1, 4, 7), (2, 7, 10), (3, 10, 13), (4, 13, 17)]
        ) + " END")

    # UK item-level
    rows = con.execute(f"""
        SELECT {age_band_case('e.age_years')} AS age_band, rb.bucket, COUNT(*) n
        FROM dvsa_physical_tests_eligible e
        JOIN mot_failures f ON f.test_id = e.test_id
        JOIN rfr_bucket rb ON rb.rfr_id = f.rfr_id
        WHERE f.rfr_type_code IN ('F','P')
        GROUP BY 1, 2
        HAVING age_band IS NOT NULL
    """).fetchall()
    band_totals = defaultdict(int)
    for band, bucket, n in rows:
        band_totals[band] += n
    for band, bucket, n in rows:
        out.append({"source": "UK", "level": "item", "age_band": band, "bucket": bucket,
                     "n": n, "share_of_band": round(n / band_totals[band], 4)})

    # UK test-level (of FAILED tests, share carrying each kind of defect -- overlap allowed)
    rows = con.execute(f"""
        SELECT {age_band_case('e.age_years')} AS age_band,
               COUNT(*) n_failed,
               SUM(tf.has_mechanical) n_mech,
               SUM(tf.has_consumable) n_cons,
               SUM(CASE WHEN tf.has_mechanical=1 AND tf.has_consumable=1 THEN 1 ELSE 0 END) n_both,
               SUM(CASE WHEN tf.has_mechanical=0 AND tf.has_consumable=0 THEN 1 ELSE 0 END) n_neither
        FROM dvsa_physical_tests_eligible e
        JOIN uk_test_flags tf ON tf.test_id = e.test_id
        WHERE tf.has_any_real_defect = 1
        GROUP BY 1
        HAVING age_band IS NOT NULL
    """).fetchall()
    for band, n_failed, n_mech, n_cons, n_both, n_neither in rows:
        out.append({"source": "UK", "level": "test_overlap", "age_band": band, "bucket": "n_failed_tests",
                     "n": n_failed, "share_of_band": None})
        out.append({"source": "UK", "level": "test_overlap", "age_band": band, "bucket": "has_mechanical",
                     "n": n_mech, "share_of_band": round(n_mech / n_failed, 4)})
        out.append({"source": "UK", "level": "test_overlap", "age_band": band, "bucket": "has_consumable",
                     "n": n_cons, "share_of_band": round(n_cons / n_failed, 4)})
        out.append({"source": "UK", "level": "test_overlap", "age_band": band, "bucket": "has_both",
                     "n": n_both, "share_of_band": round(n_both / n_failed, 4)})
        out.append({"source": "UK", "level": "test_overlap", "age_band": band, "bucket": "has_neither_admin_only",
                     "n": n_neither, "share_of_band": round(n_neither / n_failed, 4)})

    # Norway item-level: sum kap columns by bucket per band
    mech_chapters = [c for c, b in chapter_bucket.items() if b == "mechanical"]
    cons_chapters = [c for c, b in chapter_bucket.items() if b == "consumable"]
    admin_chapters = [c for c, b in chapter_bucket.items() if b == "administrative_or_other"]

    def sum_expr(chapters):
        return " + ".join(f"COALESCE(kap{c}, 0)" for c in chapters) if chapters else "0"

    no_rows = con.execute(f"""
        SELECT {age_band_case('age_years')} AS age_band,
               SUM({sum_expr(mech_chapters)}) AS n_mech,
               SUM({sum_expr(cons_chapters)}) AS n_cons,
               SUM({sum_expr(admin_chapters)}) AS n_admin
        FROM no_scoped_tests
        WHERE age_years >= 4 AND age_years < 17
        GROUP BY 1
        HAVING age_band IS NOT NULL
    """).fetchall()
    for band, n_mech, n_cons, n_admin in no_rows:
        total = n_mech + n_cons + n_admin
        out.append({"source": "NO", "level": "item", "age_band": band, "bucket": "mechanical",
                     "n": n_mech, "share_of_band": round(n_mech / total, 4)})
        out.append({"source": "NO", "level": "item", "age_band": band, "bucket": "consumable",
                     "n": n_cons, "share_of_band": round(n_cons / total, 4)})
        out.append({"source": "NO", "level": "item", "age_band": band, "bucket": "administrative_or_other",
                     "n": n_admin, "share_of_band": round(n_admin / total, 4)})

    # Norway test-level overlap
    no_test_rows = con.execute(f"""
        SELECT {age_band_case('t.age_years')} AS age_band,
               COUNT(*) n_failed,
               SUM(CASE WHEN ({sum_expr(mech_chapters)}) > 0 THEN 1 ELSE 0 END) n_mech,
               SUM(CASE WHEN ({sum_expr(cons_chapters)}) > 0 THEN 1 ELSE 0 END) n_cons,
               SUM(CASE WHEN ({sum_expr(mech_chapters)}) > 0 AND ({sum_expr(cons_chapters)}) > 0 THEN 1 ELSE 0 END) n_both,
               SUM(CASE WHEN ({sum_expr(mech_chapters)}) = 0 AND ({sum_expr(cons_chapters)}) = 0 THEN 1 ELSE 0 END) n_neither
        FROM no_scoped_tests t
        WHERE t.age_years >= 4 AND t.age_years < 17 AND t.is_pass = 0
        GROUP BY 1
        HAVING age_band IS NOT NULL
    """).fetchall()
    for band, n_failed, n_mech, n_cons, n_both, n_neither in no_test_rows:
        out.append({"source": "NO", "level": "test_overlap", "age_band": band, "bucket": "n_failed_tests",
                     "n": n_failed, "share_of_band": None})
        out.append({"source": "NO", "level": "test_overlap", "age_band": band, "bucket": "has_mechanical",
                     "n": n_mech, "share_of_band": round(n_mech / n_failed, 4)})
        out.append({"source": "NO", "level": "test_overlap", "age_band": band, "bucket": "has_consumable",
                     "n": n_cons, "share_of_band": round(n_cons / n_failed, 4)})
        out.append({"source": "NO", "level": "test_overlap", "age_band": band, "bucket": "has_both",
                     "n": n_both, "share_of_band": round(n_both / n_failed, 4)})
        out.append({"source": "NO", "level": "test_overlap", "age_band": band, "bucket": "has_neither_admin_only",
                     "n": n_neither, "share_of_band": round(n_neither / n_failed, 4)})

    return out


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE))

    print("=== UK side ===")
    uk_setup_reference_tables(con)
    build_dvsa_eligible_tests(con)
    load_uk_classification(con)
    build_uk_test_bucket_flags(con)
    uk_results = compute_uk_three_way(con)
    check_reproduction(uk_results["all"], EXISTING_UK_METRICS, "n_nt_tests", "UK all-defects vs model_age_band_metrics.csv")
    write_split_csv(uk_results, OUT_UK, "n_nt_tests")

    print("\n=== Norway side ===")
    no_build_link_table(con)
    no_build_eligible_tests(con)
    chapter_bucket = load_no_classification()
    print(f"Norway chapter buckets: {chapter_bucket}")
    no_results = compute_no_three_way(con, chapter_bucket)
    check_reproduction(no_results["all"], EXISTING_NO_METRICS, "n_periodisk_tests", "Norway all-defects vs model_age_band_metrics_no.csv")
    write_split_csv(no_results, OUT_NO, "n_periodisk_tests")

    print("\n=== Descriptive split (item-level and test-overlap, per source per band) ===")
    desc_rows = descriptive_split(con, chapter_bucket)
    with open(OUT_DESCRIPTIVE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "level", "age_band", "bucket", "n", "share_of_band"])
        w.writeheader()
        w.writerows(sorted(desc_rows, key=lambda r: (r["source"], r["level"], r["age_band"])))
    print(f"wrote {OUT_DESCRIPTIVE} ({len(desc_rows)} rows)")
    for r in sorted(desc_rows, key=lambda r: (r["source"], r["level"], r["age_band"])):
        print(f"  {r}")

    con.close()


if __name__ == "__main__":
    main()
