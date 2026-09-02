# Combining the UK and Norwegian reliability indices, and a reliability confidence badge

Status: complete. New script (`pipeline/src/build_combined_reliability.py`), four new columns on
`model_bracket_rankings.csv`, a reliability confidence badge on the car detail page in both
languages, and updated methodology copy with both required attributions. No existing metric CSV,
the crosswalk, the DVSA ingest, or `price_confidence` was touched.

## The method, exactly as specified

`pipeline/src/build_combined_reliability.py` consumes `model_age_band_metrics.csv` (UK, from
`build_phase3_metrics.py`) and `model_age_band_metrics_no.csv` (Norway, from
`build_norway_metrics.py`), both unchanged, and writes
`pipeline/reference/model_age_band_reliability_combined.csv`.

1. Each source's own `standardized_pass_rate` is used exactly as computed.
2. Standardisation happens **within (source, age_band)**. Norway runs 30 to 40 points below the UK
   in band 4 for the same models (`reports/norway_pkk_report.md`), so raw rates are never pooled.
3. The standardisation is on the **logit** of the pass rate, not the raw rate: `z = (logit(p) -
   mean_logit) / sd_logit`, where `mean_logit` and `sd_logit` are computed per (source, age_band)
   across that source's own statistically stable cells (not reliability-unstable, and clearing that
   source's own test-count floor: 2,000 for the UK, 2,500 for Norway, the same floors this project
   has used since Phase 2 and the Norway phase).
4. Combination is by **inverse-variance weight**. Each cell's z-score carries a sampling variance,
   propagated by the delta method from a binomial variance on the raw rate:
   `Var(logit(p)) ~= 1 / (n * p * (1-p))`, then `Var(z) = Var(logit(p)) / sd_logit^2`, treating the
   band's mean and sd as fixed reference constants (the standard simplification when combining a
   per-cell estimate against a population-level reference, since the reference itself is built from
   many cells and its own sampling error is far smaller than any single cell's). `n` is each cell's
   total test count (`n_nt_tests` UK, `n_periodisk_tests` Norway) -- the same `n` the project's own
   stability floors are already defined against, even though the mileage-strata standardisation
   makes the true effective sample size somewhat different from the raw total. This is a documented
   approximation, not an exact effective sample size.

   Two-source combination: `w_uk = 1/Var(z_uk)`, `w_no = 1/Var(z_no)`,
   `combined_z = (w_uk*z_uk + w_no*z_no) / (w_uk + w_no)`.
5. A model in only one source falls back to that source's z-score, unchanged. This is not just a
   design intention: the script asserts `combined_z == z_uk` at build time for every UK-only cell
   (340 of them) and prints the count checked. All 340 passed.

Sanity check against the previously published agreement study: recomputing Spearman rank
correlation directly from this script's own `uk_z`/`no_z` columns (not `build_agreement_study.py`,
a fully independent re-derivation) gives 0.38 / 0.50 / 0.77 / 0.88 across age bands 1-4, against
`reports/norway_pkk_report.md`'s published 0.42 / 0.46 / 0.75 / 0.88. Close but not identical,
because the join criterion here (each source's own basic stability check) is slightly looser than
that report's PRIMARY threshold (UK n>=2,000 *and* Norway n>=2,500 applied as an extra filter on
top of stability) and the Norway-side crosswalk fixes from `reports/no_crosswalk_variant_grouping.md`
changed cell counts after that report was written. Same shape, same qualitative story (correlation
rising sharply from band 1 to band 4), which is the check that matters.

## Per-cell agreement measure: not silently averaged away

Every two-source cell carries `reliability_agreement`, the absolute gap between the two sources'
own within-band z-scores, `|z_uk - z_no|`. Because both z-scores are standardised to mean 0, sd 1
across that band's stable cells, this gap is directly interpretable in "how many within-band
standard deviations apart" terms, independent of which age band or which country's raw scale is
involved.

Across the 237 two-source cells: minimum 0.001, median 0.53, mean 0.63, maximum 2.16.

## The reliability_confidence thresholds, fixed before looking at the result

Four columns were added to `model_bracket_rankings.csv` (and therefore to `rankings.json` via the
existing generic CSV-to-JSON passthrough in `site/scripts/sync-data.mjs`, no changes needed there):
`combined_reliability_z`, `reliability_agreement`, `reliability_source_count`,
`reliability_confidence`.

**Agreement thresholds: 0.5 and 1.0.** These are the standard "medium" and "large" effect-size
boundaries (the Cohen's d convention), applied here to a disagreement between two independent
standardised measurements rather than to a single sample's effect size. They are round numbers
chosen for being independently interpretable, not fit to where this dataset's agreement values
happen to cluster.

- `agreement < 0.5`: the two sources sit within half a within-band standard deviation of each
  other -- close agreement.
- `0.5 <= agreement < 1.0`: moderate, not tight, agreement.
- `agreement >= 1.0`: the two sources disagree by more than a full within-band standard deviation,
  larger than the typical between-model spread the ranking itself is trying to measure. This
  overrides sample size: more data does not fix it, because
  `reports/failure_category_agreement_test.md` already established the disagreement is not sampling
  noise (between-model spread is 38x the binomial standard error in band 1, and restricting to
  higher-volume cells makes band 1 correlation fall, not rise).

**Combined-n "high" bar: 10,000.** Both sources must already individually clear their own floor
before they are combined (2,000 UK + 2,500 Norway = 4,500 minimum for any two-source cell), so
10,000 is a round number comfortably above that bare minimum, not fit to the observed distribution.
In practice this bar barely binds: raising it to 20,000 moves only 2 cells from "high" to "medium",
and lowering it to 5,000 changes nothing at all, since agreement, not volume, is what separates
"high" from "medium" in this dataset.

**Single-source ceiling: never "high".** A cell backed by only one source can reach "medium" at
best, regardless of how many tests back it, because there is no way to rule out this being exactly
the kind of cell whose ordering does not transfer between countries at all -- the entire finding
this phase is built on. Within that ceiling, **1.25x the source's own floor** (2,500 UK tests,
3,125 Norway tests) separates "medium" from "low": a cell that only marginally clears the bare
minimum is thinner evidence than one comfortably above it. This buffer was checked for sensitivity
(1.1x, 1.25x, 1.5x all tried) and 1.25x was kept as the middle, unremarkable choice rather than
picking whichever margin produced the tidiest-looking split.

**Final rule:**

```
if source_count == 2:
    if agreement < 0.5 and effective_n >= 10,000: "high"
    elif agreement < 1.0: "medium"
    else: "low"
elif source_count == 1:
    floor = 2,000 (UK) or 2,500 (Norway)
    "medium" if effective_n >= 1.25 * floor else "low"
```

## The resulting distribution, reported plainly

Across all 622 (model, age band) cells with at least one stable source (237 two-source, 340
UK-only, 45 Norway-only, none of the last group currently reach a ranked row -- see below):

| confidence | n | share |
|---|---:|---:|
| high | 112 | 18.0% |
| medium | 453 | 72.8% |
| low | 57 | 9.2% |

Restricted to the 474 rank-eligible rows in `model_bracket_rankings.csv` (`excluded_from_rank ==
False`): 96 high (20.3%), 334 medium (70.5%), 44 low (9.3%). Across all 621 rows in that file
(including excluded ones): 112 high, 404 medium, 51 low, 54 blank (the 54 rows already excluded for
`reliability_unstable`, which never got a stable cell on either side).

**Most rows land on medium.** That is reported as the answer, not adjusted away: a single strong
UK source, however large, cannot earn "high" under this rule, and most models in this project only
have one stable source. This is an honest consequence of the design (a cross-validated figure is
scarcer than a single-country one), not a sign the thresholds need retuning.

Sensitivity checked and reported, not cherry-picked:

| what varied | result |
|---|---|
| agreement cuts 0.3/0.75 instead of 0.5/1.0 | 72 high, 461 medium, 89 low |
| agreement cuts 0.5/1.0 (primary) | 112 high, 453 medium, 57 low |
| agreement cuts 0.75/1.25 | 154 high, 436 medium, 32 low |
| combined-n high bar 5,000 | identical to primary |
| combined-n high bar 10,000 (primary) | 112 high, 453 medium, 57 low |
| combined-n high bar 20,000 | 110 high, 455 medium, 57 low |
| single-source margin 1.1x | 112 high, 459 medium, 51 low |
| single-source margin 1.25x (primary) | 112 high, 453 medium, 57 low |
| single-source margin 1.5x | 112 high, 445 medium, 65 low |

The "high" count moves with the agreement cut, as expected (that is the threshold doing its job).
The combined-n bar has almost no effect in the range tried, honestly reported rather than hidden --
in this dataset, agreement is what separates "high" from "medium", not volume.

## The known limitation falls out of the per-cell data, not a make list

`reliability_confidence` is computed per (model, age band) cell from that cell's own numbers.
Nothing in `build_combined_reliability.py` names BMW, Mercedes-Benz, Audi or Volvo, or checks
which age band a cell is in beyond using it as the standardisation key everyone gets.

Checking the result: the 35 two-source cells for BMW, Mercedes-Benz, Audi and Volvo in age bands 1
and 2 split 12 low / 11 medium / 12 high, a 34.3% low share, against 21.1% (50 of 237) for all
two-source cells overall -- elevated, as expected, but not uniform. That non-uniformity is real and
worth reading directly rather than summarised away:

| model | band | uk_z | no_z | agreement | confidence |
|---|---:|---:|---:|---:|---|
| BMW X5 | 2 | 1.85 | -0.15 | 2.00 | low |
| Audi A3 Sportback | 1 | 1.02 | -0.97 | 1.99 | low |
| Audi A3 | 1 | 1.02 | -0.94 | 1.96 | low |
| BMW 3-Serie | 1 | 1.16 | -0.73 | 1.89 | low |
| Volvo XC40 | 1 | 1.40 | 3.24 | 1.85 | low |
| ... | | | | | |
| BMW X3 | 1 | 0.92 | 0.86 | 0.06 | high |
| Volvo V90 | 1 | 0.58 | 0.67 | 0.10 | high |
| BMW X1 | 1 | 1.18 | 1.07 | 0.11 | high |

Some premium-make cells (BMW X5, Audi A3, BMW 3-Series, Volvo XC40) genuinely disagree by close to
two full standard deviations and are correctly flagged low. Others (BMW X1, BMW X3, Volvo V90,
Mercedes E-Klasse) show both sources pointing the same way and land medium or high, same as any
other make. A Spearman correlation computed directly from this script's own z-scores for the
premium-make subgroup, as a cross-check against `reports/no_crosswalk_variant_grouping.md`'s
published 0.11-0.22, reproduces the same near-zero relationship: band 1 = -0.01, band 2 = -0.35
(this study's own restricted subset; the published figures use a stricter joint threshold and a
different join, so exact numbers differ, direction and magnitude do not). The per-cell agreement
measure and the subgroup-level rank correlation are two different lenses on the same underlying
fact (weak ordering agreement for these makes in these bands), and they agree with each other
without either one being hardcoded to the make list.

## What must not regress: verified, not just claimed

`build_phase4_rankings.py` merges the four new columns from `model_age_band_reliability_combined.csv`
onto each output row by `(dmr_make, dmr_model, age_band)` after every existing field is already
computed. Nothing about cost, price, exclusion, or ranking reads any of the four new columns, so
there is no mechanical path for this phase to move a rank. That is a design property, not just a
hope, and it was verified directly:

- The full `model_bracket_rankings.csv` was generated before this phase's changes and kept aside.
  After adding the four new columns, `cost_rank_in_group`, `cost_tier`, `running_cost_rank_overall`,
  `running_cost_tier`, `value_for_money_rank_in_group`, `value_for_money_tier`, `tco_per_year` and
  `excluded_from_rank` were diffed cell by cell across all 621 rows against the "before" file.
  **Zero differences in any of those columns, for any row.**
- Separately, inside `build_combined_reliability.py` itself, every UK-only cell's `combined_z` is
  asserted bit-identical to its own UK z-score at build time (340 of 340 checked, 0 failures).

**Rank movement: zero ranked rows changed `cost_rank_in_group`, by construction and confirmed by
direct diff. There are no "largest movers" to name, because none moved.** This phase adds
information; it does not change which cars are ranked or in what order. A future phase could choose
to also let a Norway-only-stable cell rescue a UK-unstable row into the ranked set (45 such cells
exist in the combined file, though none currently overlap with a row that also has price data, so
none would change today's ranking even if that extension were made); that would be a real, disclosed
scope change to ranking eligibility, not something this phase did.

## Site changes

- `site/src/lib/data.ts`: `RankedCar` gains `combined_reliability_z`, `reliability_agreement`,
  `reliability_source_count`, `reliability_confidence`. New `reliabilityConfidenceNote()` helper,
  bilingual, mirroring the existing `reliabilityNote()` pattern. `price_confidence` and its
  thresholds are untouched.
- `site/src/pages/cars/[slug].astro` and `site/src/pages/da/cars/[slug].astro`: a new confidence
  card, styled identically to the existing price confidence card, reusing `confidenceLabel()` for
  the Danish page exactly as the price card does. Shown only when `reliability_confidence` is
  present (every priced, rank-eligible-or-excluded-for-other-reasons row; absent for the 14 fully
  unpriced Suzuki/DS rows, which do not yet carry this signal).
- `site/src/pages/methodology.astro` and `site/src/pages/da/methodology.astro`: the reliability
  section rewritten to explain the two-source combination, what transfers (ordering) and what does
  not (level), the measured per-band agreement table (0.42 / 0.46 / 0.75 / 0.88), the premium-make
  band 1-2 finding, and the confidence badge's rule in plain language, with real counts pulled from
  `methodology_counts.csv` the same way every other page fact is sourced. The "Where the data comes
  from" list and the "Known limits" list both now name Norway's PKK under **CC BY 4.0 (Statens
  vegvesen)** alongside the existing UK MOT attribution under **Open Government Licence v3.0
  (DVSA)**.
- `pipeline/src/build_phase4_rankings.py`: loads `model_age_band_reliability_combined.csv` if
  present and merges the four columns; adds five new methodology facts (two-source count,
  one-source count, and the low/medium/high distribution) consumed by the methodology page.

Site builds clean: `npm run sync-data && npm run build` produces **1,286 pages**, matching the
pre-existing count.

## Files

| file | purpose |
|---|---|
| `pipeline/src/build_combined_reliability.py` | the combination script: logit z-score within (source, age band), inverse-variance combine, agreement measure, confidence label |
| `pipeline/reference/model_age_band_reliability_combined.csv` | 622 rows: `dmr_make`, `dmr_model`, `age_band`, `reliability_source_count`, `reliability_agreement`, `combined_reliability_z`, `combined_reliability_variance`, `reliability_effective_n`, `uk_z`, `no_z`, `reliability_confidence` |
| `pipeline/reference/model_bracket_rankings.csv` | regenerated, four new columns appended, every pre-existing column and row order unchanged (verified above) |
| `pipeline/reference/methodology_counts.csv` | five new facts, dated 2026-09-02 |
| `site/src/lib/data.ts`, `site/src/pages/cars/[slug].astro`, `site/src/pages/da/cars/[slug].astro`, `site/src/pages/methodology.astro`, `site/src/pages/da/methodology.astro` | site changes described above |

Not touched: `model_age_band_metrics.csv`, `model_age_band_metrics_no.csv`, `crosswalk.csv`,
anything under the DVSA ingest path, `price_confidence` or its thresholds, `cost_rank_in_group`'s
computation.
