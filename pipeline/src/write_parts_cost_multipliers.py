"""Writes reference/parts_cost_multipliers.csv.

WHY THIS IS HAND-AUTHORED AND NOT SOURCED
The brief calls for a per-make parts-cost multiplier and explicitly rules out
per-model parts pricing in v1. No open dataset of Danish OEM parts prices by
make exists, so this table is a calibrated judgement, not a measurement, and
the site must label it as such wherever it surfaces.

BASIS FOR THE NUMBERS
Relative cost to keep a car on the road at a Danish independent workshop,
combining three things that move together by brand:
  - OEM parts list prices for common wear items (brake discs/pads, suspension
    arms, alternators, water pumps, sensors)
  - typical labour hours for equivalent jobs, which run higher on premium
    German cars because of packaging and required diagnostic tooling
  - parts availability and aftermarket depth: budget/volume brands have deep
    third-party supply that suppresses prices, low-volume and premium brands
    less so
The two anchors are given by the brief: Dacia at the bottom (0.70) and Land
Rover at the top (2.60). Everything else is placed relative to those on the
same scale, where 1.00 is a mainstream European volume car (Seat, Fiat,
Citroen). Land Rover is retained even though it does not appear in the
current crosswalk, because it fixes the top of the scale.

HOW TO CHALLENGE IT
The ranking is far more defensible than the absolute values. If a make's
placement looks wrong, the fix is to move it relative to its neighbours rather
than to retune the whole scale. A sensitivity check belongs in Phase 4: if the
tier assignment flips when a make moves one step, the finding is not robust
and should be reported as such.
"""

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reference" / "parts_cost_multipliers.csv"

# (make, multiplier, tier, basis)
ROWS = [
    ("DACIA",         0.70, "budget",   "brief's lower anchor; Renault mechanicals, deliberately low-spec, deep parts supply"),
    ("MG",            0.85, "budget",   "value positioning, simple mechanicals, but thinner UK/DK aftermarket than Dacia"),
    ("SUZUKI",        0.90, "budget",   "small simple cars, low parts prices, modest labour hours"),
    ("KIA",           0.90, "volume",   "shares platforms with Hyundai; parts cheap and widely stocked"),
    ("HYUNDAI",       0.92, "volume",   "as Kia; slightly wider model range pushes average up marginally"),
    ("SKODA",         0.95, "volume",   "VW group mechanicals at lower parts pricing than the VW badge"),
    ("TOYOTA",        0.95, "volume",   "high parts availability, long service intervals, conservative engineering"),
    ("SEAT",          1.00, "volume",   "reference point: mainstream European volume car"),
    ("FIAT",          1.00, "volume",   "reference point; cheap parts offset by more frequent small failures"),
    ("CITROEN",       1.00, "volume",   "reference point; PSA parts commonality keeps prices flat"),
    ("PEUGEOT",       1.02, "volume",   "as Citroen, marginally higher on diesel-specific components"),
    ("RENAULT",       1.02, "volume",   "broad aftermarket, some model-specific electrical parts priced higher"),
    ("OPEL",          1.05, "volume",   "GM-era and PSA-era parts split raises average sourcing cost"),
    ("FORD",          1.05, "volume",   "very deep aftermarket, but more labour-intensive on later diesels"),
    ("NISSAN",        1.05, "volume",   "CVT and dual-clutch components lift the average above pure volume brands"),
    ("CHEVROLET",     1.05, "volume",   "withdrawn from Europe; parts supply thinning raises real cost despite budget positioning"),
    ("MITSUBISHI",    1.08, "volume",   "shrinking European presence, narrower parts supply"),
    ("HONDA",         1.10, "volume",   "reliable but OEM-priced parts and limited third-party alternatives"),
    ("MAZDA",         1.10, "volume",   "OEM-heavy parts supply, higher list prices than Toyota equivalents"),
    ("VOLKSWAGEN",    1.15, "volume",   "volume brand at premium parts pricing; high labour hours on TSI/DSG work"),
    ("DS",            1.30, "premium",  "PSA mechanicals with premium-priced trim and electronics"),
    ("VOLVO",         1.35, "premium",  "premium parts pricing, though simpler to work on than German rivals"),
    ("MINI",          1.45, "premium",  "BMW parts and labour rates on a small car; packaging raises labour hours"),
    ("ALFA ROMEO",    1.45, "premium",  "low volume, OEM-only for many components, high diagnostic burden"),
    ("AUDI",          1.75, "premium",  "premium German: high OEM prices, heavy labour hours, tooling requirements"),
    ("BMW",           1.85, "premium",  "as Audi, with more model-specific components and higher electrical complexity"),
    ("MERCEDES-BENZ", 1.85, "premium",  "as BMW; air suspension and electronics on larger models push the tail higher"),
    ("LAND ROVER",    2.60, "premium",  "brief's upper anchor; retained to fix the scale though absent from the crosswalk"),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["make", "parts_cost_multiplier", "tier", "basis"])
        w.writerows(ROWS)
    print(f"wrote {len(ROWS)} rows to {OUT}")
    print(f"range: {min(r[1] for r in ROWS)} ({min(ROWS, key=lambda r: r[1])[0]}) "
          f"to {max(r[1] for r in ROWS)} ({max(ROWS, key=lambda r: r[1])[0]})")


if __name__ == "__main__":
    main()
