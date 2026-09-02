"""Implements reports/phase4_scoring_spec.md against the actual data, using the
four decisions the user made and the two the spec's own recommendation was
adopted for without re-asking (suppress non-positive-depreciation pairs;
3,000 DKK/yr per repair-burden-unit, see reference/repair_cost_constant.csv).

DECISIONS APPLIED (user's choices, 2026-07-31):
  1. Horizon: ONE horizon only, ~6 years, not three, not interpolated 5/10.
  2. Broken (zero/negative depreciation) pairs: suppressed, not floored.
  3. Repair constant: 3,000 DKK/yr/burden-unit (reference/repair_cost_constant.csv).
  4. Engagement: kept OUT of the primary ranking, but a second list
     ("most car for the money") blends it in at a disclosed 50/50 weight
     against cost percentile -- this is the "two toggleable orderings"
     option the user picked over "cost-only" and "small fixed weight".
  5. Row unit: (dmr_make, dmr_model, age_band). A model can appear in several
     brackets at different ages -- that's intentional, not a bug.
  6. Suzuki/DS: excluded from this file (no price data exists to rank them).
     Their Phase 3 rows are untouched in model_age_band_metrics.csv for a
     Phase 5 model page with a "no price estimate" note -- not this file's
     job to carry that flag.

MIN_DK_VEHICLES (coverage_audit.md finding 4): there was a floor on UK MOT
tests (RANKING_FLOOR_TESTS, Phase 3) but none on the DANISH side, so a row
backed by a literal handful of Danish registrations could still be ranked
as if it were a real, buyable car -- e.g. Toyota Aygo 5-DØRS 2020-2022 had
ONE registered Danish car and sat at running-cost rank 68 of 607 before this
was added. The site's own copy sells these lists as cars a reader can
actually go buy in Denmark, which one or two registered examples is not.

MIN_DK_VEHICLES = 50 IS A JUDGEMENT CALL, NOT A DERIVED THRESHOLD, unlike
RANKING_FLOOR_TESTS (which traces to a stated statistical-stability target
in the Phase 2 strategy doc). There is no equivalent statistical argument
for a Danish fleet count -- dk_vehicle_count does not feed any standard
error calculation here, it is just "is this enough cars that a reader could
plausibly cross-shop one." 50 was chosen as a round number comfortably above
the "1-3 stray DMR registrations" cases the audit called out by name, while
keeping ordinary lower-volume models (which can legitimately be in the low
hundreds for a single age band) in the rankings. Run this file's own output
at 50 vs 100 and compare the row counts dropped before treating 50 as
settled -- it is meant to be retuned, not treated as final.

WHAT "ONE 6-YEAR HORIZON" ACTUALLY MEANS PER ENTRY BAND
The only holds that exist are gaps between age bands with real data on both
ends (Rule 0, phase4_scoring_spec.md section 0). There is no single (entry,
exit) pair spanning ~6 years for every entry band, so the closest available
span is used per entry band, and it is reported per row -- never assumed
uniform:
  entry band 1 (age ~5)    -> exit band 3 (age ~11),   hold 6.0 yr
  entry band 2 (age ~8)    -> exit band 4 (age ~14.5), hold 6.5 yr
  entry band 3 (age ~11)   -> exit band 4 (age ~14.5), hold 3.5 yr (shorter; flagged)
  entry band 4 (age ~14.5) -> no older band exists.    no depreciation term at
                                                         all; tco_per_year is
                                                         running cost only,
                                                         flagged depreciation_available=False.
Excluding band-4 entries outright would erase most of the cheapest bracket,
which is exactly the budget segment ("if my budget is 30k") the site exists
to answer -- so they stay in, honestly labelled as running-cost-only rather
than a full TCO.

MILEAGE ADJUSTMENT, TWO FIXES FROM THE SPEC (not decisions -- "strictly more
correct than the status quo" per the spec, so applied directly):
  (a) Multiplicative, not linear: (1 - slope) ** (delta_km / 10000). The
      committed linear form crosses zero at ~256,000 km and goes negative
      beyond it.
  (b) Reference mileage forced monotonic via pool-adjacent-violators (PAVA)
      before use. The raw table has band 3 (135,750 km) below band 2
      (143,000 km) -- noise from only 2-7 source models per band -- which
      produced a car gaining 7.7% of value by being driven further. PAVA is
      the standard technique for enforcing a non-decreasing sequence while
      staying as close as possible to the original (noisy) values; it does
      not invent a new number, it just removes the one impossible reversal.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"
PRICE_CSV = REFERENCE / "price_estimates_calibrated.csv"
METRICS_CSV = REFERENCE / "model_age_band_metrics.csv"
TYPICAL_MILEAGE_CSV = REFERENCE / "typical_mileage_by_age_band.csv"
REPAIR_CONST_CSV = REFERENCE / "repair_cost_constant.csv"
FUEL_FLAGS_CSV = REFERENCE / "model_age_band_fuel_flags.csv"
SUZUKI_DS_PRICE_CSV = REFERENCE / "suzuki_ds_price_estimates.csv"
# Built by build_combined_reliability.py, which combines this UK metrics file
# with model_age_band_metrics_no.csv (Norway). Purely additive: the four
# columns it contributes here (combined_reliability_z, reliability_agreement,
# reliability_source_count, reliability_confidence) never feed cost_rank_in_group
# or any other ranking decision, so joining it cannot move an existing rank --
# see the "must not regress" check in main() below.
RELIABILITY_COMBINED_CSV = REFERENCE / "model_age_band_reliability_combined.csv"
OUT_CSV = REFERENCE / "model_bracket_rankings.csv"
METHODOLOGY_CSV = REFERENCE / "methodology_counts.csv"

AGE_YEARS = {"1": 5.0, "2": 8.0, "3": 11.0, "4": 14.5}
BAND_YEARS = {
    "1": "2020-2022", "2": "2017-2019", "3": "2014-2016", "4": "2010-2013",
}
HORIZON_SPEC = {  # entry_band -> (exit_band or None, hold_years, shorter_than_6yr)
    "1": ("3", 6.0, False),
    "2": ("4", 6.5, False),
    "3": ("4", 3.5, True),
    "4": (None, None, None),
}
ANNUAL_KM_ASSUMPTION = 15000  # same constant Phase 3 uses for fuel cost (section 4.6)
MIN_DK_VEHICLES = 50  # judgement call, not derived -- see module docstring
BRACKETS = [
    (0, 50_000, "1", "Up to 50,000 DKK"),
    (50_000, 90_000, "2", "50,000-90,000 DKK"),
    (90_000, 150_000, "3", "90,000-150,000 DKK"),
    (150_000, 250_000, "4", "150,000-250,000 DKK"),
    (250_000, float("inf"), "5", "Above 250,000 DKK"),
]
TIER_CUTS = [  # cumulative fraction, best-to-worst
    (0.10, "S"), (0.30, "A"), (0.70, "B"), (0.90, "C"), (1.01, "D"),
]


def pava_monotonic(values: list[float]) -> list[float]:
    """Pool-adjacent-violators: smallest set of adjustments that makes the
    sequence non-decreasing, minimizing squared deviation from the input."""
    levels = [[v, 1] for v in values]  # [mean, count] blocks
    i = 0
    while i < len(levels) - 1:
        if levels[i][0] > levels[i + 1][0]:
            merged_sum = levels[i][0] * levels[i][1] + levels[i + 1][0] * levels[i + 1][1]
            merged_count = levels[i][1] + levels[i + 1][1]
            levels[i:i + 2] = [[merged_sum / merged_count, merged_count]]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for mean, count in levels:
        out.extend([mean] * count)
    return out


def bracket_for(price: float) -> tuple[str, str]:
    for lo, hi, bid, label in BRACKETS:
        if lo <= price < hi:
            return bid, label
    return BRACKETS[-1][2], BRACKETS[-1][3]


def price_confidence(
    n_listings: int,
    pooled: bool,
    own_cell_anchor_count: int = 0,
    own_cell_anchor_spread: float | None = None,
) -> str:
    if pooled or n_listings < 30:
        existing = "low"
    elif n_listings < 100:
        existing = "medium"
    else:
        existing = "high"

    # Real, own-cell Danish anchors (calibrate_price_estimates.py's
    # price_own_cell_anchor_count/spread) are direct ground truth for this
    # exact model/band, not a foreign-market proxy -- so they can only ever
    # raise confidence above what the Poland-derived sample size implies,
    # never lower it. Thresholds specified in advance, not tuned here:
    # 5+ own anchors with a tight spread (CV <= 30%) earns "high" outright;
    # 3+ (or an existing "medium") earns at least "medium"; below that the
    # existing Poland-derived result is left untouched.
    own_n = int(own_cell_anchor_count or 0)
    own_spread = own_cell_anchor_spread

    if existing == "high":
        return "high"
    if own_n >= 5 and own_spread is not None and own_spread <= 0.30:
        return "high"
    if own_n >= 3 or existing == "medium":
        return "medium"
    return existing  # "low", unchanged


def quantile_tier(rank: int, n: int) -> str:
    frac = (rank) / n  # rank is 0-indexed position among sorted-best-first
    for cut, tier in TIER_CUTS:
        if frac < cut:
            return tier
    return "D"


def main() -> None:
    with open(PRICE_CSV, encoding="utf-8") as f:
        price_rows = list(csv.DictReader(f))
    with open(METRICS_CSV, encoding="utf-8") as f:
        metrics_rows = list(csv.DictReader(f))
    with open(TYPICAL_MILEAGE_CSV, encoding="utf-8") as f:
        typical_rows = list(csv.DictReader(f))
    with open(REPAIR_CONST_CSV, encoding="utf-8") as f:
        repair_const = float(next(r for r in csv.DictReader(open(REPAIR_CONST_CSV, encoding="utf-8"))
                                   if r["basis"] == "primary")["dkk_per_burden_unit_per_year"])
    with open(FUEL_FLAGS_CSV, encoding="utf-8") as f:
        fuel_flags_idx = {(r["dmr_make"], r["dmr_model"], r["age_band"]): r for r in csv.DictReader(f)}
    reliability_combined_idx = {}
    if RELIABILITY_COMBINED_CSV.exists():
        with open(RELIABILITY_COMBINED_CSV, encoding="utf-8") as f:
            reliability_combined_idx = {(r["dmr_make"], r["dmr_model"], r["age_band"]): r for r in csv.DictReader(f)}

    mileage_slope = float(price_rows[0]["mileage_adjustment_pct_per_10k_km"])

    raw_typical_km = {r["age_band"]: float(r["typical_mileage_km"]) for r in typical_rows}
    ordered_bands = ["1", "2", "3", "4"]
    smoothed = pava_monotonic([raw_typical_km[b] for b in ordered_bands])
    typical_km = dict(zip(ordered_bands, smoothed))
    print("typical mileage reference, raw -> PAVA-smoothed:")
    for b in ordered_bands:
        print(f"  band {b}: {raw_typical_km[b]:,.0f} -> {typical_km[b]:,.0f} km")

    price_idx = {(r["dmr_make"], r["dmr_model"], r["age_band"]): r for r in price_rows}
    if SUZUKI_DS_PRICE_CSV.exists():
        # Kept out of price_estimates_calibrated.csv itself, and merged here
        # at read time instead, so this file never needs mutating in place
        # (a past bug this session came from repeatedly mutating an
        # already-processed CSV -- regenerating from source and merging
        # additively avoids repeating that).
        with open(SUZUKI_DS_PRICE_CSV, encoding="utf-8") as f:
            suzuki_ds_rows = list(csv.DictReader(f))
        n_before = len(price_idx)
        for r in suzuki_ds_rows:
            price_idx[(r["dmr_make"], r["dmr_model"], r["age_band"])] = r
        print(f"merged {len(price_idx) - n_before} Suzuki/DS price cells from {SUZUKI_DS_PRICE_CSV.name}")
    metrics_idx = {(r["dmr_make"], r["dmr_model"], r["age_band"]): r for r in metrics_rows}
    joined = {k: {**metrics_idx[k], **v} for k, v in price_idx.items() if k in metrics_idx}
    print(f"\n{len(price_idx)} priced cells, {len(metrics_idx)} metric cells, "
          f"{len(joined)} joined (Rule 0 base set)")

    out_rows = []
    n_suppressed_nonpositive = 0
    n_no_exit_data = 0
    for (make, model, entry_band), entry in joined.items():
        exit_band, hold_years, shorter_horizon = HORIZON_SPEC[entry_band]
        entry_price = float(entry["estimated_value_dkk"])

        depreciation_available = False
        depreciation = resale_price = mileage_factor = hold_used = None
        exclusion_reason = ""

        if exit_band is not None:
            exit_key = (make, model, exit_band)
            if exit_key in joined:  # Rule 0: exit cell must also carry Phase 3 metrics
                exit_row = joined[exit_key]
                resale_raw = float(exit_row["estimated_value_dkk"])
                km_at_exit = typical_km[entry_band] + hold_years * ANNUAL_KM_ASSUMPTION
                delta_km = km_at_exit - typical_km[exit_band]
                mileage_factor = (1 - mileage_slope) ** (delta_km / 10000)
                resale_price = resale_raw * mileage_factor
                depreciation = entry_price - resale_price
                if depreciation > 0:
                    depreciation_available = True
                    hold_used = hold_years
                else:
                    n_suppressed_nonpositive += 1
                    exclusion_reason = "non_positive_depreciation"
            else:
                n_no_exit_data += 1
                exclusion_reason = "no_exit_band_data"

        fuel_annual = float(entry["median_annual_fuel_cost_dkk"]) if entry.get("median_annual_fuel_cost_dkk") else None
        tax_annual = float(entry["median_annual_ejerafgift_dkk"]) if entry.get("median_annual_ejerafgift_dkk") else None
        burden = entry.get("repair_burden_index")
        repair_annual = float(burden) * repair_const if burden not in (None, "") else None

        running_annual = sum(x for x in (fuel_annual, tax_annual, repair_annual) if x is not None)

        if depreciation_available:
            fuel_total = fuel_annual * hold_used if fuel_annual is not None else None
            tax_total = tax_annual * hold_used if tax_annual is not None else None
            repair_total = repair_annual * hold_used if repair_annual is not None else None
            tco_total = depreciation + sum(x for x in (fuel_total, tax_total, repair_total) if x is not None)
            tco_per_year = tco_total / hold_used
            running_cost_per_year = tco_per_year - (depreciation / hold_used)
        else:
            fuel_total = tax_total = repair_total = tco_total = None
            tco_per_year = running_annual  # running-cost-only figure, no resale term
            running_cost_per_year = running_annual  # same thing here: no purchase price was ever in this number

        reliability_unstable = entry.get("reliability_unstable") == "True"
        meets_floor = entry.get("meets_stability_floor") == "True"
        n_listings = int(entry.get("n_listings", 0) or 0)
        pooled = entry.get("pooled_at_brand") == "True"
        dk_vehicle_count_int = int(entry.get("dk_vehicle_count", 0) or 0)
        insufficient_dk_fleet = dk_vehicle_count_int < MIN_DK_VEHICLES

        excluded_from_rank = (
            bool(exclusion_reason) or reliability_unstable or not meets_floor or insufficient_dk_fleet
        )
        # Running-cost-only ranking never uses depreciation or the entry/exit
        # price lookup, so a row excluded from the price-based rankings for
        # "no_exit_band_data" or "non_positive_depreciation" is still valid
        # here -- only a genuine reliability data problem, OR too few real
        # Danish cars to back the row at all, disqualifies it from BOTH
        # rankings (a car with two registered examples isn't "a car you can
        # actually buy in Denmark" regardless of which list it would land in).
        excluded_from_running_cost_rank = reliability_unstable or not meets_floor or insufficient_dk_fleet
        if not exclusion_reason and insufficient_dk_fleet:
            exclusion_reason = "insufficient_dk_fleet"
        elif not exclusion_reason and reliability_unstable:
            exclusion_reason = "reliability_unstable"
        elif not exclusion_reason and not meets_floor:
            exclusion_reason = "below_stability_floor"

        price_bracket_id, price_bracket_label = bracket_for(entry_price)

        fuel_flags = fuel_flags_idx.get((make, model, entry_band))
        is_hybrid = fuel_flags["is_hybrid"] == "True" if fuel_flags else False
        is_diesel_dominant = fuel_flags["is_diesel_dominant"] == "True" if fuel_flags else False

        # New columns from build_combined_reliability.py -- see that script's
        # module docstring for the combination rule. Present only for cells
        # with at least one statistically stable reliability source (every
        # row missing here is already excluded_from_rank for the pre-existing
        # reliability_unstable/meets_stability_floor reason, so nothing ranked
        # is left without a confidence label).
        rel = reliability_combined_idx.get((make, model, entry_band))

        out_rows.append({
            "dmr_make": make, "dmr_model": model, "age_band": entry_band,
            "band_years": BAND_YEARS[entry_band], "approx_age_years": AGE_YEARS[entry_band],
            "price_bracket_id": price_bracket_id, "price_bracket_label": price_bracket_label,
            "entry_price_dkk": round(entry_price), "entry_price_reference_km": round(typical_km[entry_band]),
            "exit_age_band": exit_band or "", "hold_years": hold_used if hold_used is not None else "",
            "shorter_than_6yr_horizon": bool(shorter_horizon) if shorter_horizon is not None else "",
            "horizon_available": exit_band is not None,
            "resale_price_dkk": round(resale_price) if resale_price is not None else "",
            "mileage_adjustment_factor": round(mileage_factor, 4) if mileage_factor is not None else "",
            "depreciation_dkk": round(depreciation) if depreciation is not None else "",
            "depreciation_available": depreciation_available,
            "fuel_total_dkk": round(fuel_total) if fuel_total is not None else "",
            "ejerafgift_total_dkk": round(tax_total) if tax_total is not None else "",
            "repair_total_dkk": round(repair_total) if repair_total is not None else "",
            "tco_total_dkk": round(tco_total) if tco_total is not None else "",
            "tco_per_year": round(tco_per_year) if tco_per_year is not None else "",
            "running_cost_per_year": round(running_cost_per_year),
            "standardized_pass_rate": entry.get("standardized_pass_rate", ""),
            "raw_pass_rate": entry.get("raw_pass_rate", ""),
            "repair_burden_index": entry.get("repair_burden_index", ""),
            "median_annual_fuel_cost_dkk": entry.get("median_annual_fuel_cost_dkk", ""),
            "median_annual_ejerafgift_dkk": entry.get("median_annual_ejerafgift_dkk", ""),
            "engagement_score": entry.get("engagement_score", ""),
            "reliability_unstable": reliability_unstable,
            "meets_stability_floor": meets_floor,
            "dk_vehicle_count": entry.get("dk_vehicle_count", ""),
            "n_nt_tests": entry.get("n_nt_tests", ""),
            "price_n_listings": n_listings,
            "price_pooled_at_brand": pooled,
            "price_calibration_factor": entry.get("calibration_factor_applied", ""),
            # Carried through from calibrate_price_estimates.py so the confidence
            # figure below is auditable after the fact: which rows earned their
            # confidence from real, own-cell Danish anchors versus a pooled or
            # global correction, without re-deriving it from the intermediate file.
            "price_anchor_source": entry.get("price_anchor_source", ""),
            "price_own_cell_anchor_count": entry.get("price_own_cell_anchor_count", ""),
            "price_own_cell_anchor_spread": entry.get("price_own_cell_anchor_spread", ""),
            "price_confidence": price_confidence(
                n_listings, pooled,
                own_cell_anchor_count=int(entry.get("price_own_cell_anchor_count", 0) or 0),
                own_cell_anchor_spread=(
                    float(entry["price_own_cell_anchor_spread"])
                    if entry.get("price_own_cell_anchor_spread") not in (None, "")
                    else None
                ),
            ),
            # Empty for every normal (Poland-sourced) row. Only set for the Suzuki/DS
            # rows build_suzuki_ds_prices.py produces, so the site can tell the two
            # pricing mechanisms apart and describe each honestly instead of always
            # narrating the foreign-listings path.
            "donor_model": entry.get("donor_model", ""),
            "excluded_from_rank": excluded_from_rank,
            "excluded_from_running_cost_rank": excluded_from_running_cost_rank,
            "exclusion_reason": exclusion_reason,
            "is_hybrid": is_hybrid,
            "is_diesel_dominant": is_diesel_dominant,
            "combined_reliability_z": rel["combined_reliability_z"] if rel else "",
            "reliability_agreement": rel["reliability_agreement"] if rel else "",
            "reliability_source_count": rel["reliability_source_count"] if rel else "",
            "reliability_confidence": rel["reliability_confidence"] if rel else "",
        })

    print(f"\n{n_suppressed_nonpositive} pairs suppressed (non-positive depreciation, DECISION 2)")
    print(f"{n_no_exit_data} entry cells have no exit-band data at all (still kept, running-cost-only)")

    # --- rank within bracket only, mixing age bands, per spec section 1.6
    #     and DECISION 5: the whole point of a (model, age_band) row is that
    #     a 14-year-old Octavia and a 5-year-old Aygo at the same price
    #     compete directly for the same buyer. tco_per_year is already
    #     annualised so different hold lengths are comparable. Band-4 rows
    #     carry no depreciation term (no forward resale point exists), so
    #     their tco_per_year is running-cost-only -- genuinely not the same
    #     quantity as a full TCO figure, which is why the site marks those
    #     rows with an asterisk and an explanation rather than hiding the
    #     gap by silo-ing them into their own ranking group.
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in out_rows:
        if not r["excluded_from_rank"]:
            groups[r["price_bracket_id"]].append(r)

    for bracket, members in groups.items():
        n = len(members)
        # list 1: cheapest to own -- pure cost ascending
        by_cost = sorted(members, key=lambda r: r["tco_per_year"])
        for i, r in enumerate(by_cost):
            r["cost_rank_in_group"] = i + 1
            r["cost_tier"] = quantile_tier(i, n)

        # list 2: most car for the money -- 50/50 disclosed blend of cost
        # percentile (cheaper = higher) and engagement percentile (Phase 3's
        # subjective desirability score), computed only among rows that have
        # both figures.
        eligible = [r for r in members if r["engagement_score"] not in ("", None)]
        m = len(eligible)
        if m >= 3:
            by_cost_pct = sorted(eligible, key=lambda r: r["tco_per_year"], reverse=True)  # worst first
            for i, r in enumerate(by_cost_pct):
                r["_cost_pct"] = i / (m - 1) if m > 1 else 1.0  # 1.0 = cheapest
            by_eng_pct = sorted(eligible, key=lambda r: float(r["engagement_score"]))
            for i, r in enumerate(by_eng_pct):
                r["_eng_pct"] = i / (m - 1) if m > 1 else 1.0  # 1.0 = most engaging
            for r in eligible:
                r["value_for_money_score"] = round(0.5 * r["_cost_pct"] + 0.5 * r["_eng_pct"], 4)
                r["value_for_money_weight_cost"] = 0.5
                r["value_for_money_weight_engagement"] = 0.5
            by_vfm = sorted(eligible, key=lambda r: r["value_for_money_score"], reverse=True)
            for i, r in enumerate(by_vfm):
                r["value_for_money_rank_in_group"] = i + 1
                r["value_for_money_tier"] = quantile_tier(i, m)

    # list 3: cheapest to run -- fuel + tax + repairs only, purchase price
    # and resale left out entirely. Deliberately NOT scoped to a price
    # bracket like lists 1 and 2: the whole point is to let a reader compare
    # a car they'd normally never cross-shop against one in a different
    # bracket, and see whether the pricier car actually costs less to keep
    # on the road. Ranked across the whole fleet.
    running_eligible = [r for r in out_rows if not r["excluded_from_running_cost_rank"]]
    n_running = len(running_eligible)
    by_running_cost = sorted(running_eligible, key=lambda r: r["running_cost_per_year"])
    for i, r in enumerate(by_running_cost):
        r["running_cost_rank_overall"] = i + 1
        r["running_cost_tier"] = quantile_tier(i, n_running)
    print(f"\n{n_running} rows eligible for the price-agnostic running-cost ranking "
          f"(excludes only reliability-unstable/below-floor rows, not depreciation gaps)")

    for r in out_rows:
        r.setdefault("running_cost_rank_overall", "")
        r.setdefault("running_cost_tier", "")
        r.setdefault("cost_rank_in_group", "")
        r.setdefault("cost_tier", "")
        r.setdefault("value_for_money_score", "")
        r.setdefault("value_for_money_weight_cost", "")
        r.setdefault("value_for_money_weight_engagement", "")
        r.setdefault("value_for_money_rank_in_group", "")
        r.setdefault("value_for_money_tier", "")
        r.pop("_cost_pct", None)
        r.pop("_eng_pct", None)

    fieldnames = list(out_rows[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {OUT_CSV} ({len(out_rows)} rows)")

    n_ranked = sum(1 for r in out_rows if not r["excluded_from_rank"])
    print(f"{n_ranked} of {len(out_rows)} rows are rank-eligible")

    # --- the headline finding: which bracket minimises cost-per-utility ---
    bracket_medians = defaultdict(list)
    for r in out_rows:
        if not r["excluded_from_rank"] and r["cost_tier"] in ("S", "A"):
            bracket_medians[r["price_bracket_label"]].append(r["tco_per_year"])
    print("\nmedian tco_per_year among S+A tier members, by bracket:")
    best_bracket, best_val = None, float("inf")
    for label, vals in sorted(bracket_medians.items()):
        med = statistics.median(vals)
        print(f"  {label}: {med:,.0f} DKK/yr (n={len(vals)})")
        if med < best_val:
            best_val, best_bracket = med, label
    print(f"-> lowest-TCO bracket among top performers: {best_bracket} ({best_val:,.0f} DKK/yr)")

    # --- methodology counts, for the "how we got here" page ------------
    # 1,778,307 is dk_fleet's total scoped population (Personbil, registered,
    # 2010-2022, non-BEV) -- pipeline/reports/phase1_warehouse_report.md line
    # 32. Coverage is recomputed from the live crosswalk.csv, not hardcoded,
    # since the crosswalk has grown since Phase 3's report was written (210
    # models there vs however many rows crosswalk.csv actually has now).
    TOTAL_SCOPED_FLEET = 1_778_307
    with open(REFERENCE / "crosswalk.csv", encoding="utf-8") as f:
        crosswalk_rows = list(csv.DictReader(f))
    crosswalk_vehicle_count = sum(int(r["dk_vehicle_count"]) for r in crosswalk_rows)
    crosswalk_pct = crosswalk_vehicle_count / TOTAL_SCOPED_FLEET * 100

    suzuki_ds_models = {(m, mo) for (m, mo, b) in metrics_idx if m in ("SUZUKI", "DS")}
    suzuki_ds_priced_models = {(m, mo) for (m, mo, b) in price_idx if m in ("SUZUKI", "DS")}
    n_suzuki_ds_unpriced = len(suzuki_ds_models - suzuki_ds_priced_models)

    methodology = [
        {"fact": "Danish vehicles in scope (2010-2022, petrol/diesel/hybrid)", "value": TOTAL_SCOPED_FLEET, "source": "phase1_warehouse_report.md", "date": "2026-07-31"},
        {"fact": "Eligible DVSA MOT tests after filters", "value": 48220796, "source": "phase3_metrics_report.md", "date": "2026-07-31"},
        {"fact": "Physical DVSA NT tests before filters", "value": 48626203, "source": "phase3_metrics_report.md", "date": "2026-07-31"},
        {"fact": "Crosswalked models (share of DK fleet by count)", "value": f"{len(crosswalk_rows)} ({crosswalk_pct:.1f}%)", "source": "crosswalk.csv", "date": "2026-07-31"},
        {"fact": "Model/age-band cells with Phase 3 running-cost metrics", "value": len(metrics_rows), "source": "model_age_band_metrics.csv", "date": "2026-07-31"},
        {"fact": "Model/age-band cells with a calibrated price estimate", "value": len(price_rows), "source": "price_estimates_calibrated.csv", "date": "2026-07-31"},
        {"fact": "Cells with both price and running-cost data (Rule 0 base)", "value": len(joined), "source": "build_phase4_rankings.py", "date": "2026-07-31"},
        {"fact": "Real Danish listings used to calibrate prices", "value": 27, "source": "calibration_prices.csv", "date": "2026-07-31"},
        {"fact": "Rows in the final bracket ranking, rank-eligible", "value": f"{n_ranked} of {len(out_rows)}", "source": "model_bracket_rankings.csv", "date": "2026-07-31"},
        {"fact": "Suzuki/DS models still unpriced (no real price found yet)", "value": n_suzuki_ds_unpriced, "source": "suzuki_ds_price_anchors.csv", "date": "2026-07-31"},
        {"fact": "Repair cost constant (DKK per burden-unit-year)", "value": repair_const, "source": "repair_cost_constant.csv", "date": "2026-07-31"},
        {"fact": "Rows flagged hybrid (trim badge, or petrol economy too high for a combustion engine)", "value": sum(1 for r in out_rows if r["is_hybrid"]), "source": "model_age_band_fuel_flags.csv", "date": "2026-07-31"},
        {"fact": "Rows flagged diesel-dominant (over half the cell is diesel)", "value": sum(1 for r in out_rows if r["is_diesel_dominant"]), "source": "model_age_band_fuel_flags.csv", "date": "2026-07-31"},
        {"fact": "Mileage adjustment slope (%/10,000 km)", "value": round(mileage_slope * 100, 2), "source": "price_estimates_calibrated.csv", "date": "2026-07-31"},
        {"fact": "Ranked rows backed by two reliability sources (UK + Norway)", "value": sum(1 for r in out_rows if str(r["reliability_source_count"]) == "2"), "source": "model_age_band_reliability_combined.csv", "date": "2026-09-02"},
        {"fact": "Ranked rows backed by one reliability source only", "value": sum(1 for r in out_rows if str(r["reliability_source_count"]) == "1"), "source": "model_age_band_reliability_combined.csv", "date": "2026-09-02"},
        {"fact": "Ranked rows flagged low reliability confidence", "value": sum(1 for r in out_rows if r["reliability_confidence"] == "low"), "source": "model_age_band_reliability_combined.csv", "date": "2026-09-02"},
        {"fact": "Ranked rows flagged medium reliability confidence", "value": sum(1 for r in out_rows if r["reliability_confidence"] == "medium"), "source": "model_age_band_reliability_combined.csv", "date": "2026-09-02"},
        {"fact": "Ranked rows flagged high reliability confidence", "value": sum(1 for r in out_rows if r["reliability_confidence"] == "high"), "source": "model_age_band_reliability_combined.csv", "date": "2026-09-02"},
    ]
    with open(METHODOLOGY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["fact", "value", "source", "date"])
        w.writeheader()
        w.writerows(methodology)
    print(f"wrote {METHODOLOGY_CSV} ({len(methodology)} facts)")


if __name__ == "__main__":
    main()
