"""The point of this phase: does Norwegian PKK data predict the same
reliability ordering as the existing UK DVSA-derived ranking, or is the
UK-as-proxy-for-Denmark assumption unsupported?

Joins pipeline/reference/model_age_band_metrics.csv (UK, existing, unchanged)
against pipeline/reference/model_age_band_metrics_no.csv (Norway, this phase)
on (dmr_make, dmr_model, age_band) and computes Spearman rank correlation of
standardized_pass_rate per age band, at several minimum-sample thresholds, plus
a variant restricted to nameplate-clean makes (Skoda, Peugeot, Volkswagen,
Toyota) where the BMW/Mercedes variant-code grouping hazard cannot be the
explanation for any disagreement found.

BAND-CONFOUND CORRECTION (added after an external review caught this): pass
rates fall steeply and monotonically with age in BOTH countries (age band
alone explains 68.1% of the variance in the UK rate and 79.0% in the
Norwegian rate, measured below). Pooling all (model, age_band) cells together
and rank-correlating them therefore measures, in large part, the two series
agreeing that old cars fail more than young cars -- a real fact, but not
evidence that the MODEL ordering transfers, which is the only thing this
study exists to test. A pooled rank correlation must not exceed every one of
its own per-band components; the original 0.937 pooled figure did exactly
that (it sat above all four per-band figures: 0.42, 0.46, 0.75, 0.88), which
is the tell that it was inflated by the shared age trend, not genuine
cross-source agreement.

The fix: within EACH age band separately, convert every cell's uk_rate and
no_rate to a within-band percentile rank (so a model is scored only against
its age-band peers, on both sides), then pool those percentiles across bands
and rank-correlate the pooled percentiles. This removes the shared age trend
by construction (every band contributes percentiles spanning the same 0-1
range regardless of its raw pass-rate level) while still pooling for a single
summary figure. See within_band_pooled() below.

De-duplication for this study only (does not touch either metrics file):
several DK model-name rows are known, documented spelling/body-style splits
that resolve to the SAME underlying UK test pool AND the same underlying
Norwegian test pool (pipeline/reference/model_spelling_aliases.csv records
the confirmed spelling-duplicate ones; coverage_audit.md finding 1 lists
others, some deliberately NOT merged because they are a genuine hatch/estate
split, e.g. FABIA/FABIA COMBI). A duplicate pair sharing an identical
standardized_pass_rate on BOTH sides contributes a trivially "perfectly
agreeing" extra data point to the correlation and inflates both N and the
coefficient for no real reason, so: within each age band, when two DK models
share bit-identical (uk_rate, no_rate), only the first (alphabetically) is
kept for the correlation. This applies to every variant below, not only the
clean-makes one, since the same inflation risk exists project-wide (Renault
Clio/Ny Clio, Toyota Yaris/Yaris 5-dors, etc.).
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "pipeline" / "reference"
UK_METRICS_CSV = REFERENCE / "model_age_band_metrics.csv"
NO_METRICS_CSV = REFERENCE / "model_age_band_metrics_no.csv"
OUT_JOINED_CSV = REFERENCE / "no_uk_agreement.csv"

CLEAN_MAKES = {"SKODA", "PEUGEOT", "VOLKSWAGEN", "TOYOTA"}

# Primary reported threshold: each side must individually clear ITS OWN
# established stability floor (UK: RANKING_FLOOR_TESTS=2000 from the Phase 2
# strategy doc; Norway: the SE<1pp floor derived in build_norway_metrics.py).
# Sensitivity swept separately below, per the phase brief's explicit request.
PRIMARY_UK_MIN = 2000
PRIMARY_NO_MIN = 2500

SENSITIVITY_PAIRS = [
    (2000, 500), (2000, 1000), (2000, 1500), (2000, 2000), (2000, 2500),
    (1000, 1000), (500, 500),
]


def load_uk() -> dict[tuple[str, str, int], dict]:
    out = {}
    with open(UK_METRICS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["standardized_pass_rate"]:
                continue
            out[(r["dmr_make"], r["dmr_model"], int(r["age_band"]))] = {
                "n": int(r["n_nt_tests"]),
                "rate": float(r["standardized_pass_rate"]),
            }
    return out


def load_no() -> dict[tuple[str, str, int], dict]:
    out = {}
    with open(NO_METRICS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["standardized_pass_rate"]:
                continue
            out[(r["dmr_make"], r["dmr_model"], int(r["age_band"]))] = {
                "n": int(r["n_periodisk_tests"]),
                "rate": float(r["standardized_pass_rate"]),
            }
    return out


def dedupe_signature(rows: list[dict]) -> list[dict]:
    """Within one age band's row list, drop DK models that share a
    bit-identical (uk_rate, no_rate) pair with an earlier (alphabetically
    sorted) model -- see module docstring."""
    rows = sorted(rows, key=lambda r: (r["dmr_make"], r["dmr_model"]))
    seen_sig = set()
    out = []
    for r in rows:
        sig = (r["uk_rate"], r["no_rate"])
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        out.append(r)
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation with average-rank tie handling, computed as
    Pearson correlation on the rank arrays (standard equivalence)."""
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / math.sqrt(vx * vy)


def spearman_ci(rho: float, n: int) -> tuple[float, float]:
    """95% CI via Fisher z-transform, standard approximation for Spearman."""
    if n < 4 or abs(rho) >= 1.0:
        return (float("nan"), float("nan"))
    z = math.atanh(rho)
    se = 1 / math.sqrt(n - 3)
    lo, hi = z - 1.96 * se, z + 1.96 * se
    return (math.tanh(lo), math.tanh(hi))


def variance_explained_by_band(rows: list[dict], field: str) -> float:
    """Eta-squared: share of the total variance in `field` (uk_rate or
    no_rate) explained by age_band group membership alone. Quantifies the
    band-confound the within_band_pooled() correction below removes."""
    vals = [r[field] for r in rows]
    bands = [r["age_band"] for r in rows]
    grand_mean = sum(vals) / len(vals)
    ss_total = sum((v - grand_mean) ** 2 for v in vals)
    ss_between = 0.0
    for b in set(bands):
        gv = [v for v, bb in zip(vals, bands) if bb == b]
        gm = sum(gv) / len(gv)
        ss_between += len(gv) * (gm - grand_mean) ** 2
    return ss_between / ss_total if ss_total else float("nan")


def within_band_pooled(rows: list[dict]) -> tuple[float, int]:
    """The band-confound-corrected pooled statistic. Within each age band
    present in `rows`, converts uk_rate and no_rate to a within-band
    percentile rank ((rank - 0.5) / n_in_band, average-rank tie handling via
    the same ranks() logic spearman() uses), pools the percentiles across all
    bands, and returns (Spearman rho of the pooled percentiles, n pooled).

    Because every band's percentiles span the same 0-1 range regardless of
    that band's raw pass-rate level, this measures only whether a model's
    standing RELATIVE TO ITS AGE-BAND PEERS agrees between sources -- the
    shared "old cars fail more" trend that inflates the naive pooled
    Spearman on raw rates cannot contribute here by construction."""
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    by_band = defaultdict(list)
    for r in rows:
        by_band[r["age_band"]].append(r)

    uk_pctl, no_pctl = [], []
    for band, grp in by_band.items():
        n = len(grp)
        if n < 2:
            continue
        ruk = ranks([r["uk_rate"] for r in grp])
        rno = ranks([r["no_rate"] for r in grp])
        for ru, rn in zip(ruk, rno):
            uk_pctl.append((ru - 0.5) / n)
            no_pctl.append((rn - 0.5) / n)

    if len(uk_pctl) < 4:
        return float("nan"), len(uk_pctl)
    return spearman(uk_pctl, no_pctl), len(uk_pctl)


def build_joined(uk: dict, no: dict) -> list[dict]:
    rows = []
    for key in set(uk) & set(no):
        make, model, band = key
        rows.append({
            "dmr_make": make, "dmr_model": model, "age_band": band,
            "uk_n": uk[key]["n"], "uk_rate": uk[key]["rate"],
            "no_n": no[key]["n"], "no_rate": no[key]["rate"],
        })
    return rows


def run_age_band(rows: list[dict], band: int, uk_min: int, no_min: int, makes: set[str] | None) -> dict:
    subset = [r for r in rows if r["age_band"] == band and r["uk_n"] >= uk_min and r["no_n"] >= no_min]
    if makes is not None:
        subset = [r for r in subset if r["dmr_make"] in makes]
    subset = dedupe_signature(subset)
    n = len(subset)
    if n < 4:
        return {"age_band": band, "n": n, "rho": None, "ci_lo": None, "ci_hi": None}
    rho = spearman([r["uk_rate"] for r in subset], [r["no_rate"] for r in subset])
    ci_lo, ci_hi = spearman_ci(rho, n)
    return {"age_band": band, "n": n, "rho": round(rho, 4),
            "ci_lo": round(ci_lo, 4) if ci_lo == ci_lo else None,
            "ci_hi": round(ci_hi, 4) if ci_hi == ci_hi else None,
            "rows": subset}


def main() -> None:
    uk = load_uk()
    no = load_no()
    joined = build_joined(uk, no)
    print(f"joined (model, age_band) cells with a standardized rate on both sides: {len(joined)}")

    with open(OUT_JOINED_CSV, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["dmr_make", "dmr_model", "age_band", "uk_n", "uk_rate", "no_n", "no_rate"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(sorted(joined, key=lambda r: (r["age_band"], r["dmr_make"], r["dmr_model"])))
    print(f"wrote {OUT_JOINED_CSV}")

    print("\n=== BAND CONFOUND: why the naive pooled figure is not the headline number ===")
    uk_eta2 = variance_explained_by_band(joined, "uk_rate")
    no_eta2 = variance_explained_by_band(joined, "no_rate")
    print(f"  variance in uk_rate explained by age_band alone: {uk_eta2*100:.1f}%")
    print(f"  variance in no_rate explained by age_band alone: {no_eta2*100:.1f}%")
    band_means = defaultdict(list)
    for r in joined:
        band_means[r["age_band"]].append(r)
    for band in [1, 2, 3, 4]:
        grp = band_means[band]
        uk_m = sum(r["uk_rate"] for r in grp) / len(grp)
        no_m = sum(r["no_rate"] for r in grp) / len(grp)
        print(f"  band {band} mean: uk={uk_m:.3f}  no={no_m:.3f}  (n={len(grp)})")
    naive_407 = spearman([r["uk_rate"] for r in joined], [r["no_rate"] for r in joined])
    within_407, n_within_407 = within_band_pooled(joined)
    print(f"  naive pooled Spearman, ALL {len(joined)} joined cells (no threshold): rho={round(naive_407,4)}")
    print(f"  within-band-percentile pooled Spearman, same {n_within_407} cells:    rho={round(within_407,4)}")
    print(f"  -- the naive figure sits above every one of the four per-band coefficients computed below "
          f"(that is the tell); the within-band figure does not, and is the defensible summary.")

    print(f"\n=== PRIMARY: UK n>={PRIMARY_UK_MIN}, NO n>={PRIMARY_NO_MIN}, all makes ===")
    all_bands_rows = []
    for band in [1, 2, 3, 4]:
        res = run_age_band(joined, band, PRIMARY_UK_MIN, PRIMARY_NO_MIN, None)
        print(f"  band {band}: n={res['n']:>3}  rho={res['rho']}  95% CI=({res['ci_lo']}, {res['ci_hi']})")
        if res.get("rows"):
            all_bands_rows.extend(res["rows"])

    if all_bands_rows:
        pooled_rho = spearman([r["uk_rate"] for r in all_bands_rows], [r["no_rate"] for r in all_bands_rows])
        n_pooled = len(all_bands_rows)
        lo, hi = spearman_ci(pooled_rho, n_pooled)
        print(f"  POOLED (naive, band-confounded, DO NOT quote as the headline): n={n_pooled}  "
              f"rho={round(pooled_rho,4)}  95% CI=({round(lo,4) if lo==lo else None}, {round(hi,4) if hi==hi else None})")
        within_rho, n_within = within_band_pooled(all_bands_rows)
        wlo, whi = spearman_ci(within_rho, n_within)
        print(f"  POOLED (within-band corrected, THE headline figure):        n={n_within}  "
              f"rho={round(within_rho,4)}  95% CI=({round(wlo,4) if wlo==wlo else None}, {round(whi,4) if whi==whi else None})")

    print(f"\n=== SENSITIVITY: pooled across all 4 bands, all makes, varying thresholds ===")
    for uk_min, no_min in SENSITIVITY_PAIRS:
        pooled = []
        for band in [1, 2, 3, 4]:
            res = run_age_band(joined, band, uk_min, no_min, None)
            if res.get("rows"):
                pooled.extend(res["rows"])
        if len(pooled) >= 4:
            rho = spearman([r["uk_rate"] for r in pooled], [r["no_rate"] for r in pooled])
            within_rho, n_within = within_band_pooled(pooled)
            print(f"  UK>={uk_min:<5} NO>={no_min:<5}  n={len(pooled):>4}  naive_rho={round(rho,4)}  "
                  f"within_band_rho={round(within_rho,4) if within_rho==within_rho else None}")
        else:
            print(f"  UK>={uk_min:<5} NO>={no_min:<5}  n={len(pooled):>4}  (too few for a coefficient)")

    print(f"\n=== CLEAN MAKES ONLY (Skoda, Peugeot, Volkswagen, Toyota), UK n>={PRIMARY_UK_MIN}, NO n>={PRIMARY_NO_MIN} ===")
    clean_pooled = []
    for band in [1, 2, 3, 4]:
        res = run_age_band(joined, band, PRIMARY_UK_MIN, PRIMARY_NO_MIN, CLEAN_MAKES)
        print(f"  band {band}: n={res['n']:>3}  rho={res['rho']}  95% CI=({res['ci_lo']}, {res['ci_hi']})")
        if res.get("rows"):
            clean_pooled.extend(res["rows"])
    if clean_pooled:
        rho = spearman([r["uk_rate"] for r in clean_pooled], [r["no_rate"] for r in clean_pooled])
        n_pooled = len(clean_pooled)
        lo, hi = spearman_ci(rho, n_pooled)
        print(f"  POOLED clean-makes (naive, band-confounded): n={n_pooled}  rho={round(rho,4)}  "
              f"95% CI=({round(lo,4) if lo==lo else None}, {round(hi,4) if hi==hi else None})")
        within_rho, n_within = within_band_pooled(clean_pooled)
        wlo, whi = spearman_ci(within_rho, n_within)
        print(f"  POOLED clean-makes (within-band corrected):  n={n_within}  rho={round(within_rho,4)}  "
              f"95% CI=({round(wlo,4) if wlo==wlo else None}, {round(whi,4) if whi==whi else None})")

    # Also try a looser threshold on clean makes since the strict primary
    # threshold may leave too few clean-make cells to say anything.
    print(f"\n=== CLEAN MAKES ONLY, looser threshold UK n>=500, NO n>=500 ===")
    clean_loose = []
    for band in [1, 2, 3, 4]:
        res = run_age_band(joined, band, 500, 500, CLEAN_MAKES)
        print(f"  band {band}: n={res['n']:>3}  rho={res['rho']}  95% CI=({res['ci_lo']}, {res['ci_hi']})")
        if res.get("rows"):
            clean_loose.extend(res["rows"])
    if clean_loose:
        rho = spearman([r["uk_rate"] for r in clean_loose], [r["no_rate"] for r in clean_loose])
        n_pooled = len(clean_loose)
        lo, hi = spearman_ci(rho, n_pooled)
        print(f"  POOLED clean-makes loose (naive, band-confounded): n={n_pooled}  rho={round(rho,4)}  "
              f"95% CI=({round(lo,4) if lo==lo else None}, {round(hi,4) if hi==hi else None})")
        within_rho, n_within = within_band_pooled(clean_loose)
        wlo, whi = spearman_ci(within_rho, n_within)
        print(f"  POOLED clean-makes loose (within-band corrected):  n={n_within}  rho={round(within_rho,4)}  "
              f"95% CI=({round(wlo,4) if wlo==wlo else None}, {round(whi,4) if whi==whi else None})")

    print(f"\n=== LARGEST DISAGREEMENTS (primary threshold, all bands, deduped) ===")
    primary_all = []
    for band in [1, 2, 3, 4]:
        res = run_age_band(joined, band, PRIMARY_UK_MIN, PRIMARY_NO_MIN, None)
        if res.get("rows"):
            primary_all.extend(res["rows"])
    for r in primary_all:
        r["diff"] = r["no_rate"] - r["uk_rate"]
    primary_all.sort(key=lambda r: r["diff"])
    print("  Norway looks WORSE than UK suggests (no_rate << uk_rate):")
    for r in primary_all[:10]:
        print(f"    {r['dmr_make']:<15} {r['dmr_model']:<20} band{r['age_band']}  "
              f"uk={r['uk_rate']:.3f}(n={r['uk_n']:,})  no={r['no_rate']:.3f}(n={r['no_n']:,})  diff={r['diff']:+.3f}")
    print("  Norway looks BETTER than UK suggests (no_rate >> uk_rate):")
    for r in primary_all[-10:][::-1]:
        print(f"    {r['dmr_make']:<15} {r['dmr_model']:<20} band{r['age_band']}  "
              f"uk={r['uk_rate']:.3f}(n={r['uk_n']:,})  no={r['no_rate']:.3f}(n={r['no_n']:,})  diff={r['diff']:+.3f}")


if __name__ == "__main__":
    main()
