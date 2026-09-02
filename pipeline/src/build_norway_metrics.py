"""Norwegian analogue of build_phase3_metrics.py's reliability index (metric 1
only -- repair burden, fuel cost, ejerafgift and engagement are DMR-vehicle-
attribute metrics with no Norwegian equivalent in scope for this phase; see
reports/norway_pkk_report.md for the full metric-by-metric comparison against
phase3_metrics_spec.md).

Mirrors the UK method wherever the data allows, and documents every place it
cannot:
  - Age bands: same four age-at-test ranges as AGE_BANDS in
    build_phase3_metrics.py (4-6, 7-9, 10-12, 13-16 years), computed here from
    PKK Kontrollmåned year minus Første gang registrert year -- YEAR-ONLY
    precision on both ends, unlike DVSA's exact test_date - first_use_date.
  - Mileage standardisation: direct standardisation over the SAME 6 strata
    boundaries as MILEAGE_STRATA (0-50k/50-100k/.../250k+ km), which happen to
    line up exactly with PKK's own reporting resolution (Kilometerstand is
    already rounded UP to the nearest 50,000 km) -- so unlike the UK side,
    every Norwegian test sits exactly on a stratum boundary already, not
    somewhere inside a continuous range. That rounding is systematically
    upward, so a car's true stratum is, on average, below the one it's placed
    in here -- a real bias, documented, not corrected.
  - Failure definition: Godkjent = 'Nei'. Advisory analogue: Ant 1er merknad
    (minor deficiency, does NOT affect approval per the official
    Kontrollinstruks v4.1 -- verified directly from the source PDF, see report)
    is excluded from failure, exactly like DVSA rfr_type_code = 'A'.
  - Ant 4er merknad is EXCLUDED from every defect/category count in this
    script. It is not a severity class at all -- the Kontrollinstruks defines
    it as "not possible to measure at the time of inspection due to climatic
    conditions" (Kontrollinstruks v4.1, boilerplate at the top of the control-
    point table). Counting it as a real defect, as the phase brief's working
    assumption suggested, would silently mix a measurement-incomplete flag
    into the mechanical-fault signal. This is exactly the kind of vocabulary
    mismatch the brief asked to be verified and reported, not silently
    absorbed -- see the "stop and report" section of the report.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_no_crosswalk_review import (  # noqa: E402
    classify_model_token,
    despace_known_code,
    normalize_no_raw,
    strip_make_prefix,
)
from crosswalk_normalize import normalize  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
REFERENCE = ROOT / "pipeline" / "reference"
NO_CROSSWALK_CSV = REFERENCE / "no_crosswalk.csv"

OUT_METRICS = REFERENCE / "model_age_band_metrics_no.csv"
OUT_CATEGORY_RATES = REFERENCE / "model_age_band_category_failure_rates_no.csv"
OUT_STRATA_DETAIL = REFERENCE / "model_age_band_reliability_strata_no.csv"

# Same four age-at-test ranges as build_phase3_metrics.py's AGE_BANDS
# (min inclusive years, max exclusive years) -- kept as a separate literal
# here rather than imported, since the UK module also carries reg-year
# columns Norway has no equivalent for.
AGE_BANDS = [(1, 4, 7), (2, 7, 10), (3, 10, 13), (4, 13, 17)]

MILEAGE_STRATA = [
    (1, 0, 50_000),
    (2, 50_000, 100_000),
    (3, 100_000, 150_000),
    (4, 150_000, 200_000),
    (5, 200_000, 250_000),
    (6, 250_000, None),
]

# Scaled down from the UK's STRATUM_MIN_CELL=100: Norway's total scoped
# volume is roughly 4% of the UK's (2.83M vs ~40M/year), so reusing 100 would
# force merging almost every stratum for all but the handful of highest-
# volume models. Not a strict proportional scale (that would be ~4, too small
# to mean anything) -- chosen as a floor that still filters genuinely thin
# cells while leaving standardisation usable at Norway's scale.
STRATUM_MIN_CELL = 25
MIN_SURVIVING_STRATA = 3

# Final per-(model, age_band) ranking floor. Derived, not borrowed: Norway's
# own observed pass rate in scope is close to 0.50 (measured below), not the
# UK's ~0.75, and variance p(1-p) is maximised at p=0.5 -- so the SAME
# "SE < 1pp" standard the Phase 2 strategy doc used for the UK's 2,000-test
# floor implies a HIGHER Norwegian floor (n >= 2,500), even though Norway's
# total volume is much smaller. Reported honestly below, alongside how many
# cells clear it and the sensitivity to lower thresholds, rather than lowered
# to make the ranked set look fuller.
RANKING_FLOOR_SE_TARGET = 2500
RANKING_FLOOR_SENSITIVITY = [500, 1000, 1500, 2000, 2500]

SCOPE_SQL = """
    gruppeavgift = 'PERSONBIL'
    AND kontrolltype = 'Periodisk'
    AND fuel IS NOT NULL AND fuel NOT IN ('Elektrisk', 'Hydrogen')
"""

CHAPTER_NAMES = {
    0: "Identifikasjon av kjoretoyet (vehicle identification)",
    1: "Bremseanlegg (braking system)",
    2: "Styring (steering)",
    3: "Sikt (visibility)",
    4: "Lykter, refleksinnretninger og elektrisk utstyr (lights, reflectors, electrical)",
    5: "Aksler, hjul, dekk og hjuloppheng (axles, wheels, tyres, suspension)",
    6: "Understell og understellsutstyr (chassis and chassis equipment)",
    7: "Annet utstyr (other equipment)",
    8: "Skadevirkninger (noise, exhaust/emissions nuisance)",
    9: "Tilleggskontroller for M2/M3 buss (bus-only supplementary checks -- not applicable to M1/PERSONBIL)",
    10: "Forevisning for trafikkstasjon (administrative referral to the traffic station)",
}


def age_band_case(age_col: str) -> str:
    whens = " ".join(f"WHEN {age_col} >= {amin} AND {age_col} < {amax} THEN {band}" for band, amin, amax in AGE_BANDS)
    return f"CASE {whens} END"


def stratum_case(km_col: str) -> str:
    whens = []
    for stratum, lo, hi in MILEAGE_STRATA:
        cond = f"{km_col} >= {lo}" if hi is None else f"{km_col} >= {lo} AND {km_col} < {hi}"
        whens.append(f"WHEN {cond} THEN {stratum}")
    return f"CASE {' '.join(whens)} END"


def build_link_table(con: duckdb.DuckDBPyConnection) -> int:
    """Resolves every confirmed no_crosswalk.csv row's proposed_no_model_token
    back to the actual raw Kjoretoy Modell strings it covers, by re-running
    classify_model_token (the SAME function used to build the match index)
    over every distinct raw model string Norway actually has for that make.
    Writes a (dmr_make, dmr_model, no_make, model_raw) link table -- the
    Norwegian-side analogue of build_crosswalk_dvsa_match.py's resolver."""
    with open(NO_CROSSWALK_CSV, encoding="utf-8") as f:
        cw_rows = list(csv.DictReader(f))

    raw_by_make: dict[str, list[str]] = {}
    for r in cw_rows:
        raw_by_make.setdefault(r["proposed_no_make"], None)

    for no_make in raw_by_make:
        rows = con.execute(
            f"SELECT DISTINCT model_raw FROM pkk_inspections WHERE make = ? AND {SCOPE_SQL}", [no_make]
        ).fetchall()
        raw_by_make[no_make] = [m for (m,) in rows if m]

    link_rows = []
    for r in cw_rows:
        no_make = r["proposed_no_make"]
        token = r["proposed_no_model_token"]
        make_norm = normalize(no_make)
        rule = r["rule_fired"]

        if rule == "family_series_literal":
            bucket_key = token.split(" ")[0]
            for raw in raw_by_make.get(no_make, []):
                if classify_model_token(raw, make_norm) == bucket_key:
                    link_rows.append((r["dmr_make"], r["dmr_model"], no_make, raw))
        elif " " in token:
            # Multi-word prefix-identity match (Audi 'A3 SPORTBACK', VW
            # 'T-ROC', Mazda 'CX-5', Honda 'CR-V', ...). classify_model_token
            # always collapses a code-like string down to its single leading
            # token, which is correct for a bare nameplate but can never
            # equal a multi-word token, so bucket membership here used to
            # match nothing at all. Bucket membership for these is instead
            # the same normalized-string PREFIX test that produced the
            # token's own inspection count in the first place
            # (best_prefix_identity / this module's own prefix_counts in
            # build_no_index). Verified this bug was silently zeroing out 30
            # confirmed rows across many makes, including 7 of Audi's own
            # (A3 Sportback/Limousine/Cabriolet, A4 Avant, A5 Sportback, A6
            # Avant, A1 Sportback) -- every one of them linked zero raw
            # strings and produced zero metrics cells before this fix.
            for raw in raw_by_make.get(no_make, []):
                stripped = normalize(strip_make_prefix(normalize_no_raw(raw), make_norm))
                stripped = despace_known_code(stripped, make_norm)
                if stripped == token or stripped.startswith(token + " "):
                    link_rows.append((r["dmr_make"], r["dmr_model"], no_make, raw))
        else:
            for raw in raw_by_make.get(no_make, []):
                if classify_model_token(raw, make_norm) == token:
                    link_rows.append((r["dmr_make"], r["dmr_model"], no_make, raw))

    con.execute("""
        CREATE OR REPLACE TABLE no_model_link (
            dmr_make VARCHAR, dmr_model VARCHAR, no_make VARCHAR, model_raw VARCHAR
        )
    """)
    con.executemany("INSERT INTO no_model_link VALUES (?, ?, ?, ?)", link_rows)
    n = con.execute("SELECT COUNT(DISTINCT (dmr_make, dmr_model)) FROM no_model_link").fetchone()[0]
    print(f"no_model_link: {len(link_rows):,} (dk_model -> no raw string) rows, {n} distinct DK models covered")
    return n


def build_eligible_tests(con: duckdb.DuckDBPyConnection) -> None:
    """Attributes every scoped Periodisk PERSONBIL inspection to every DK
    model it links to (fan-out, same intentional design as the UK side), with
    age-at-test and mileage-stratum computed once here."""
    con.execute(f"""
        CREATE OR REPLACE TABLE no_scoped_tests AS
        SELECT *,
               kontroll_year - first_reg_year AS age_years,
               CASE WHEN godkjent = 'Ja' THEN 1 WHEN godkjent = 'Nei' THEN 0 END AS is_pass
        FROM pkk_inspections
        WHERE {SCOPE_SQL}
          AND first_reg_year IS NOT NULL AND kontroll_year IS NOT NULL
          AND godkjent IN ('Ja', 'Nei')
    """)
    n_scoped = con.execute("SELECT COUNT(*) FROM no_scoped_tests").fetchone()[0]

    con.execute(f"""
        CREATE OR REPLACE TABLE no_eligible_tests AS
        SELECT link.dmr_make, link.dmr_model, t.*,
               {age_band_case('t.age_years')} AS age_band,
               {stratum_case('t.km')} AS stratum
        FROM no_scoped_tests t
        JOIN no_model_link link ON link.no_make = t.make AND link.model_raw = t.model_raw
        WHERE t.age_years >= 4 AND t.age_years < 17
    """)
    n_attributed = con.execute("SELECT COUNT(*) FROM no_eligible_tests").fetchone()[0]
    print(f"no_scoped_tests (Periodisk, PERSONBIL, non-BEV/hydrogen, valid age/godkjent): {n_scoped:,}")
    print(f"no_eligible_tests (age 4-16, attributed to a DK model): {n_attributed:,} rows")


def merge_strata(stratum_counts: dict[int, list[int]], min_cell: int) -> list[dict]:
    ordered = sorted(stratum_counts.keys())
    merged: list[dict] = []
    carry_ids: list[int] = []
    carry_pass = carry_fail = 0
    for s in ordered:
        p, fcount = stratum_counts[s]
        carry_ids.append(s)
        carry_pass += p
        carry_fail += fcount
        n = carry_pass + carry_fail
        if n >= min_cell:
            merged.append({"strata": list(carry_ids), "n": n, "passes": carry_pass, "fails": carry_fail})
            carry_ids, carry_pass, carry_fail = [], 0, 0
    if carry_ids:
        if merged:
            merged[-1]["strata"].extend(carry_ids)
            merged[-1]["n"] += carry_pass + carry_fail
            merged[-1]["passes"] += carry_pass
            merged[-1]["fails"] += carry_fail
        else:
            merged.append({"strata": list(carry_ids), "n": carry_pass + carry_fail,
                            "passes": carry_pass, "fails": carry_fail})
    return merged


def compute_reliability(con: duckdb.DuckDBPyConnection) -> tuple[list[dict], list[dict]]:
    cell_rows = con.execute("""
        SELECT dmr_make, dmr_model, age_band, stratum,
               SUM(CASE WHEN is_pass = 1 THEN 1 ELSE 0 END) AS n_pass,
               SUM(CASE WHEN is_pass = 0 THEN 1 ELSE 0 END) AS n_fail
        FROM no_eligible_tests
        WHERE age_band IS NOT NULL AND stratum IS NOT NULL
        GROUP BY 1, 2, 3, 4
    """).fetchall()

    # reference population = deduplicated scoped tests, not model-attributed
    # rows (a test claimed by more than one DK model, e.g. a BMW family-series
    # sibling, must not be double-counted in the population it's standardised
    # against). Matches the UK spec's "share of stratum k across ALL eligible
    # tests in that age_band".
    ref_rows = con.execute(f"""
        SELECT {age_band_case('age_years')} AS age_band,
               {stratum_case('km')} AS stratum,
               SUM(CASE WHEN is_pass = 1 THEN 1 ELSE 0 END) AS n_pass,
               SUM(CASE WHEN is_pass = 0 THEN 1 ELSE 0 END) AS n_fail
        FROM no_scoped_tests
        WHERE age_years >= 4 AND age_years < 17
        GROUP BY 1, 2
        HAVING age_band IS NOT NULL AND stratum IS NOT NULL
    """).fetchall()

    cells: dict[tuple, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for dmr_make, dmr_model, band, stratum, n_pass, n_fail in cell_rows:
        cells[(dmr_make, dmr_model, band)][stratum] = [n_pass, n_fail]

    ref_cells: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for band, stratum, n_pass, n_fail in ref_rows:
        ref_cells[band][stratum] = [n_pass, n_fail]

    metrics_rows, detail_rows = [], []

    for (dmr_make, dmr_model, band), stratum_counts in cells.items():
        total_pass = sum(v[0] for v in stratum_counts.values())
        total_fail = sum(v[1] for v in stratum_counts.values())
        n_tests = total_pass + total_fail
        raw_pass_rate = total_pass / n_tests if n_tests else None

        merged = merge_strata(stratum_counts, STRATUM_MIN_CELL)
        n_surviving = sum(1 for m in merged if m["n"] >= STRATUM_MIN_CELL)
        unstable = n_surviving < MIN_SURVIVING_STRATA

        std_rate = None
        if not unstable:
            ref_counts = ref_cells[band]
            total_ref = sum(sum(v) for v in ref_counts.values())
            weighted_sum = weight_total = 0.0
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
                    "n_tests": m["n"], "pass_rate": round(p_k, 4), "reference_weight": round(w, 4),
                })
            std_rate = (weighted_sum / weight_total) if weight_total > 0 else None

        meets_floor = n_tests >= RANKING_FLOOR_SE_TARGET
        metrics_rows.append({
            "dmr_make": dmr_make, "dmr_model": dmr_model, "age_band": band,
            "n_periodisk_tests": n_tests, "n_pass": total_pass, "n_fail": total_fail,
            "n_strata_surviving": n_surviving,
            "raw_pass_rate": round(raw_pass_rate, 4) if raw_pass_rate is not None else None,
            "standardized_pass_rate": round(std_rate, 4) if std_rate is not None else None,
            "reliability_unstable": unstable,
            "meets_stability_floor_2500": meets_floor,
        })
        for thr in RANKING_FLOOR_SENSITIVITY:
            metrics_rows[-1][f"meets_floor_{thr}"] = n_tests >= thr

    return metrics_rows, detail_rows


def compute_category_rates(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Chapter-level (kap 0..kap 10) 2-3er defect rates per (model, age_band).
    Ant 4er is deliberately excluded everywhere -- see module docstring."""
    rows = []
    for chapter in range(11):
        col = f"kap{chapter}"
        res = con.execute(f"""
            SELECT dmr_make, dmr_model, age_band,
                   SUM(COALESCE({col}, 0)) AS n_defects,
                   COUNT(*) AS n_tests
            FROM no_eligible_tests
            WHERE age_band IS NOT NULL
            GROUP BY 1, 2, 3
        """).fetchall()
        for dmr_make, dmr_model, band, n_defects, n_tests in res:
            rows.append({
                "dmr_make": dmr_make, "dmr_model": dmr_model, "age_band": band,
                "chapter": chapter, "chapter_name": CHAPTER_NAMES[chapter],
                "n_defects_2_3er": n_defects, "n_tests": n_tests,
                "defect_rate_per_test": round(n_defects / n_tests, 4) if n_tests else None,
            })
    return rows


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE))

    build_link_table(con)
    build_eligible_tests(con)

    print("\nreference population overall pass rate (for the ranking-floor SE calc):")
    r = con.execute("SELECT AVG(is_pass::DOUBLE) FROM no_scoped_tests WHERE age_years >= 4 AND age_years < 17").fetchone()[0]
    print(f"  overall Periodisk pass rate, age 4-16: {r:.4f}")

    metrics_rows, detail_rows = compute_reliability(con)
    category_rows = compute_category_rates(con)

    with open(OUT_METRICS, "w", newline="", encoding="utf-8") as f:
        fieldnames = list(metrics_rows[0].keys()) if metrics_rows else []
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(metrics_rows)
    print(f"\nwrote {OUT_METRICS}: {len(metrics_rows)} (model, age_band) cells")

    with open(OUT_STRATA_DETAIL, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["dmr_make", "dmr_model", "age_band", "strata_merged", "n_tests", "pass_rate", "reference_weight"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(detail_rows)
    print(f"wrote {OUT_STRATA_DETAIL}: {len(detail_rows)} stratum-detail rows")

    with open(OUT_CATEGORY_RATES, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["dmr_make", "dmr_model", "age_band", "chapter", "chapter_name", "n_defects_2_3er", "n_tests", "defect_rate_per_test"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(category_rows)
    print(f"wrote {OUT_CATEGORY_RATES}: {len(category_rows)} category-cell rows")

    n_meets_2500 = sum(1 for r in metrics_rows if r["meets_stability_floor_2500"])
    print(f"\ncells clearing the SE<1pp floor (n>=2500): {n_meets_2500} / {len(metrics_rows)}")
    for thr in RANKING_FLOOR_SENSITIVITY:
        n = sum(1 for r in metrics_rows if r[f"meets_floor_{thr}"])
        print(f"  cells clearing n>={thr}: {n} / {len(metrics_rows)}")

    con.close()


if __name__ == "__main__":
    main()
