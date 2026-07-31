"""Prices the 11 Suzuki/DS models that build_price_estimates.py cannot reach,
because Poland's listings (the foreign-market stand-in used for every other
make) carry zero Suzuki or DS rows -- there is no curve there to anchor.

METHOD: shape from a donor, level from real Danish prices.
Every other model's curve has a SHAPE (how much of its value it loses by
each age band, in percentage terms) and a LEVEL (what it's actually worth in
kroner). Poland supplied both for 199 models. Here, Poland can't supply
either, but a same-segment model that Poland DID cover can still supply a
believable SHAPE (Suzuki and, say, Hyundai depreciate at broadly similar
rates for a similar kind of car), and real Danish asking prices found by
hand supply the LEVEL. One or more listings per model is enough, because the
shape is borrowed, not built from scratch.

    price(model, band) = anchor_price_at_typical_mileage
                          * donor_price(band) / donor_price(anchor_band)

When a model has more than one real listing, each is first mileage-adjusted
to that age band's typical mileage (same multiplicative formula and
PAVA-smoothed reference table build_phase4_rankings.py uses elsewhere, so a
249,000 km listing and a 51,000 km listing for the same model don't just get
averaged as if mileage didn't matter), then those adjusted prices are
averaged into a single anchor. This is the same reasoning already applied
site-wide, just run by hand here since these two listings are all the real
price signal that exists for these models.

DONOR ASSIGNMENT, by segment, each a non-pooled (model-specific, not
brand-average) curve in price_estimates_calibrated.csv:
    ALTO, Celerio, IGNIS, SPLASH  (city cars)        -> Hyundai I10
    SWIFT, BALENO                (superminis)        -> Toyota Yaris
    VITARA                       (compact SUV)       -> Nissan Qashqai
    SX4 S-Cross                  (subcompact crossover) -> Renault Captur
    SX4, SX4 COMBIBACK           (older compact hatch/wagon) -> Ford Focus
    DS 3                         (premium supermini)  -> Peugeot 208

This is a real approximation and is labelled as one: `pooled_at_brand` is
set True and `price_confidence` will read "low" for every row this script
produces, same as any other heavily-borrowed estimate on the site, and the
donor used is recorded in a comment column so it can be checked or swapped.

HOW TO SUPPLY DATA: add rows to reference/suzuki_ds_price_anchors.csv (one
row per real listing, several rows per model are fine) with a real DKK
asking price and mileage you found by hand, then rerun this script.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"
PRICE_CSV = REFERENCE / "price_estimates_calibrated.csv"
TYPICAL_MILEAGE_CSV = REFERENCE / "typical_mileage_by_age_band.csv"
ANCHORS_CSV = REFERENCE / "suzuki_ds_price_anchors.csv"
ANCHORS_TEMPLATE = REFERENCE / "suzuki_ds_price_anchors_TEMPLATE.csv"
OUT_CSV = REFERENCE / "suzuki_ds_price_estimates.csv"

DONORS = {
    ("SUZUKI", "ALTO"): ("HYUNDAI", "I10"),
    ("SUZUKI", "Celerio"): ("HYUNDAI", "I10"),
    ("SUZUKI", "IGNIS"): ("HYUNDAI", "I10"),
    ("SUZUKI", "SPLASH"): ("HYUNDAI", "I10"),
    ("SUZUKI", "SWIFT"): ("TOYOTA", "YARIS"),
    ("SUZUKI", "BALENO"): ("TOYOTA", "YARIS"),
    ("SUZUKI", "VITARA"): ("NISSAN", "QASHQAI"),
    ("SUZUKI", "SX4 S-Cross"): ("RENAULT", "CAPTUR"),
    ("SUZUKI", "SX4"): ("FORD", "FOCUS"),
    ("SUZUKI", "SX4 COMBIBACK"): ("FORD", "FOCUS"),
    ("DS", "DS 3"): ("PEUGEOT", "208"),
}


def pava_monotonic(values: list[float]) -> list[float]:
    """Same pool-adjacent-violators smoothing build_phase4_rankings.py runs
    on the typical-mileage table, duplicated here (it's four numbers) so
    this script stays runnable on its own."""
    levels = [[v, 1] for v in values]
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


def main() -> None:
    if not ANCHORS_CSV.exists():
        print(f"No {ANCHORS_CSV} found.")
        print(f"Fill in real prices in {ANCHORS_TEMPLATE} and save it as "
              f"{ANCHORS_CSV.name} in the same folder, then rerun this script.")
        return

    with open(PRICE_CSV, encoding="utf-8") as f:
        price_rows = list(csv.DictReader(f))
    donor_curve: dict[tuple[str, str], dict[str, float]] = {}
    for r in price_rows:
        key = (r["dmr_make"], r["dmr_model"])
        donor_curve.setdefault(key, {})[r["age_band"]] = float(r["estimated_value_dkk"])
    mileage_slope = float(price_rows[0]["mileage_adjustment_pct_per_10k_km"])

    with open(TYPICAL_MILEAGE_CSV, encoding="utf-8") as f:
        typical_rows = list(csv.DictReader(f))
    raw_typical_km = {r["age_band"]: float(r["typical_mileage_km"]) for r in typical_rows}
    ordered_bands = ["1", "2", "3", "4"]
    smoothed = pava_monotonic([raw_typical_km[b] for b in ordered_bands])
    typical_km = dict(zip(ordered_bands, smoothed))

    with open(ANCHORS_CSV, encoding="utf-8") as f:
        anchor_rows = [r for r in csv.DictReader(f) if r.get("real_price_dkk", "").strip()]

    # group real listings per (make, model, age_band), mileage-adjust each to
    # that band's typical mileage, then average into one anchor per model.
    grouped: dict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for r in anchor_rows:
        key = (r["dmr_make"], r["dmr_model"], r["age_band"])
        grouped[key].append((float(r["real_price_dkk"]), float(r["real_mileage_km"])))

    anchors: dict[tuple[str, str], tuple[str, float]] = {}
    for (make, model, band), listings in grouped.items():
        adjusted = []
        for price, km in listings:
            factor = (1 - mileage_slope) ** ((typical_km[band] - km) / 10000)
            adjusted.append(price * factor)
        avg_price = statistics.mean(adjusted)
        anchors[(make, model)] = (band, avg_price)
        if len(listings) > 1:
            detail = ", ".join(f"{p:,.0f} kr @ {k:,.0f} km -> {a:,.0f} kr @ typical" for (p, k), a in zip(listings, adjusted))
            print(f"{make} {model}: {len(listings)} listings averaged ({detail}) -> anchor {avg_price:,.0f} kr")

    out_rows = []
    for (make, model), (anchor_band, anchor_price) in anchors.items():
        donor_key = DONORS.get((make, model))
        if donor_key is None:
            raise ValueError(f"no donor assigned for {make}/{model} -- add one to DONORS")
        donor_prices = donor_curve.get(donor_key)
        if donor_prices is None or anchor_band not in donor_prices:
            raise ValueError(f"donor {donor_key} has no price for band {anchor_band}")

        for band, donor_price in donor_prices.items():
            scaled = anchor_price * donor_price / donor_prices[anchor_band]
            out_rows.append({
                "dmr_make": make, "dmr_model": model, "age_band": band,
                "estimated_value_dkk": round(scaled),
                "n_listings": 1, "pooled_at_brand": True, "calibrated": True,
                "calibration_factor_applied": "",
                "mileage_adjustment_pct_per_10k_km": price_rows[0]["mileage_adjustment_pct_per_10k_km"],
                "donor_model": f"{donor_key[0]} {donor_key[1]}",
                "anchor_band": anchor_band, "anchor_price_dkk": round(anchor_price),
            })
        print(f"{make} {model}: anchored at band {anchor_band} = {anchor_price:,.0f} DKK (mileage-adjusted), "
              f"donor {donor_key[0]} {donor_key[1]} -> "
              + ", ".join(f"band{b}={round(anchor_price * p / donor_prices[anchor_band]):,}"
                           for b, p in sorted(donor_prices.items()))
              )

    if not out_rows:
        print("No filled-in anchors yet.")
        return

    fieldnames = list(out_rows[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {OUT_CSV} ({len(out_rows)} rows, {len(anchors)} models anchored)")
    print("Next: merge this into price_estimates_calibrated.csv and rerun "
          "build_phase4_rankings.py.")


if __name__ == "__main__":
    main()
