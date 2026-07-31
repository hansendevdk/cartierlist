"""Writes reference/ejerafgift_rates.csv -- the grøn ejerafgift (periodic
ownership tax) rate bands for all three regimes in scope.

TRANSCRIBED, NOT INFERRED. Every number below was read directly off the raw
HTML of the two authoritative Skattestyrelsen "Den juridiske vejledning" pages
(fetched and parsed by hand, not summarised by a model -- a first pass through
an LLM-summarised version of the km/l table silently swapped two columns and
would have shipped a wrong petrol regime-A rate; this version was checked
against the raw table cells).

SOURCES (fetched and cross-checked 2026-07-31):
  - km/l-based tables (regimes A and B), sections I.A.3.3 "Halvårlig
    brændstofforbrugsafgift, benzin" and "... diesel":
    https://info.skat.dk/data.aspx?oid=2303932
  - CO2-based table (regime C), section I.A.3.3.1 "Opgørelse efter
    CO2-udledning":
    https://info.skat.dk/data.aspx?oid=2303931
  - Cross-checked against https://motorst.dk periodic-tax pages, which
    describe the same three-regime structure without a full table.

All DKK amounts are the "2026-satser" column: the rate actually charged in
2026 (Grundbeløb-for-2026 is a smaller, un-indexed figure used only as the
base for future indexation; the law text on the source page states rates stay
at the 2026 level through 2027, so this is also next year's rate). Every
amount is a HALF-YEAR charge; downstream code must multiply by 2 for an
annual figure, not double the CSV.

REGIMES
  A: first registered on or before 2017-10-02, consumption-based (km/l).
  B: first registered 2017-10-03 through 2021-06-30, consumption-based
     (km/l), on a DIFFERENT rate table from A -- same bands, higher amounts.
  C: first registered on or after 2021-07-01, CO2-based (g/km). Same table
     for petrol and diesel; diesel pays the surcharge below on top.

DIESEL SURCHARGE (udligningsafgift)
  Diesel pays consumption/CO2 tax AND a separate surcharge, banded the same
  way as the regime it falls under. The 2026 amount in this file already has
  the legally mandated "nedsættes med 30 pct. for 2026" reduction baked in --
  it is the number actually charged in 2026, not the pre-reduction base.

KNOWN GAP IN THE SOURCE TABLE, not an error in this transcription: regime A's
diesel schedule (pre-2017-10-03) only has published bands from "under 25.0
km/l" downward -- the source table itself prints "-" for every band above
that (the old diesel scale topped out at 32.1 km/l per the page's own prose,
and apparently never populated bands between 25 and 32.1 either). A
pre-2017-10-03 diesel car with measured consumption >= 25.0 km/l has no
published rate to look up. Handled explicitly in the loader, not silently: it
is billed at the rate of the highest km/l band that IS published for regime A
diesel (390 grundbeløb / 460 2026-sats, i.e. the "22.5 to 25.0" band), flagged
with `note = 'regime-A-diesel-scale-gap, floored to lowest published band'`,
and the row count this affects must be reported at build time -- diesel
engines rarely exceeded 20 km/l on pre-2018 test cycles, so this is expected
to be a handful of vehicles, not a systemic issue, but the count must be
checked, not assumed.

ALSO NOTE, transcribed faithfully from the source rather than corrected: the
diesel km/l table's own boundary labels are internally inconsistent between
two adjacent rows -- "Under 41,0, mindst 37,6" is immediately followed by a
row labelled "Under 37,3, mindst 32,1" (37.3, not 37.6). This looks like a
data-entry slip on Skattestyrelsen's own page, not a real second boundary a
km/l value could fall between. This file uses 37.6 as the shared boundary so
every km/l value maps to exactly one band with no gap or overlap; the
discrepancy is noted here for anyone re-verifying against the live page.

SANITY CHECK (run by build_phase3_metrics.py at build time): a petrol car
first registered in 2018 (regime B) at 19 km/l falls in the "18.2 <= x < 20.0"
band, 2026-sats 1,220 DKK/half-year. A pre-transcription estimate in the
Phase 3 spec guessed "roughly 1,110 DKK on 2025 rates" -- 1,220 is the actual
verified 2026 rate (about 10% higher, consistent with one more year of the
law's annual indexation), which is close enough to confirm the band and
regime logic is right, not so close that it looks copied.
"""

from __future__ import annotations

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reference" / "ejerafgift_rates.csv"

VERIFIED_DATE = "2026-07-31"
SOURCE_KML = "https://info.skat.dk/data.aspx?oid=2303932"
SOURCE_CO2 = "https://info.skat.dk/data.aspx?oid=2303931"

# --- Regime A & B: petrol, km/l bands -------------------------------------
# (km_l_min, km_l_max, regime_a_2026_dkk, regime_b_2026_dkk)
# km_l_max is exclusive ("under"); km_l_min is inclusive ("mindst"); the top
# band's max is None (no upper bound), the bottom band's min is None (no
# lower bound -- worst case, most polluting).
PETROL_KML_BANDS = [
    (50.0, None, 460, 460),
    (44.4, 50.0, 460, 520),
    (40.0, 44.4, 460, 540),
    (36.4, 40.0, 460, 570),
    (33.3, 36.4, 460, 600),
    (28.6, 33.3, 460, 640),
    (25.0, 28.6, 460, 700),
    (22.2, 25.0, 460, 760),
    (20.0, 22.2, 460, 800),
    (18.2, 20.0, 880, 1220),
    (16.7, 18.2, 1290, 1630),
    (15.4, 16.7, 1740, 2080),
    (14.3, 15.4, 2160, 2500),
    (13.3, 14.3, 2570, 2910),
    (12.5, 13.3, 2990, 3330),
    (11.8, 12.5, 3400, 3740),
    (11.1, 11.8, 3830, 4180),
    (10.5, 11.1, 4260, 4600),
    (10.0, 10.5, 4680, 5020),
    (9.1, 10.0, 5500, 5840),
    (8.3, 9.1, 6380, 6720),
    (7.7, 8.3, 7210, 7550),
    (7.1, 7.7, 8040, 8380),
    (6.7, 7.1, 8880, 9230),
    (6.3, 6.7, 9740, 10080),
    (5.9, 6.3, 10580, 10920),
    (5.6, 5.9, 11410, 11760),
    (5.3, 5.6, 12290, 12630),
    (5.0, 5.3, 13120, 13470),
    (4.8, 5.0, 13960, 14300),
    (4.5, 4.8, 14800, 15140),
    (None, 4.5, 15660, 16000),
]

# --- Regime A & B: diesel, km/l bands (consumption tax + surcharge) -------
# (km_l_min, km_l_max, regime_a_2026_dkk_or_None, regime_b_2026_dkk, surcharge_2026_dkk)
# regime_a is None for every band above 25.0 km/l: the source table prints
# "-" there (see docstring "KNOWN GAP" above). The loader floors these to the
# 460 band rather than leaving them unpriced.
DIESEL_KML_BANDS = [
    (56.3, None, None, 460, 120),
    (50.0, 56.3, None, 520, 120),
    (45.0, 50.0, None, 540, 120),
    (41.0, 45.0, None, 570, 120),
    (37.6, 41.0, None, 600, 120),  # source row prints "37,3" as this band's min; see docstring
    (32.1, 37.6, None, 640, 120),
    (28.1, 32.1, None, 700, 520),
    (25.0, 28.1, None, 760, 930),
    (22.5, 25.0, 460, 800, 1000),
    (20.5, 22.5, 880, 1220, 1100),
    (18.8, 20.5, 1290, 1630, 1190),
    (17.3, 18.8, 1740, 2080, 1280),
    (16.1, 17.3, 2160, 2500, 1380),
    (15.0, 16.1, 2570, 2910, 1470),
    (14.1, 15.0, 2990, 3330, 1590),
    (13.2, 14.1, 3400, 3740, 1680),
    (12.5, 13.2, 3830, 4180, 1800),
    (11.9, 12.5, 4260, 4600, 1880),
    (11.3, 11.9, 4680, 5020, 1970),
    (10.2, 11.3, 5500, 5840, 2180),
    (9.4, 10.2, 6380, 6720, 2360),
    (8.7, 9.4, 7210, 7550, 2550),
    (8.1, 8.7, 8040, 8380, 2770),
    (7.5, 8.1, 8880, 9230, 2930),
    (7.0, 7.5, 9740, 10080, 3110),
    (6.6, 7.0, 10580, 10920, 3340),
    (6.2, 6.6, 11410, 11760, 3520),
    (5.9, 6.2, 12290, 12630, 3710),
    (5.6, 5.9, 13120, 13470, 3920),
    (5.4, 5.6, 13960, 14300, 4120),
    (5.1, 5.4, 14800, 15140, 4370),
    (None, 5.1, 15660, 16000, 4580),
]

# --- Regime C: CO2-based, both fuels, from 2021-07-01 ----------------------
# (co2_gkm_min, co2_gkm_max, forbrugsafgift_2026_dkk, udligningsafgift_2026_dkk)
# udligningsafgift only applies if the vehicle is diesel; petrol under regime
# C pays forbrugsafgift only.
CO2_BANDS = [
    (None, 58, 460, 120),
    (58, 65, 520, 120),
    (65, 73, 540, 120),
    (73, 80, 570, 120),
    (80, 87, 600, 120),
    (87, 102, 640, 120),
    (102, 116, 700, 520),
    (116, 131, 760, 930),
    (131, 145, 800, 1000),
    (145, 160, 1220, 1100),
    (160, 174, 1630, 1190),
    (174, 189, 2080, 1280),
    (189, 203, 2500, 1380),
    (203, 218, 2910, 1470),
    (218, 232, 3330, 1590),
    (232, 246, 3740, 1680),
    (246, 262, 4180, 1800),
    (262, 277, 4600, 1880),
    (277, 290, 5020, 1970),
    (290, 319, 5840, 2180),
    (319, 350, 6720, 2360),
    (350, 377, 7550, 2550),
    (377, 409, 8380, 2770),
    (409, 433, 9230, 2930),
    (433, 461, 10080, 3110),
    (461, 492, 10920, 3340),
    (492, 519, 11760, 3520),
    (519, 548, 12630, 3710),
    (548, 581, 13470, 3920),
    (581, 605, 14300, 4120),
    (605, 645, 15140, 4370),
    (645, None, 16000, 4580),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []

    for lo, hi, rate_a, rate_b in PETROL_KML_BANDS:
        rows.append(dict(
            regime="A", basis="km_per_liter", fuel_type="Benzin",
            band_min=lo, band_max=hi, dkk_per_half_year=rate_a,
            surcharge_dkk_per_half_year="", note="",
        ))
        rows.append(dict(
            regime="B", basis="km_per_liter", fuel_type="Benzin",
            band_min=lo, band_max=hi, dkk_per_half_year=rate_b,
            surcharge_dkk_per_half_year="", note="",
        ))

    # regime-A-diesel floor: the lowest published band (22.5-25.0, 460 DKK)
    # stands in for every unpublished band above 25.0 km/l.
    regime_a_floor = 460
    for lo, hi, rate_a, rate_b, surcharge in DIESEL_KML_BANDS:
        note_a = "regime-A-diesel-scale-gap, floored to lowest published band" if rate_a is None else ""
        rows.append(dict(
            regime="A", basis="km_per_liter", fuel_type="Diesel",
            band_min=lo, band_max=hi, dkk_per_half_year=rate_a if rate_a is not None else regime_a_floor,
            surcharge_dkk_per_half_year=surcharge, note=note_a,
        ))
        rows.append(dict(
            regime="B", basis="km_per_liter", fuel_type="Diesel",
            band_min=lo, band_max=hi, dkk_per_half_year=rate_b,
            surcharge_dkk_per_half_year=surcharge, note="",
        ))

    for lo, hi, rate, surcharge in CO2_BANDS:
        for fuel in ("Benzin", "Diesel"):
            rows.append(dict(
                regime="C", basis="co2_gkm", fuel_type=fuel,
                band_min=lo, band_max=hi, dkk_per_half_year=rate,
                surcharge_dkk_per_half_year=surcharge if fuel == "Diesel" else "",
                note="",
            ))

    fieldnames = [
        "regime", "basis", "fuel_type", "band_min", "band_max",
        "dkk_per_half_year", "surcharge_dkk_per_half_year", "note",
        "verified_date", "source_url",
    ]
    for r in rows:
        r["verified_date"] = VERIFIED_DATE
        r["source_url"] = SOURCE_CO2 if r["basis"] == "co2_gkm" else SOURCE_KML

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {len(rows)} rows to {OUT}")
    print(f"  regime A: {sum(1 for r in rows if r['regime']=='A')} rows")
    print(f"  regime B: {sum(1 for r in rows if r['regime']=='B')} rows")
    print(f"  regime C: {sum(1 for r in rows if r['regime']=='C')} rows")


if __name__ == "__main__":
    main()
