"""Computes Phase 3 metrics 1 (reliability), 2 (repair burden), 3 (fuel cost),
4 (ejerafgift), and 6 (engagement score), grain = one row per (dmr_make,
dmr_model, age_band). Writes reference/model_age_band_metrics.csv plus two
supporting detail files (per-category failure rates, per-stratum reliability
detail) and a build report.

METRIC 5 (DEPRECIATION) IS DELIBERATELY NOT COMPUTED HERE. DMR has no price
field (verified in Phase 3 spec) and no open Danish per-model price source
exists. You decided 2026-07-31 to drop the price axis for v1 rather than
supply prices or estimate them from attributes -- option 3 in
phase3_metrics_spec.md. Ranking in Phase 4 will run on annual running cost
alone (reliability + repair burden + fuel + ejerafgift); no price brackets.

Every threshold, filter, and formula below is specified in
phase3_metrics_spec.md, not decided here -- this file is the implementation,
not the design. Deviations from that spec would be a decision and belong back
in the spec, not silently in code.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import duckdb

from crosswalk_normalize import strip_diacritics

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
REFERENCE = ROOT / "pipeline" / "reference"
REPORTS = ROOT / "pipeline" / "reports"

OUT_METRICS = REFERENCE / "model_age_band_metrics.csv"
OUT_CATEGORY_RATES = REFERENCE / "model_age_band_category_failure_rates.csv"
OUT_RELIABILITY_DETAIL = REFERENCE / "model_age_band_reliability_strata.csv"
OUT_REPORT = REPORTS / "phase3_metrics_report.md"

MILES_TO_KM = 1.609344

# (band, reg_year_min, reg_year_max, age_years_min_inclusive, age_years_max_exclusive)
AGE_BANDS = [
    (1, 2020, 2022, 4, 7),
    (2, 2017, 2019, 7, 10),
    (3, 2014, 2016, 10, 13),
    (4, 2010, 2013, 13, 17),
]

# (stratum, km_min_inclusive, km_max_exclusive_or_None)
MILEAGE_STRATA = [
    (1, 0, 50_000),
    (2, 50_000, 100_000),
    (3, 100_000, 150_000),
    (4, 150_000, 200_000),
    (5, 200_000, 250_000),
    (6, 250_000, None),
]

RANKING_FLOOR_TESTS = 2000     # per (model, age band), Phase 2 strategy doc
STRATUM_MIN_CELL = 100          # per stratum, else merge
MIN_SURVIVING_STRATA = 3        # below this -> unstable, excluded from ranking

ANNUAL_KM = 15_000


def age_band_sql_case(reg_year_col: str) -> str:
    whens = " ".join(
        f"WHEN {reg_year_col} BETWEEN {ymin} AND {ymax} THEN {band}"
        for band, ymin, ymax, _, _ in AGE_BANDS
    )
    return f"CASE {whens} END"


def age_band_from_years_sql_case(age_years_col: str) -> str:
    """Same AGE_BANDS boundaries, but against a continuous age-in-years
    expression (DVSA side: age at test = test_date - first_use_date), not a
    registration-year integer (DMR side)."""
    whens = " ".join(
        f"WHEN {age_years_col} >= {amin} AND {age_years_col} < {amax} THEN {band}"
        for band, _, _, amin, amax in AGE_BANDS
    )
    return f"CASE {whens} END"


def stratum_sql_case(km_col: str) -> str:
    whens = []
    for stratum, lo, hi in MILEAGE_STRATA:
        cond = f"{km_col} >= {lo}" if hi is None else f"{km_col} >= {lo} AND {km_col} < {hi}"
        whens.append(f"WHEN {cond} THEN {stratum}")
    return f"CASE {' '.join(whens)} END"


# ---------------------------------------------------------------------------
# Setup: load reference CSVs as DuckDB tables/views
# ---------------------------------------------------------------------------

def setup_reference_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"CREATE OR REPLACE TABLE crosswalk_dvsa_match AS "
                f"SELECT * FROM read_csv_auto('{REFERENCE / 'crosswalk_dvsa_match.csv'}')")
    con.execute(f"CREATE OR REPLACE TABLE ejerafgift_rates AS "
                f"SELECT * FROM read_csv_auto('{REFERENCE / 'ejerafgift_rates.csv'}')")
    con.execute(f"CREATE OR REPLACE TABLE fuel_prices AS "
                f"SELECT * FROM read_csv_auto('{REFERENCE / 'fuel_prices.csv'}')")
    con.execute(f"CREATE OR REPLACE TABLE parts_cost_multipliers AS "
                f"SELECT * FROM read_csv_auto('{REFERENCE / 'parts_cost_multipliers.csv'}')")
    con.execute(f"CREATE OR REPLACE TABLE crosswalk AS "
                f"SELECT * FROM read_csv_auto('{REFERENCE / 'crosswalk.csv'}')")
    con.execute("CREATE OR REPLACE TABLE covered_models AS "
                "SELECT DISTINCT dmr_make, dmr_model FROM crosswalk")
    n = con.execute("SELECT COUNT(*) FROM covered_models").fetchone()[0]
    print(f"covered models (crosswalk-confirmed): {n}")


# ---------------------------------------------------------------------------
# DMR side: fuel cost, ejerafgift, engagement inputs -- per vehicle then
# aggregated per (model, age_band). Never aggregate DMR fields first.
# ---------------------------------------------------------------------------

def build_dmr_metrics(con: duckdb.DuckDBPyConnection) -> None:
    n_total = con.execute("""
        SELECT COUNT(*) FROM dmr_vehicles_scoped v
        JOIN covered_models cm ON v.make_name = cm.dmr_make AND v.model_name = cm.dmr_model
    """).fetchone()[0]

    n_bad_power = con.execute("""
        SELECT COUNT(*) FROM dmr_vehicles_scoped v
        JOIN covered_models cm ON v.make_name = cm.dmr_make AND v.model_name = cm.dmr_model
        WHERE v.engine_power IS NOT NULL AND (v.engine_power <= 1 OR v.engine_power > 700)
    """).fetchone()[0]

    n_bad_fuel_type = con.execute("""
        SELECT COUNT(*) FROM dmr_vehicles_scoped v
        JOIN covered_models cm ON v.make_name = cm.dmr_make AND v.model_name = cm.dmr_model
        WHERE v.fuel_type_primary NOT IN ('Benzin', 'Diesel')
    """).fetchone()[0]

    n_missing_kmpl = con.execute("""
        SELECT COUNT(*) FROM dmr_vehicles_scoped v
        JOIN covered_models cm ON v.make_name = cm.dmr_make AND v.model_name = cm.dmr_model
        WHERE v.fuel_type_primary IN ('Benzin', 'Diesel')
          AND (v.km_per_liter_primary IS NULL OR v.km_per_liter_primary <= 0)
    """).fetchone()[0]

    print(f"DMR covered vehicles: {n_total:,}")
    print(f"  engine_power outside (1, 700] kW, excluded from power-to-weight: {n_bad_power:,}")
    print(f"  fuel_type_primary not Benzin/Diesel (N-Gas/Brint/F-Gas), excluded from fuel/ejerafgift: {n_bad_fuel_type:,}")
    print(f"  missing/zero km_per_liter among Benzin/Diesel, excluded from fuel/ejerafgift: {n_missing_kmpl:,}")

    con.execute(f"""
        CREATE OR REPLACE TABLE dmr_vehicle_metrics AS
        WITH base AS (
            SELECT
                cm.dmr_make, cm.dmr_model,
                {age_band_sql_case('v.first_registration_year')} AS age_band,
                CAST(v.first_registration_date AS DATE) AS first_registration_date, v.fuel_type_primary,
                v.km_per_liter_primary, v.co2_primary,
                v.engine_power, v.koereklar_vaegt_min_kg, v.cylinder_count,
                CASE
                    WHEN CAST(v.first_registration_date AS DATE) < DATE '2017-10-03' THEN 'A'
                    WHEN CAST(v.first_registration_date AS DATE) < DATE '2021-07-01' THEN 'B'
                    ELSE 'C'
                END AS regime
            FROM dmr_vehicles_scoped v
            JOIN covered_models cm ON v.make_name = cm.dmr_make AND v.model_name = cm.dmr_model
        ),
        priced AS (
            SELECT
                b.*,
                CASE WHEN b.engine_power > 1 AND b.engine_power <= 700 AND b.koereklar_vaegt_min_kg > 0
                     THEN b.engine_power / b.koereklar_vaegt_min_kg * 1000 END AS power_to_weight_wkg,
                CASE WHEN b.fuel_type_primary IN ('Benzin', 'Diesel') AND b.km_per_liter_primary > 0
                     THEN (CAST({ANNUAL_KM} AS DOUBLE) / b.km_per_liter_primary) * fp.price_dkk_per_litre
                END AS annual_fuel_cost_dkk,
                CASE WHEN b.regime IN ('A', 'B') THEN b.km_per_liter_primary ELSE b.co2_primary END AS ejerafgift_basis_value
            FROM base b
            LEFT JOIN fuel_prices fp ON fp.fuel_type = b.fuel_type_primary
        ),
        taxed AS (
            SELECT
                p.*,
                CASE WHEN p.fuel_type_primary IN ('Benzin', 'Diesel') AND p.ejerafgift_basis_value IS NOT NULL
                     THEN (er.dkk_per_half_year
                           + CASE WHEN p.fuel_type_primary = 'Diesel'
                                  THEN COALESCE(TRY_CAST(er.surcharge_dkk_per_half_year AS DOUBLE), 0)
                                  ELSE 0 END
                          ) * 2
                END AS annual_ejerafgift_dkk
            FROM priced p
            LEFT JOIN ejerafgift_rates er
              ON er.regime = p.regime
             AND er.fuel_type = p.fuel_type_primary
             AND (er.band_min IS NULL OR p.ejerafgift_basis_value >= er.band_min)
             AND (er.band_max IS NULL OR p.ejerafgift_basis_value < er.band_max)
        )
        SELECT * FROM taxed
        WHERE age_band IS NOT NULL
    """)

    n_no_ejerafgift = con.execute(
        "SELECT COUNT(*) FROM dmr_vehicle_metrics WHERE fuel_type_primary IN ('Benzin','Diesel') AND annual_ejerafgift_dkk IS NULL"
    ).fetchone()[0]
    print(f"  Benzin/Diesel vehicles with no ejerafgift band match (missing km/l or CO2 for their regime): {n_no_ejerafgift:,}")

    con.execute(f"""
        CREATE OR REPLACE TABLE dmr_model_age_metrics AS
        SELECT
            dmr_make, dmr_model, age_band,
            COUNT(*) AS dk_vehicle_count,
            COUNT(power_to_weight_wkg) AS n_power_to_weight,
            median(power_to_weight_wkg) AS median_power_to_weight_wkg,
            median(koereklar_vaegt_min_kg) AS median_weight_kg,
            median(cylinder_count) AS median_cylinder_count,
            median(annual_fuel_cost_dkk) AS median_annual_fuel_cost_dkk,
            median(annual_ejerafgift_dkk) AS median_annual_ejerafgift_dkk
        FROM dmr_vehicle_metrics
        GROUP BY dmr_make, dmr_model, age_band
    """)
    n_cells = con.execute("SELECT COUNT(*) FROM dmr_model_age_metrics").fetchone()[0]
    print(f"dmr_model_age_metrics: {n_cells} (model, age_band) cells")


# ---------------------------------------------------------------------------
# DVSA side: reliability (direct standardization) + repair burden
# ---------------------------------------------------------------------------

def build_dvsa_eligible_tests(con: duckdb.DuckDBPyConnection) -> dict:
    """Builds the filtered NT-test population once, reports every drop, and
    returns the counts for the report.

    Built in two stages, deliberately: a PHYSICAL-test table (one row per
    DVSA test_id, deduplicated) that all the odometer/date/clocking filters
    and the is_pass/age_years/stratum computation run against, and only THEN
    a fan-out join to crosswalk_dvsa_match to attribute each surviving
    physical test to every DMR model that covers it (a real, intended
    property of the crosswalk: BMW's generic "3-Serie" DMR model and its
    "320"/"330" sibling rows deliberately share DVSA ground truth).

    An earlier version joined the make/model attribution in BEFORE computing
    the clocking window function, which put duplicate rows (one per
    attributed DMR model) into that computation's input; a second, later
    join back onto that already-duplicated table then multiplied the
    duplication further, so the reliability counts were provably wrong -- the
    "eligible after filters" count came out to 148M against ~75M raw rows,
    more rows than existed before filtering, which is what caught it. Doing
    the filtering on the deduplicated physical-test table first and
    attributing to models last avoids this class of bug entirely.
    """
    counts = {}

    counts["nt_tests_covered_models_attributed_raw"] = con.execute("""
        SELECT COUNT(*) FROM mot_tests t
        JOIN crosswalk_dvsa_match m ON t.make = m.dvsa_make AND t.model = m.dvsa_model
        WHERE t.test_type = 'NT'
    """).fetchone()[0]

    con.execute("""
        CREATE OR REPLACE TABLE dvsa_physical_tests AS
        SELECT t.test_id, t.vehicle_id, t.test_date, t.test_result, t.test_mileage,
               t.first_use_date, t.make, t.model,
               t.test_mileage * ? AS test_mileage_km
        FROM mot_tests t
        WHERE t.test_type = 'NT'
          AND EXISTS (
              SELECT 1 FROM crosswalk_dvsa_match m
              WHERE m.dvsa_make = t.make AND m.dvsa_model = t.model
          )
    """, [MILES_TO_KM])
    counts["nt_tests_covered_models_physical"] = con.execute(
        "SELECT COUNT(*) FROM dvsa_physical_tests"
    ).fetchone()[0]

    counts["dropped_mileage_le_0"] = con.execute(
        "SELECT COUNT(*) FROM dvsa_physical_tests WHERE test_mileage <= 0"
    ).fetchone()[0]
    counts["dropped_mileage_over_1m_km"] = con.execute(
        "SELECT COUNT(*) FROM dvsa_physical_tests WHERE test_mileage_km > 1000000"
    ).fetchone()[0]
    counts["dropped_bad_first_use_date"] = con.execute(
        "SELECT COUNT(*) FROM dvsa_physical_tests WHERE first_use_date < DATE '1990-01-01' OR first_use_date > test_date"
    ).fetchone()[0]
    counts["dropped_aborted"] = con.execute(
        "SELECT COUNT(*) FROM dvsa_physical_tests WHERE test_result IN ('ABR', 'ABA', 'ABRVE')"
    ).fetchone()[0]

    # clocking: a test's mileage lower than the running max mileage seen
    # earlier (by test_date) for the same vehicle_id. Computed once per
    # physical test_id -- vehicle_id/test_date/test_mileage_km are properties
    # of the physical test, not of which DMR model later claims it.
    #
    # ORDER BY test_date alone is not a total order: a vehicle with two tests
    # on the same date has its relative order inside the window frame left
    # unspecified, so which of the two counted as "earlier" (and therefore
    # which later test could be flagged clocked against it) varied between
    # runs on identical data. test_id breaks the tie deterministically: it is
    # unique per physical test (dvsa_physical_tests is deduplicated on it,
    # see above), so adding it makes the ordering total.
    con.execute("""
        CREATE OR REPLACE TABLE dvsa_clocking_flag AS
        SELECT test_id,
               test_mileage_km < MAX(test_mileage_km) OVER (
                   PARTITION BY vehicle_id ORDER BY test_date, test_id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
               ) AS is_clocked
        FROM dvsa_physical_tests
    """)
    counts["dropped_clocking"] = con.execute(
        "SELECT COUNT(*) FROM dvsa_clocking_flag WHERE is_clocked"
    ).fetchone()[0]

    con.execute(f"""
        CREATE OR REPLACE TABLE dvsa_physical_tests_eligible AS
        SELECT
            s.test_id, s.make, s.model, s.test_mileage_km,
            date_diff('day', s.first_use_date, s.test_date) / 365.25 AS age_years,
            CASE WHEN s.test_result = 'P' THEN 1
                 WHEN s.test_result IN ('F', 'PRS') THEN 0
            END AS is_pass
        FROM dvsa_physical_tests s
        LEFT JOIN dvsa_clocking_flag c ON c.test_id = s.test_id
        WHERE s.test_mileage > 0
          AND s.test_mileage_km <= 1000000
          AND s.first_use_date >= DATE '1990-01-01'
          AND s.first_use_date <= s.test_date
          AND s.test_result NOT IN ('ABR', 'ABA', 'ABRVE')
          AND NOT COALESCE(c.is_clocked, FALSE)
    """)
    n_eligible_physical = con.execute("SELECT COUNT(*) FROM dvsa_physical_tests_eligible").fetchone()[0]

    # NOW attribute each surviving physical test to every DMR model it
    # covers -- the intentional fan-out.
    con.execute(f"""
        CREATE OR REPLACE TABLE dvsa_eligible_tests AS
        SELECT m.dmr_make, m.dmr_model, e.test_id, e.test_mileage_km, e.age_years, e.is_pass,
               {age_band_from_years_sql_case('e.age_years')} AS age_band,
               {stratum_sql_case('e.test_mileage_km')} AS stratum
        FROM dvsa_physical_tests_eligible e
        JOIN crosswalk_dvsa_match m ON m.dvsa_make = e.make AND m.dvsa_model = e.model
    """)
    n_eligible_attributed = con.execute("SELECT COUNT(*) FROM dvsa_eligible_tests").fetchone()[0]
    counts["eligible_physical_tests"] = n_eligible_physical
    counts["eligible_attributed_rows"] = n_eligible_attributed

    print(f"DVSA NT tests in covered models: {counts['nt_tests_covered_models_physical']:,} physical tests "
          f"({counts['nt_tests_covered_models_attributed_raw']:,} model-attributed rows before dedup -- "
          f"some physical tests legitimately cover more than one DMR model, e.g. BMW family-series siblings)")
    for k in ["dropped_mileage_le_0", "dropped_mileage_over_1m_km", "dropped_bad_first_use_date",
              "dropped_aborted", "dropped_clocking"]:
        print(f"  dropped ({k}): {counts[k]:,}")
    print(f"  eligible physical tests after all filters: {n_eligible_physical:,}")
    print(f"  eligible model-attributed rows: {n_eligible_attributed:,}")
    return counts


def compute_reliability(con: duckdb.DuckDBPyConnection) -> tuple[list[dict], list[dict]]:
    """Direct standardization over mileage strata, per (model, age_band).
    Returns (metrics_rows, stratum_detail_rows).

    The heavy aggregation (tens of millions of rows down to a few thousand
    cells) runs in SQL; only the small per-cell result set is pulled into
    Python for the stratum-merge/standardization arithmetic, which is
    inherently procedural (each model's merge boundaries differ) and not
    worth expressing in SQL.
    """

    cell_rows = con.execute(f"""
        SELECT dmr_make, dmr_model, age_band, stratum,
               SUM(CASE WHEN is_pass = 1 THEN 1 ELSE 0 END) AS n_pass,
               SUM(CASE WHEN is_pass = 0 THEN 1 ELSE 0 END) AS n_fail
        FROM dvsa_eligible_tests
        WHERE is_pass IS NOT NULL AND age_band IS NOT NULL AND stratum IS NOT NULL
        GROUP BY 1, 2, 3, 4
    """).fetchall()

    # reference population = deduplicated PHYSICAL tests (not model-attributed
    # rows), so a model that happens to be claimed by several crosswalk rows
    # doesn't get overweighted in the population it's being standardized
    # against. Spec: "share of stratum k across ALL eligible tests in that
    # age_band", i.e. the study population, not per-model attribution.
    ref_rows = con.execute(f"""
        SELECT {age_band_from_years_sql_case('age_years')} AS age_band,
               {stratum_sql_case('test_mileage_km')} AS stratum,
               SUM(CASE WHEN is_pass = 1 THEN 1 ELSE 0 END) AS n_pass,
               SUM(CASE WHEN is_pass = 0 THEN 1 ELSE 0 END) AS n_fail
        FROM dvsa_physical_tests_eligible
        WHERE is_pass IS NOT NULL
        GROUP BY 1, 2
        HAVING age_band IS NOT NULL AND stratum IS NOT NULL
    """).fetchall()

    cells: dict[tuple, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for dmr_make, dmr_model, band, stratum, n_pass, n_fail in cell_rows:
        cells[(dmr_make, dmr_model, band)][stratum] = [n_pass, n_fail]

    ref_cells: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for band, stratum, n_pass, n_fail in ref_rows:
        ref_cells[band][stratum] = [n_pass, n_fail]

    def merge_strata(stratum_counts: dict[int, list[int]]) -> list[dict]:
        """Left-to-right merge of adjacent strata until each merged bucket has
        >= STRATUM_MIN_CELL tests (or it's the last one). Returns a list of
        {strata: [ids], n: total, passes, fails}."""
        ordered = sorted(stratum_counts.keys())
        merged = []
        carry_ids: list[int] = []
        carry_pass = 0
        carry_fail = 0
        for s in ordered:
            p, fcount = stratum_counts[s]
            carry_ids.append(s)
            carry_pass += p
            carry_fail += fcount
            n = carry_pass + carry_fail
            if n >= STRATUM_MIN_CELL:
                merged.append({"strata": list(carry_ids), "n": n, "passes": carry_pass, "fails": carry_fail})
                carry_ids, carry_pass, carry_fail = [], 0, 0
        if carry_ids:
            # trailing thin remainder: fold into the last merged bucket if one
            # exists, otherwise it stands alone as a thin (sub-floor) bucket.
            if merged:
                merged[-1]["strata"].extend(carry_ids)
                merged[-1]["n"] += carry_pass + carry_fail
                merged[-1]["passes"] += carry_pass
                merged[-1]["fails"] += carry_fail
            else:
                merged.append({"strata": list(carry_ids), "n": carry_pass + carry_fail,
                                "passes": carry_pass, "fails": carry_fail})
        return merged

    metrics_rows = []
    detail_rows = []

    for (dmr_make, dmr_model, band), stratum_counts in cells.items():
        total_pass = sum(v[0] for v in stratum_counts.values())
        total_fail = sum(v[1] for v in stratum_counts.values())
        n_tests = total_pass + total_fail
        raw_pass_rate = total_pass / n_tests if n_tests else None

        merged = merge_strata(stratum_counts)
        n_surviving = sum(1 for m in merged if m["n"] >= STRATUM_MIN_CELL)
        unstable = n_surviving < MIN_SURVIVING_STRATA

        # recompute reference weights using the SAME merge boundaries chosen
        # for this model's strata, over the reference population for this age_band
        std_rate = None
        if not unstable:
            ref_counts = ref_cells[band]
            total_ref = sum(sum(v) for v in ref_counts.values())
            weighted_sum = 0.0
            weight_total = 0.0
            for m in merged:
                if m["n"] < STRATUM_MIN_CELL:
                    continue
                ref_n = sum(sum(ref_counts[s]) for s in m["strata"])
                w = ref_n / total_ref if total_ref else 0
                p_k = m["passes"] / m["n"]
                weighted_sum += w * p_k
                weight_total += w
                detail_rows.append({
                    "dmr_make": dmr_make, "dmr_model": dmr_model, "age_band": band,
                    "strata_merged": "+".join(str(s) for s in m["strata"]),
                    "n_tests": m["n"], "pass_rate": round(p_k, 4),
                    "reference_weight": round(w, 4),
                })
            std_rate = (weighted_sum / weight_total) if weight_total > 0 else None

        metrics_rows.append({
            "dmr_make": dmr_make, "dmr_model": dmr_model, "age_band": band,
            "n_nt_tests": n_tests,
            "raw_pass_rate": round(raw_pass_rate, 4) if raw_pass_rate is not None else None,
            "standardized_pass_rate": round(std_rate, 4) if std_rate is not None else None,
            "n_strata_surviving": n_surviving,
            "reliability_unstable": unstable or n_tests < RANKING_FLOOR_TESTS,
            "meets_stability_floor": n_tests >= RANKING_FLOOR_TESTS,
        })

    return metrics_rows, detail_rows


def compute_repair_burden(con: duckdb.DuckDBPyConnection) -> tuple[list[dict], list[dict]]:
    """Category failure rates and the make-multiplier-weighted burden index,
    over the SAME eligible, model-attributed NT test set used for
    reliability (odometer/date/clocking filters already applied), excluding
    advisory items (rfr_type_code = 'A').

    A physical test attributed to more than one DMR model (BMW family-series
    siblings) has its failure items counted once per attributed model, same
    as the test itself is -- consistent with how n_tests (the rate's
    denominator) is counted for that model, so the per-model rate stays a
    genuine failures-per-test figure rather than being denominator-mismatched
    against a numerator computed a different way.
    """

    n_tests_rows = con.execute("""
        SELECT dmr_make, dmr_model, age_band, COUNT(*) AS n_tests
        FROM dvsa_eligible_tests
        WHERE is_pass IS NOT NULL AND age_band IS NOT NULL
        GROUP BY 1, 2, 3
    """).fetchall()
    band_test_counts = {(mk, md, band): n for mk, md, band, n in n_tests_rows}

    category_agg = con.execute("""
        SELECT e.dmr_make, e.dmr_model, e.age_band,
               COALESCE(f.component_category, '(uncategorised)') AS component_category,
               COUNT(*) AS n_failures
        FROM dvsa_eligible_tests e
        JOIN mot_failures f ON f.test_id = e.test_id
        WHERE e.age_band IS NOT NULL AND f.rfr_type_code != 'A'
        GROUP BY 1, 2, 3, 4
    """).fetchall()
    n_null_category = con.execute("""
        SELECT COUNT(*) FROM dvsa_eligible_tests e
        JOIN mot_failures f ON f.test_id = e.test_id
        WHERE e.age_band IS NOT NULL AND f.rfr_type_code != 'A' AND f.component_category IS NULL
    """).fetchone()[0]
    print(f"  repair burden: failure items with no component_category: {n_null_category:,}")

    # parts_cost_multipliers.csv is hand-authored in plain ASCII ("CITROEN");
    # dmr_make carries DMR's raw make_name, diacritics included ("CITROËN").
    # Match on a diacritics-stripped, uppercased key rather than assuming the
    # two sources spell every make identically -- verified needed: a literal
    # join silently dropped Citroën (38,244+ DK vehicles) from repair burden.
    multipliers_raw = con.execute(
        "SELECT make, parts_cost_multiplier FROM parts_cost_multipliers"
    ).fetchall()
    multipliers = {strip_diacritics(make).upper(): mult for make, mult in multipliers_raw}

    category_rows = []
    burden_by_model_band: dict[tuple, float] = defaultdict(float)
    makes_missing_multiplier: set[str] = set()
    for dmr_make, dmr_model, band, category, fail_count in category_agg:
        n_tests = band_test_counts.get((dmr_make, dmr_model, band), 0)
        if n_tests == 0:
            continue
        rate = fail_count / n_tests
        category_rows.append({
            "dmr_make": dmr_make, "dmr_model": dmr_model, "age_band": band,
            "component_category": category, "failure_rate_per_test": round(rate, 4),
            "n_failures": fail_count, "n_tests": n_tests,
        })
        mult = multipliers.get(strip_diacritics(dmr_make).upper())
        if mult is not None:
            burden_by_model_band[(dmr_make, dmr_model, band)] += rate * mult
        else:
            makes_missing_multiplier.add(dmr_make)

    if makes_missing_multiplier:
        print(f"  repair burden: {len(makes_missing_multiplier)} make(s) with no parts_cost_multiplier row "
              f"(burden not computed for them): {sorted(makes_missing_multiplier)}")

    burden_rows = [
        {"dmr_make": k[0], "dmr_model": k[1], "age_band": k[2], "repair_burden_index": round(v, 4)}
        for k, v in burden_by_model_band.items()
    ]
    return burden_rows, category_rows


# ---------------------------------------------------------------------------
# Engagement score: percentile ranks across the final (model, age_band) rows
# ---------------------------------------------------------------------------

def add_engagement_scores(final_rows: list[dict]) -> None:
    def percentile_ranks(values: list[float | None]) -> list[float | None]:
        present = [(i, v) for i, v in enumerate(values) if v is not None]
        if not present:
            return [None] * len(values)
        sorted_vals = sorted(v for _, v in present)
        n = len(sorted_vals)
        out = [None] * len(values)
        for i, v in present:
            # average-rank percentile, 0..1
            rank = sum(1 for x in sorted_vals if x < v) + 0.5 * sum(1 for x in sorted_vals if x == v)
            out[i] = rank / n if n > 1 else 0.5
        return out

    ptw = [r.get("median_power_to_weight_wkg") for r in final_rows]
    cyl = [r.get("median_cylinder_count") for r in final_rows]
    wt = [r.get("median_weight_kg") for r in final_rows]

    pct_ptw = percentile_ranks(ptw)
    pct_cyl = percentile_ranks(cyl)
    pct_wt = percentile_ranks(wt)

    for i, r in enumerate(final_rows):
        p_ptw, p_cyl, p_wt = pct_ptw[i], pct_cyl[i], pct_wt[i]
        if p_ptw is None:
            r["engagement_score"] = None
            continue
        cyl_term = 0.30 * p_cyl if p_cyl is not None else 0.0
        weight_used = 0.30 if p_cyl is not None else 0.0
        wt_term = 0.20 * (1 - p_wt) if p_wt is not None else 0.0
        weight_used += 0.20 if p_wt is not None else 0.0
        # renormalise if a component is missing for this row, rather than
        # silently scoring it lower for a data gap unrelated to engagement
        base_weight = 0.50
        total_weight = base_weight + weight_used
        score = (0.50 * p_ptw + cyl_term + wt_term) / total_weight if total_weight > 0 else None
        r["engagement_score"] = round(score, 4) if score is not None else None
        r["engagement_pct_power_to_weight"] = round(p_ptw, 4)
        r["engagement_pct_cylinder_count"] = round(p_cyl, 4) if p_cyl is not None else None
        r["engagement_pct_weight_inverted"] = round(1 - p_wt, 4) if p_wt is not None else None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    con = duckdb.connect(str(WAREHOUSE))
    setup_reference_tables(con)
    build_dmr_metrics(con)
    build_dvsa_eligible_tests(con)

    print("\ncomputing reliability (direct standardization over mileage strata)...")
    reliability_rows, stratum_detail_rows = compute_reliability(con)
    reliability_by_key = {(r["dmr_make"], r["dmr_model"], r["age_band"]): r for r in reliability_rows}
    print(f"  reliability computed for {len(reliability_rows)} (model, age_band) cells")

    print("\ncomputing repair burden...")
    burden_rows, category_rows = compute_repair_burden(con)
    burden_by_key = {(r["dmr_make"], r["dmr_model"], r["age_band"]): r for r in burden_rows}
    print(f"  repair burden computed for {len(burden_rows)} (model, age_band) cells")

    dmr_result = con.execute("SELECT * FROM dmr_model_age_metrics")
    dmr_columns = [d[0] for d in dmr_result.description]
    dmr_rows = [dict(zip(dmr_columns, row)) for row in dmr_result.fetchall()]

    final_rows = []
    for r in dmr_rows:
        key = (r["dmr_make"], r["dmr_model"], r["age_band"])
        rel = reliability_by_key.get(key, {})
        burden = burden_by_key.get(key, {})
        merged = dict(r)
        merged["n_nt_tests"] = rel.get("n_nt_tests", 0)
        merged["raw_pass_rate"] = rel.get("raw_pass_rate")
        merged["standardized_pass_rate"] = rel.get("standardized_pass_rate")
        merged["reliability_unstable"] = rel.get("reliability_unstable", True)
        merged["meets_stability_floor"] = rel.get("meets_stability_floor", False)
        merged["repair_burden_index"] = burden.get("repair_burden_index")
        final_rows.append(merged)

    add_engagement_scores(final_rows)

    n_meets_floor = sum(1 for r in final_rows if r["meets_stability_floor"])
    n_unstable = sum(1 for r in final_rows if r["reliability_unstable"])
    n_ranking_eligible = sum(1 for r in final_rows if r["meets_stability_floor"] and not r["reliability_unstable"])
    print(f"\n(model, age_band) cells total: {len(final_rows)}")
    print(f"  meets {RANKING_FLOOR_TESTS}-test stability floor: {n_meets_floor}")
    print(f"  flagged unstable (< {MIN_SURVIVING_STRATA} surviving mileage strata, or below the test floor): {n_unstable}")
    print(f"  eligible for ranking (both conditions): {n_ranking_eligible}")

    fieldnames = [
        "dmr_make", "dmr_model", "age_band", "dk_vehicle_count",
        "n_nt_tests", "meets_stability_floor",
        "raw_pass_rate", "standardized_pass_rate", "reliability_unstable",
        "repair_burden_index",
        "median_annual_fuel_cost_dkk", "median_annual_ejerafgift_dkk",
        "median_power_to_weight_wkg", "median_weight_kg", "median_cylinder_count",
        "engagement_score", "engagement_pct_power_to_weight",
        "engagement_pct_cylinder_count", "engagement_pct_weight_inverted",
    ]
    with open(OUT_METRICS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(final_rows, key=lambda r: (r["dmr_make"], r["dmr_model"], r["age_band"])))
    print(f"\nwrote {OUT_METRICS} ({len(final_rows)} rows)")

    with open(OUT_CATEGORY_RATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "dmr_make", "dmr_model", "age_band", "component_category",
            "failure_rate_per_test", "n_failures", "n_tests",
        ])
        w.writeheader()
        w.writerows(sorted(category_rows, key=lambda r: (r["dmr_make"], r["dmr_model"], r["age_band"], -r["failure_rate_per_test"])))
    print(f"wrote {OUT_CATEGORY_RATES} ({len(category_rows)} rows)")

    with open(OUT_RELIABILITY_DETAIL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "dmr_make", "dmr_model", "age_band", "strata_merged", "n_tests",
            "pass_rate", "reference_weight",
        ])
        w.writeheader()
        w.writerows(sorted(stratum_detail_rows, key=lambda r: (r["dmr_make"], r["dmr_model"], r["age_band"])))
    print(f"wrote {OUT_RELIABILITY_DETAIL} ({len(stratum_detail_rows)} rows)")

    con.close()


if __name__ == "__main__":
    main()
