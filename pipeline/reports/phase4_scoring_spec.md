# Phase 4: brackets, cost-of-ownership scoring, and tier assignment

Written before implementation, grounded in queries against the actual CSVs.
Implementation follows this document. Deviations are decisions, not details,
and should come back for review.

Phase 3 shipped without a price axis. That is now reversed:
`price_estimates_calibrated.csv` supplies a Danish-taxed value per (model,
age_band), which makes a real total-cost-of-ownership calculation possible for
the first time. This document specifies that calculation, the bracket
boundaries, and the output table Phase 5 renders.

**Six decisions are flagged as yours, not mine, and marked `DECISION`. They all
move the ranking. Nothing below silently resolves them.**

## 0. Join verification, done first

The 796-vs-699 gap is **fully explained and is not a join problem.** Outer join
on `(dmr_make, dmr_model, age_band)`:

| | rows | meaning |
|---|---|---|
| both | **668** | usable cells with price and running-cost data |
| metrics only | 31 | Suzuki (29) and DS (2). No Poland brand mapping. |
| price only | 128 | 83 models, in age bands where **Denmark has no vehicles** |

The shapes differ by construction, not by key mismatch. The price file is
**199 models x 4 bands = 796 exactly**: every model gets all four bands whether
or not such a car exists. `model_age_band_metrics.csv` is 210 models with
variable coverage (119 have 4 bands, 50 have 3, 32 have 2, 9 have 1), because a
cell exists only where DMR holds vehicles. 210 - 199 = 11 is the Suzuki and DS
families. Zero make-name mismatches: `CITROËN` with diaeresis joins cleanly on
both sides, so the Phase 3 diacritics bug did not recur.

**The 128 price-only rows are the important finding, and they are dangerous.**
They price cars that do not exist at that age. Verified: Ford Puma has rows for
bands 2 to 4 (2010-2019 registrations) though the model launched in 2019;
Skoda Karoq has band 3 and 4 rows for a 2017 model; Chevrolet Aveo and Spark
have band 1 rows for a brand that left Europe in 2015.

> **Rule 0, structural, not a decision.** Both the entry price and the resale
> price must come from a `(model, age_band)` cell that **also exists in
> `model_age_band_metrics.csv`**. An inner join at both ends of the hold. As
> section 1.3 shows, this rule alone removes most depreciation artefacts.

After Rule 0 and Phase 3's stability flag: 668 joined cells, **611
ranking-eligible** (57 carry `reliability_unstable`). Phase 3's 633 becomes 611
because the 22 lost are Suzuki and DS cells.

## 1. Cost of ownership

### 1.1 What the data can actually answer

The user asked for cost over "5, 10, 20 years". The data does not reach that
far, and pretending otherwise would be this phase's biggest available honesty
failure. Depreciation here is **observed between two real data points**, not
modelled from a curve. That is a genuine strength and a hard constraint: the
only holding periods that exist are the gaps between age bands.

| entry | exit | hold | models with both cells present |
|---|---|---|---|
| 1 (age 5) | 2 (age 8) | 3.0 yr | 154 |
| 2 (age 8) | 3 (age 11) | 3.0 yr | 163 |
| 3 (age 11) | 4 (age 14.5) | 3.5 yr | 150 |
| 1 | 3 | 6.0 yr | 137 |
| 2 | 4 | 6.5 yr | 141 |
| 1 | 4 | **9.5 yr** | 118 |

**9.5 years is the maximum observable hold.** A 20-year horizon needs a resale
value at age 25, outside both the Danish scope (2010-2022 registrations) and
the Poland source. There is no honest way to produce it.

> ### DECISION 1: what horizon does the site publish?
>
> 1. **The three real spans (3 / 6 / 9.5 yr), labelled honestly**, with copy
>    saying "hold for about 3, 6 or 9 years" rather than 5/10/20. Every number
>    observed. **Recommended.**
> 2. **5 and 10 years, interpolated** between band anchors per model. Closer to
>    the user's words, but the headline number stops being observed and becomes
>    modelled, which is exactly the trade Phase 3 refused. 20 years stays
>    impossible either way.
> 3. **One horizon only.** I would pick 6 years: close to a real Danish
>    ownership period, and the span least damaged by the artefacts in 1.3.
>    Simplest tier list, least to explain, least flexible.
>
> Recommend **option 1**, with option 3 as fallback if three horizons makes the
> site read as a spreadsheet. The user asked for "just the tier list", which
> argues for fewer horizons.

### 1.2 The formula

Per (model, entry_band, exit_band), all terms in DKK over the whole hold:

```
hold_years   = age(exit_band) - age(entry_band)

entry_price  = calibrated value at (model, entry_band)
resale_price = calibrated value at (model, exit_band) * mileage_adjustment
depreciation = entry_price - resale_price

fuel_total   = hold_years * median_annual_fuel_cost_dkk     (entry band)
tax_total    = hold_years * median_annual_ejerafgift_dkk    (entry band)
repair_total = hold_years * repair_burden_index * REPAIR_DKK_PER_BURDEN_UNIT

tco_total    = depreciation + fuel_total + tax_total + repair_total
tco_per_year = tco_total / hold_years
```

Running-cost terms come from the **entry** band and stay flat across the hold.
That understates the true figure slightly, since a car ages into a worse band
while owned, but blending bands mixes a measured quantity with an assumption
and the ordinal effect is small. State it on the methodology page. Emit **every
term separately**, never just the total, so the site can show the stacked
breakdown and a reader can reject one component without discarding the ranking.

Scale check on real medians, band 2 to 3, three-year hold, 163 usable models:
median depreciation 37,123 DKK, median fuel plus ejerafgift 42,353 DKK.
**Depreciation is 47.7% of TCO before any repair term.** It is the largest line
for young cars (median 17,204 DKK/yr, band 1 to 2) and much smaller for old
ones (6,256 DKK/yr, band 3 to 4). That asymmetry is the finding the site exists
to show, and it falls out of the formula without being engineered in.

### 1.3 The depreciation term has three real defects, all quantified

**(a) Clamped curves produce zero depreciation.** The price build interpolates
but never extrapolates, so where Poland listings do not reach an age band the
curve flatlines. Across the 199 priced models: 12 have `b1 == b2`, 11 have
`b2 == b3`, 23 have `b3 == b4`. 46 flat consecutive pairs, in models holding
151,867 vehicles (10.0% of the joined fleet).

Not cosmetic. In a trial ranking of band-2 entries by three-year TCO, **Skoda
Karoq took first place in the 150k-250k bracket on a depreciation of exactly
0 DKK**, and Mazda CX-3 took third on 981 DKK. Both artefacts. **Rule 0 removes
them**: Karoq's band-3 price is a phantom, so requiring the exit cell to exist
in the metrics file deletes the row and the false first place with it. Same for
Ford Puma and Skoda Kamiq's deeper bands.

**(b) Eleven models gain value with age.** After Rule 0 the residual damage is
small enough to enumerate completely: **14 (entry, exit) pairs have zero or
negative depreciation**, 12 of them band 1 to band 2.

```
ALFA ROMEO GIULIETTA 1->2 ( 92,579 ->  92,579)  KIA Optima   1->2 (108,055 -> 111,404)
AUDI A3              1->2 (121,977 -> 123,893)  KIA VENGA    1->2 ( 83,058 ->  83,491)
AUDI A3 CABRIOLET    1->2 (138,181 -> 138,181)  MAZDA 2      1->2 (111,513 -> 117,913)
AUDI A3 Limousine    1->2 (134,014 -> 134,014)  OPEL KARL    2->3 ( 38,864 ->  41,757)
AUDI A3 Sportback    1->2 (134,848 -> 134,848)  SKODA KAMIQ  1->2 (210,138 -> 213,776)
DACIA Logan MCV      1->2 ( 39,310 ->  39,310)  VW CALIFORNIA 3->4 (572,375 -> 572,375)
FORD S-MAX           1->2 (132,593 -> 140,484)  HONDA JAZZ   1->2 (106,681 -> 107,142)
```

Opel Karl also topped the sub-50k bracket in the trial, on a depreciation of
**-2,893 DKK**, i.e. scored as appreciating.

> ### DECISION 2: what to do with the 14 broken pairs
>
> 1. **Suppress the pair.** No TCO row for that (model, entry, exit); the model
>    still appears at other horizons. Costs 14 of 863 possible pairs. No
>    published rank is then built on a zero. **Recommended.**
> 2. **Floor depreciation at a fleet-wide median retention ratio** (measured:
>    0.697 per 3-yr step from band 1, 0.684 from band 2, 0.664 per 3.5-yr step
>    from band 3). Keeps coverage, but substitutes a modelled number into the
>    one term the design claims is observed.
> 3. **Publish with a "depreciation not measurable" badge and no rank**,
>    matching Phase 3's treatment of `reliability_unstable`.
>
> Either way the affected pairs need a boolean in the output. Options 1 and 3
> barely dent coverage, because the damage concentrates in band 1 to band 2,
> which the six-year horizons avoid entirely: band 1 to 3, band 1 to 4 and band
> 2 to 4 each have **zero** broken pairs after Rule 0.

**(c) The mileage adjustment is larger than it looks, and is inconsistent.**
`estimated_value_dkk` is the price at that band's reference mileage. A car
bought in band 2 and sold in band 3 has driven three more years, so resale must
be adjusted to the mileage it actually reaches, not read off the band-3
reference. At Phase 3's 15,000 km/yr and the committed 3.91%/10,000 km slope:

| hold | km at exit | exit reference | resale factor |
|---|---|---|---|
| b1 -> b2 | 150,250 | 143,000 | x0.972 |
| b2 -> b3 | 188,000 | 135,750 | **x0.796** |
| b3 -> b4 | 188,250 | 207,833 | **x1.077** |
| b1 -> b3 | 195,250 | 135,750 | x0.767 |
| b2 -> b4 | 240,500 | 207,833 | x0.872 |
| b1 -> b4 | 247,750 | 207,833 | x0.844 |

A 20% resale haircut is roughly half the median three-year depreciation. This
term is not a rounding detail; omitting it would materially change the ranking.
Two problems are visible in that table:

- **The reference mileage table is not monotonic.** Band 2 is 143,000 km but
  band 3 is 135,750 km, so the reference car drives backwards between age 8 and
  11. It rests on 2, 7, 2 and 3 source models respectively. It produces the
  nonsensical **x1.077**, a car gaining 7.7% of value by being driven three and
  a half more years.
- **The linear form breaks at high mileage.** `1 - 0.0391 * delta / 10000`
  crosses zero at delta = 255,754 km and goes negative beyond. The slope was
  fitted in log space then applied linearly; the two agree at 10,000 km (0.961
  vs 0.961) and diverge badly at 100,000 km (0.671 vs 0.609).

Both fixes are strictly more correct than the status quo, so I do not think
this needs a decision: **apply the slope multiplicatively**,
`(1 - 0.0391) ^ (delta / 10000)`, which cannot go negative, and **enforce
monotonic reference mileage** from the implied annual rate (see 4.6). If you
prefer to leave the committed formula untouched, clamp the factor to
`[0.15, 1.0]` and say so, but b3 -> b4 will still read as appreciation.

### 1.4 The repair term has no data anchor

`repair_burden_index` is dimensionless. Over the 649 joined cells that have
one: min 0.15, median 0.76, max 4.32. Converting it to kroner needs a constant
that exists nowhere in our sources. At an illustrative 3,000 DKK/yr per burden
unit, three-year repair cost across band-2 models spans 1,991 to 12,234 DKK
(median 5,507), about 6.9% of median TCO. At 10,000 DKK/yr it would be ~23% and
would start reordering brackets.

> ### DECISION 3: how repair cost enters the TCO
>
> 1. **Pick one constant, state it prominently, ship a sensitivity note.** I
>    would use **3,000 DKK per burden unit per year**, putting a median car near
>    2,300 DKK/yr of repairs: low, but defensible for a metric counting MOT
>    failure items rather than all workshop visits. Publish the ranking at 1,500
>    and 6,000 too and report how many tiers move. **Recommended.**
> 2. **Leave repair out of the total**, showing the index as a separate ordinal
>    column. Zero invented parameters, but it drops the axis that most
>    distinguishes a cheap car that stays cheap from one that does not.
> 3. **Rank on TCO, then break ties and adjust tiers by burden.** Hybrid, harder
>    to explain.
>
> Whatever the constant, it belongs in a committed reference file with a header
> comment stating it is a judgement, exactly as `parts_cost_multipliers.csv`
> does. It must not be a literal in the script.

Phase 3's known weakness carries forward: the index has no per-category cost
weight, so a failed bulb and a failed suspension arm count alike. That caps how
much load this term should bear, itself an argument for the lower constant.

### 1.5 Engagement score: recommend keeping it out of the ranking

Phase 3 computed `engagement_score` and explicitly labelled it subjective and
not a cost. Folding it into "best value" would change what the ranking means,
and the measured relationship is not neutral. Within band 2, Spearman
correlation between cost rank and engagement rank is **-0.527**; engagement
correlates +0.431 with annual fuel cost and +0.332 with ejerafgift. Engaging
cars are heavier, more powerful, thirstier and taxed harder. **Any positive
weight on engagement directly fights the cost ranking**, and at a high enough
weight the "best value car" becomes the most expensive one to run.

> ### DECISION 4: does engagement affect rank?
>
> 1. **No. Rank on cost alone; carry engagement as a labelled sort-by column and
>    show it on the model page.** The tier list answers the question actually
>    asked, and the subjective axis stays visible without contaminating it.
>    **Recommended.**
> 2. **Yes, at a small fixed weight** (a 5-10% nudge), disclosed. Prevents the
>    list being a wall of city cars, at the cost of the headline no longer being
>    a pure cost ranking.
> 3. **Two toggleable orderings**, "cheapest to own" and "most car for the
>    money". Most faithful to both, most work for Phase 5.
>
> Under 2 or 3, engagement must be min-max scaled and the weight must appear in
> the output row, not only in the code.

### 1.6 Tiers

The brief calls for S/A/B/C/D and states output is **ordinal**, so the boundary
rule matters more than the kroner. Assign **within each bracket**, on
`tco_per_year` ascending, by quantile: S = best 10%, A = next 20%, B = next 40%,
C = next 20%, D = worst 10%. Quantiles rather than absolute cutoffs, because
bracket TCO levels differ by roughly 3x from bottom to top and a 40-member
bracket should still have an S tier.

Ranking within a bracket also sidesteps a confound that would wreck a global
ranking: **price correlates +0.62 with standardized pass rate**, and still +0.44
to +0.54 within each individual age band. Expensive cars really do fail MOT
less, so a single global "best value" list would just be an expensive-car list.

The brief's headline finding, the bracket where cost-per-utility is minimised,
falls out as the bracket with the lowest median `tco_per_year` among its S and
A tier members. Compute it, do not hand-pick it.

## 2. Price brackets

### 2.1 What "budget X" refers to, which must be decided before boundaries

One model spans four very different prices: band 1 to band 4 ratio has **median
3.25x, p90 4.80x, max 9.42x**.

| model | band 1 | band 2 | band 3 | band 4 |
|---|---|---|---|---|
| Toyota Aygo | 74,294 | 61,449 | 42,932 | 26,420 |
| VW Golf | 180,592 | 121,724 | 77,740 | 49,809 |
| Skoda Octavia | 237,991 | 145,456 | 86,522 | 56,081 |
| BMW 3-Serie | 519,588 | 312,454 | 193,778 | 108,281 |

"My budget is 60,000 DKK" therefore does not identify a car, it identifies a
(model, age_band) pair. A 60k buyer can have a 14-year-old Octavia or a
5-year-old Aygo, and those have completely different ownership costs.

> ### DECISION 5: what is the unit of the tier list?
>
> 1. **A (model, age_band) cell, bracketed on that cell's price.** A model can
>    appear in several brackets at different ages, which is truthful and is
>    exactly the comparison needed ("for 60k, this old big car or this newer
>    small one"). 611 eligible rows across five brackets. **Recommended.**
> 2. **A model, priced at one canonical age band.** Cleaner list, but it either
>    discards three quarters of the price data or forces an arbitrary canonical
>    age.
> 3. **A (model, age_band, horizon) triple.** Most complete, but with three
>    horizons the table triples and it stops reading as a tier list.
>
> Recommend **option 1**, with horizon as a page-level selector rather than a
> row dimension: one row per card, and Phase 5 can still re-sort. Site copy must
> then say "budget X buys you *this model at this age*", which is a better
> answer than was asked for.

### 2.2 Boundaries, derived from the real distribution

The brief specifies five brackets from data. Over the 611 eligible cells: min
21,639, q25 60,216, median 106,615, q75 170,107, max 938,220. The histogram is
dense and unimodal from 25k to 175k, thins sharply above 300k, and has a
secondary lump at 500k-575k (premium SUVs and the VW California). The largest
natural gap anywhere is **57,172 DKK between 447,097 and 504,269**, the only
boundary the data hands us for free.

Recommended boundaries: round, near fleet-weighted quantiles, every bracket
populated in more than one age band.

| bracket | range (DKK) | eligible cells | distinct models |
|---|---|---|---|
| 1 | up to 50,000 | 94 | 67 |
| 2 | 50,000 to 90,000 | 170 | 120 |
| 3 | 90,000 to 150,000 | 149 | 120 |
| 4 | 150,000 to 250,000 | 123 | 103 |
| 5 | above 250,000 | 75 | 49 |

50k, 90k and 150k sit near the fleet-weighted 30th, 60th and 78th percentiles
(50,416 / 87,817 / ~150,000), so each bracket holds a comparable slice of the
cars Danes actually own, not of model names. Equal-count quintiles of the
eligible cells (56,081 / 84,187 / 127,431 / 201,657) are the alternative if you
want exactly 122 members each; less memorable, no better justified.

Two things to state on the site:

- **Brackets are strongly age-stratified.** Bracket 1 is 61 of 94 cells in band
  4; bracket 5 is 49 of 75 in band 1. Cheap means old, almost tautologically. A
  real market fact, not an artefact, but "best value under 50,000 DKK" is mostly
  a question about 13-to-16-year-old cars.
- **Bracket 4 has no band-4 cells and bracket 5 has one band-3 cell.** No
  14-year-old car is worth 150,000 DKK, so the 9.5-year horizon is unavailable
  for most of bracket 5: the exit cell does not exist. Horizons must be computed
  per row, never assumed uniform.

The user's own 30k / 60k / 100k figures were checked and are not recommended: a
30,000 DKK cap leaves only **13 eligible cells across 10 models**, too thin to
tier. 50,000 is the lowest cutoff yielding a populated bottom bracket.

## 3. Output schema

One row per **(dmr_make, dmr_model, age_band)** per DECISION 5 option 1, with
one set of TCO columns per published horizon. Write
`reference/model_bracket_rankings.csv`. Phase 5 consumes this and nothing else
for the ranked pages.

**Identity and bracket:** `dmr_make`, `dmr_model`, `age_band`, `band_years`
(display string), `approx_age_years`, `price_bracket_id`, `price_bracket_label`,
`entry_price_dkk`, `entry_price_reference_km`.

**Per horizon H, suffixed `_h3` / `_h6` / `_h9`:** `exit_age_band`,
`hold_years`, `resale_price_dkk`, `mileage_adjustment_factor`,
`depreciation_dkk`, `fuel_total_dkk`, `ejerafgift_total_dkk`,
`repair_total_dkk`, `tco_total_dkk`, `tco_per_year`, `rank_in_bracket`, `tier`,
`depreciation_unmeasurable` (the DECISION 2 flag), `horizon_available` (false
where the exit cell does not exist, e.g. most of bracket 5 at 9.5 yr).

**Phase 3 metrics passed through unchanged:** `standardized_pass_rate`,
`raw_pass_rate`, `repair_burden_index`, `median_annual_fuel_cost_dkk`,
`median_annual_ejerafgift_dkk`, `engagement_score`, `reliability_unstable`,
`meets_stability_floor`.

**Confidence and provenance, so the site can be honest per row:**
`dk_vehicle_count`, `n_nt_tests`, `price_n_listings`, `price_pooled_at_brand`,
`price_calibration_factor`, `price_confidence`, `excluded_from_rank`,
`exclusion_reason`.

`price_confidence` is a three-level flag Sonnet derives, not a new estimate:
**low** if `pooled_at_brand` or `n_listings < 30` (44 rows), **medium** if
`n_listings < 100` (168 rows), else **high**. This matters because the worst
calibration residual in the whole exercise (Citroën C1, 94.9%) is a
`pooled_at_brand` row, and pooling is the likeliest explanation: the C1 is a
cheap city car inheriting Citroën's brand-average curve. 164 rows across 41
models are pooled.

**Methodology narrative counts** go to a separate one-row-per-fact file,
`reference/methodology_counts.csv`, so the "we imported X and compared it
against Y" page is generated rather than hand-written. Minimum contents, all
already established: 1,597,916 Danish vehicles in scope; 48,220,796 eligible
DVSA tests after filters, from 48,626,203 physical NT tests; 210 crosswalked
models covering 89.5% of the Danish fleet by count; 699 model/age cells, 668
priced, 611 ranked; 796 price estimates from 27 real Danish listings; and every
drop count from the Phase 3 report. Each row needs a source file and a date, so
the page cannot drift out of sync with the data.

## 4. Caveats carried forward. None are fixed by this phase.

**4.1 Calibration is in-sample only.** The median 10.1% / max 94.9% residual
measures how well the correction fits the 27 anchors it was fitted to. It is
**not** held-out accuracy and must not be described as validated accuracy. 27
anchors calibrate 796 estimates. "Calibrated against real Danish listings" is
fair; "accurate to within 10%" is not.

**4.2 The calibration split is discontinuous at 150,000 DKK.** Two factors are
baked in (0.6677 below, 0.7098 at or above), applied to the *raw* estimate. A
raw estimate of 149,999 lands at 100,154 DKK and 150,001 lands at 106,471: **a
6,315 DKK jump for a 2 DKK difference in input**. No calibrated value exists
between 100,061 and 106,615, a visible hole in the distribution. 72 rows sit
within 10,000 DKK of the split. Bracket 3 begins at 90,000 so nothing straddles
a boundary today, but it will if boundaries move. List it as a known artefact.

**4.3 Suzuki and DS have no price data at all.** 11 models, 31 cells, 82,439
vehicles, **5.16% of the covered fleet**, including Swift (22,549), Vitara
(9,524) and SX4 S-Cross (8,987). Ordinary Danish cars, not exotica, so a Danish
reader will notice the hole.

> ### DECISION 6: how to handle Suzuki and DS
>
> 1. **Exclude from bracket ranking, publish their model pages** with
>    running-cost and reliability metrics and an explicit "no price estimate, so
>    no value ranking" note. Nothing invented, gap visible. **Recommended
>    fallback.**
> 2. **Omit entirely.** Cleaner, but 5% of the fleet silently vanishes and a
>    reader searching for a Swift finds nothing and no explanation.
> 3. **Source ~11 more manual price anchors** and extend the calibration, the
>    same way the 27 existing anchors were collected. The only option that
>    actually fixes it. Costs about an hour of manual collection, and is worth
>    considering before shipping.

**4.4 The mileage slope is a single global constant.** 3.91% per 10,000 km,
median of per-model slopes from the anchor set, applied identically to a 26,000
DKK Aygo and a 938,000 DKK California. In reality high-value cars lose more
absolute value per kilometre and cheap old cars approach a scrap floor where
mileage stops mattering. Not price-tiered because there are not enough anchors
to tier it. Flag on the methodology page; do not silently tier it.

**4.5 Poland stands in for intrinsic value.** The whole price chain rests on
Poland's used market approximating tax-free value, plus Denmark's 2026
registration tax formula, plus a 2023 snapshot representing 2026 prices, with
the tax applied unscaled where the law technically wants a scaled value.
Documented in `build_price_estimates.py`, and the reason the calibration step
exists at all.

**4.6 The 15,000 km/yr assumption disagrees with the price anchors.** Phase 3's
fuel cost uses 15,000 km/yr. The reference mileages imply 21,050 (band 1),
17,875 (band 2), 12,341 (band 3) and 14,333 km/yr (band 4). Both cannot be
right, and the disagreement is largest where TCO is largest. Recommend keeping
15,000 for fuel, since changing it rescales every model identically and does not
move the ordinal ranking, but using it consistently in the mileage adjustment
too, and stating the tension. Band 3 at 12,341 km/yr is the clearest sign the
reference table is undersupported.

**4.7 NEDC vs WLTP, unchanged from Phase 3.** Fuel figures straddle the
September 2018 transition and older cars carry optimistic NEDC numbers.
Mitigated only because age band correlates with test regime, so within-band
comparison is close to like-for-like. No numeric correction applied, by Phase
3's decision. Because brackets are strongly age-stratified (2.2), most
comparisons the site shows are within-band, which helps.

**4.8 Hybrids remain unidentifiable, unchanged from Phase 3.** Plug-in hybrid
type-approval km/l is unrealistically high and we cannot flag affected rows, so
their fuel cost and therefore their TCO is understated. Kia Niro appears in the
trial band-2 ranking at 21,080 DKK of three-year fuel and tax, lowest in its
bracket, very likely this effect surfacing in the output.

**4.9 The UK-market reliability caveat** (DVSA tests standing in for Danish
mechanical condition) and **the repair index's missing per-category cost
weights** carry forward unchanged and belong on the methodology page.

## Acceptance criteria mapping

- Bracket boundaries justified from data: section 2.2, from the measured
  distribution and fleet-weighted quantiles, with rejected alternatives and the
  reason the user's 30k figure fails.
- Tier assignments reproducible from a single script: one script reading
  `price_estimates_calibrated.csv`, `model_age_band_metrics.csv` and
  `typical_mileage_by_age_band.csv`, writing `model_bracket_rankings.csv` and
  `methodology_counts.csv`. No manual steps, no hand edits.
- Passes a sanity check against your intuition: the trial ranking in 1.3 already
  failed this twice (Karoq, Karl), which is why Rule 0 and DECISION 2 exist.
  Re-run the check on the top five of every bracket at every horizon before
  Phase 5 starts.

## Open decisions, for the record

| # | question | recommendation |
|---|---|---|
| 1 | Horizon: 3/6/9.5 real, or 5/10 interpolated? | 3/6/9.5, labelled honestly |
| 2 | 14 zero-or-negative depreciation pairs | suppress the pair, flag it |
| 3 | DKK per repair burden unit | 3,000 DKK/yr, plus sensitivity table |
| 4 | Does engagement affect rank? | no, carry as a labelled column |
| 5 | Row unit: (model, age_band) or model? | (model, age_band) |
| 6 | Suzuki and DS | collect ~11 more anchors, else publish unranked |
