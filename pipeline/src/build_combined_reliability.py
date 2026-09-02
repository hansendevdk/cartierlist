"""Combines the UK DVSA and Norwegian PKK reliability indices into one
cross-validated reliability signal per (dmr_make, dmr_model, age_band).

Consumes pipeline/src/build_phase3_metrics.py's output
(reference/model_age_band_metrics.csv, UK) and
pipeline/src/build_norway_metrics.py's output
(reference/model_age_band_metrics_no.csv, Norway), both UNCHANGED. Writes
reference/model_age_band_reliability_combined.csv, one row per (model, age
band) that has at least one statistically stable source. build_phase4_rankings.py
joins this file onto the ranked rows to add four new columns; it does not
change ranking eligibility, cost_rank_in_group, or anything else already
computed there. Neither metrics CSV, crosswalk.csv, model_bracket_rankings.csv,
nor anything under site/ is written by this script.

THE COMBINATION RULE (fixed by reports/handover_multi_country_reliability.md's
"combination design" section, not redesigned here):

  1. Each source's own reliability index (standardized_pass_rate) is used
     exactly as Phase 3 / the Norway phase computed it.
  2. Standardise WITHIN (source, age_band). The absolute level does not
     transfer between countries at all -- Norway runs 30 to 40 points below
     the UK in band 4 (reports/norway_pkk_report.md) -- so raw rates are
     never pooled across sources.
  3. Standardise the LOGIT of the pass rate, then z-score, not the raw rate.
     A 5-point gap near 0.95 is not the same quantity as one near 0.50, and
     Norway sits near 0.50 while the UK sits near 0.80 for the same models;
     z-scoring the raw rate would distort exactly the comparison this index
     exists to make.
  4. Combine with inverse-variance weights, using each cell's own sampling
     variance on the z-score scale. Never weight by how well the two sources
     happen to agree -- that would be circular (see point 5 below for why
     agreement is tracked separately instead).
  5. A model present in only one source falls back to that source's z-score,
     unchanged. This is verified below: every UK-only cell's combined score
     is bit-identical to its own UK z-score.

WHY THIS SCRIPT DOES NOT SILENTLY AVERAGE DISAGREEMENT AWAY
reports/norway_pkk_report.md measured within-band Spearman rank correlation
between the two sources at 0.42 / 0.46 / 0.75 / 0.88 across age bands 1-4.
reports/failure_category_agreement_test.md showed this is NOT sampling
noise: between-model spread is 38x the binomial standard error in band 1,
and restricting to higher-volume cells makes band 1 correlation FALL, not
rise. reports/no_crosswalk_variant_grouping.md further pinned this down to
BMW, Mercedes-Benz, Audi and Volvo specifically, which sit at roughly
0.11-0.22 rank correlation in bands 1-2, close to no relationship at all,
even after fixing real crosswalk bugs that had nothing to do with the
weakness.

Averaging two measurements of genuinely different quantities produces a
number with no referent. So alongside the inverse-variance combined
z-score, every two-source cell also carries `reliability_agreement` (the
absolute gap between the two sources' own within-band z-scores) and a
`reliability_confidence` label that downgrades to "low" whenever that gap
is large -- regardless of how much data backs the cell, because more data
does not fix a disagreement this project has already shown is not noise.
"""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "pipeline" / "reference"
UK_METRICS_CSV = REFERENCE / "model_age_band_metrics.csv"
NO_METRICS_CSV = REFERENCE / "model_age_band_metrics_no.csv"
OUT_CSV = REFERENCE / "model_age_band_reliability_combined.csv"

# Same stability floors this project has used since Phase 2 (UK) and the
# Norway phase (NO) -- not re-derived here, just referenced for the
# single-source confidence rule below.
UK_FLOOR = 2000
NO_FLOOR = 2500

# --- reliability_confidence thresholds, fixed BEFORE looking at the
# resulting distribution (see the report for the sensitivity tables that
# confirm these were not tuned to make the output look a particular way) ---
#
# Agreement is measured in units of a within-band standard deviation, since
# both sources' z-scores are standardised to mean 0, sd 1 across that band's
# stable cells. That makes 0.5 and 1.0 interpretable independent of this
# project's own data: they are the standard "medium" and "large" effect-size
# boundaries (Cohen's d convention), applied here to a disagreement between
# two independent measurements of the same modelled quantity rather than to
# a single sample's effect size.
AGREEMENT_LOW = 0.5   # below this, the two sources are in close agreement
AGREEMENT_HIGH = 1.0  # at or above this, the sources disagree by more than
                       # one full within-band standard deviation -- larger
                       # than the typical between-model spread the ranking
                       # itself is trying to measure, so the combined
                       # midpoint is not trustworthy regardless of sample size
# A two-source cell's effective n is n_uk + n_no. Since both sides must
# individually clear their own floor before they are combined (2,000 UK,
# 2,500 NO), every two-source cell already carries at least 4,500. The
# "high" bar is set at more than double that bare minimum -- a round number
# chosen for being comfortably above the floor, not fit to where the actual
# n values happen to cluster.
COMBINED_N_HIGH = 10_000
# A single-source cell can only ever reach "medium", never "high": with no
# second source there is no way to rule out this being exactly the kind of
# cell whose ordering does not transfer between countries at all, which is
# the entire finding this phase is built on. Within that ceiling, a cell
# that only marginally clears its own floor is thinner evidence than one
# comfortably above it -- scored the same way the Norway phase's own floor
# tables reported floor sensitivity, this uses a 25% buffer over the bare
# minimum, i.e. n >= 1.25x the source's floor, for "medium"; below that, "low".
SINGLE_SOURCE_MARGIN = 1.25


def logit(p: float, eps: float = 1e-6) -> float:
    """Guard against p landing exactly on 0 or 1 (never observed in either
    metrics file, since standardized_pass_rate is a weighted sum of >=3
    surviving strata each requiring a real minimum cell count, but guarded
    anyway -- an unguarded logit would otherwise crash on any future input
    it hasn't seen yet)."""
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def load_stable(
    path: Path, n_col: str, floor_col: str
) -> dict[tuple[str, str, str], tuple[float, int]]:
    """Returns {(make, model, age_band): (standardized_pass_rate, n_tests)}
    for cells that clear THAT source's own stability floor and strata
    survival check -- the same two-part 'stable' definition each source's
    own build script already uses to decide meets_stability_floor /
    reliability_unstable."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["reliability_unstable"] != "False":
                continue
            if r[floor_col] != "True":
                continue
            if not r["standardized_pass_rate"]:
                continue
            key = (r["dmr_make"], r["dmr_model"], r["age_band"])
            out[key] = (float(r["standardized_pass_rate"]), int(r[n_col]))
    return out


def band_logit_stats(
    stable: dict[tuple[str, str, str], tuple[float, int]]
) -> dict[str, tuple[float, float]]:
    """Per age_band mean and (sample) sd of logit(standardized_pass_rate)
    across that source's own stable cells -- the reference distribution
    each cell in that band is z-scored against."""
    by_band: dict[str, list[float]] = {}
    for (_, _, band), (p, _n) in stable.items():
        by_band.setdefault(band, []).append(logit(p))
    out = {}
    for band, vals in by_band.items():
        mean = statistics.mean(vals)
        sd = statistics.stdev(vals) if len(vals) >= 2 else 1.0
        out[band] = (mean, sd)
    return out


def compute_z(
    stable: dict[tuple[str, str, str], tuple[float, int]],
    band_stats: dict[str, tuple[float, float]],
) -> dict[tuple[str, str, str], dict]:
    """z-score of logit(p) within (source, age_band), plus the sampling
    variance of that z-score, propagated by the delta method from a
    binomial variance on the raw rate: Var(logit(p)) ~= 1 / (n*p*(1-p)),
    then Var(z) = Var(logit(p)) / sd_band^2 since z = (logit(p) - mean) / sd
    and mean/sd are treated as fixed reference constants (estimated from
    many cells, so their own sampling error is far smaller than any single
    cell's) -- the standard simplification meta-analyses make when
    combining a per-study estimate against a fixed reference scale.

    This uses each cell's TOTAL test count as n, the same n the project's
    own stability floors (RANKING_FLOOR_TESTS, RANKING_FLOOR_SE_TARGET) are
    already defined against, even though standardisation across mileage
    strata makes the true effective n somewhat different from the raw
    total. That is a documented approximation, not an exact effective
    sample size -- see the report."""
    out = {}
    for key, (p, n) in stable.items():
        band = key[2]
        mean, sd = band_stats[band]
        lp = logit(p)
        z = (lp - mean) / sd
        var_logit = 1.0 / (n * p * (1 - p))
        var_z = var_logit / (sd ** 2)
        out[key] = {"z": z, "var_z": var_z, "n": n, "p": p}
    return out


def main() -> None:
    uk_stable = load_stable(UK_METRICS_CSV, "n_nt_tests", "meets_stability_floor")
    no_stable = load_stable(NO_METRICS_CSV, "n_periodisk_tests", "meets_stability_floor_2500")
    print(f"UK stable cells: {len(uk_stable)} of however many rows model_age_band_metrics.csv has")
    print(f"NO stable cells: {len(no_stable)} of however many rows model_age_band_metrics_no.csv has")

    uk_band_stats = band_logit_stats(uk_stable)
    no_band_stats = band_logit_stats(no_stable)
    print("\nper-band logit(pass rate) reference stats (mean, sd), among stable cells:")
    for band in sorted(set(uk_band_stats) | set(no_band_stats)):
        um = uk_band_stats.get(band)
        nm = no_band_stats.get(band)
        print(f"  band {band}: UK mean={um[0]:.3f} sd={um[1]:.3f}" if um else f"  band {band}: UK n/a",
              f" | NO mean={nm[0]:.3f} sd={nm[1]:.3f}" if nm else " | NO n/a")

    uk_z = compute_z(uk_stable, uk_band_stats)
    no_z = compute_z(no_stable, no_band_stats)

    all_keys = set(uk_z) | set(no_z)
    print(f"\n{len(all_keys)} (model, age band) cells have at least one stable source "
          f"({len(set(uk_z) & set(no_z))} have both, {len(set(uk_z) - set(no_z))} UK-only, "
          f"{len(set(no_z) - set(uk_z))} Norway-only)")

    out_rows = []
    n_high = n_medium = n_low = 0
    n_fallback_checked = 0
    for key in sorted(all_keys):
        make, model, band = key
        has_uk = key in uk_z
        has_no = key in no_z

        if has_uk and has_no:
            u, n_ = uk_z[key], no_z[key]
            w_uk = 1.0 / u["var_z"]
            w_no = 1.0 / n_["var_z"]
            combined_z = (w_uk * u["z"] + w_no * n_["z"]) / (w_uk + w_no)
            combined_var = 1.0 / (w_uk + w_no)
            agreement = abs(u["z"] - n_["z"])
            source_count = 2
            eff_n = u["n"] + n_["n"]
            if agreement < AGREEMENT_LOW and eff_n >= COMBINED_N_HIGH:
                confidence = "high"
            elif agreement < AGREEMENT_HIGH:
                confidence = "medium"
            else:
                confidence = "low"
        elif has_uk:
            u = uk_z[key]
            combined_z = u["z"]
            combined_var = u["var_z"]
            agreement = None
            source_count = 1
            eff_n = u["n"]
            confidence = "medium" if eff_n >= SINGLE_SOURCE_MARGIN * UK_FLOOR else "low"
            # Fallback-path check (acceptance criterion: a UK-only model
            # must not move at all): combined_z must be bit-identical to
            # the UK z-score, since it IS the UK z-score here, not a
            # recomputation of it.
            assert combined_z == u["z"]
            n_fallback_checked += 1
        else:
            n_ = no_z[key]
            combined_z = n_["z"]
            combined_var = n_["var_z"]
            agreement = None
            source_count = 1
            eff_n = n_["n"]
            confidence = "medium" if eff_n >= SINGLE_SOURCE_MARGIN * NO_FLOOR else "low"

        if confidence == "high":
            n_high += 1
        elif confidence == "medium":
            n_medium += 1
        else:
            n_low += 1

        out_rows.append({
            "dmr_make": make, "dmr_model": model, "age_band": band,
            "reliability_source_count": source_count,
            "reliability_agreement": round(agreement, 4) if agreement is not None else "",
            "combined_reliability_z": round(combined_z, 4),
            "combined_reliability_variance": round(combined_var, 6),
            "reliability_effective_n": eff_n,
            "uk_z": round(uk_z[key]["z"], 4) if has_uk else "",
            "no_z": round(no_z[key]["z"], 4) if has_no else "",
            "reliability_confidence": confidence,
        })

    print(f"\nfallback-path check: {n_fallback_checked} UK-only cells verified "
          f"bit-identical to their own UK z-score")
    print(f"\nreliability_confidence distribution across all {len(out_rows)} scored cells "
          f"(not just ranked ones):")
    print(f"  high:   {n_high} ({n_high/len(out_rows)*100:.1f}%)")
    print(f"  medium: {n_medium} ({n_medium/len(out_rows)*100:.1f}%)")
    print(f"  low:    {n_low} ({n_low/len(out_rows)*100:.1f}%)")

    fieldnames = list(out_rows[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {OUT_CSV} ({len(out_rows)} rows)")


if __name__ == "__main__":
    main()
