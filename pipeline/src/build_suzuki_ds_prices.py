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

SAME-CAR EXCEPTION: DS "DS 3" needs no hand-collected anchor at all.
Poland's listings have zero rows under the DS make, but DS Automobiles'
"DS 3" is not a different vehicle from Citroen's "DS3" -- Citroen sold this
exact hatchback as the "DS3" from 2010, then spun DS off as its own brand in
2015 and the same car (and its facelift) continued as DS's "DS 3". Citroen
DS3 already has its own calibrated price curve (pooled at brand level, since
Poland's own DS3-specific listings are thin -- see price_estimates_calibrated.csv),
which is a strictly better price signal than borrowing only the SHAPE from an
unrelated segment donor (Peugeot 208, still listed in DONORS below as a
fallback) and separately hand-collecting a Danish DS 3 LEVEL anchor for a car
that already has a directly-applicable one. SAME_CAR_DONORS below copies the
donor's SHAPE AND LEVEL both, verbatim, per age band -- see main().

This is deliberately NOT the same move as merging DS "DS 3" and Citroen
"DS3" on the DVSA/reliability side (crosswalk.csv correctly keeps them as
two separate UK test pools, and model_spelling_aliases.csv correctly does
not merge them either -- reliability genuinely differs by production era and
badge, which is exactly the kind of thing UK MOT data can tell apart and
Polish asking-price data mostly cannot).

If a real DS 3 listing is ever added to suzuki_ds_price_anchors.csv, it wins
over this fallback -- see main()'s ordering -- since model-specific ground
truth for the exact model beats a same-car substitute either way.
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
    # "Captur" -- price_estimates_calibrated.csv carries Renault's models in
    # DMR's own mixed-case spelling (verified: "Ny Clio", "Captur", but
    # "CLIO", "MEGANE", "SCENIC", "TWINGO" all caps -- no single convention),
    # so this key has to match that exact string, not the DVSA-style all-caps
    # form. A prior version had "CAPTUR" here, which silently produced NO
    # price rows for SX4 S-Cross at all (donor_curve.get() returned None and
    # the anchor loop below raises before writing anything) -- caught by
    # running the anchor-to-ranking path end to end with test values, not by
    # inspection, since a dict miss here fails loud but only once someone
    # actually supplies an SX4 S-Cross anchor and reruns this script.
    ("SUZUKI", "SX4 S-Cross"): ("RENAULT", "Captur"),
    ("SUZUKI", "SX4"): ("FORD", "FOCUS"),
    ("SUZUKI", "SX4 COMBIBACK"): ("FORD", "FOCUS"),
    # Kept as the segment-shape fallback for if a real DS 3 anchor is ever
    # added (see SAME_CAR_DONORS below for the default path, which needs no
    # anchor at all).
    ("DS", "DS 3"): ("PEUGEOT", "208"),
}

# Same physical car as an already-priced model under a different make/model
# string -- not merely a similar-segment analog. For these, SHAPE and LEVEL
# are both copied directly from the donor's own calibrated curve, so no
# hand-collected Danish anchor is needed at all. Only consulted for a model
# with no real anchor in suzuki_ds_price_anchors.csv (see main()); a real
# anchor, once supplied, wins over this substitute. See the module docstring
# for why DS "DS 3" qualifies and why this is unrelated to the (deliberately
# separate) DVSA/reliability crosswalk decision for the same two model names.
SAME_CAR_DONORS: dict[tuple[str, str], tuple[str, str]] = {
    ("DS", "DS 3"): ("CITROËN", "DS3"),
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

    # Same-car donors: copy SHAPE and LEVEL both, verbatim per band, and only
    # for a model with no real anchor above -- a real anchor is model-specific
    # ground truth and outranks a same-car substitute even for DS "DS 3".
    for (make, model), donor_key in SAME_CAR_DONORS.items():
        if (make, model) in anchors:
            continue
        donor_prices = donor_curve.get(donor_key)
        if donor_prices is None:
            raise ValueError(f"same-car donor {donor_key} has no price curve at all -- "
                              f"add one to DONORS instead, or check the spelling against "
                              f"price_estimates_calibrated.csv")
        donor_row = next(
            r for r in price_rows if (r["dmr_make"], r["dmr_model"]) == donor_key
        )
        for band, donor_price in donor_prices.items():
            out_rows.append({
                "dmr_make": make, "dmr_model": model, "age_band": band,
                "estimated_value_dkk": round(donor_price),
                "n_listings": int(donor_row["n_listings"]), "pooled_at_brand": True, "calibrated": True,
                "calibration_factor_applied": donor_row["calibration_factor_applied"],
                "mileage_adjustment_pct_per_10k_km": price_rows[0]["mileage_adjustment_pct_per_10k_km"],
                "donor_model": f"{donor_key[0]} {donor_key[1]} (same car, direct price copy, no hand-collected anchor)",
                "anchor_band": "", "anchor_price_dkk": "",
            })
        print(f"{make} {model}: no hand-collected anchor needed -- same physical car as "
              f"{donor_key[0]} {donor_key[1]}, copied its price curve directly: "
              + ", ".join(f"band{b}={round(p):,}" for b, p in sorted(donor_prices.items())))

    if not out_rows:
        print("No filled-in anchors yet.")
        return

    fieldnames = list(out_rows[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    n_models_priced = len({(r["dmr_make"], r["dmr_model"]) for r in out_rows})
    print(f"\nwrote {OUT_CSV} ({len(out_rows)} rows, {n_models_priced} models priced: "
          f"{len(anchors)} from a hand-collected anchor, "
          f"{n_models_priced - len(anchors)} from a same-car donor copy)")
    print("Next: rerun build_phase4_rankings.py (it merges this file in at read time, "
          "see its SUZUKI_DS_PRICE_CSV handling -- price_estimates_calibrated.csv itself "
          "does not need editing).")


if __name__ == "__main__":
    main()
