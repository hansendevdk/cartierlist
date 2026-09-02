"""The point of this phase: does restricting the UK/Norway reliability index
to MECHANICAL defects only (structural/mechanical faults that measure how
the car was built) improve cross-country rank agreement versus the existing
all-defects index, especially in age band 1 (2020-2022 cars), where the
existing agreement study (reports/norway_pkk_report.md) found the weakest
correlation (0.42) and ruled out thin-sample noise as the explanation?

STATED PREDICTION, made before this script was run and before any of its
numbers were seen (see reports/failure_category_agreement_test.md for the
full writeup): mechanical-only should correlate BETTER than all-defects,
consumable-only should correlate WORSE, and the gap should be largest in
band 1. If mechanical-only and consumable-only BOTH improve on all-defects,
the effect is something other than the stated hypothesis (most likely
variance reduction from a smaller, higher-signal item set) and this script's
own printed output says so rather than the report reinterpreting a null
result as support.

Re-runs pipeline/src/build_agreement_study.py's within-band-percentile
pooling method (imported, not re-implemented) three times -- all-defects,
mechanical-only, consumable-only -- against
reference/model_age_band_metrics_category_split.csv and
reference/model_age_band_metrics_category_split_no.csv (both written by
build_failure_category_metrics.py, itself downstream of the FROZEN
classification in reference/dvsa_defect_classification.csv and
reference/norway_defect_classification.csv). Also runs the clean-makes
control (Skoda, Peugeot, Volkswagen, Toyota) and a sample-size threshold
sensitivity sweep, exactly as the phase brief asks.

De-duplication: same bit-identical-rate-pair rule as build_agreement_study.py,
applied independently per variant (two models sharing an identical uk_rate/
no_rate pair on the ALL-DEFECTS variant may legitimately differ on the
mechanical-only variant, since a different item subset drives each).
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_agreement_study import (  # noqa: E402
    spearman, spearman_ci, within_band_pooled, variance_explained_by_band,
    CLEAN_MAKES,
)

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "pipeline" / "reference"
UK_SPLIT_CSV = REFERENCE / "model_age_band_metrics_category_split.csv"
NO_SPLIT_CSV = REFERENCE / "model_age_band_metrics_category_split_no.csv"
OUT_JOINED_CSV = REFERENCE / "failure_category_agreement.csv"

VARIANTS = ["all", "mechanical", "consumable"]

# Primary thresholds: same as build_agreement_study.py -- each side must
# individually clear its own established stability floor for the ALL-DEFECTS
# n (n_tests_all), applied uniformly to all three variants so the same set of
# (model, age_band) cells is compared across variants -- otherwise a
# correlation difference could be an artefact of a different N, not of which
# items count.
PRIMARY_UK_MIN = 2000
PRIMARY_NO_MIN = 2500

SENSITIVITY_PAIRS = [(2000, 500), (2000, 1000), (2000, 1500), (2000, 2000), (2000, 2500),
                     (1000, 1000), (500, 500)]


def load_uk() -> dict[tuple[str, str, int], dict]:
    out = {}
    with open(UK_SPLIT_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r["dmr_make"], r["dmr_model"], int(r["age_band"]))
            cell = {}
            ok = True
            for v in VARIANTS:
                rate = r[f"standardized_rate_{v}"]
                n = r[f"n_tests_{v}"]
                if not rate or not n:
                    ok = False
                    break
                cell[f"rate_{v}"] = float(rate)
                cell[f"n_{v}"] = int(n)
            if ok:
                out[key] = cell
    return out


def load_no() -> dict[tuple[str, str, int], dict]:
    out = {}
    with open(NO_SPLIT_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r["dmr_make"], r["dmr_model"], int(r["age_band"]))
            cell = {}
            ok = True
            for v in VARIANTS:
                rate = r[f"standardized_rate_{v}"]
                n = r[f"n_tests_{v}"]
                if not rate or not n:
                    ok = False
                    break
                cell[f"rate_{v}"] = float(rate)
                cell[f"n_{v}"] = int(n)
            if ok:
                out[key] = cell
    return out


def build_joined(uk: dict, no: dict) -> list[dict]:
    rows = []
    for key in set(uk) & set(no):
        make, model, band = key
        row = {"dmr_make": make, "dmr_model": model, "age_band": band}
        for v in VARIANTS:
            row[f"uk_n_{v}"] = uk[key][f"n_{v}"]
            row[f"uk_rate_{v}"] = uk[key][f"rate_{v}"]
            row[f"no_n_{v}"] = no[key][f"n_{v}"]
            row[f"no_rate_{v}"] = no[key][f"rate_{v}"]
        rows.append(row)
    return rows


def dedupe_signature(rows: list[dict], variant: str) -> list[dict]:
    rows = sorted(rows, key=lambda r: (r["dmr_make"], r["dmr_model"]))
    seen = set()
    out = []
    for r in rows:
        sig = (r[f"uk_rate_{variant}"], r[f"no_rate_{variant}"])
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def run_age_band(rows: list[dict], band: int, variant: str, uk_min: int, no_min: int,
                  makes: set[str] | None) -> dict:
    # threshold gate uses the ALL-DEFECTS n so the same cell set underlies
    # every variant's comparison (see module docstring)
    subset = [r for r in rows if r["age_band"] == band and r["uk_n_all"] >= uk_min and r["no_n_all"] >= no_min]
    if makes is not None:
        subset = [r for r in subset if r["dmr_make"] in makes]
    subset = dedupe_signature(subset, variant)
    n = len(subset)
    if n < 4:
        return {"age_band": band, "n": n, "rho": None, "ci_lo": None, "ci_hi": None, "rows": []}
    rho = spearman([r[f"uk_rate_{variant}"] for r in subset], [r[f"no_rate_{variant}"] for r in subset])
    ci_lo, ci_hi = spearman_ci(rho, n)
    return {"age_band": band, "n": n, "rho": round(rho, 4),
            "ci_lo": round(ci_lo, 4) if ci_lo == ci_lo else None,
            "ci_hi": round(ci_hi, 4) if ci_hi == ci_hi else None,
            "rows": subset}


def pooled_within_band(rows: list[dict], variant: str) -> tuple[float, int]:
    renamed = [{"age_band": r["age_band"], "uk_rate": r[f"uk_rate_{variant}"], "no_rate": r[f"no_rate_{variant}"]}
               for r in rows]
    return within_band_pooled(renamed)


def main() -> None:
    uk = load_uk()
    no = load_no()
    joined = build_joined(uk, no)
    print(f"joined (model, age_band) cells with all three variants populated on both sides: {len(joined)}")

    with open(OUT_JOINED_CSV, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["dmr_make", "dmr_model", "age_band"] + [
            f"{side}_{p}_{v}" for v in VARIANTS for side in ["uk", "no"] for p in ["n", "rate"]
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(joined, key=lambda r: (r["age_band"], r["dmr_make"], r["dmr_model"])))
    print(f"wrote {OUT_JOINED_CSV}")

    print(f"\n=== PER-BAND, ALL MAKES, UK n>={PRIMARY_UK_MIN}, NO n>={PRIMARY_NO_MIN} (threshold gated on all-defects n) ===")
    print(f"{'band':<6}{'variant':<12}{'n':>5}  {'rho':>7}  95% CI")
    per_band_results: dict[str, dict[int, dict]] = {v: {} for v in VARIANTS}
    for band in [1, 2, 3, 4]:
        for variant in VARIANTS:
            res = run_age_band(joined, band, variant, PRIMARY_UK_MIN, PRIMARY_NO_MIN, None)
            per_band_results[variant][band] = res
            print(f"{band:<6}{variant:<12}{res['n']:>5}  {str(res['rho']):>7}  ({res['ci_lo']}, {res['ci_hi']})")
        print()

    print("=== PREDICTION CHECK (band by band): mechanical > all > consumable ? ===")
    for band in [1, 2, 3, 4]:
        a = per_band_results["all"][band]["rho"]
        m = per_band_results["mechanical"][band]["rho"]
        c = per_band_results["consumable"][band]["rho"]
        if a is None or m is None or c is None:
            print(f"  band {band}: insufficient n for one or more variants")
            continue
        mech_better = m > a
        cons_worse = c < a
        verdict = ("PREDICTION HOLDS" if mech_better and cons_worse else
                    "BOTH IMPROVE (variance-reduction pattern, not the stated hypothesis)" if mech_better and m > a and c > a else
                    "PREDICTION DOES NOT HOLD")
        print(f"  band {band}: all={a}  mechanical={m} ({'better' if mech_better else 'NOT better'})  "
              f"consumable={c} ({'worse' if cons_worse else 'NOT worse'})  -> {verdict}")

    print(f"\n=== POOLED (within-band corrected), ALL MAKES, primary threshold ===")
    for variant in VARIANTS:
        all_rows = []
        for band in [1, 2, 3, 4]:
            res = run_age_band(joined, band, variant, PRIMARY_UK_MIN, PRIMARY_NO_MIN, None)
            all_rows.extend(res["rows"])
        rho, n = pooled_within_band(all_rows, variant)
        lo, hi = spearman_ci(rho, n) if rho == rho else (float("nan"), float("nan"))
        print(f"  {variant:<12} n={n:>4}  rho={round(rho,4) if rho==rho else None}  "
              f"95% CI=({round(lo,4) if lo==lo else None}, {round(hi,4) if hi==hi else None})")

    print(f"\n=== CLEAN MAKES ONLY (Skoda, Peugeot, Volkswagen, Toyota), UK n>={PRIMARY_UK_MIN}, NO n>={PRIMARY_NO_MIN} ===")
    print(f"{'band':<6}{'variant':<12}{'n':>5}  {'rho':>7}  95% CI")
    clean_per_band: dict[str, dict[int, dict]] = {v: {} for v in VARIANTS}
    for band in [1, 2, 3, 4]:
        for variant in VARIANTS:
            res = run_age_band(joined, band, variant, PRIMARY_UK_MIN, PRIMARY_NO_MIN, CLEAN_MAKES)
            clean_per_band[variant][band] = res
            print(f"{band:<6}{variant:<12}{res['n']:>5}  {str(res['rho']):>7}  ({res['ci_lo']}, {res['ci_hi']})")
        print()
    print("  POOLED clean-makes (within-band corrected):")
    for variant in VARIANTS:
        all_rows = []
        for band in [1, 2, 3, 4]:
            res = run_age_band(joined, band, variant, PRIMARY_UK_MIN, PRIMARY_NO_MIN, CLEAN_MAKES)
            all_rows.extend(res["rows"])
        rho, n = pooled_within_band(all_rows, variant)
        lo, hi = spearman_ci(rho, n) if rho == rho else (float("nan"), float("nan"))
        print(f"    {variant:<12} n={n:>4}  rho={round(rho,4) if rho==rho else None}  "
              f"95% CI=({round(lo,4) if lo==lo else None}, {round(hi,4) if hi==hi else None})")

    print(f"\n=== SENSITIVITY: mechanical-only pooled (within-band), varying thresholds ===")
    for uk_min, no_min in SENSITIVITY_PAIRS:
        for variant in ["all", "mechanical"]:
            pooled = []
            for band in [1, 2, 3, 4]:
                res = run_age_band(joined, band, variant, uk_min, no_min, None)
                pooled.extend(res["rows"])
            if len(pooled) >= 4:
                rho, n = pooled_within_band(pooled, variant)
                print(f"  UK>={uk_min:<5} NO>={no_min:<5}  {variant:<12} n={n:>4}  "
                      f"within_band_rho={round(rho,4) if rho==rho else None}")
            else:
                print(f"  UK>={uk_min:<5} NO>={no_min:<5}  {variant:<12} n={len(pooled):>4}  (too few)")

    print(f"\n=== BAND-1-ONLY SENSITIVITY (the band this phase is really about) ===")
    for uk_min, no_min in SENSITIVITY_PAIRS:
        row = f"  UK>={uk_min:<5} NO>={no_min:<5}  "
        for variant in VARIANTS:
            res = run_age_band(joined, 1, variant, uk_min, no_min, None)
            row += f"{variant}: n={res['n']:>3} rho={res['rho']}   "
        print(row)


if __name__ == "__main__":
    main()
