# Phase 3 — Metrics specification

Written before implementation, grounded in queries against the built warehouse.
Implementation follows this document. Deviations are decisions, not details, and
should come back for review.

**Decision recorded 2026-07-31: depreciation (metric 5) is dropped for v1 --
option 3 below. No price axis, no brackets from a price dimension. Ranking
runs on annual running cost alone (reliability + repair burden + fuel +
ejerafgift). Revisit if a price source turns up later. Metrics 1, 2, 3, 4, and
6 are implemented; see `phase3_metrics_report.md` for results.**

## Verified inputs (previously assumed)

Three things Phase 1 left open are now settled by direct query, because each
feeds a metric and a wrong assumption would corrupt it silently:

| question | answer | evidence |
|---|---|---|
| Is `engine_power` kW or hp? | **kW**, confirmed | VW Up! median 44 (60 hp), Aygo 51 (68 hp), Octavia 110, BMW X5 210. All match kW exactly. |
| Is CO2 `0.0` a systemic problem? | **No**, my Phase 1 flag was overstated | Only 82 petrol and 1,164 diesel rows out of 1.78M are zero. Medians (107 petrol, 106 diesel g/km) are plausible. |
| Which weight field? | **`koereklar_vaegt_min_kg`** | 99.4% populated in scope vs `egen_vaegt_kg` at 1.8%. It is EU "mass in running order" and includes a 75 kg driver allowance, which is also the correct denominator for a power-to-weight figure. |

Power-to-weight sanity-checks correctly: 79-82 W/kg for mid-size (Octavia,
3-Series, A4), 42-45 W/kg for city cars (Up!, Citigo, Mii).

`engine_power` has a bad tail (`max = 40,000` kW). Filter to `1 < kW <= 700`
and **report the dropped count** rather than clipping silently, per the brief.

## Grain and the one structural rule

**Compute per vehicle, then aggregate. Never aggregate then compute.**

Ejerafgift and fuel cost both depend on per-vehicle attributes (registration
date, km/l) that are non-linear and regime-dependent. Averaging km/l across a
model and then applying a tax band gives a different, wrong answer versus
taxing each car and averaging the result. `dmr_vehicles_scoped` has 1.78M rows;
DuckDB does this trivially.

Output table: one row per **(model_id, age_band)**.

Age bands, from Danish registration year against the current year (2026):

| band | registration years | age |
|---|---|---|
| 1 | 2020-2022 | 4-6 |
| 2 | 2017-2019 | 7-9 |
| 3 | 2014-2016 | 10-12 |
| 4 | 2010-2013 | 13-16 |

Reliability comes from DVSA tests at the *matching age*, computed as
`test_date - first_use_date`, not from the Danish registration year.

## 1. Reliability index

Pass rate, normalised for odometer, using the Phase 1 conventions already
locked: initial tests only (`test_type = 'NT'`), `PRS` counts as a failure,
aborted results (`ABR`/`ABA`/`ABRVE`) excluded from the denominator.

**Odometer must be converted to km.** DVSA `test_mileage` is in **miles**.
Multiply by 1.609344. The brief requires metric throughout and this is the one
place a unit error would be invisible in the output.

Odometer filters, each reported as a dropped count:
- drop `test_mileage <= 0`
- drop `test_mileage_km > 1,000,000`
- drop tests where the odometer is lower than an earlier test on the same
  `vehicle_id` (clocking or mis-key)

**Normalisation method: direct standardisation over mileage strata.** Not a
regression. Chosen because it is non-parametric, assumes no functional form,
and is auditable by hand.

```
strata k: 0-50k, 50-100k, 100-150k, 150-200k, 200-250k, 250k+ km

for each (model, age_band, stratum k):
    p_k = passes / (passes + fails)        # PRS counted as fail

w_k = share of stratum k across ALL eligible tests in that age_band
      (the reference population, not the model's own distribution)

standardised_pass_rate = sum_k ( w_k * p_k )
```

This answers "what would this model's pass rate be if it were driven like the
average car of its age", which is exactly what the brief asks for.

Cell-size rule: require **>= 100 tests in a stratum** for that stratum to
contribute. If a stratum is too thin, merge it with the adjacent one and record
that it was merged. If fewer than 3 strata survive for a model, mark the model
`unstable` and exclude it from ranking rather than publishing a noisy number.

Also emit the raw (unstandardised) pass rate alongside. If the two diverge
sharply for a model, that is a finding worth surfacing on the methodology page,
not something to hide.

**Documented side effect:** diesels are driven substantially further than
petrols, so standardising by mileage also partially removes a real
petrol-vs-diesel difference within the same model. That is intended (we want
mechanical reliability, not usage intensity), but it must be stated on the
methodology page.

Failure rate by category comes from `mot_failures` joined to
`failure_categories`, restricted to the same NT tests, excluding advisories
(`rfr_type_code = 'A'`). Rate is failure items per test, per category.

Minimum for inclusion in ranking: **>= 2,000 NT tests per (model, age band)**,
the floor set in the Phase 2 strategy doc (SE < 1pp on a ~0.75 pass rate).
Models below it are excluded from ranking, not shown with wide error bars.

## 2. Repair burden index

```
burden = sum over categories c of ( failure_rate_c * make_multiplier )
```

Multiplier table is authored and committed:
`reference/parts_cost_multipliers.csv`, 28 makes, range 0.70 (Dacia) to 2.60
(Land Rover), covering **all 27 makes in the crosswalk**. The file's header
comment states the basis in full and, importantly, that it is a calibrated
judgement rather than a measurement, since no open dataset of Danish parts
prices by make exists.

**Known weakness, flagged not fixed.** The brief specifies category failure
rates times a per-make multiplier, and rules out per-model parts pricing in v1.
Implemented literally, this treats a failed headlamp bulb and a failed
suspension arm as equally burdensome, because there is no per-category cost
weight. That is a real limitation of the index and belongs on the methodology
page. A hand-authored per-category weight table (roughly 10-20 rows: brakes,
suspension, engine, electrical, body, lamps, tyres) would fix it cheaply and I
recommend it for v1.1, but adding it now exceeds what the brief specified, so
I have not.

Emit **per-category rates as well as the summed index**, so the summing choice
stays inspectable.

## 3. Fuel cost per year

```
annual_fuel_cost_dkk = (15000 / km_per_liter) * price_per_litre_dkk
```

Computed per vehicle, then take the **median** per (model, age band).

**The brief's named source `fuelprices.dk` is dead** — connection failure, and
`/api` returns 404 as of 2026-07-30. Use the brief's own fallback: Circle K
(responds 200) or OK. Fetch once per build, cache, and record the fetch date in
the output. If unreachable at build time, fall back to a committed constant
with a verification date, and make the site say which was used.

Petrol and diesel prices are needed **separately**. Note that the absolute
price level barely affects the ranking, because it scales every model's fuel
cost by the same factor. What genuinely affects ranking is the **petrol:diesel
price ratio**, so that ratio deserves the attention, not the headline price.

**NEDC vs WLTP, a real comparability problem.** Our 2010-2022 scope straddles
the WLTP transition (mandatory for new registrations from September 2018).
Older cars carry optimistic NEDC figures, newer ones realistic WLTP figures, so
a naive cross-era comparison systematically flatters older cars. Measured
medians for petrol: 21.3 km/l pre-WLTP, 23.4 km/l WLTP era. The newer cars
still look better, because genuine efficiency gains outweigh the stricter test,
which masks the bias rather than removing it.

Mitigation, already implicit in the design: **age band correlates strongly with
test regime**, so within-band comparisons are close to like-for-like. Applying
a numeric NEDC correction factor would be exactly the kind of ranking-affecting
estimate the brief says to stop and ask about, so I have not. It is documented
as a caveat instead.

**Hybrids remain unidentifiable** (Phase 1 finding, unchanged). Plug-in hybrid
type-approval km/l figures are unrealistically high because the test runs with
battery assist, and we cannot flag which rows are affected. Their fuel cost
will be understated. Methodology page must say so.

## 4. Grøn ejerafgift

**This is more complicated than the brief assumed, and getting it wrong is
invisible in the output.** There are three regimes inside our scope, not one.
Measured split of the in-scope fleet:

| regime | registration date | basis | vehicles | share |
|---|---|---|---|---|
| A | before 2017-10-03 | fuel consumption (km/l) | 1,089,124 | 61.2% |
| B | 2017-10-03 to 2021-06-30 | fuel consumption (km/l), **different rate table** | 566,757 | 31.9% |
| C | from 2021-07-01 | **CO2 emissions, not consumption** | 122,426 | 6.9% |

The data supports all three: km/l is missing on 5 of 1,655,881 consumption-regime
cars (0.00%), and CO2 is missing or zero on 1.02% of CO2-regime cars.

Structural facts that must be encoded:
- Published rates are **per half-year**. Multiply by 2 for annual cost.
- **Diesels pay a second tax**, the *udligningsafgift* (equalisation
  surcharge), on top of the consumption tax. Omitting it understates diesel
  running costs materially.
- The diesel surcharge is **reduced by 30% for 2025 and 2026**.
- Rates rise annually through 2026.
- Petrol and diesel have separate bands, and the diesel scale extends further
  (to 56.3 km/l vs 50.0 km/l for petrol).

Sonnet must **transcribe the bands from the official source, not infer them**:
- Primary: `https://info.skat.dk/data.aspx?oid=2303932` (Motorstyrelsen /
  Skattestyrelsen guidance on brændstofforbrugsafgift)
- Cross-check against `https://motorst.dk` periodic-tax pages

Commit as `reference/ejerafgift_rates.csv` with columns for regime, fuel type,
km/l (or CO2) lower and upper bound, half-year DKK, and surcharge DKK. **Every
row needs the verification date in a comment**, per the brief's explicit
warning that Danish tax law changes.

Sanity check to run after transcription: a 2018 petrol car at 19 km/l should
come to roughly **1,110 DKK per half-year** on the 2025 rates. If the
transcribed table disagrees, the transcription is wrong.

## 5. Depreciation — DROPPED FOR v1 (decided 2026-07-31)

You chose option 3 below: drop the price axis for v1, rank on annual running
cost only, revisit brackets/price later if a source turns up. Not implemented.
The analysis that led to the three options is kept as-written below for the
record.

**DMR contains no price field of any kind.** I checked the full 180-tag
vocabulary: the only value-like fields are `Nyttelastvaerdi` (payload in kg)
and `VVaerdiLuft`/`VVaerdiMekanisk` (trailer coupling ratings). Neither is a
price.

The brief's fallback is to use a published Danish depreciation curve. That
alone is insufficient: a depreciation curve gives *percentage retention over
time*, so it produces a value only when multiplied by a **new price**, which we
do not have and cannot derive from our sources.

I checked for an open source of Danish per-model new prices. Danmarks Statistik
publishes registration counts and price *indices*, not model-level prices.
Bilbasen and DBA are prohibited by the brief. There is no automated path.

This blocks more than one metric. Depreciation is normally the **largest single
line in total cost of ownership**, and Phase 4's entire price-bracket axis
depends on a price level per model. The brief anticipated exactly this: "Used
prices are the weakest input. If the depreciation model looks unreliable, say
so loudly — the entire bracket axis depends on it." Saying so loudly.

**Three options. This is your call, not mine.**

1. **You supply new prices** for the ~210 crosswalked models (one number each,
   Danish list price when new). Combined with registration year and a published
   Danish depreciation curve, this yields an estimated current value per model
   per age band. Most defensible, and the resulting number is clearly labelled
   as modelled rather than observed. Cost is roughly 210 manual entries.
2. **Model price from vehicle attributes** (power, weight, size, make tier).
   Cheap and fully automatic, but it is precisely the "estimate something that
   materially affects the ranking" the brief tells me to stop and ask about. It
   would also make the bracket axis partly circular, since engagement score uses
   the same attributes. I do not recommend it.
3. **Drop the price axis for v1.** Rank on annual running cost only
   (reliability + repair burden + fuel + ejerafgift), and ship brackets in a
   later version. Honest and fully supported by the data we have, but it changes
   the product: the brief's headline finding is "where the value curve peaks
   within a price bracket", which needs prices.

My recommendation is **option 1** if you can source the prices, **option 3** if
you cannot. Option 2 buys convenience at the cost of the finding being an
artefact of our own assumptions.

## 6. Engagement score

Explicitly computed and subjective. Must be labelled that way in the output,
per the brief.

```
power_to_weight = engine_power_kw / koereklar_vaegt_min_kg * 1000   # W/kg
```

Each component is converted to a percentile rank (0-1) across the eligible
population, then combined:

```
engagement = 0.50 * pct(power_to_weight)
           + 0.30 * pct(cylinder_count)
           + 0.20 * (1 - pct(koereklar_vaegt_min_kg))
```

Percentile ranks rather than z-scores, because the underlying distributions are
skewed and a z-score would let a handful of very powerful cars dominate the
scale. Lighter scores higher, hence the inversion on mass. Weights are a
judgement and are stated in the output so they can be argued with.

`cylinder_count` is 8.6% null in scope; leave those null and exclude them from
that component rather than imputing a value.

## Acceptance criteria mapping

- One row per (model, age band) with all six metrics: yes, subject to the
  depreciation decision above.
- Every metric has a documented formula: this document.
- Outliers investigated and explained, not silently clipped: engine power
  filter, odometer filters, and the reliability `unstable` flag all report
  counts rather than dropping quietly.

## Handover to Sonnet -- completed 2026-07-31

Settled and not re-litigated during implementation: the per-vehicle-then-
aggregate rule, the miles-to-km conversion, direct standardisation for odometer
normalisation, NT-only with PRS-as-failure, the 2,000-test floor, the weight
field choice, the engagement weights, and the parts multiplier table.

1. Transcribed the ejerafgift bands from the raw HTML of the official source
   (not an LLM summary of it -- a first-pass summary silently swapped two
   columns) into `reference/ejerafgift_rates.csv`, with verification dates and
   the 1,220 DKK sanity check. See `phase3_metrics_report.md` for the check.
2. Wired up a working fuel price fetch against Circle K's public
   `api.circlek.com/eu/prices` endpoint (found via a linked API doc PDF, not a
   scrape), with a committed fallback constant. `fetch_fuel_prices.py`.
3. Built `build_crosswalk_dvsa_match.py`, a resolver that reproduces Stage B's
   exact matching rules to turn each crosswalk row's token into the real DVSA
   (make, model) rows it covers, with a reconciliation check against
   crosswalk.csv's own recorded test counts (passed, zero mismatches across
   244 rows) -- needed because `proposed_dvsa_model_token` is a prefix/code,
   not a literal DVSA model string, in most rows.
4. Implemented metrics 1, 2, 3, 4, 6 in `build_phase3_metrics.py`. Output:
   `reference/model_age_band_metrics.csv`.
5. Left metric 5 (depreciation) unimplemented per your decision above.
