# Phase 3 — Metrics implementation report

Implements `phase3_metrics_spec.md` (Opus, formulas/tax bands/depreciation
analysis) against the built warehouse. Depreciation (metric 5) is dropped for
v1 per your 2026-07-31 decision: no price field in DMR, no open Danish
per-model price source, and estimating one from vehicle attributes was
rejected as circular with the engagement score. Ranking in Phase 4 will run
on annual running cost alone.

## What was built

| file | purpose |
|---|---|
| `reference/ejerafgift_rates.csv` | 192-row transcribed tax band table, all 3 regimes |
| `reference/fuel_prices.csv` | live-fetched petrol/diesel prices, cached with source + date |
| `reference/crosswalk_dvsa_match.csv` | resolves each crosswalk model to its real DVSA test rows |
| `reference/model_age_band_metrics.csv` | **the Phase 3 output**: 699 rows, one per (model, age band) |
| `reference/model_age_band_category_failure_rates.csv` | per-category failure rate detail behind the repair burden index |
| `reference/model_age_band_reliability_strata.csv` | per-stratum detail behind the standardized pass rate |
| `src/write_ejerafgift_rates.py`, `src/fetch_fuel_prices.py`, `src/build_crosswalk_dvsa_match.py`, `src/build_phase3_metrics.py` | the code that produced the above |

## Ejerafgift: transcribed from raw HTML, not a model summary

The first pass at this used an LLM-summarized read of `info.skat.dk`'s rate
page, which silently swapped the "Grundbeløb" and "2026-satser" columns for
one regime. Caught by re-fetching the raw HTML directly and diffing cell by
cell. `ejerafgift_rates.csv`'s numbers come from that raw parse, cross-checked
against a second, independently-fetched CO2 table whose udligningsafgift
column turned out to reuse the exact same rate ladder as the km/l table's —
a real feature of how the bands were legislated, confirmed by seeing it twice
from two different pages, not assumed.

**Sanity check**: 2018 petrol car (regime B) at 19 km/l → band "18.2 ≤ x <
20.0" → verified 1,220 DKK/half-year (2026 rate). The spec's pre-transcription
estimate guessed ~1,110 DKK on 2025 rates — about 10% off, consistent with one
more year of the law's indexation, close enough to confirm the band/regime
logic without looking suspiciously exact.

**Known gap in the source table itself, not a transcription error**: pre-2017
diesel (regime A) has no published rate above 25.0 km/l — the government's own
table prints "–" there. Floored to the lowest published band (460 DKK/half
year); affects a small number of vehicles (diesel engines rarely exceeded 20
km/l on pre-2018 test cycles). Documented in the script's docstring with the
exact source URLs and fetch date (2026-07-31).

## Fuel prices: live API, not a scrape

`fuelprices.dk` is confirmed dead. Found a genuine public JSON API for Circle
K (`api.circlek.com/eu/prices`, documented in a linked PDF on their own site,
no key required) returning live prices for 403 Danish stations. Used the
median of each fuel's *base* grade (excluding premium "miles+"/"upgrade"
variants) — petrol 16.69 DKK/l, diesel 17.49 DKK/l as of 2026-07-31, 09:59
UTC. Falls back to a committed constant (same numbers) if the live call fails
at build time; the output CSV records which source was actually used.

## Crosswalk → DVSA resolution, with a built-in correctness check

`proposed_dvsa_model_token` in crosswalk.csv is a prefix, a numeric code, or a
literal family-series string depending on which Phase 2 rule matched it — not
a literal DVSA model string in most rows. `build_crosswalk_dvsa_match.py`
re-runs the exact same classification rules Phase 2 used to resolve each
token back to real `(make, model)` rows in `mot_tests`, then **recomputes each
row's test count and diffs it against crosswalk.csv's own recorded
`uk_test_count`**. Passed with zero mismatches across all 244 confirmed rows —
proof the join Phase 3 uses is counting exactly what Phase 2 counted, not a
close approximation of it.

## Two real bugs found and fixed during implementation

Neither was cosmetic; both would have shipped visibly wrong numbers.

1. **Reliability/repair-burden join fan-out.** A DVSA test can legitimately
   belong to more than one DMR model (BMW's generic "3-Serie" and its "320"/
   "330" sibling rows deliberately share UK ground truth — that's by Phase 2's
   design, not a bug). The first implementation joined this model-attribution
   *before* computing the odometer-clocking window function, then joined the
   (now duplicated) result again — the two joins compounded, and the
   "eligible after filters" count came out to 148M against ~75M rows *before*
   filtering, which is what caught it. Fixed by filtering on a deduplicated
   physical-test table first and attributing to models only as the last step.
2. **Repair burden silently dropped Citroën.** `parts_cost_multipliers.csv`
   is hand-authored in plain ASCII (`CITROEN`); DMR's raw make name carries
   the diaeresis (`CITROËN`). A literal join matched every make except that
   one, silently. Caught because the build log named the exact make it
   couldn't price. Fixed by matching on a diacritics-stripped key.

## Dropped-count reporting (per the brief: investigate outliers, don't clip silently)

DMR side, 1,597,916 vehicles across the 210 crosswalk-covered models:
- engine_power outside (1, 700] kW, excluded from power-to-weight only: 27
- fuel_type_primary not Benzin/Diesel (N-Gas/Brint/F-Gas), excluded from fuel cost and ejerafgift: 56
- Benzin/Diesel vehicles with no ejerafgift band match (missing km/l or CO2 for their regime): 45

DVSA side, 48,626,203 physical NT tests in covered models (74.9M model-
attributed rows before the intentional multi-model fan-out):
- mileage ≤ 0: 305,749
- mileage > 1,000,000 km after miles→km conversion: 695
- unusable first_use_date (before 1990 or after the test date — a real DMR-side data quality issue, ~0.04% of tests): 19,573
- aborted results (ABR/ABA/ABRVE): 267,696
- odometer clocking (mileage below an earlier test for the same vehicle): 228,308
- **eligible after all filters: 48,220,796 physical tests**

## Output shape and stability floors

699 (model, age_band) cells across all 210 crosswalk models (max possible 840;
not every model has vehicles in every age band). 633 cells clear both the
2,000-test ranking floor and the ≥3-surviving-mileage-strata stability check
and are usable for Phase 4 ranking; 66 are flagged `reliability_unstable` and
should be shown, if at all, without a ranked position. Standardized pass rate
across ranking-eligible cells ranges 43.7%–89.8%, which is a wide enough
spread to be worth ranking on — not so wide that outliers look like data
errors on inspection.

Fuel cost, ejerafgift, and engagement score are populated for all 699 rows
(vehicle-level nulls were near-zero, per the drop counts above). Reliability
fields are null only where the data genuinely doesn't support a number: 14
rows have no raw pass rate at all (zero eligible tests after filtering), 49
have no standardized rate (fewer than 3 surviving mileage strata), 22 have no
repair burden figure for the same reason.

Spot-checked Toyota Aygo (city car, low power) and BMW 3-Serie (large
multi-attributed model) by hand: pass rates decline plausibly with age,
repair burden rises with age, fuel cost and W/kg land in sane physical ranges,
and the BMW family aggregation (140k–190k tests per cell) shows the
multi-model fan-out is pulling real volume, not noise.

## Minor known nondeterminism, not investigated further

The clocking filter's count varied by ~185 tests (0.0004%) between two runs
on identical input, from DuckDB's window function tie-breaking on same-date
tests with no secondary sort key. Immaterial at this scale; noted rather than
silently ignored.

## Acceptance criteria

- One row per (model, age band), five of six metrics populated: **yes**, depreciation excluded by decision, not by gap.
- Every metric has a documented formula: **yes**, `phase3_metrics_spec.md`.
- Outliers investigated and explained, not silently clipped: **yes**, every filter above is a reported count, not a silent drop.
