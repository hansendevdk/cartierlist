# Does restricting the reliability index to mechanical faults improve it?

Status: complete. Report only. No metric, ranking, reference CSV consumed by the site, or site page
changed by this test.

**Answer: no. The hypothesis this test was built to check is falsified, and the investigation
surfaced a better explanation for the thing that prompted it.**

The classification was frozen and written to disk (`pipeline/reference/dvsa_defect_classification.csv`,
`pipeline/reference/norway_defect_classification.csv`) before any correlation was computed, and the
prediction below was recorded before the result was known.

## The prediction, stated before the result

The UK/Norway agreement study found rank correlation of the reliability index rising sharply with
car age: 0.42 in band 1, 0.46 in band 2, 0.75 in band 3, 0.88 in band 4. That gap was shown not to
be sampling noise (between-model spread is 38x the binomial sampling error on the UK side in band 1,
and restricting to higher-volume cells makes band 1 *fall* rather than rise).

Proposed explanation: young-car inspection failures are dominated by consumables that measure the
owner, the climate and the local testing regime rather than the vehicle, while old-car failures are
dominated by mechanical faults that measure how the car was built.

Falsifiable prediction: **mechanical-only should correlate better than all-defects, consumable-only
should correlate worse, and the gap should be largest in band 1.**

## Step 1: the descriptive premise, which is correct

The UK failure composition shifts with age exactly as the hypothesis requires. Share of failure
items by bucket:

| age band | consumable | mechanical | admin/other |
|---|---:|---:|---:|
| 1 (2020-2022) | **68.4%** | 29.4% | 2.2% |
| 2 (2017-2019) | 54.0% | 44.0% | 2.1% |
| 3 (2014-2016) | 48.5% | 49.4% | 2.1% |
| 4 (2010-2013) | 44.8% | **52.9%** | 2.3% |

At test level the same gradient holds: among failed band 1 tests, 75.2% carry a consumable defect
against 36.2% carrying a mechanical one. By band 4 that has inverted to 69.1% mechanical against
67.2% consumable.

So the premise is real. A young car's MOT failure genuinely is mostly wipers, bulbs, tread and
headlamp aim. The hypothesis fails at the next step, not this one.

## Step 2: the agreement study, which refutes the prediction

Within-band Spearman correlation, UK against Norway, all makes, cells clearing both stability
floors:

| age band | n | all-defects | mechanical only | consumable only |
|---|---:|---:|---:|---:|
| 1 | 105 | 0.52 | **0.48** | 0.45 |
| 2 | 127 | 0.68 | **0.51** | 0.78 |
| 3 | 133 | 0.81 | **0.67** | 0.87 |
| 4 | 122 | 0.80 | **0.73** | 0.78 |

Restricted to the four nameplate-clean makes (Skoda, Peugeot, Volkswagen, Toyota):

| age band | n | all-defects | mechanical only | consumable only |
|---|---:|---:|---:|---:|
| 1 | 32 | 0.77 | **0.65** | 0.83 |
| 2 | 36 | 0.79 | **0.67** | 0.86 |
| 3 | 38 | 0.85 | **0.55** | 0.81 |
| 4 | 34 | 0.79 | **0.57** | 0.80 |

**Mechanical-only is worse than all-defects in all eight comparisons.** Consumable-only beats
mechanical-only in seven of the eight. The prediction was wrong in direction, not merely in
magnitude, and no reading of these numbers supports restricting the index to mechanical faults.

Consumables correlating *better* across countries than mechanical faults is the surprise here. A
plausible reading, not a proven one: consumable failure rates partly measure design properties that
are constant across markets (a model with poorly aimed headlamps fails headlamp aim everywhere,
a model with a bad wiper linkage fails wipers everywhere), whereas mechanical faults at these ages
are rarer per test and therefore noisier.

### Two caveats that stop this being a clean refutation

1. **The mechanical buckets are not symmetric across the two countries.** Norwegian PKK chapter 5
   bundles axles, wheels, tyres and suspension into one number, mixing systems that the DVSA
   hierarchy splits into oppositely-classified sections (suspension and road wheels mechanical,
   tyres consumable, roughly 62/38 by UK defect volume). It was correctly routed to the third
   bucket rather than forced, but the consequence is that Norway's mechanical rate covers brakes,
   steering, chassis and emissions while the UK's also includes suspension. Chapter 7 (other
   equipment) is excluded on the Norwegian side for the same reason.
2. **Mechanical failures are rarer, so their pass rates sit closer to the ceiling** and carry less
   between-model variance for a rank correlation to work with. Some of the drop is statistical
   rather than substantive.

A symmetric test, restricting the UK side to only the systems Norway can supply at chapter
granularity, would be the clean version. It is worth doing before treating this as settled, but it
would have to overturn a consistent eight-out-of-eight result to change the recommendation.

## Step 3: what actually explains the band 1 weakness

The category composition does not explain it. Band 1 is weak in all three buckets (0.52, 0.48,
0.45), so the answer is not which defects are counted.

Splitting instead by **how well the model name crosswalks**:

| age band | clean-name makes | variant-code makes | all other makes |
|---|---:|---:|---:|
| 1 | **0.77** (n=32) | **0.11** (n=27) | 0.49 (n=46) |
| 2 | 0.79 (n=36) | **0.00** (n=28) | 0.78 (n=63) |
| 3 | 0.85 (n=38) | 0.47 (n=25) | 0.72 (n=70) |
| 4 | 0.79 (n=34) | 0.67 (n=21) | 0.57 (n=67) |

Variant-code makes are BMW, Mercedes-Benz, Audi and Volvo, the makes whose Norwegian `Kjøretøy
Modell` strings are engine designations (`520D`, `X3 XDRIVE20D`, `C 200 CDI`, `A 180`) that have to
be grouped up to nameplate level before they can meet a Danish model string.

**These makes correlate at 0.11 in band 1 and 0.00 in band 2.** That is no relationship at all.
The clean-name makes in those same bands sit at 0.77 and 0.79, which is roughly where bands 3 and 4
sit for everyone.

The band 1 problem is therefore a **crosswalk quality problem, not a property of young cars**. The
previous phase already suspected this, noting clean makes correlating at 0.82 against 0.65 overall,
and labelled it open. This resolves it: the variant-code grouping is close to worthless in the two
youngest bands and only becomes usable in band 4.

Why the age gradient within the variant-code group is not established here. One candidate worth
testing: mis-grouping a 318d with a 320d matters less when both are old and both fail often, and
more when both are young and the true difference between models is small.

## Recommendation

**Do not restrict the reliability index to mechanical faults.** The evidence points the other way
in every comparison run, and the two caveats above weaken the finding without reversing it.

Reweighting rather than exclusion is still defensible on cost-of-ownership grounds, since a car
that repeatedly needs tyres and bulbs genuinely does cost more to run, but nothing in this test
supports it as a *reliability* signal improvement, and it should not be presented as one.

**Fix the variant-code crosswalk instead.** That is where the measurable gain is. Bringing BMW,
Mercedes, Audi and Volvo up to the clean-name makes' level would lift band 1 from 0.52 toward 0.77
and band 2 from 0.68 toward 0.79, which is a far larger improvement than any category reweighting
produced here.

Correction to an earlier draft of this section: this is a **Norwegian-side defect only**. DVSA
carries the same fragmented strings (`3 SERIES` at 1.9M tests alongside `118` at 669k, `116` at
512k, `1 SERIES` at 379k), but `crosswalk.csv` already aggregates them correctly through the
`family_series_literal` and `family_series_sibling` rules, so Danish `1-Serie` draws on ten UK
tokens rather than one. The Norwegian crosswalk has no equivalent rule. The fix is therefore to
port existing, already-reviewed logic from `build_crosswalk_review.py` to the Norwegian side, not
to invent a new mechanism.

A secondary consequence worth recording: the site's confidence copy should reflect that
reliability figures for BMW, Mercedes, Audi and Volvo in the two youngest age bands are currently
the least supported numbers published, and that this is a known, located defect rather than
general uncertainty.

## Files

Frozen before any correlation was computed:
- `pipeline/reference/dvsa_defect_classification.csv` (260 categories: 225 mechanical, 31
  consumable, 21 administrative/other, each with a basis, classified through the DVSA item
  hierarchy rather than by leaf-name guessing)
- `pipeline/reference/norway_defect_classification.csv` (11 chapters, each with a basis)

Computed:
- `pipeline/reference/model_age_band_metrics_category_split.csv` (UK, three rates per cell)
- `pipeline/reference/model_age_band_metrics_category_split_no.csv` (Norway, three rates per cell)
- `pipeline/reference/failure_category_descriptive_split.csv` (the step 1 table)

Scripts: `pipeline/src/build_dvsa_defect_classification.py`,
`pipeline/src/build_failure_category_metrics.py`,
`pipeline/src/build_failure_category_agreement_study.py`.

## Outstanding

The all-defects recomputation gate (that the three-way rebuild reproduces the published
`standardized_pass_rate` in `model_age_band_metrics.csv` and `model_age_band_metrics_no.csv`) was
specified for this phase but is not evidenced in the artefacts left on disk. The correlations above
are computed from the rebuilt rates, so this check should be run and recorded before the
recommendation is acted on. It does not affect the direction of the result, since all three buckets
come from the same rebuild and the comparison between them is internally consistent, but it is a
required gate that has not been closed.
