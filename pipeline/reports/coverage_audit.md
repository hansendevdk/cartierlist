# Coverage audit: are cars missing from the rankings?

Status: complete. Report only. No metric, ranking, reference CSV, crosswalk row, or site page
changed by this audit.

Triggered by an external review (Gemini) that read the site and reported roughly a dozen models
as absent from the dataset. Every one of those specific claims is wrong. The audit did find four
genuine coverage defects, listed in "Real findings" below, none of which the external review
identified.

## Method

Traced the model universe through every stage of the pipeline and diffed the survivors at each
step:

1. `top_models_by_name` in `data/warehouse.duckdb` (the in-scope Danish fleet, 1,778,307 vehicles)
2. `pipeline/reference/crosswalk.csv` (245 confirmed DMR to DVSA mappings)
3. `pipeline/reference/model_age_band_metrics.csv` (684 model/age-band cells)
4. `pipeline/reference/model_bracket_rankings.csv` (667 ranked rows)
5. What the site actually renders (`site/src/lib/data.ts`, `brackets/[id].astro`,
   `running-costs.astro`)

Plus three targeted checks: duplicate model identities sharing one UK test pool, ranked rows
backed by a negligible Danish fleet, and crosswalk matches pointing at the wrong UK car.

## The external review's claims

The reviewer was reading **one page**: `/brackets/1/`, the "Up to 50,000 DKK" bracket, "Cheapest
to own" list, 84 cars. Its rank numbers line up exactly with that list (rank 25 Toyota Yaris at
16,935 kr/year, rank 31 Suzuki Swift at 17,301, rank 45 Hyundai i20 at 18,494, rank 53 Honda
Jazz, rank 63 VW Polo, rank 79 Mazda 3). It then treated "not in this price bracket" as "not in
the dataset".

Every model it named is present. It is one bracket up, because a 2014-2016 car costs more than
50,000 kr:

| Claimed missing | Actually at |
|---|---|
| Hyundai i20 2014-2016 (gen 2) | bracket 2, rank 57, 20,139 kr/year, 9,154 DK cars |
| Toyota Yaris 2014-2016 | bracket 2, rank 22, 18,567 kr/year |
| Kia Rio 2014-2016 | bracket 2, rank 25, 18,740 kr/year |
| Suzuki Swift 2014-2016 | bracket 2, rank 19, 18,436 kr/year |
| Opel Corsa 2014-2016 | bracket 2, rank 92, 21,700 kr/year |
| Honda Jazz 2014-2016 | bracket 2, rank 142, 25,471 kr/year |
| VW Polo 2014-2016 | bracket 2, rank 76, 20,953 kr/year |
| Renault Clio petrol 2017-2019 | bracket 3, rank 55 (as "Ny Clio") |
| Mazda 2 | ranked at all four age bands, twice over (see finding 1) |
| Mitsubishi Space Star | in the data, excluded from ranking (see finding 2) |

Two further points in that review are factually wrong about this project and worth recording so
they do not get repeated:

- It attributes the gap to "listing scrapers" and "exact string matching against the
  Motorregistret". Nothing here is scraped, by design (`PROJECT_BRIEF.md`), and the DMR extract is
  parsed from XML, not string-matched.
- It claims the Mazda 2 fell below a minimum-listings threshold. The only volume threshold in the
  pipeline is `RANKING_FLOOR_TESTS = 2000` UK MOT tests
  (`pipeline/src/build_phase3_metrics.py:61`). The Mazda 2 clears it with 313,689.

Its instinct on `Mazda2` vs `Mazda 2` was half-right, but backwards: both strings exist in DMR and
**both are in the rankings as separate cars**, which is the actual bug (finding 1).

## Real findings

### 1. The same car is ranked twice under two DMR spellings

DMR carries multiple spellings for one model. The existing merge pass
(`pipeline/src/fix_case_duplicate_models.py`) only groups rows whose model strings match after
stripping non-alphanumerics, so `MAZDA2` and `2` never land in the same group and are never
compared.

Detection used here is stronger and does not depend on the strings: a pair is the same car if
every DVSA-derived field is identical at every shared age band, which can only happen if both
resolved to the same UK test pool. Confirmed pairs the current merge misses:

| Make | Split across | Bands affected |
|---|---|---|
| MAZDA | `2`, `MAZDA2` | 4 |
| MAZDA | `3`, `MAZDA3` | 4 |
| MERCEDES-BENZ | `C`, `C-Klasse` | 4 |
| MERCEDES-BENZ | `E`, `E-Klasse` | 4 |
| RENAULT | `CLIO`, `Ny Clio` | 4 |
| TOYOTA | `AYGO`, `AYGO 3/5-DØRS`, `AYGO 5-DØRS` | 3 |
| TOYOTA | `YARIS`, `YARIS 5-DØRS` | 3 |
| FORD | `FIESTA`, `FIESTA 5 DØRS` | 3 |
| FORD | `FOCUS`, `NY Focus` | 1 |
| HYUNDAI | `I10`, `i10 AC3` | 1 |
| HYUNDAI | `I30`, `I30CW`, `i30 Stc.` | 2 |
| KIA | `CEED`, `CEE'D SW`, `CEED SW` | 2 |
| NISSAN | `QASHQAI`, `Qashqai J11A` | 2 |
| SEAT | `IBIZA`, `Ibiza GP2` | 2 |
| SUZUKI | `SX4`, `SX4 COMBIBACK` | 1 |

Consequence, same as the bug that merge pass was written to fix: fleet counts and every
DMR-derived attribute (fuel cost, weight, engagement) are computed from two artificially small
samples instead of one correct one, and the car occupies two slots in a bracket list. Bracket 1
currently shows `AYGO 3/5-DØRS` at rank 14 and `AYGO 5-DØRS` at rank 15, both at 16,194 kr/year,
which reads to a visitor as an obvious error.

A separate group shares a UK test pool but is genuinely two cars (hatch and estate): `FABIA` /
`FABIA COMBI`, `OCTAVIA COMBI`, `PASSAT VARIANT`, `GOLF VARIANT`, `MONDEO STATIONCAR`,
`ASTRA SPORTS TOURER`, `MEGANE SPORT TOURER`, `FOCUS STATIONSVOGN`, `SUPERB COMBI`, `AVENSIS STW`,
`RAPID SPACEBACK`, Audi `A3 Sportback` / `A3 Cabriolet` / `A3 Limousine`. Sharing reliability data
between body styles is defensible. These should **not** be merged, but note that Skoda `FABIA` and
`FABIA COMBI` 2010-2013 both land on 18,571 kr/year at bracket 1 ranks 46 and 47, which has the
same "this looks broken" effect on a reader.

`TOYOTA RAV4` / `RAV4 Plug in` sharing one UK pool is worth a second look given the recent
plug-in-hybrid detection work: the plug-in variant inherits the petrol car's reliability figures.

### 2. Mitsubishi Space Star is matched to the wrong UK car

7,009 Danish cars, 65th most common model in scope, excluded from every ranked list with
`exclusion_reason = reliability_unstable`.

`crosswalk.csv` maps it to DVSA `MITSUBISHI SPACE STAR` (3,423 tests) by `prefix_identity`. That
UK pool is the 1998-2005 Space Star MPV, a different car. First-use years in the DVSA pool:

```
2000: 54   2001: 203   2002: 513   2003: 751   2004: 1,149   2005: 722
2015: 3    2016: 6     2017: 3     2019: 1     2020: 2
```

The Danish 2013-onward Space Star is sold in the UK as the **Mirage**: `MITSUBISHI MIRAGE`,
23,860 tests, first-use 2013-2021, matching the Danish fleet's years exactly.

Resulting per-band UK test counts today: band 1 = 3 tests, band 2 = 6, band 3 = 0, band 4 = 1.
Nowhere near the 2,000-test floor, hence the exclusion. Remapping to `MIRAGE` should clear the
floor and put the Space Star into the rankings.

This is the same class of finding as the already-handled `OPEL KARL` to `VAUXHALL VIVA` rename
(`crosswalk.csv`, `rule_fired = known-rename`). It slipped through precisely because a literal
`SPACE STAR` string exists on the DVSA side, so `prefix_identity` fired and nothing looked wrong.

A systematic sweep for the same failure mode (UK pool dominated by cars registered outside
2010-2022) turned up only one other outlier, `PEUGEOT 206 +` at 0.1% in-range, and that one is
fine: reliability is matched on age-at-test, not registration year, so its band-4 cell still draws
4,177 in-band tests. Everything else in the tail (Colt, V70, V50, 207, Avensis, Corolla, Civic,
Micra) is a long-lived nameplate whose UK pool spans generations, which the age-band split already
handles.

### 3. 35,426 Danish cars have no price, so no ranked row at all

Seven models, 17 model/age-band cells, present in `model_age_band_metrics.csv` but absent from
`model_bracket_rankings.csv` entirely. They ship in `unpriced.json` and get a car page, but appear
in no bracket list and no running-cost list.

| Model | DK cars | Bands with no price |
|---|---|---|
| SUZUKI VITARA | 9,524 | 3 |
| SUZUKI SX4 S-Cross | 8,987 | 4 |
| SUZUKI ALTO | 6,754 | 2 |
| SUZUKI SPLASH | 5,129 | 2 |
| SUZUKI SX4 COMBIBACK | 2,103 | 1 |
| SUZUKI SX4 | 1,616 | 3 |
| DS DS 3 | 1,313 | 2 |

Cause: `build_suzuki_ds_prices.py` prices Suzuki and DS from hand-collected anchors, and
`pipeline/reference/suzuki_ds_price_anchors.csv` only has anchors for four models (Swift, Baleno,
Ignis, Celerio). The other seven were never anchored.

Suzuki Vitara and SX4 S-Cross are the 39th and 43rd most common cars in the Danish fleet in scope.
Two hand-collected listing anchors each, in the same format as the existing file, would bring all
seven into the rankings. This is the highest-value fix per unit of effort in this audit.

### 4. Rows backed by one or two Danish cars are ranked as if real

There is a floor on UK MOT tests (2,000) but **no floor on Danish fleet count**. 61 ranked rows
are backed by fewer than 50 Danish cars; 15 are backed by fewer than 5. Examples currently visible
to visitors:

- `TOYOTA AYGO 5-DØRS` 2020-2022, **1 Danish car**, running-cost rank 68 of 607
- `MAZDA 3` 2020-2022, **1 Danish car**, bracket 4
- `RENAULT MEGANE SPORT TOURER` 2020-2022, **3 Danish cars**, running-cost rank 27 of 607
- `SKODA CITIGO` 2020-2022, **2 Danish cars**, running-cost rank 109

These are mostly DMR stragglers: one late registration filed under a superseded model string. They
are a direct consequence of finding 1, and merging the spelling splits removes many of them. A
minimum `dk_vehicle_count` per ranked row (100 would drop 108 rows, 50 would drop 61) would remove
the rest. Note the site's own copy sells these lists as "cars you can actually buy in Denmark", and
a car with one registered example is not that.

### 5. Small, cheap: the DMR make string "VW"

`make_aliases.csv` maps DMR `VW` to DVSA `VOLKSWAGEN` on the DVSA side, but the DMR-side make
string was never folded into `VOLKSWAGEN`. 4,632 Danish cars sit under `VW` (`VW PASSAT` 1,082,
`VW POLO` 233, and so on), each too small individually to reach the universe cut, so all of them
drop out. Folding the make string before the universe cut recovers them.

## What is correctly absent

- **Dacia Lodgy** (2,670 cars, 137th) and **MG EHS Plug-in Hybrid** (2,109 cars): both reached
  the crosswalk review and were explicitly rejected there, with the reason recorded in
  `crosswalk_review.csv`. Lodgy matches DVSA `LODGY` on 14 UK tests, EHS matches `EHS` on 2, both
  far below the 2,000-test stability floor. Correct decisions, correctly documented.
- **BEVs**: excluded by the brief for v1.
- **Everything below the universe cut**: the cut is `TOP_N_MODELS = 214`
  (`pipeline/src/build_crosswalk_review.py:41`), raised from the brief's 150 to hit a 90% fleet
  coverage target. Porsche, Land Rover, Jaguar, Subaru, Smart, Jeep, Lexus, BMW 5-serie and so on
  fall below it. By design. One boundary artefact worth noting but not chasing: the cut is applied
  on a model_id grouping, so Audi `A4` as a name string (1,674 cars, 193rd by name) falls outside
  while `A4 AVANT` is inside.
- Make-level coverage is complete for every make above ~2,500 cars except `VW` (finding 5) and
  `DS` (finding 3).

## Headline numbers

- In-scope Danish fleet: 1,778,307 vehicles
- Covered by at least one ranked row: 1,551,715 (87.3%)
- Ranked rows: 667. Rank-eligible: 535. Running-cost-eligible: 607.
- Exclusion reasons on the 132 rank-ineligible rows: `no_exit_band_data` 95,
  `reliability_unstable` 32, `non_positive_depreciation` 5

## Suggested order of work

1. Anchor the seven unpriced Suzuki/DS models (finding 3). Largest coverage gain, no code change,
   just data collection into an existing file.
2. Remap Space Star to Mirage (finding 2). One crosswalk row, recovers 7,009 cars.
3. Extend the duplicate merge to catch make-prefixed and suffixed spellings (finding 1). Keep the
   existing DVSA-field-equality guard; only the grouping key needs to widen. Do not merge the
   hatch/estate group.
4. Add a minimum `dk_vehicle_count` for ranked rows (finding 4), after 3, since 3 removes many of
   them on its own.
5. Fold DMR make string `VW` into `VOLKSWAGEN` before the top-150 cut (finding 5).
