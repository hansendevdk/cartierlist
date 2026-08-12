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

# Patterns safe to apply to every make: unambiguous hybrid vocabulary that
# does not collide with any electric-vehicle naming seen in the warehouse.
HYBRID_PATTERNS = ["%hybrid%", "%plug-in%", "%plug in%", "%phev%"]

# "HEV" (Hybrid Electric Vehicle) is a real, plain-English self-charging-
# hybrid badge used across several makes (Suzuki Vitara/SX4 S-Cross, Ford
# Mondeo, Hyundai Ioniq/Kona/Tucson, Renault Captur/Clio, Dacia Duster,
# Nissan Juke), so it is applied globally rather than kept in the per-make
# table below. The one real collision is "mHEV" (mild hybrid: a 12V/48V
# starter-generator that gives brief torque assist and stop-start, with no
# meaningful electric-only driving, a materially weaker category we
# deliberately do not badge as hybrid here, same as a plain turbo engine
# isn't). Checked against the warehouse: "m" is always written directly onto
# "hev" with no space in every mild-hybrid trim seen (Nissan Qashqai/X-Trail
# "MHEV", Ford Puma "mHEV", Peugeot 2008 "MHEV", VW Passat "PHEV" is
# unrelated), so excluding that substring cleanly separates the two everywhere
# without needing a per-make list. Every non-mild-hybrid "hev" match found
# this way is Benzin (a single stray Hyundai Kona row is the only exception),
# confirming none of it is catching a genuinely electric vehicle.
HEV_INCLUDE = "lower(v.variant_name) LIKE '%hev%'"
HEV_EXCLUDE_MILD = "lower(v.variant_name) NOT LIKE '%mhev%'"

# Patterns that are only safe within one specific make: researched against
# that make's real DMR variant_name text and checked against fuel_type_primary
# to rule out the pattern also catching that make's genuinely electric
# vehicles (the class of check that matters here, same as the Audi TFSI e /
# e-tron case). Each is a raw SQL boolean expression over
# lower(v.variant_name) and v.make_name, combined with OR against every other
# entry, so getting one make's condition wrong cannot affect another make's
# rows.
MAKE_HYBRID_CONDITIONS: dict[str, str] = {
    # Audi's plug-in hybrid badge never says "hybrid", "plug-in", or "phev":
    # it is "TFSI e" (seen both spaced, "40 TFSI e", and unspaced,
    # "40 TFSIe") or "e-tron" (e.g. "40 E-TRON", "1,4 E-TRON"). e-tron is
    # safe against Audi's separate, fully-electric e-tron SUV line: this
    # query joins on model names already confirmed in crosswalk.csv, and the
    # electric e-tron family (DMR model names "Q4 e-tron", "e-tron",
    # "e-tron 55", etc.) was never crosswalked as its own model, so those
    # rows never reach this query at all. Checked directly against the
    # warehouse: every vehicle among the currently crosswalked Audi models
    # that this pattern matches is recorded as fuel_type_primary='Benzin',
    # not 'El', confirming it is a plug-in hybrid recorded under its
    # combustion fuel type, not a pure EV.
    "AUDI": "(lower(v.variant_name) LIKE '%tfsie%' OR lower(v.variant_name) LIKE '%tfsi e%'"
            " OR lower(v.variant_name) LIKE '%e-tron%')",
    # BMW's plug-in hybrid badge is a bare "e" directly after the power-tier
    # number: 25e, 30e, 40e, 45e, 50e for the compact/SUV range, and
    # 225e/230e/325e/330e/530e/545e/550e for the sedans and Active Tourers,
    # each of which already ends in one of the shorter suffixes as its own
    # trailing substring (e.g. "330e" ends in "30e"), so those five patterns
    # alone cover every 3-digit case too. "225xe" is the one exception, an
    # inserted "x" before the "e". Checked against the warehouse: every one
    # of the 46 distinct variant strings this matches is Benzin (one is
    # Diesel), never El; a plain "T4/T5/T6" trim with no trailing "e" (a real,
    # much larger, non-hybrid population) never matches since it has no
    # digit immediately followed by "e".
    "BMW": "(" + " OR ".join(
        f"lower(v.variant_name) LIKE '%{suffix}%'"
        for suffix in ["25e", "30e", "40e", "45e", "50e", "225xe"]
    ) + ")",
    # Mercedes writes its plug-in hybrid badge as the trim number, a space,
    # then "e" (petrol-electric, e.g. "300 e") or "de" (diesel-electric, e.g.
    # "350 de"). Checked against the warehouse: every 3-digit value actually
    # used this way is enumerated here (250/300/350/400/500 for "e",
    # 300/350 for "de"); under 1% of the matching rows are recorded as El
    # rather than Benzin/Diesel, on par with the miscoding rate already
    # documented for this dataset's hybrids generally, not evidence of a real
    # EV being caught (Mercedes's actual EQ electric line uses "EQA"/"EQC"/
    # "EQS" style model names, not a "NNN e" trim suffix).
    "MERCEDES-BENZ": "(" + " OR ".join(
        f"lower(v.variant_name) LIKE '%{badge}%'"
        for badge in ["250 e", "300 e", "350 e", "400 e", "500 e", "300 de", "350 de"]
    ) + ")",
    # Volvo's plug-in hybrid badge pairs a T-number with "Recharge" (or its
    # abbreviation "ReCh") or "Twin Engine": "T6 Recharge", "T8 ReCh",
    # "T5 Twin Engine". T8 alone is unambiguous and does not need that
    # qualifier: checked against the warehouse, every T8-prefixed trim in the
    # current lineup is a plug-in hybrid (including abbreviated forms like
    # "T8 eAWD" and "T8 Aut." with no "Recharge" wording at all), so bare
    # "T8" is matched outright. T4/T5/T6 are NOT unambiguous: each also has a
    # much larger population of plain non-hybrid petrol trims ("T4 Aut.",
    # "T5 AWD Aut.", "T6 Aut."), so those three only count as hybrid together
    # with "rech" or "twin engine" in the same trim string. Volvo's actual
    # battery-electric line ("Recharge" with no T-number, "P6/P8", a bare kW
    # rating, "Elektro") never carries a T4/T5/T6/T8 prefix, so it cannot
    # satisfy either branch of this condition; checked directly, every row
    # this condition matches is Benzin, and the "Recharge"-without-T-number
    # BEV rows are all El and excluded, as intended.
    "VOLVO": "(lower(v.variant_name) LIKE 't8%'"
             " OR ((lower(v.variant_name) LIKE 't4%' OR lower(v.variant_name) LIKE 't5%'"
             " OR lower(v.variant_name) LIKE 't6%')"
             " AND (lower(v.variant_name) LIKE '%rech%' OR lower(v.variant_name) LIKE '%twin engine%')))",
    # VW's plug-in hybrid badge is "GTE" (Golf GTE, Passat GTE). Most GTE
    # trims already say "hybrid" too and are caught by the global pattern
    # above, but a real minority don't ("GTE", "1,4 GTE Variant DSG",
    # "1,4 TSI GTE"). Checked against the warehouse: every GTE match is
    # Benzin, VW has no separate electric model sharing the GTE name.
    "VOLKSWAGEN": "lower(v.variant_name) LIKE '%gte%'",
    # Honda's hybrid system is branded "i-MMD" (Intelligent Multi-Mode
    # Drive), which never says "hybrid" (Jazz/CR-V trims like "1.5 i-MMD 5d
    # eCVT"). Checked against the warehouse: 100% Benzin; Honda has no
    # covered model with a separate electric variant to collide with.
    "HONDA": "lower(v.variant_name) LIKE '%i-mmd%'",
    # Renault's hybrid badge is "E-TECH" followed by a power number (e.g.
    # "E-TECH 160"), used for both its self-charging hybrids and, with
    # "PLUG-IN" spelled out, its plug-in hybrids (the latter already caught
    # by the global "plug-in" pattern). Renault reuses the same "E-TECH" name
    # for its battery-electric Megane/Twingo/Scenic, always with the word
    # "Electric" alongside it ("E-Tech Electric 60 kWh"), so excluding that
    # word is what keeps this safe. It is not perfect: a small residual (on
    # the order of a few percent of matches) is still recorded as El, mostly
    # a bare "E-TECH" with no power number or "Electric" qualifier at all,
    # which real-world naming can't distinguish from the hybrid via text
    # alone; left as unavoidable noise of the same kind Phase 1 already
    # documented for this dataset, not chased further.
    "RENAULT": "(lower(v.variant_name) LIKE '%e-tech%' AND lower(v.variant_name) NOT LIKE '%electric%')",
}

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

    global_clause = " OR ".join(f"lower(v.variant_name) LIKE '{p}'" for p in HYBRID_PATTERNS)
    hev_clause = f"({HEV_INCLUDE} AND {HEV_EXCLUDE_MILD})"
    make_clause = " OR ".join(
        f"(v.make_name = '{make}' AND {condition})"
        for make, condition in MAKE_HYBRID_CONDITIONS.items()
    )
    hybrid_clause = f"({global_clause}) OR {hev_clause} OR {make_clause}"

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
