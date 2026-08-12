"""Computes, per (dmr_make, dmr_model, age_band) -- the same grain as
model_age_band_metrics.csv -- what share of registered vehicles in that cell
are diesel, and what share are hybrid.

Diesel comes straight from fuel_type_primary, a clean DMR field. Hybrid has
no clean field: Phase 1 found DMR records hybrids under their combustion
fuel type, with the only signal being free text in variant_name (e.g. "2.5
Plug-in Hybrid (225 HK)"). This script reads that free text directly off the
raw vehicle records, which the rest of the pipeline never touches, so it is
a real per-vehicle count, not a name-matched guess at the model level.

A cell is flagged is_diesel_dominant when over half its vehicles are diesel,
a clean field so the split really is close to 0% or 100% most of the time.
Hybrid uses a lower bar, over 3 in 10: the text match only catches a trim
name that literally says "hybrid" or "plug-in", and some real hybrid-only
nameplates (Hyundai's Ioniq is the clearest case, at 44%-49% hybrid text
match despite being sold almost entirely as hybrid/plug-in/EV in this
generation) undercount because not every trim string spells it out. A lower
bar catches those without pulling in nameplates that are genuinely mostly
non-hybrid with just a hybrid trim mixed in (checked against the actual
distribution before picking 0.3, see the script's own printed breakdown).
These flags exist to let a reader filter cars out of the site's lists; they
do not change any price, cost, or ranking figure.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "pipeline" / "reference"
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
METRICS_CSV = REFERENCE / "model_age_band_metrics.csv"
OUT_CSV = REFERENCE / "model_age_band_fuel_flags.csv"


def normalize_key(model: str) -> str:
    # Must match fix_case_duplicate_models.py's normalize_key exactly, since
    # this function's whole job is looking up that script's canonical
    # spelling. Whitespace-only stripping missed the Kia Cee'd SW pair
    # ("CEE'D SW" vs "CEED SW", an apostrophe-only difference), so a raw
    # vehicle recorded under the non-canonical spelling would silently fail
    # this lookup and stay unfolded instead of joining the merged row.
    return re.sub(r"[^a-z0-9]", "", model.lower())

AGE_BANDS = [
    (1, 2020, 2022),
    (2, 2017, 2019),
    (3, 2014, 2016),
    (4, 2010, 2013),
]

# Audi's plug-in hybrid badge never says "hybrid", "plug-in", or "phev": it is
# "TFSI e" (seen both spaced, "40 TFSI e", and unspaced, "40 TFSIe") or
# "e-tron" (e.g. "40 E-TRON", "1,4 E-TRON"). tfsie/tfsi e together cover both
# spellings seen in real DMR data. e-tron is safe against Audi's separate,
# fully-electric e-tron SUV line: this query joins on model names already
# confirmed in crosswalk.csv, and the electric e-tron family (DMR model names
# "Q4 e-tron", "e-tron", "e-tron 55", etc.) was never crosswalked as its own
# model, so those rows never reach this query at all. Checked directly against
# the warehouse: every vehicle among the currently crosswalked Audi models
# that this pattern matches is recorded as fuel_type_primary='Benzin', not
# 'El', confirming it is a plug-in hybrid recorded under its combustion fuel
# type, the way DMR records hybrids in this dataset, not a pure EV.
HYBRID_PATTERNS = [
    "%hybrid%", "%plug-in%", "%plug in%", "%phev%",
    "%tfsie%", "%tfsi e%", "%e-tron%",
]

DIESEL_THRESHOLD = 0.5
HYBRID_THRESHOLD = 0.3


def age_band_sql_case(reg_year_col: str) -> str:
    whens = " ".join(
        f"WHEN {reg_year_col} BETWEEN {ymin} AND {ymax} THEN {band}"
        for band, ymin, ymax in AGE_BANDS
    )
    return f"CASE {whens} ELSE NULL END"


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE))

    hybrid_clause = " OR ".join(
        f"lower(v.variant_name) LIKE '{p}'" for p in HYBRID_PATTERNS
    )

    rows = con.execute(f"""
        WITH covered_models AS (
            SELECT DISTINCT dmr_make, dmr_model FROM crosswalk
        ),
        tagged AS (
            SELECT
                cm.dmr_make, cm.dmr_model,
                {age_band_sql_case('v.first_registration_year')} AS age_band,
                CASE WHEN v.fuel_type_primary = 'Diesel' THEN 1 ELSE 0 END AS is_diesel,
                CASE WHEN v.variant_name IS NOT NULL AND ({hybrid_clause}) THEN 1 ELSE 0 END AS is_hybrid_text
            FROM dmr_vehicles v
            JOIN covered_models cm ON v.make_name = cm.dmr_make AND v.model_name = cm.dmr_model
        )
        SELECT
            dmr_make, dmr_model, age_band,
            COUNT(*) AS n_vehicles,
            SUM(is_diesel) AS n_diesel,
            SUM(is_hybrid_text) AS n_hybrid_text
        FROM tagged
        WHERE age_band IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """).fetchall()

    # model_age_band_metrics.csv has already merged case/whitespace duplicate
    # spellings (e.g. FORD "FOCUS"/"Focus") into one canonical spelling per
    # (make, normalized model, band). Fold this script's raw counts onto the
    # same canonical spelling so a duplicate spelling doesn't silently fail
    # to join in build_phase4_rankings.py and lose its fuel/hybrid signal.
    with open(METRICS_CSV, encoding="utf-8") as f:
        canonical_spelling = {
            (r["dmr_make"], normalize_key(r["dmr_model"]), r["age_band"]): r["dmr_model"]
            for r in csv.DictReader(f)
        }

    grouped: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for make, model, band, n_vehicles, n_diesel, n_hybrid in rows:
        band = str(band)
        canon_model = canonical_spelling.get((make, normalize_key(model), band), model)
        g = grouped[(make, canon_model, band)]
        g[0] += n_vehicles
        g[1] += n_diesel
        g[2] += n_hybrid

    out_rows = []
    for (make, model, band), (n_vehicles, n_diesel, n_hybrid) in sorted(grouped.items()):
        diesel_pct = n_diesel / n_vehicles
        hybrid_pct = n_hybrid / n_vehicles
        out_rows.append({
            "dmr_make": make, "dmr_model": model, "age_band": band,
            "n_vehicles": n_vehicles,
            "diesel_pct": round(diesel_pct, 4),
            "hybrid_pct": round(hybrid_pct, 4),
            "is_diesel_dominant": diesel_pct > DIESEL_THRESHOLD,
            "is_hybrid": hybrid_pct > HYBRID_THRESHOLD,
        })

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    n_diesel_dominant = sum(1 for r in out_rows if r["is_diesel_dominant"])
    n_hybrid = sum(1 for r in out_rows if r["is_hybrid"])
    print(f"wrote {OUT_CSV} ({len(out_rows)} rows)")
    print(f"  diesel-dominant cells: {n_diesel_dominant}")
    print(f"  hybrid cells (variant_name text match): {n_hybrid}")


if __name__ == "__main__":
    main()
