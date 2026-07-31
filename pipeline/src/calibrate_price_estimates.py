"""Calibrates reference/price_estimates.csv against real, currently-listed
Danish prices you supply, and writes reference/price_estimates_calibrated.csv
plus reference/typical_mileage_by_age_band.csv.

This is the step that makes the Poland-derived estimates trustworthy rather
than merely plausible-looking. Everything upstream (build_price_estimates.py)
is a statistically-grounded scaffold with known, documented approximations:
a foreign market's depreciation shape standing in for Denmark's, an unscaled
tax formula applied to a value where the law technically wants it scaled, and
a 2023 data snapshot representing 2026 prices. None of those are fixed by
more cleverness -- they're fixed by comparison against ground truth, which is
what this script does.

MILEAGE
price_estimates.csv has no mileage dimension -- it's one number per
(model, age_band), regardless of how far the car has driven. That's a real
gap: two cars of the same age with very different mileage aren't worth the
same. Poland's listings data has mileage per row, but there isn't a clean way
to fold a second dimension into an already-thin per-model foreign curve
without overfitting on noise.

Instead, this script fits the mileage effect from the anchors themselves.
For every (make, model, age_band) with 2+ real Danish listings at different
mileages, it fits log(price) linearly against mileage -- exact for 2 points,
least-squares for more. That gives, per group, a "typical" (mean-mileage)
price -- which by construction of the least-squares fit is exactly the
geometric mean of that group's listed prices -- used as the calibration
anchor, plus an implied %-price-change-per-10,000-km. The median of that
slope across all groups becomes a single pipeline-wide mileage adjustment,
applied on top of the age-based calibrated estimate:

    price(km) = calibrated_estimate * (1 - MILEAGE_PCT_PER_10K * (km - typical_km) / 10000)

where typical_km is read off reference/typical_mileage_by_age_band.csv (also
written by this script, from the same anchors).

HOW TO SUPPLY GROUND TRUTH
Add rows to reference/calibration_prices.csv: dmr_make, dmr_model, age_band,
our_estimate_dkk (copy from price_estimates.csv), real_asking_price_dkk,
real_mileage_km, source_note. Two real listings per (model, age_band) at
different mileages is far more useful than one -- it's what makes the
mileage adjustment possible at all.

METHOD
Base correction: ratio = real_price / our_estimate per group (using the
group's typical/mean-mileage price when there are 2+ listings). A single
global multiplicative correction (the median ratio) is applied unless the
anchors show a clear trend by price level, in which case low/high price
bands are corrected separately. With a couple dozen points this is
deliberately not a regression against many features -- there isn't enough
data to support one, and a model that looks precise with this few points is
overfit, not accurate.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"
ESTIMATES_CSV = REFERENCE / "price_estimates.csv"
CALIBRATION_CSV = REFERENCE / "calibration_prices.csv"
CALIBRATION_TEMPLATE = REFERENCE / "calibration_prices_TEMPLATE.csv"
OUT_CSV = REFERENCE / "price_estimates_calibrated.csv"
MILEAGE_OUT_CSV = REFERENCE / "typical_mileage_by_age_band.csv"

LOW_HIGH_SPLIT_DKK = 150_000  # if enough anchors on both sides, calibrate separately

# Age bands, restated here in plain years so console output is self-explanatory
# without cross-referencing build_price_estimates.py.
BAND_YEARS = {
    "1": "2020-2022 reg. (~5 yrs old)",
    "2": "2017-2019 reg. (~8 yrs old)",
    "3": "2014-2016 reg. (~11 yrs old)",
    "4": "2010-2013 reg. (~14.5 yrs old)",
}


def fit_log_price_vs_mileage(points: list[tuple[float, float]]) -> tuple[float, float]:
    """points = [(mileage_km, price_dkk), ...], len >= 2.
    Returns (intercept_a, slope_b) for ln(price) = a + b*mileage.
    Least squares; exact fit through both points when len(points) == 2."""
    xs = [p[0] for p in points]
    ys = [math.log(p[1]) for p in points]
    xbar, ybar = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    den = sum((x - xbar) ** 2 for x in xs)
    b = num / den if den else 0.0
    a = ybar - b * xbar
    return a, b


def main() -> None:
    if not CALIBRATION_CSV.exists():
        print(f"No {CALIBRATION_CSV} found.")
        print(f"Fill in real prices in {CALIBRATION_TEMPLATE} and save it as "
              f"{CALIBRATION_CSV.name} in the same folder, then rerun this script.")
        print("Until then, price_estimates.csv is UNCALIBRATED -- do not treat it as final.")
        return

    with open(CALIBRATION_CSV, encoding="utf-8") as f:
        raw_rows = [r for r in csv.DictReader(f) if r.get("real_asking_price_dkk", "").strip()]

    if len(raw_rows) < 5:
        print(f"Only {len(raw_rows)} filled-in listing(s) found in {CALIBRATION_CSV}. "
              f"Need at least 5 for a meaningful calibration -- fill in more rows and rerun.")
        return

    # group individual real listings by (make, model, band) -- there may be
    # 1 or several listings (different mileages) per group
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in raw_rows:
        key = (r["dmr_make"], r["dmr_model"], r["age_band"])
        groups[key].append(r)

    group_results = []
    mileage_slopes_pct_per_10k = []
    typical_mileage_by_band: dict[str, list[float]] = defaultdict(list)

    for (make, model, band), rows in groups.items():
        our_est = float(rows[0]["our_estimate_dkk"])
        listings = [
            (float(r["real_mileage_km"]), float(r["real_asking_price_dkk"]))
            for r in rows
            if r.get("real_mileage_km", "").strip()
        ]

        if len(listings) >= 2:
            a, b = fit_log_price_vs_mileage(listings)
            typical_mileage = statistics.fmean(m for m, _ in listings)
            # at the mean mileage, the fitted line passes through the mean
            # log-price by construction -- i.e. the geometric mean of prices
            anchor_price = math.exp(a + b * typical_mileage)
            pct_per_10k = 1 - math.exp(b * 10000)
            mileage_slopes_pct_per_10k.append(pct_per_10k)
        elif len(listings) == 1:
            typical_mileage = listings[0][0]
            anchor_price = listings[0][1]
        else:
            # no mileage supplied at all -- fall back to plain average asking price
            typical_mileage = None
            anchor_price = statistics.fmean(float(r["real_asking_price_dkk"]) for r in rows)

        if typical_mileage is not None:
            typical_mileage_by_band[band].append(typical_mileage)

        group_results.append({
            "make": make, "model": model, "band": band,
            "our_estimate": our_est, "anchor_price": anchor_price,
            "ratio": anchor_price / our_est, "n_listings": len(rows),
        })

    print(f"{len(group_results)} calibration groups ({len(raw_rows)} individual listings):")
    for x in sorted(group_results, key=lambda x: x["our_estimate"]):
        print(f"  {x['make']:<12} {x['model']:<16} band{x['band']} ({x['n_listings']} listing(s))  "
              f"ours={x['our_estimate']:>10,.0f}  anchor={x['anchor_price']:>10,.0f}  ratio={x['ratio']:.3f}")

    # --- mileage adjustment, derived from real Danish spread, not Poland ---
    if mileage_slopes_pct_per_10k:
        mileage_pct_per_10k = statistics.median(mileage_slopes_pct_per_10k)
        print(f"\nmileage adjustment: median {mileage_pct_per_10k*100:.2f}% price change per "
              f"10,000 km, from {len(mileage_slopes_pct_per_10k)} models with 2+ listings at "
              f"different mileages")
        print("  per-model slopes: " + ", ".join(f"{p*100:.1f}%" for p in sorted(mileage_slopes_pct_per_10k)))
    else:
        mileage_pct_per_10k = None
        print("\nno groups had 2+ listings at different mileages -- cannot derive a mileage "
              "adjustment yet. Add a second listing (different mileage) for at least one "
              "model/band to enable this.")

    print("\ntypical mileage per age band (mean of supplied Danish listings' mileage):")
    typical_mileage_rows = []
    for band in sorted(typical_mileage_by_band):
        vals = typical_mileage_by_band[band]
        mean_km = statistics.fmean(vals)
        print(f"  band {band} ({BAND_YEARS.get(band, '?')}): {mean_km:,.0f} km "
              f"(from {len(vals)} model(s))")
        typical_mileage_rows.append({
            "age_band": band, "band_years": BAND_YEARS.get(band, ""),
            "typical_mileage_km": round(mean_km), "n_source_models": len(vals),
        })

    if typical_mileage_rows:
        with open(MILEAGE_OUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(typical_mileage_rows[0].keys()))
            w.writeheader()
            w.writerows(typical_mileage_rows)
        print(f"wrote {MILEAGE_OUT_CSV}")

    # --- base (age-only) calibration, same method as before ---
    all_ratios = [x["ratio"] for x in group_results]
    global_median = statistics.median(all_ratios)
    print(f"\nglobal median ratio (real / our_estimate): {global_median:.3f}")

    low = [x["ratio"] for x in group_results if x["our_estimate"] < LOW_HIGH_SPLIT_DKK]
    high = [x["ratio"] for x in group_results if x["our_estimate"] >= LOW_HIGH_SPLIT_DKK]
    use_split = len(low) >= 4 and len(high) >= 4
    low_median = statistics.median(low) if low else None
    high_median = statistics.median(high) if high else None
    if use_split:
        print(f"split calibration in use: below {LOW_HIGH_SPLIT_DKK:,} DKK -> x{low_median:.3f} "
              f"({len(low)} groups), at/above -> x{high_median:.3f} ({len(high)} groups)")
    else:
        print(f"not enough groups on both sides of {LOW_HIGH_SPLIT_DKK:,} DKK for a split "
              f"correction ({len(low)} below, {len(high)} at/above) -- using one global factor")
        if high and not use_split:
            print("  NOTE: anchors above the split are thin or absent -- calibration is least "
                  "trustworthy for pricier cars (Audi/BMW/Volvo/Skoda/RAV4/Qashqai/Focus etc.) "
                  "until more anchors are added there.")

    def correction_for(value: float) -> float:
        if use_split:
            return low_median if value < LOW_HIGH_SPLIT_DKK else high_median
        return global_median

    # in-sample residual check -- optimistic (these ARE the calibration
    # points) but still catches a badly-misspecified split.
    errs = []
    for x in group_results:
        corrected = x["our_estimate"] * correction_for(x["our_estimate"])
        pct_err = abs(corrected - x["anchor_price"]) / x["anchor_price"]
        errs.append(pct_err)
    print(f"\nin-sample residual error after calibration: median {statistics.median(errs)*100:.1f}%, "
          f"max {max(errs)*100:.1f}%")
    print("(in-sample only -- this is how well calibration fits the anchors themselves, "
          "not a held-out accuracy estimate. Report it as such.)")

    with open(ESTIMATES_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        raw = float(r["estimated_value_dkk"])
        factor = correction_for(raw)
        r["estimated_value_dkk"] = round(raw * factor)
        r["calibration_factor_applied"] = round(factor, 4)
        r["calibrated"] = True
        r["mileage_adjustment_pct_per_10k_km"] = (
            round(mileage_pct_per_10k, 4) if mileage_pct_per_10k is not None else ""
        )

    fieldnames = list(rows[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {OUT_CSV} ({len(rows)} rows, calibrated)")

    if mileage_pct_per_10k is not None:
        print(f"\nTo price a specific car: take its row's estimated_value_dkk (that's the price "
              f"at this band's typical_mileage_km from {MILEAGE_OUT_CSV.name}), then adjust:\n"
              f"  price(km) = estimated_value_dkk * (1 - {mileage_pct_per_10k:.4f} * "
              f"(km - typical_mileage_km) / 10000)")


if __name__ == "__main__":
    main()
