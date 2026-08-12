"""Merges (make, model) rows in model_age_band_metrics.csv that are the same
real car split into two DMR spellings -- formatting noise (case, stray
whitespace), not a genuine model difference. Found while building the site:
Astro's static router collapsed two rows to the same URL slug and refused to
build one of them, which is what surfaced FORD "FOCUS" vs "Focus" first.
A full scan (comparing DVSA-side stats, see below) turned up three more:
CITROËN "C1"/"C 1", FIAT "500C"/"500 C", HYUNDAI "I10"/"I 10".

WHY THIS IS SAFE TO AUTOMATE: a spelling pair is only merged if every
DVSA-derived field (n_nt_tests, pass rates, repair burden index) is IDENTICAL
between the two rows at every age band they share. Two rows only produce
identical DVSA figures if both spellings resolved to the exact same UK test
pool (see build_crosswalk_dvsa_match.py) -- which can only happen if they are
the same real car. A genuinely different model/variant (e.g. "AYGO" vs
"AYGO 3/5-DØRS", which really are recorded separately in DMR and do carry
different stats) will fail that check and is left untouched, not merged.
This is a real ranking-correctness bug, not a cosmetic one: vehicle-count
and vehicle-attribute figures (fuel cost, weight, engagement) were each
computed from two artificially split, smaller samples instead of one
correct one, and the affected car showed up twice in bracket rankings as if
it were two different cars.

MERGE RULE, per age band, applied to any group of rows sharing (make,
lowercased model with whitespace removed, age band):
  dk_vehicle_count: summed (no data lost).
  n_nt_tests and every DVSA-derived field (pass rates, repair burden):
    asserted equal across the whole group before merging. If they ever
    aren't, this script stops rather than silently picking one.
  Every DMR-vehicle-derived field (fuel cost, ejerafgift, weight,
    power-to-weight, engagement and its percentile components): recomputed
    as a dk_vehicle_count-weighted average across the group's medians. This
    is an approximation -- averaging medians is not the same as the true
    median of the pooled vehicles -- but is far closer to correct than
    keeping contradictory rows or arbitrarily discarding one.
  Canonical spelling: whichever variant carries the largest total vehicle
    count (e.g. FOCUS, 14,472 vs Focus, 2,582 for band 1 alone).
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"
METRICS_CSV = REFERENCE / "model_age_band_metrics.csv"
PRICE_CSV = REFERENCE / "price_estimates_calibrated.csv"

DVSA_FIELDS = [
    "n_nt_tests", "meets_stability_floor", "raw_pass_rate", "standardized_pass_rate",
    "reliability_unstable", "repair_burden_index",
]
WEIGHTED_FIELDS = [
    "median_annual_fuel_cost_dkk", "median_annual_ejerafgift_dkk",
    "median_power_to_weight_wkg", "median_weight_kg", "median_cylinder_count",
    "engagement_score", "engagement_pct_power_to_weight",
    "engagement_pct_cylinder_count", "engagement_pct_weight_inverted",
]


def normalize_key(model: str) -> str:
    # Whitespace-only stripping missed the Kia Cee'd SW case: "CEE'D SW" vs
    # "CEED SW" differ only by an apostrophe, so they never even landed in the
    # same group to be considered for merging, a narrower kind of duplicate
    # than the case/whitespace pairs already handled (FOCUS/Focus, C1/C 1,
    # 500C/500 C, I10/I 10). Stripping all non-alphanumeric characters covers
    # that case too. This is still safe: the normalized key only decides who
    # gets compared, the DVSA-field-equality assertion below decides who
    # actually merges, so a coincidental key collision between two genuinely
    # different cars would still be caught rather than silently merged.
    return re.sub(r"[^a-z0-9]", "", model.lower())


def main() -> None:
    with open(METRICS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["dmr_make"], normalize_key(r["dmr_model"]), r["age_band"])].append(r)

    out_rows = []
    n_merged_groups = 0
    for (make, model_key, band), members in groups.items():
        if len(members) == 1:
            out_rows.append(members[0])
            continue

        identical = all(
            all(m[field] == members[0][field] for field in DVSA_FIELDS) for m in members
        )
        if not identical:
            spellings = sorted(set(m["dmr_model"] for m in members))
            print(f"NOT merging {make} {spellings} band {band}: DVSA stats differ, "
                  "treating as genuinely different variants, not a formatting duplicate.")
            out_rows.extend(members)
            continue

        n_merged_groups += 1
        total = sum(int(m["dk_vehicle_count"]) for m in members)
        canonical = max(members, key=lambda m: int(m["dk_vehicle_count"]))
        merged = dict(canonical)  # canonical spelling + DVSA fields
        merged["dk_vehicle_count"] = total
        for field in WEIGHTED_FIELDS:
            values = [(m.get(field), int(m["dk_vehicle_count"])) for m in members]
            if any(v in (None, "") for v, _ in values):
                merged[field] = next((v for v, _ in values if v not in (None, "")), "")
                continue
            merged[field] = round(sum(float(v) * c for v, c in values) / total, 4)
        out_rows.append(merged)
        counts = ", ".join(f"{m['dmr_model']!r}={m['dk_vehicle_count']}" for m in members)
        print(f"merged {make} band {band}: {counts} -> {total} vehicles, "
              f"kept spelling {merged['dmr_model']!r}")

    with open(METRICS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n{n_merged_groups} case/whitespace-duplicate row groups merged. "
          f"{len(rows)} rows -> {len(out_rows)} rows. Wrote {METRICS_CSV}")

    dedupe_price_estimates(out_rows)


def dedupe_price_estimates(canonical_metrics_rows: list[dict]) -> None:
    """price_estimates_calibrated.csv is keyed off the same crosswalk model
    strings, so it carries the identical formatting-duplicate split -- but
    since price comes from a foreign-listing match keyed on the exact
    spelling, NOT case/whitespace-insensitive, the two spellings can get
    priced completely differently: one matches its own Poland listings
    directly (pooled_at_brand=False), the other's internal space breaks the
    match and it silently falls back to a brand-wide pooled curve. Found via
    HYUNDAI "I10" (own curve, 70,242 DKK) vs "I 10" (pooled across all of
    Hyundai, including far pricier SUVs, 172,241 DKK) for the identical car
    -- 2.5x apart, not noise. This is a real gap in build_price_estimates.py's
    model matcher, worth fixing there directly at some point; this script
    works around it for the site by always preferring a non-pooled match
    when the group has one, since that's real model-specific data outranking
    a brand-wide fallback. Only averages when every spelling in the group
    pooled the same way (seen for CITROËN "C1"/"C 1", both pooled, ~0.5%
    apart -- a genuine small CO2-median difference between the two DMR-side
    vehicle subsets, not a matching failure)."""
    # per (make, model_key, age_band), NOT just (make, model_key) -- the
    # winning spelling can differ by band (FIAT 500C's band 4 has more
    # "500 C"-spelled vehicles than "500C", while bands 1-3 go the other
    # way), so a band-blind lookup silently mismatches whichever band
    # picked the minority spelling.
    canonical_spelling = {
        (r["dmr_make"], normalize_key(r["dmr_model"]), r["age_band"]): r["dmr_model"]
        for r in canonical_metrics_rows
    }
    with open(PRICE_CSV, encoding="utf-8") as f:
        price_rows = list(csv.DictReader(f))
        price_fieldnames = list(price_rows[0].keys())

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in price_rows:
        groups[(r["dmr_make"], normalize_key(r["dmr_model"]), r["age_band"])].append(r)

    kept, n_dropped = [], 0
    for (make, model_key, band), members in groups.items():
        preferred_spelling = canonical_spelling.get((make, model_key, band))
        chosen = dict(next((m for m in members if m["dmr_model"] == preferred_spelling), members[0]))
        if len(members) > 1:
            n_dropped += len(members) - 1
            non_pooled = [m for m in members if m["pooled_at_brand"] == "False"]
            if non_pooled:
                # a real model-specific match beats a brand-wide fallback,
                # regardless of which spelling triggered which
                best = non_pooled[0]
                chosen["estimated_value_dkk"] = best["estimated_value_dkk"]
                chosen["n_listings"] = best["n_listings"]
                chosen["pooled_at_brand"] = "False"
            else:
                values = [float(m["estimated_value_dkk"]) for m in members]
                if max(values) - min(values) > 0.15 * min(values):
                    raise ValueError(f"price gap too large to average for {make}/{model_key}/{band}: {values}")
                chosen["estimated_value_dkk"] = round(sum(values) / len(values))
        kept.append(chosen)

    with open(PRICE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=price_fieldnames)
        w.writeheader()
        w.writerows(kept)
    print(f"price_estimates_calibrated.csv: dropped {n_dropped} formatting-duplicate rows "
          f"(preferred non-pooled matches where available), {len(price_rows)} -> {len(kept)} rows")


if __name__ == "__main__":
    main()
