"""Estimates a current Danish market value per (dmr_make, dmr_model, age_band),
to unblock Phase 4's price-bracket axis without asking for 210 hand-entered
prices and without touching Bilbasen/DBA.

THE METHOD, AND WHY IT AVOIDS A "NEW PRICE" INPUT
Danish law values a USED car by comparison to other used vehicles of similar
make/model/condition, not by starting from a new price and depreciating it
(see registration_tax_2026.csv's docstring for the full citation trail). That
comparable-used-vehicle value is exactly what a foreign used-car listing IS,
once converted to DKK and taxed under Danish rules -- so this script never
needs a new-price anchor at all, hand-entered or extrapolated:
  1. A third-party, CC0-licensed dataset of ~91,500 real Polish used-car
     listings (make, model, year, mileage, price; Poland chosen because it
     has no meaningful vehicle registration tax, so its prices track intrinsic
     value, not a local tax regime -- the same reasoning that would apply to
     Germany, which had no equivalent open dataset with full-brand coverage).
  2. Each DMR model's Polish listings are bucketed by age; the bucket medians
     form an age-vs-price curve. Our four target ages (5/8/11/14.5 years) are
     estimated by interpolating that curve, clamped to the age range actually
     observed -- never extrapolated past it. An earlier version tried fitting
     a single exponential and reading off its age=0 intercept as a "new
     price"; checked against VW Golf, that extrapolation (backward past the
     youngest observed data, ~3 years) produced a implied new-car price of
     580,000 DKK, well above any real Golf's sticker price, because the
     Poland data has essentially no near-new listings to constrain the
     steepest part of the curve. Interpolation-only avoids that failure mode
     entirely, at the cost of never producing a "new price" figure -- which
     this design doesn't need one for.
  3. The Danish registration tax FORMULA (registration_tax_2026.csv) is
     applied directly to the interpolated foreign value at each target age,
     using that model's own measured CO2 from DMR data. This is a real
     simplification -- the law technically scales the tax brackets themselves
     down for a depreciated car, which this does not do -- but unlike the
     age=0 extrapolation, it is applied only to values within the range we
     actually observe, and the error it introduces is a smooth function of
     price level, which the calibration step below is specifically there to
     correct.
  4. The whole pipeline's output is then calibrated against a small set of
     real, currently-listed Danish prices (see calibrate_price_estimates.py)
     to fix whatever the first three steps get wrong in aggregate -- market
     movement since the Polish data was collected (2023), residual cross-
     market differences, the uncorrected bracket-scaling simplification,
     Polish VAT, etc. This step is not optional; treat the pre-calibration
     output here as a scaffold, not a final number.

WHAT THIS IS NOT: a claim that any individual estimate is accurate. It is a
statistically-grounded, fully-documented substitute for a number nobody could
otherwise supply, explicitly flagged wherever it appears downstream.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import urllib.request
from collections import defaultdict
from pathlib import Path

import duckdb

from crosswalk_normalize import normalize, strip_diacritics
from write_registration_tax_formula import registration_tax_dkk

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
REFERENCE = ROOT / "pipeline" / "reference"
POLAND_CSV = ROOT / "pipeline" / "data" / "raw" / "price_reference" / "poland_all.csv"
OUT_CSV = REFERENCE / "price_estimates.csv"
OUT_CURVES = REFERENCE / "price_depreciation_curves.csv"

CURRENT_YEAR = 2026
DATASET_SNAPSHOT_YEAR = 2023  # Kaggle "last updated" date on the Poland source

# (age_band, representative_age_years) -- midpoints of the bands used
# throughout Phase 3 (2020-22, 2017-19, 2014-16, 2010-13, read against 2026).
TARGET_AGES = [(1, 5), (2, 8), (3, 11), (4, 14.5)]

MIN_LISTINGS_FOR_MODEL_FIT = 15
FALLBACK_FX_PLN_DKK = 1.73  # 2026-07-31 live rate; see fetch_fx_rate()

# DMR make -> Polish dataset brand slug. Poland dataset covers 24 of the 26
# crosswalk makes; SUZUKI and DS have no listings in it (checked directly --
# not a parsing gap) and get no price estimate, flagged explicitly rather
# than silently interpolated from an unrelated brand.
MAKE_MAP = {
    "ALFA ROMEO": "alfa-romeo", "AUDI": "audi", "BMW": "bmw", "CHEVROLET": "chevrolet",
    "CITROËN": "citroen", "DACIA": "dacia", "FIAT": "fiat", "FORD": "ford",
    "HONDA": "honda", "HYUNDAI": "hyundai", "KIA": "kia", "MAZDA": "mazda",
    "MERCEDES-BENZ": "mercedes-benz", "MINI": "mini", "MITSUBISHI": "mitsubishi",
    "NISSAN": "nissan", "OPEL": "opel", "PEUGEOT": "peugeot", "RENAULT": "renault",
    "SEAT": "seat", "SKODA": "skoda", "TOYOTA": "toyota", "VOLKSWAGEN": "volkswagen",
    "VOLVO": "volvo",
}


def fetch_fx_rate() -> tuple[float, str]:
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/PLN", timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rate = data["rates"]["DKK"]
        return rate, f"live open.er-api.com fetch, {data['time_last_update_utc']}"
    except Exception as e:
        print(f"  FX live fetch failed ({e}), using fallback {FALLBACK_FX_PLN_DKK}")
        return FALLBACK_FX_PLN_DKK, "fallback constant, verified 2026-07-31"


def load_poland_listings() -> list[dict]:
    rows = []
    with open(POLAND_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                price_pln = float(r["price_in_pln"])
                year = int(r["year"])
                mileage_km = int(r["mileage"].replace(" km", "").replace(" ", "").replace("\xa0", ""))
            except (ValueError, KeyError):
                continue
            if not (1000 <= price_pln <= 2_000_000):
                continue
            if not (1990 <= year <= CURRENT_YEAR):
                continue
            if not (0 <= mileage_km <= 500_000):
                continue
            rows.append({
                "brand": r["brand"], "model_raw": r["model"],
                "price_pln": price_pln, "year": year, "mileage_km": mileage_km,
                "fuel_type": r["fuel_type"],
            })
    return rows


def polish_model_normalized(brand_slug: str, model_raw: str) -> str:
    """Strips the leading brand name (Polish listings write it as
    'Volkswagen Golf 1.9 TDI') and normalizes the rest with the same
    diacritics/punctuation rules used throughout the crosswalk, so matching
    reuses logic already proven on DMR/DVSA strings rather than a new,
    unverified normalization path."""
    norm = normalize(model_raw)
    brand_norm = normalize(strip_diacritics(brand_slug).replace("-", " "))
    if norm.startswith(brand_norm + " "):
        norm = norm[len(brand_norm):].strip()
    return norm


def matches(dmr_norm: str, polish_norm: str) -> bool:
    if not polish_norm:
        return False
    if dmr_norm == polish_norm:
        return True
    if polish_norm.startswith(dmr_norm + " "):
        return True
    if dmr_norm.startswith(polish_norm + " "):
        return True
    return False


# Some DMR model names have no Polish-side match under the rule above even
# though Poland's data has thousands of real listings for the car -- the
# naming CONVENTION differs, not just spelling. Found by checking why every
# BMW/Mercedes/Volvo model except the plainest ones (X1, X3, GLC, V70, ...)
# was falling back to a whole-brand pooled price: DMR spells these "1-Serie",
# "A-Klasse", "XC60"; Poland's listings (after load_poland_listings() strips
# the leading brand name) read "Seria 1", "Klasa A", "XC 60" -- reversed word
# order for the first two, a missing space for the third. Each entry is one
# more accepted spelling for that DMR model, checked with the same prefix
# rule as matches() above so trim suffixes ("Seria 1 118i M Sport") still
# match. This is the model-name equivalent of the make-alias table Phase 2
# built for brand names; same fix, one level down.
MODEL_MATCH_ALIASES: dict[tuple[str, str], list[str]] = {
    ("BMW", "1-Serie"): ["SERIA 1"],
    ("BMW", "2-Serie"): ["SERIA 2"],
    ("BMW", "3-Serie"): ["SERIA 3"],
    ("BMW", "4-serie"): ["SERIA 4"],
    ("BMW", "5-Serie"): ["SERIA 5"],
    ("MERCEDES-BENZ", "A-Klasse"): ["KLASA A"],
    ("MERCEDES-BENZ", "B-Klasse"): ["KLASA B"],
    ("MERCEDES-BENZ", "C"): ["KLASA C"],
    ("MERCEDES-BENZ", "C-Klasse"): ["KLASA C"],
    ("MERCEDES-BENZ", "E"): ["KLASA E"],
    ("MERCEDES-BENZ", "E-Klasse"): ["KLASA E"],
    ("VOLVO", "XC40"): ["XC 40"],
    ("VOLVO", "XC60"): ["XC 60"],
    ("VOLVO", "XC90"): ["XC 90"],
}

# A different problem from the aliasing above: not a spelling mismatch, just
# too little real data. Skoda Citigo has 2 Poland listings total (one with
# an implausible 1968cc "Diesel" spec this car never shipped with) -- far
# below MIN_LISTINGS_FOR_MODEL_FIT, so it would fall back to a whole-Skoda
# brand pool, which is dominated by much bigger, pricier models (Octavia,
# Superb, Kodiaq) and prices a cheap city car like an executive saloon.
# Citigo, VW Up! and Seat Mii are the same car built on the same line (VW
# Group's "New Small Family" platform, sold under three badges) so this
# borrows VW Up!'s real, well-populated Poland curve as Citigo's market-value
# signal. Only that curve is borrowed -- the registration tax below is still
# computed from Citigo's own measured CO2 figure, not VW's.
PLATFORM_SHARED_LISTINGS: dict[tuple[str, str], tuple[str, str]] = {
    ("SKODA", "CITIGO"): ("volkswagen", "UP"),
}


def build_age_price_curve(points: list[tuple[float, float]]) -> list[tuple[float, float]] | None:
    """points: list of (age_years, price_dkk). Buckets by age and returns
    [(mean_age_in_bucket, median_price), ...] sorted by age, median per
    bucket to resist scam/typo listings.

    Deliberately NOT a parametric fit extrapolated back to age zero. An
    earlier version fit a single exponential decay across all buckets and
    read off its age=0 intercept as a "new price" -- but the Poland data has
    essentially no near-new listings (the youngest bucket observed is
    already ~3 years old), so that intercept was extrapolating INTO the
    steepest, least-observed part of a real depreciation curve (new cars lose
    value fastest in years 0-2) using a decay rate fit mostly from the flatter
    years 3-16+. Checked directly against VW Golf: it produced a 305,000 DKK
    "ex-tax new price" that implied a ~580,000 DKK Danish new price, well
    above any real Golf's sticker price. This version only ever interpolates
    OR CLAMPS within the age range actually observed, never extrapolates
    past it -- see estimate_at_age().
    """
    if len(points) < MIN_LISTINGS_FOR_MODEL_FIT:
        return None
    buckets: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for age, price in points:
        b = 0 if age < 2 else 2 if age < 5 else 5 if age < 8 else 8 if age < 12 else 12 if age < 16 else 16
        buckets[b].append((age, price))
    curve = []
    for entries in buckets.values():
        if len(entries) < 3:
            continue
        ages = [e[0] for e in entries]
        prices = [e[1] for e in entries]
        curve.append((sum(ages) / len(ages), statistics.median(prices)))
    curve.sort()
    return curve if len(curve) >= 2 else None


def estimate_at_age(curve: list[tuple[float, float]], target_age: float) -> float:
    """Log-space interpolation between the two bracketing curve points.
    Clamps to the youngest/oldest observed bucket rather than extrapolating
    past the data -- see build_age_price_curve()'s docstring for why that
    matters here."""
    if target_age <= curve[0][0]:
        return curve[0][1]
    if target_age >= curve[-1][0]:
        return curve[-1][1]
    for (a0, p0), (a1, p1) in zip(curve, curve[1:]):
        if a0 <= target_age <= a1:
            t = (target_age - a0) / (a1 - a0)
            return math.exp(math.log(p0) + t * (math.log(p1) - math.log(p0)))
    return curve[-1][1]


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)

    fx_rate, fx_source = fetch_fx_rate()
    print(f"PLN -> DKK rate: {fx_rate:.4f} ({fx_source})")

    print("loading Poland listings...")
    listings = load_poland_listings()
    print(f"  {len(listings):,} usable rows after basic filters")

    for r in listings:
        r["price_dkk"] = r["price_pln"] * fx_rate
        r["age_2026"] = CURRENT_YEAR - r["year"]

    by_brand: dict[str, list[dict]] = defaultdict(list)
    for r in listings:
        by_brand[r["brand"]].append(r)

    cw_rows = con.execute(
        "SELECT DISTINCT dmr_make, dmr_model FROM (SELECT * FROM read_csv_auto(?))",
        [str(REFERENCE / "crosswalk.csv")],
    ).fetchall()

    # median CO2 per DMR model, for the registration-tax input -- the actual
    # measured CO2 of the Danish-registered variant, not a foreign proxy.
    co2_rows = con.execute("""
        SELECT make_name, model_name, median(co2_primary) AS co2
        FROM dmr_vehicles_scoped
        WHERE fuel_type_primary IN ('Benzin', 'Diesel') AND co2_primary > 0
        GROUP BY 1, 2
    """).fetchall()
    co2_by_model = {(mk, md): co2 for mk, md, co2 in co2_rows}

    out_rows = []
    curve_rows = []
    n_no_brand, n_no_co2, n_insufficient, n_ok, n_brand_pooled = 0, 0, 0, 0, 0

    for dmr_make, dmr_model in cw_rows:
        brand_slug = MAKE_MAP.get(dmr_make)
        if brand_slug is None:
            n_no_brand += 1
            continue

        co2 = co2_by_model.get((dmr_make, dmr_model))
        if co2 is None:
            n_no_co2 += 1
            continue

        dmr_norm = normalize(dmr_model)
        aliases = MODEL_MATCH_ALIASES.get((dmr_make, dmr_model), [])
        match_brand_slug, match_norm = PLATFORM_SHARED_LISTINGS.get((dmr_make, dmr_model), (brand_slug, dmr_norm))
        brand_listings = by_brand.get(match_brand_slug, [])
        matched = [
            (r["age_2026"], r["price_dkk"]) for r in brand_listings
            if matches(match_norm, polish_model_normalized(match_brand_slug, r["model_raw"]))
            or any(matches(alias, polish_model_normalized(match_brand_slug, r["model_raw"])) for alias in aliases)
        ]

        pooled_at_brand = False
        curve = build_age_price_curve(matched)
        n_points = len(matched)
        if curve is None:
            # not enough model-specific listings -- pool at brand level so
            # every covered make still gets a (less specific) estimate,
            # flagged as such rather than silently omitted.
            pooled = [(r["age_2026"], r["price_dkk"]) for r in brand_listings]
            curve = build_age_price_curve(pooled)
            pooled_at_brand = True
            n_points = len(pooled)
            if curve is None:
                n_insufficient += 1
                continue

        if pooled_at_brand:
            n_brand_pooled += 1
        else:
            n_ok += 1

        curve_rows.append({
            "dmr_make": dmr_make, "dmr_model": dmr_model,
            "n_listings": n_points, "pooled_at_brand": pooled_at_brand,
            "co2_gkm_used": round(co2, 1),
            "curve_age_range": f"{curve[0][0]:.1f}-{curve[-1][0]:.1f} yrs "
                                f"({round(curve[0][1]):,}-{round(curve[-1][1]):,} DKK observed)",
        })

        for age_band, age_years in TARGET_AGES:
            foreign_value_at_age = estimate_at_age(curve, age_years)
            tax = registration_tax_dkk(foreign_value_at_age, co2)
            estimated_dkk = foreign_value_at_age + tax
            out_rows.append({
                "dmr_make": dmr_make, "dmr_model": dmr_model, "age_band": age_band,
                "estimated_value_dkk": round(estimated_dkk),
                "n_listings": n_points, "pooled_at_brand": pooled_at_brand,
                "calibrated": False,
            })

    print(f"\nmodels with no Poland brand coverage (Suzuki, DS): {n_no_brand}")
    print(f"models with no DMR CO2 data: {n_no_co2}")
    print(f"models with insufficient listings even pooled at brand level: {n_insufficient}")
    print(f"models fit at model-specific level: {n_ok}")
    print(f"models fit only at pooled brand level (flagged): {n_brand_pooled}")
    print(f"total (model, age_band) price estimates: {len(out_rows)}")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "dmr_make", "dmr_model", "age_band", "estimated_value_dkk",
            "n_listings", "pooled_at_brand", "calibrated",
        ])
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {OUT_CSV}")

    with open(OUT_CURVES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "dmr_make", "dmr_model", "n_listings", "pooled_at_brand", "co2_gkm_used",
            "curve_age_range",
        ])
        w.writeheader()
        w.writerows(curve_rows)
    print(f"wrote {OUT_CURVES}")

    # spot check on a well-known model
    for r in curve_rows:
        if r["dmr_make"] == "VOLKSWAGEN" and r["dmr_model"] == "GOLF":
            print(f"\nspot check VW Golf curve: {r}")
    for r in out_rows:
        if r["dmr_make"] == "VOLKSWAGEN" and r["dmr_model"] == "GOLF":
            print(f"  age_band {r['age_band']}: {r['estimated_value_dkk']:,} DKK")


if __name__ == "__main__":
    main()
