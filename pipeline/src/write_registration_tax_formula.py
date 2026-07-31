"""Writes reference/registration_tax_2026.csv -- the current Danish vehicle
registration tax (registreringsafgift) formula for conventional (petrol/
diesel) personbiler.

TRANSCRIBED FROM RAW HTML, not an LLM-summarized read. The source page lists
2025 AND 2026 columns side by side for every parameter; a first-pass summary
of it silently reported the 2025 CO2-surcharge figures (280/560/1,064
kr/gram) as if they were 2026's -- caught by re-fetching the raw table and
reading the column headers directly, the same failure mode found earlier
while transcribing the ejerafgift bands. The verified 2026 figures are
294/587/1,115 kr/gram.

SOURCE: https://skm.dk/tal-og-metode/satser/satser-og-beloebsgraenser-i-lovgivningen/gaeldende-satser-for-registreringsafgiften
Page dated 18-12-2025 on the ministry's own site; fetched and verified
2026-07-31.

WHAT THIS FORMULA IS FOR HERE, AND WHY IT ONLY COVERS THE "NEW CAR" CASE
Danish law computes registration tax for a USED car by scaling every part of
this formula (the bracket thresholds, the CO2-surcharge bands, and the
bundfradrag) down by the same percentage the car's value has depreciated by
relative to an equivalent new car -- and that percentage is normally read off
the car's own new-price, which is exactly the per-model data point the brief
avoided asking you to supply by hand.

This project sidesteps that without inventing a number: it applies this
UNSCALED formula only to a NEW-price estimate, derived statistically from
foreign listings' own age-vs-price relationship (see
`build_price_estimates.py`), and then applies THAT SAME foreign market's own
observed depreciation curve to bring the number down to a used car's age --
never scaling the Danish tax brackets themselves. The formula below is
therefore only ever evaluated at "age zero," where the law's unscaled bracket
structure is unambiguously correct, not approximated.

SCOPE LIMITATION, same one already flagged for ejerafgift: plug-in hybrids
get a reduced rate (68 pct., 43,000 kr bundfradrag) and are not identifiable
in DMR data (Phase 1 finding, unchanged) -- they are taxed here as
conventional cars, which overstates their estimated price. Zero-emission
(EV) rates are irrelevant; BEVs are out of scope for v1 per the brief.
"""

from __future__ import annotations

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reference" / "registration_tax_2026.csv"
SOURCE_URL = "https://skm.dk/tal-og-metode/satser/satser-og-beloebsgraenser-i-lovgivningen/gaeldende-satser-for-registreringsafgiften"
VERIFIED_DATE = "2026-07-31"

ROWS = [
    # component, threshold_from, threshold_to, rate_or_amount, unit, note
    ("value_bracket", 0, 72900, 0.25, "fraction_of_value", "25 pct of afgiftspligtig vaerdi up to 72900 DKK"),
    ("value_bracket", 72900, 226500, 0.85, "fraction_of_value", "85 pct of the portion between 72900 and 226500 DKK"),
    ("value_bracket", 226500, None, 1.50, "fraction_of_value", "150 pct of the portion above 226500 DKK"),
    ("co2_surcharge", 0, 107, 294, "dkk_per_gram", "low rate on the first 107 g CO2/km"),
    ("co2_surcharge", 107, 137, 587, "dkk_per_gram", "medium rate on the next 30 g CO2/km (107-137)"),
    ("co2_surcharge", 137, None, 1115, "dkk_per_gram", "high rate on CO2/km above 137"),
    ("bundfradrag", None, None, 25500, "dkk_flat", "flat deduction from total computed tax; floor total tax at 0"),
]


def registration_tax_dkk(value_dkk: float, co2_gkm: float) -> float:
    """New-car registration tax on a conventional (petrol/diesel) personbil,
    per the unscaled 2026 formula. Only valid at "new" -- see module
    docstring for why used cars are handled by scaling the OUTPUT of this
    function via an observed depreciation ratio, not by re-deriving a scaled
    version of the formula itself."""
    if value_dkk <= 72900:
        bracket_tax = 0.25 * value_dkk
    elif value_dkk <= 226500:
        bracket_tax = 0.25 * 72900 + 0.85 * (value_dkk - 72900)
    else:
        bracket_tax = 0.25 * 72900 + 0.85 * (226500 - 72900) + 1.50 * (value_dkk - 226500)

    co2 = max(co2_gkm, 0)
    low = min(co2, 107) * 294
    mid = min(max(co2 - 107, 0), 30) * 587
    high = max(co2 - 137, 0) * 1115
    co2_surcharge = low + mid + high

    return max(bracket_tax + co2_surcharge - 25500, 0)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["component", "threshold_from", "threshold_to", "rate_or_amount", "unit", "note",
                    "verified_date", "source_url"])
        for row in ROWS:
            w.writerow([*row, VERIFIED_DATE, SOURCE_URL])
    print(f"wrote {len(ROWS)} rows to {OUT}")

    # sanity check: a conventional petrol car worth 200,000 DKK ex-tax at
    # 130 g CO2/km should land in a plausible, checkable range.
    example = registration_tax_dkk(200000, 130)
    print(f"sanity check: 200,000 DKK car @ 130 g/km CO2 -> tax = {example:,.0f} DKK, "
          f"total price = {200000 + example:,.0f} DKK")


if __name__ == "__main__":
    main()
