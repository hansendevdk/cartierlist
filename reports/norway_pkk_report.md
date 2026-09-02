# Norway PKK: a second, independent reliability source, and the first real test of the UK proxy

Status: complete. This phase adds Norwegian periodic vehicle inspection data (PKK / EU-kontroll)
as a second reliability source alongside the existing UK DVSA data, and answers the question the
project has carried as an unverified assumption since Phase 3: does foreign inspection data predict
the same reliability ordering the UK data implies, or is the UK-as-proxy-for-Denmark assumption
unsupported. Nothing in `pipeline/reference/model_age_band_metrics.csv`,
`model_bracket_rankings.csv`, `site/`, or the DVSA ingest path was touched. Everything here is new
files: a Norwegian ingest, a DK-to-NO crosswalk, a Norwegian reliability result, and an agreement
study joining it against the existing UK result.

## Headline finding

**The UK proxy is supported, moderately overall and strongly for older cars, but the honest pooled
figure is 0.72, not 0.94.** A first pass at this pooled all four age bands together and got a
Spearman rank correlation of 0.937 between the UK and Norwegian standardized pass rates. That number
is real (independently reproduced from the raw joined data) but it is not a valid measurement of what
this study exists to test. Pass rates fall steeply and monotonically with age in *both* countries, so
pooling across bands mostly measures the two sources agreeing that old cars fail more than young
ones, which is true and uninteresting, not that the *model ordering* transfers, which is the actual
question. The tell: a pooled rank correlation cannot legitimately exceed every one of its own
per-band components, and 0.937 sat above all four (0.42, 0.46, 0.75, 0.88). See "Why the naive pooled
figure is wrong" below for the full decomposition.

**The corrected, band-adjusted pooled figure is 0.719** (all 407 joined model/age-band cells, no
sample-size threshold applied; `build_agreement_study.py`'s `within_band_pooled()`), computed by
ranking each model only against its own age-band peers on both sides before pooling, which removes
the shared age trend by construction. Restricted to the cells that individually clear each source's
own stability floor (UK n>=2,000, Norway n>=2,500, n=186), the same corrected approach gives **0.653
(95% CI 0.562 to 0.729)**. Both corrected figures sit inside the range implied by the four per-band
coefficients themselves, which the naive 0.937 did not -- that consistency is the check that the fix
is right, not just different.

**The per-band table is the primary result, not the pooled number.** Read band by band:

| age band | n models | Spearman rho | 95% CI |
|---|---:|---:|---|
| 1 (age 4-6) | 39 | 0.418 | (0.118, 0.648) |
| 2 (age 7-9) | 40 | 0.462 | (0.175, 0.676) |
| 3 (age 10-12) | 55 | 0.747 | (0.600, 0.845) |
| 4 (age 13-16) | 52 | 0.879 | (0.798, 0.929) |

Band 1 holds the 2020-2022 cars, the most recent and most prominent cohort on the site, and its
correlation is genuinely weak: 0.42, with a confidence interval (0.12 to 0.65) wide enough to include
"barely related." Band 2 is not much stronger. This should not be softened: for the newest cars on
the site, this phase does not provide strong evidence that the UK ranking and a hypothetical
Norway-based ranking would agree. Bands 3 and 4, the older cars, show a real and fairly strong
signal (0.75 and 0.88) that the two countries are measuring something in common. One plausible
explanation for the age gradient, offered as a **hypothesis, not a demonstrated cause**: young cars
cluster near the pass-rate ceiling in both countries (most pass), which compresses the spread a rank
correlation needs to distinguish models, and Norway's own age-4 inspection is structurally the
thinnest, most boundary-sensitive slice of Norwegian data (see the age-blur quantification below).
Older cars have more differentiated failure rates, which happens to be exactly where a ranking is
most useful to a buyer and exactly where the two countries agree most -- a fortunate correlation
between "where the data is strong" and "where a ranking matters", but still only a hypothesis about
why band 1 is weak, not a proven mechanism.

Restricted to the four nameplate-clean makes named in the brief (Skoda, Peugeot, Volkswagen, Toyota,
after de-duplication), where the BMW/Mercedes variant-code grouping hazard cannot be the explanation
for anything, the same band-corrected approach gives **0.821 (95% CI 0.719 to 0.888, n=63)** at the
primary threshold, or 0.831 (n=93) at a looser one -- noticeably *higher* than the all-makes corrected
figure (0.653), not merely "close to it" as an earlier, uncorrected read of this study concluded. See
"Clean makes, corrected" below for what this can and cannot be read to mean.

**What does not transfer is the absolute level.** Norway's measured pass rate is dramatically lower
than the UK's at the same age, by 30 to 40 percentage points in band 4 (UK models mostly land in
0.55 to 0.75, the same Norwegian models mostly land in 0.20 to 0.42). This is the reason
`reports/handover_multi_country_reliability.md` recommended standardising within source and combining
ranks rather than pooling raw rates, and this phase's own results confirm that recommendation was
right: the *ordering* transfers well, the *level* does not, at all. Nothing here should be read as
"Norwegian cars fail twice as often" without a large caveat about differing statutory defect
thresholds, tester incentives, and Norway's climate (road salt, freeze-thaw corrosion on
undercarriage and brake lines) -- exactly the kind of measurement that is not comparable across
countries, per `phase2_crosswalk_strategy.md`'s and the handover's own warnings.

## Data acquisition and funnel

Source: `github.com/vegvesen/periodisk-kjoretoy-kontroll`, CC BY 4.0, Statens vegvesen. Twelve
quarterly zips, 2023Q1 through 2025Q4, downloaded by `pipeline/src/download_pkk.py` (168 MB total,
matching the brief's ~180 MB estimate). Filename case genuinely does change between years exactly as
flagged before this phase started: `PKK-2023-*`/`PKK-2024-*` (capital), `pkk-2025-*` (lowercase).

Each zip's single CSV (203 columns, latin-1, comma-delimited) was streamed directly out of the zip
via `pipeline/src/build_pkk_warehouse.py` -- never extracted to disk in full -- pruned to the ~28
columns this project needs, and loaded into a `pkk_inspections` DuckDB table. All twelve quarters
parsed cleanly with no row-shape anomalies.

| quarter | rows | quarter | rows |
|---|---:|---|---:|
| 2023 Q1 | 661,566 | 2024 Q1 | 566,566 |
| 2023 Q2 | 596,057 | 2024 Q2 | 581,720 |
| 2023 Q3 | 499,989 | 2024 Q3 | 527,867 |
| 2023 Q4 | 425,988 | 2024 Q4 | 465,794 |
| 2025 Q1 | 658,536 | 2025 Q2 | 625,400 |
| 2025 Q3 | 533,397 | 2025 Q4 | 448,406 |

**Total: 6,591,286 rows across three years**, close to but under the recon estimate of ~2.6M/year all
vehicle types (measured: ~2.2M/year). Real data, not the estimate, is what feeds everything below.

Funnel from raw rows to the scope this phase's metric uses:

| step | rows remaining | note |
|---|---:|---|
| raw, all vehicle types, all quarters | 6,591,286 | |
| `Kjøretøy Gruppeavgift = 'PERSONBIL'` | 5,057,272 | 76.7% of raw, close to the recon's ~78% estimate |
| excl. `Drivstofftype IN ('Elektrisk','Hydrogen')` or null | 4,209,798 | see BEV/fuel section below |
| `PKK Kontrolltype = 'Periodisk'` only | 2,827,977 | this is the reliability denominator |
| age at test in [4, 17) years | 2,382,720 | attributed to at least one confirmed DK model |

**PERSONBIL vs Tekniskgruppe = 'M1' cross-check, as the brief required**: 4,750,182 of the 5,057,272
PERSONBIL rows are also `M1` (93.9%). The remaining 307,090 (6.1%) are all `M1G`, the EU sub-category
for off-road passenger cars (raised ground clearance / approach-angle criteria under the type-approval
regulation), not a data-quality disagreement -- these are ordinary SUV-shaped passenger cars (many
4x4-badged Volvo, Subaru, Land Rover and similar variants) that happen to trip the off-road
sub-classification. Scope was kept at `Gruppeavgift = 'PERSONBIL'` without also requiring
`Tekniskgruppe = 'M1'`, matching how DVSA's own `test_class_id = 4` scope already includes ordinary
SUVs; excluding M1G would have arbitrarily dropped legitimate passenger models. 84,092 rows are `M1`
but not `PERSONBIL` (some other duty/tax classification on an M1-type-approved vehicle); left out of
scope, not investigated further, since they are outside the `PERSONBIL` definition this phase commits
to.

**Fuel distribution within PERSONBIL** (verifying the brief's ~14% BEV estimate against the real
number): Diesel 2,268,208 (44.9%), Bensin 1,988,082 (39.3%), **Elektrisk 800,397 (15.8%)**, CNG-gass
270, Hydrogen 188, Gass 65, null 47, and five other negligible categories. The 47 null-fuel rows are
excluded along with BEV/hydrogen (too few to characterise, and unusable for a fuel-conditioned
metric anyway).

**Kontrolltype within PERSONBIL**: Periodisk 3,425,384 (67.7%), Etterkontroll 1,631,888 (32.3%) --
matches the recon's ~68% estimate closely, a good internal-consistency check that the streaming
extraction is reading the right column. Etterkontroll is excluded from the reliability denominator,
per the brief, as the re-check analogue of a retest.

**Godkjent within the final scope** (PERSONBIL, Periodisk, non-BEV/hydrogen): Ja 1,418,825, Nei
1,409,152, a **raw pass rate of 50.2%**. Restricted further to age 4-16 (the four ranking age bands),
the pass rate rises to **55.8%**. Both numbers are far lower than casual intuition about EU-kontroll
pass rates might suggest, and far lower than the UK's own ~75% MOT pass rate baseline the Phase 2
strategy doc used to size its stability floor. This is reported as measured, not adjusted: it is
internally consistent (the volume of Etterkontroll re-checks, 1.63M, sits close to the volume of
Periodisk failures, 1.41M, which is exactly the relationship you would expect if most failures lead
to one re-check), and it is the actual reason the Norwegian ranking-stability floor computed below
(2,500 tests, not 2,000) ends up *higher* than the UK's despite Norway's much smaller total volume:
variance is maximised at a 50/50 split, and Norway sits almost exactly there.

## The severity vocabulary: verified against the source, and it does not fully match the brief's assumption

The brief asked for `Ant 1er merknad` to be treated as advisory (not a failure) and `Ant 2er`, `3er`,
`4er` to be treated as real defects, with an explicit instruction to verify this against the control
instruction and report if the vocabulary differs. It differs, on one point.

Fetched and read `Kontrollinstruks for periodisk kontroll av kjøretøy, versjon 4.1` (Statens vegvesen,
covers EU directive 2014/45/EU) directly. Its own classification table, verbatim:

> 1: Mindre feil/mangel som må rettes, men som ikke har betydning for om kjøretøyet kan godkjennes.
> 2: Større feil/mangel som vil føre til at Statens vegvesen ikke kan godkjenne kjøretøyet.
> 3: Farlig feil/mangel som innebærer en umiddelbar fare for trafikksikkerhet eller miljø... Dette
> innebærer at det vedtas bruksforbud umiddelbart.
> 4: På kontrolltidspunktet ikke mulig å måle på grunn av klimatiske forhold.

In English: class 1 is a minor fault that must be fixed but does **not** affect approval (confirms the
brief's assumption -- excluded from failure, correctly). Class 2 is a major fault that **does** cause
non-approval (a real defect). Class 3 is a dangerous fault, non-approval plus an immediate usage ban
(a real defect, more severe than class 2). **Class 4 is not a defect severity at all** -- it means "not
possible to measure at the time of inspection due to climatic conditions" (the worked example found in
the source, chapter 8 noise testing: "not measured because climatic conditions make measurement
impossible" is explicitly coded 4). Counting `Ant 4er merknad` as a real defect alongside 2er/3er, as
the brief's working assumption suggested, would have silently mixed a measurement-incomplete flag into
the mechanical-fault signal.

The practical stakes are low in this dataset: only 953 of 2,382,720 eligible rows (0.04%) carry any
`Ant 4er merknad` at all, so the correction barely moves any number. It is applied anyway, on
principle, in `build_norway_metrics.py`: **`Ant 4er merknad` is excluded from every defect and category
count in this phase's output.** `Ant 1er merknad` remains excluded from failure as the advisory
analogue of DVSA `rfr_type_code = 'A'`. `Ant 2er` and `Ant 3er` are the real-defect signal, totalling
2,909,244 and 48,946 occurrences respectively across the eligible scope.

The eleven `Ant 2-3er kap 0` through `kap 10` chapter columns, also verified against the same source
(chapter headings, verbatim from the instruction's own table of contents):

| kap | Norwegian heading | covers |
|---:|---|---|
| 0 | Identifikasjon av kjøretøyet | plates, chassis number |
| 1 | Bremseanlegg | braking system |
| 2 | Styring | steering |
| 3 | Sikt | visibility (windows, wipers, mirrors) |
| 4 | Lykter, refleksinnretninger og elektrisk utstyr | lights, reflectors, electrical |
| 5 | Aksler, hjul, dekk og hjuloppheng | axles, wheels, tyres, suspension |
| 6 | Understell og understellsutstyr | chassis and chassis-mounted equipment |
| 7 | Annet utstyr | other equipment |
| 8 | Skadevirkninger | noise, exhaust/emissions nuisance |
| 9 | Tilleggskontroller for M2/M3 buss | bus-only supplementary checks |
| 10 | Forevisning for trafikkstasjon | administrative referral to the traffic station |

Chapter 9 is confirmed bus-only by both the source text and the data: 57 non-zero occurrences across
2,382,720 `PERSONBIL`-scoped eligible rows, versus tens of thousands per chapter elsewhere -- noise,
not signal, in this scope. Per the brief, the fine-grained ~165 control-point columns underneath these
chapters are **not** mapped to the DVSA category vocabulary in this phase; the chapter-level rates are
written to `reference/model_age_band_category_failure_rates_no.csv` and stop there. Cross-taxonomy
harmonisation (the coarse "brakes / suspension / tyres / lighting / emissions / body / other" bucket
set the handover recommended) is future work.

## The hazard: Norwegian model-string normalisation, and why it turned out easier than feared

The brief's own reconnaissance found the raw hazard directly: BMW and Mercedes-Benz carry engine/trim
variant strings instead of nameplates (`520D`, `X3 XDRIVE20D` vs `X3 xDrive20d`), and several makes
carry a make-prefixed duplicate (`RAV4` vs `TOYOTA RAV4`, 92,451 vs 21,944 rows across all three
years; `YARIS`/`YARIS HYBRID`/`TOYOTA YARIS`/`TOYOTA YARIS HYBRID` split four ways). Both confirmed at
full scale: **17,790 distinct (make, model) string pairs** in the three-year `PERSONBIL` scope (up
from the single-quarter figure of 4,391 in the recon, as expected -- three years accumulate more
spelling variants). BMW alone carries 1,402 distinct model strings across the full window, Mercedes-
Benz 2,585.

The key finding that made this phase far less risky than the brief's own "close to trivial was wrong"
warning implied: **the Norwegian variant-code hazard is structurally identical to a problem this
project already solved on the DVSA side.** DVSA's own model field is also bare variant codes
(`320`, `X3`, `C`), and `pipeline/src/crosswalk_normalize.py` and `build_crosswalk_review.py`'s
matching primitives (`normalize`, `family_series_digit`, `strip_klasse_suffix`, `is_code_like`,
`leading_code`, `dmr_probes`, `best_prefix_identity`, `match_model`) already encode exactly the rules
needed: numeric tokens require exact equality, BMW family-series digits collapse siblings
(`320`/`318`/`316`/... under `3-Serie`), and `-Klasse` strips to the bare letter. Per the brief's
explicit instruction to reuse rather than invent a parallel mechanism, `pipeline/src/
build_no_crosswalk_review.py` imports these functions **unchanged** and points them at a Norwegian
match index instead of a DVSA one. Confirmed working exactly as intended:

- `MERCEDES-BENZ C-Klasse` (DK) -> Norwegian bare `C` (31,181 inspections), `A-Klasse` -> `A`,
  `E-Klasse` -> `E`, `B-Klasse` -> `B`. All `exact / prefix_identity`, no inference.
- `BMW 3-Serie` (DK, 7,390 vehicles) -> Norwegian siblings `320` (17,606), `318` (8,228), `316`
  (5,807), `330` (5,397), `325`, `328`, `335`, `323`, `340`, all `high / family_series_sibling`,
  structurally implied rather than guessed, same as the UK side.
- The **one genuinely new** piece of logic, because it does not exist on the DVSA side at all: a
  make-prefix-stripping step applied when building the Norwegian match index (`strip_make_prefix` in
  `build_no_crosswalk_review.py`), so `TOYOTA RAV4` folds into the same bucket as `RAV4` before
  classification, mirroring the exact glued-prefix rule `match_model()` already applies to DMR's own
  `MAZDA2`-style strings, just applied on the candidate-index side instead of the query side.
- Case inconsistency (`X3 XDRIVE20D` vs `X3 xDrive20d`) is a non-issue: `normalize()` already
  uppercases everything, for free, since it was written to solve the exact same problem for DMR/DVSA
  strings.

**Make aliasing needed no hand-authored table at all.** Verified directly: all 26 DK makes present in
`crosswalk.csv` have an exact `normalize()`-identical Norwegian make string in the data (only a
diacritic difference for `CITROËN`/`CITROEN`, handled by the shared `normalize()` function already).
This confirms the brief's claim that "Norway has no rebadging problem" -- there is no Opel/Vauxhall-
style trap on the Norwegian side.

## The rare-combination suppression rule: a proxy measurement, not an exact one

The repo's own text: "Datasettet inneholder heller ikke forekomster av kombinasjonen «Første gang
registrert», «Første gang registrert i Norge», «Kjøretøymerke», «Kjøretøy Modell» og «fylke», som det
bare finnes én av pr. år" -- combinations of that five-field tuple occurring only once per year are
dropped entirely, before the data is ever published. Because suppressed rows are by definition absent
from the released files, there is no way to count them directly; what can be measured is how close the
*surviving* data sits to the suppression edge, as a proxy for how thin the true (pre-suppression) tail
must be.

Reconstructing the same five-field tuple (grouped per calendar year, `PERSONBIL` scope, both
Kontrolltype included since the rule is not documented as test-type-specific): **356,451 distinct
combinations survive across the three years. 138,883 of them (39.0%) sit at count = 2, the minimum
possible value after a "drop if count = 1" rule.** That a full 39% of the released long tail sits
exactly one inspection away from having been suppressed is a strong indicator that the true tail (what
a naive reader might expect to see for rare model/county/year combinations) is thinner than the raw
row counts alone suggest, and this matters directly for this project: it is precisely the long tail
where the crosswalk's weakest cells already live.

One honesty note on the method: a small residual, 6,373 combinations (1.8%), still shows count = 1 in
the released data, which a perfectly-reconstructed suppression rule should show as zero. This gap is
most likely because the true suppression grain is not fully reconstructable from the released columns
alone (for example, whether it is applied before or after Etterkontroll rows are folded in, or an exact
match on `fylke` that differs subtly from `Kontrollorganets fylke`). Reported as a proxy with a stated
error, not as an exact figure.

## Methodological differences from the UK metric, all in one place

| dimension | UK (DVSA) | Norway (PKK) | consequence |
|---|---|---|---|
| age at test | exact date arithmetic (`test_date - first_use_date`) | year-only on both ends (`PKK Kontrollmåned` year minus `Første gang registrert` year) | see age-blur quantification below |
| mileage | continuous, converted from miles | pre-binned by the source into exact 50,000 km steps, rounded **up** | Norwegian mileage strata are systematically shifted toward the higher band versus a car's true reading; a real bias, not corrected |
| vehicle identity | `vehicle_id` present; dedup and an odometer-monotonicity ("clocking") filter both applied | **no vehicle identifier of any kind exists in PKK** | no dedup, no clocking filter possible; noted, not worked around |
| test-type denominator | `test_type = 'NT'`, `PRS` counted as failure | `PKK Kontrolltype = 'Periodisk'` only, `Etterkontroll` excluded (its analogue of a retest) | direct methodological parallel, not an approximation |
| failure definition | `test_result` fail/PRS | `Godkjent = 'Nei'` | direct parallel |
| advisory exclusion | `rfr_type_code = 'A'` | `Ant 1er merknad` | direct parallel, verified against the source instruction |
| stability floor | 2,000 NT tests (SE < 1pp at UK's ~0.75 pass rate) | **2,500** tests (SE < 1pp at Norway's own ~0.50-0.56 pass rate; variance is higher at p=0.5 than at p=0.75, which outweighs Norway's much smaller total volume) | Norway's floor is *higher* than the UK's despite ~4% of the UK's volume, an honest consequence of the observed pass rate, not adjusted to look better |
| mileage-stratum minimum cell | 100 tests/stratum | 25 tests/stratum (scaled down, not proportionally -- documented in `build_norway_metrics.py`) | |
| category taxonomy | ~165 fine-grained `component_category` values | 11 chapter-level columns only, fine-grained control points not mapped | narrower category resolution, by design for this phase |

**Age-year-precision blur, quantified as the brief asked**: each age band spans three age-years (e.g.
band 1 = ages 4, 5, 6). A car's true (exact-date) age can differ from the year-difference computed here
by up to a year in either direction, since both `Første gang registrert` and `PKK Kontrollmåned`'s year
component discard sub-year timing (well, the latter carries a month, but the former is year-only, so
the asymmetry is real). Flagging every row whose computed age sits at either boundary year of its band
(4 or 6 for band 1, 7 or 9 for band 2, and so on) as "within one year of a boundary": **1,590,367 of
2,382,720 eligible rows, 66.7%.** This is a large number, and it is supposed to be: two of every three
possible age-years in a 3-year-wide band sit at a boundary by construction. It means a substantial
share of Norwegian rows could plausibly belong to the adjacent age band under exact-date arithmetic.
This is a genuine, structural difference from the UK metric's exact-date precision, not a data defect,
and it is the most important caveat to carry into any age-band-level reading of the Norwegian numbers.

## The DK-to-NO crosswalk

Built in three stages mirroring the existing UK pipeline's own Stage A/B/C split (`make_aliases.csv`
had no Norwegian analogue needed, see above):

1. `pipeline/src/build_no_crosswalk_review.py` matches all 211 distinct DK models in the confirmed UK
   `crosswalk.csv` against a Norwegian match index, producing `reference/no_crosswalk_review.csv`
   (277 candidate rows: 196 exact, 74 high-confidence structural, 2 medium-confidence fuzzy guesses,
   5 no-candidate).
2. `pipeline/src/auto_decide_no_crosswalk.py` auto-confirms only rows with no inference made (literal
   identity or structural family membership, match_score = 1.0) that clear a 200-inspection noise
   floor -- the same posture as the UK's own `auto_decide_crosswalk.py`, not a looser one. This
   filtered out a handful of clearly spurious BMW family-series "siblings" the pure structural rule
   proposed with 1-20 inspections behind them (`1969`, `3200`, `1995` -- almost certainly stray
   model-year digits sitting in the model-name field, not real cars).
3. `pipeline/src/promote_no_crosswalk.py` writes `reference/no_crosswalk.csv` from `decision = 'y'`
   rows only.

**Result: 188 of 211 DK models (89.1%) settled automatically, covering 1,494,263 of the 1,595,873 DK
vehicles in the UK crosswalk's own universe (93.6%; 84.0% of the full 1,778,307-vehicle in-scope
Danish fleet).** 16 models (2.9% of the universe by fleet count) had no usable Norwegian match at any
confidence and are excluded, not guessed at. **7 models (3.1% of the universe) are left in
`no_crosswalk_review.csv` with a blank `decision`, for human review**, per the brief's explicit
requirement that ambiguous rows are routed to a human rather than auto-accepted:

| DK model | DK fleet | note |
|---|---:|---|
| SEAT MII | 11,905 | no candidate found automatically |
| OPEL KARL | 8,920 | no candidate found automatically (same UK-side rename hazard as `crosswalk.csv`'s own `KARL`->`VIVA` row; Norway may use a different name entirely, needs a human) |
| SUZUKI Celerio | 8,391 | no candidate found automatically |
| RENAULT TWINGO | 7,445 | exact Norwegian `TWINGO` token exists but only 20 inspections behind it, below the noise floor; needs a human judgement call on whether to accept anyway |
| CITROËN GRAND C4 PICASSO | 6,346 | no candidate found automatically |
| RENAULT GRAND SCENIC | 5,269 | fuzzy `SCENIC` candidate (135 inspections, medium confidence) exists but is an inference, not an identity |
| CITROËN Grand C4 SpaceTourer | 1,762 | no candidate found automatically |

## The Norwegian per-(model, age band) result

`pipeline/src/build_norway_metrics.py` produces `reference/model_age_band_metrics_no.csv`: **556
(model, age band) cells across 157 distinct DK models**, computed from 2,382,720 eligible inspections
attributed via the crosswalk link table (3,241 raw Norwegian model strings resolved back to 158 DK
models -- one model's raw-string links produced zero surviving eligible rows after the age-4-16 and
valid-`Godkjent` filters, hence 157 in the final metrics versus 158 linked).

Stability floor sensitivity (SE < 1pp target implies n >= 2,500 at Norway's observed ~0.50-0.56 pass
rate; shown at several thresholds since the brief asked for sensitivity to be visible):

| threshold | cells clearing it | share |
|---:|---:|---:|
| n >= 500 | 449 | 80.8% |
| n >= 1,000 | 376 | 67.6% |
| n >= 1,500 | 327 | 58.8% |
| n >= 2,000 | 291 | 52.3% |
| **n >= 2,500 (primary)** | **256** | **46.0%** |

**Four (model, age band) cells the UK data marks `reliability_unstable` (below the UK's own 2,000-test
floor) now have a stable, usable Norwegian rate**, a small but genuine coverage gain the brief asked
about: Hyundai i40 (band 4, n=753, rate 0.292), Mercedes-Benz GLC (band 3, n=311, rate 0.631), Toyota
Corolla (band 3, n=284, rate 0.394), Volvo V40 (band 4, n=243, rate 0.428). This is a small number (4
of 58 UK-unstable cells), not a headline result, and it is reported at face value rather than inflated.

Full detail: `reference/model_age_band_metrics_no.csv` (main output), `reference/
model_age_band_reliability_strata_no.csv` (2,161 stratum-merge detail rows, the audit trail behind
standardisation), `reference/model_age_band_category_failure_rates_no.csv` (6,116 chapter-level rate
rows).

## The agreement study

Joined `model_age_band_metrics.csv` (UK, unchanged) against `model_age_band_metrics_no.csv` (Norway,
this phase) on `(dmr_make, dmr_model, age_band)` wherever both sides carry a standardized pass rate:
**407 joined cells** before any sample-size filtering. Written in full to `reference/
no_uk_agreement.csv` for independent inspection.

**De-duplication, applied to every number below**: several DK model-name rows are documented
spelling/body-style splits resolving to the identical underlying UK test pool *and* the identical
underlying Norwegian test pool (Toyota `RAV4`/`RAV4 Plug in`, `AVENSIS`/`AVENSIS STW`, Skoda
`OCTAVIA`/`OCTAVIA COMBI`, and others -- `pipeline/reference/model_spelling_review.csv` lists the ones
already flagged as pending human confirmation). A pair sharing a bit-identical rate on *both* sides
would otherwise contribute a trivially "perfectly agreeing" extra data point and inflate both n and
the correlation for no real reason. Within every age band, when two DK models share an identical
`(uk_rate, no_rate)` pair, only the alphabetically-first is kept for this study specifically -- the
metrics files themselves are untouched.

### Why the naive pooled figure is wrong: the age-band confound

Pass rates fall steeply and monotonically with age in both countries:

| age band | UK mean rate | Norway mean rate | n |
|---|---:|---:|---:|
| 1 (age 4-6) | 0.841 | 0.783 | 87 |
| 2 (age 7-9) | 0.760 | 0.629 | 109 |
| 3 (age 10-12) | 0.659 | 0.454 | 111 |
| 4 (age 13-16) | 0.585 | 0.317 | 100 |

Age band alone (a one-way ANOVA-style variance decomposition, eta-squared) explains **68.1% of the
variance in the UK rate and 79.0% of the variance in the Norwegian rate**, across all 407 joined
cells. Both series decline monotonically across the same four bands, so the four band means alone
correlate at rho = 1.0, trivially. Ranking all 407 cells together, ignoring which band each one
belongs to, mostly picks up the two sources agreeing on that shared, uninteresting fact ("old cars
fail more"), not on which *specific models within an age group* are more or less reliable, which is
the only thing this study exists to test.

The fix, implemented in `build_agreement_study.py`'s `within_band_pooled()`: within each age band
separately, convert every cell's `uk_rate` and `no_rate` to a **within-band percentile rank** (a
model is scored only against its age-band peers, on both sides), then pool those percentiles across
all four bands and compute the Spearman correlation of the pooled percentiles. Every band's
percentiles span the same 0-1 range regardless of that band's raw pass-rate level, so the shared age
trend cannot contribute to the result by construction.

| statistic | naive pooled (raw rates) | within-band corrected |
|---|---:|---:|
| all 407 joined cells, no threshold | 0.937 | **0.719** |
| primary threshold (UK n>=2,000, Norway n>=2,500, deduplicated, n=186) | 0.937 | **0.653** (95% CI 0.562, 0.729) |

Both corrected figures land inside the range spanned by the four per-band coefficients (0.42 to
0.88); the naive 0.937 sat above all four, which is the mechanical impossibility that flags it as
wrong rather than merely different. **0.72 (unfiltered) to 0.65 (threshold-matched) is the honest
pooled headline; 0.937 should not be quoted as a summary of this study.**

### Per age band, all makes, UK n >= 2,000 and Norway n >= 2,500

This is the primary result of the study -- read band by band, not as a single pooled number, since
the strength of agreement genuinely differs by age (see the headline finding above for the full
discussion, including the ceiling-compression hypothesis for band 1's weaker figure).

| age band | n models | Spearman rho | 95% CI |
|---|---:|---:|---|
| 1 (age 4-6) | 39 | 0.418 | (0.118, 0.648) |
| 2 (age 7-9) | 40 | 0.462 | (0.175, 0.676) |
| 3 (age 10-12) | 55 | 0.747 | (0.600, 0.845) |
| 4 (age 13-16) | 52 | 0.879 | (0.798, 0.929) |
| naive pooled (do not quote) | 186 | 0.937 | (0.916, 0.952) |
| **within-band corrected pooled** | **186** | **0.653** | **(0.562, 0.729)** |

### Sensitivity to the sample-size threshold, pooled across bands, all makes

| UK min | Norway min | n | naive rho | within-band rho |
|---:|---:|---:|---:|---:|
| 2,000 | 500 | 331 | 0.938 | 0.693 |
| 2,000 | 1,000 | 283 | 0.939 | 0.698 |
| 2,000 | 1,500 | 242 | 0.941 | 0.684 |
| 2,000 | 2,000 | 212 | 0.942 | 0.695 |
| 2,000 | 2,500 | 186 | 0.937 | 0.653 |
| 1,000 | 1,000 | 283 | 0.939 | 0.698 |
| 500 | 500 | 332 | 0.938 | 0.694 |

Two things worth separating here. The naive figure is stable to within 0.005 across every threshold
tried, which looked reassuring in an earlier read of this study but is now understood to mean the
age-band confound is present at every threshold equally, not that the (wrong) headline number was
robust. The within-band-corrected figure is also fairly stable, in the 0.65 to 0.70 range across every
threshold, which *is* the reassuring result: the corrected conclusion (moderate-to-strong ordering
agreement, well short of 0.9) does not depend on where the sample-size line is drawn either.

### Clean makes, corrected (Skoda, Peugeot, Volkswagen, Toyota, de-duplicated)

| age band | n (primary) | rho (primary) | n (loose, both >=500) | rho (loose) |
|---|---:|---:|---:|---:|
| 1 | 13 | 0.764 | 21 | 0.799 |
| 2 | 14 | 0.820 | 24 | 0.815 |
| 3 | 19 | 0.867 | 26 | 0.869 |
| 4 | 17 | 0.802 | 22 | 0.837 |
| naive pooled (do not quote) | 63 | 0.954 | 93 | 0.949 |
| **within-band corrected pooled** | **63** | **0.821** (95% CI 0.719, 0.888) | **93** | **0.831** (95% CI 0.755, 0.885) |

The per-band clean-makes coefficients were never affected by the pooling confound (they were already
computed within a single band each) and are unchanged from the first pass at this study. What changes
is the pooled summary: naively it looked "about the same as, marginally above" the all-makes pooled
figure (0.954 vs 0.937); corrected, clean-makes pools noticeably *higher* than the all-makes corrected
figure (0.821 vs 0.653, confidence intervals overlapping only narrowly around 0.72-0.73).

This still supports the same qualitative conclusion the first pass drew -- crosswalk normalisation is
not *manufacturing* the agreement, since the makes least exposed to the BMW/Mercedes variant-grouping
hazard show the *strongest* corrected agreement, not the weakest -- but it is a more careful claim than
before. What the gap does leave open, and this report labels as an open question rather than resolving
it: whether the family-series-sibling grouping used for BMW and Mercedes-Benz (necessarily pooling
several UK model strings and several Norwegian model strings into one crosswalk cell each) adds some
genuine noise to those makes' standardized rates beyond ordinary cross-country disagreement, or whether
premium German makes simply transfer less well between the UK and Norwegian markets for reasons
unrelated to the crosswalk (different ownership patterns, or Norway's climate affecting these
specific cars differently). The BMW/Mercedes-heavy "largest disagreements" table below is consistent
with either explanation and does not distinguish between them.

### Largest disagreements

Every one of the ten largest negative gaps (Norway rate far below what the UK ranking would predict)
is in **band 4**, and eight of the ten are BMW, Mercedes-Benz, or another car sharing that
band's general pattern of a large UK-Norway *level* gap:

| make | model | band | UK rate (n) | NO rate (n) | diff |
|---|---|---:|---|---|---:|
| BMW | 3-Serie | 4 | 0.696 (406,242) | 0.334 (10,635) | -0.362 |
| FIAT | 500 | 4 | 0.539 (195,462) | 0.180 (2,705) | -0.359 |
| BMW | X1 | 4 | 0.712 (23,364) | 0.364 (4,390) | -0.348 |
| MINI | COOPER | 4 | 0.615 (24,334) | 0.287 (2,672) | -0.328 |
| BMW | 5-Serie | 4 | 0.738 (134,337) | 0.414 (10,877) | -0.324 |
| BMW | 1-Serie | 4 | 0.674 (278,804) | 0.352 (6,307) | -0.321 |
| SKODA | SUPERB | 4 | 0.654 (14,927) | 0.337 (3,621) | -0.317 |
| MERCEDES-BENZ | C-Klasse | 4 | 0.655 (240,851) | 0.338 (7,755) | -0.317 |
| TOYOTA | AYGO | 4 | 0.539 (177,427) | 0.228 (3,007) | -0.311 |
| TOYOTA | YARIS | 4 | 0.586 (342,210) | 0.274 (12,845) | -0.311 |

Read this table carefully: this is **not** a ranking disagreement. All ten of these are old (13-16
year-old) cars, and the *whole band* runs 30-40 points lower in Norway than in the UK (this is the
level gap described in the headline finding, not a Norway-specific problem with these particular
models). Whether a given model sits at -0.362 or -0.311 within that shared band-wide gap is
compressed and noisy, which is exactly why band 4's rank correlation (0.879), while the strongest of
the four bands, is not perfect.

The positive-diff table is far more muted, both in count and in magnitude, which is itself informative:

| make | model | band | UK rate (n) | NO rate (n) | diff |
|---|---|---:|---|---|---:|
| VOLVO | XC40 | 1 | 0.888 (90,138) | 0.928 (6,206) | +0.040 |
| VOLVO | XC60 | 1 | 0.870 (140,248) | 0.889 (16,959) | +0.020 |
| SUZUKI | VITARA | 1 | 0.852 (125,101) | 0.870 (3,773) | +0.018 |
| VOLVO | V60 | 1 | 0.848 (43,623) | 0.861 (11,028) | +0.013 |
| VOLKSWAGEN | POLO | 1 | 0.792 (487,075) | 0.799 (5,836) | +0.007 |

Every positive-diff row is in **band 1** (age 4-6), where both countries' rates are close to their
respective ceilings and the level gap seen in older bands has not yet opened up -- consistent with the
"level gap widens with age" pattern the headline finding describes, and with band 1's own weaker rank
correlation (0.418): when both sides cluster near their ceiling, small measurement noise dominates
rank order.

## Attribution

Data: Statens vegvesen, `github.com/vegvesen/periodisk-kjoretoy-kontroll`, licence **CC BY 4.0** --
attribution required. Not yet added to the site's methodology page; the brief scoped this phase to
report and reference files only. When the site is updated to reflect a second reliability source, the
methodology page's attribution block needs a Statens vegvesen credit alongside the existing DVSA Open
Government Licence v3.0 one.

## Files produced

| file | purpose |
|---|---|
| `pipeline/src/download_pkk.py` | fetches the twelve quarterly zips |
| `pipeline/src/build_pkk_warehouse.py` | streams and prunes them into `pkk_inspections` |
| `pipeline/src/build_no_crosswalk_review.py` | Stage B/C candidate generation, reusing `crosswalk_normalize.py` |
| `pipeline/src/auto_decide_no_crosswalk.py` | Stage C narrow auto-confirmation |
| `pipeline/src/promote_no_crosswalk.py` | writes the confirmed crosswalk |
| `pipeline/src/build_norway_metrics.py` | the Norwegian reliability index |
| `pipeline/src/build_agreement_study.py` | the UK-Norway rank correlation study, including the within-band-percentile pooling correction (`within_band_pooled()`) that removes the age-band confound from the pooled figure |
| `pipeline/reference/no_crosswalk_review.csv` | all 277 candidate rows, 7 left blank for human review |
| `pipeline/reference/no_crosswalk.csv` | 207 confirmed rows, 188 DK models |
| `pipeline/reference/model_age_band_metrics_no.csv` | 556 (model, age band) Norwegian reliability cells |
| `pipeline/reference/model_age_band_reliability_strata_no.csv` | stratum-merge audit detail |
| `pipeline/reference/model_age_band_category_failure_rates_no.csv` | chapter-level defect rates |
| `pipeline/reference/no_uk_agreement.csv` | the full 407-row UK/Norway joined comparison, undeduplicated, for independent audit |

## What to do next, and what needs your judgement

1. **7 crosswalk rows need a human decision** (`no_crosswalk_review.csv`, blank `decision` column),
   3.1% of the crosswalk universe by DK fleet count. Small, not urgent.
2. **The methodology page's UK-proxy caveat can now cite a measured figure instead of stating an
   untested assumption** -- that update was explicitly out of scope for this phase (site untouched,
   per the brief) but is now unblocked. The honest figure to cite is the per-band table (0.42 / 0.46 /
   0.75 / 0.88), not a single pooled number, and band 1 (the newest, most-viewed cars on the site)
   is the band where this phase provides the weakest support. A copy change that says "supported for
   older cars, weakly tested for the newest ones" is accurate; a copy change that says "validated at
   0.94" is not.
3. The four-model UK-unstable-cells-recovered result (Hyundai i40, Mercedes GLC, Toyota Corolla,
   Volvo V40) is real but small; folding a second source into the actual ranking (as opposed to this
   validation study) is the combination work the handover describes as a separate, later step, not
   attempted here.
4. Chapter-level category harmonisation against the DVSA taxonomy (the coarse
   brakes/suspension/tyres/lighting/emissions/body/other bucket set) remains future work, as scoped.
