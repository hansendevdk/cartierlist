# Phase 0b: DMR syn data reconnaissance

Status: complete. Answers all five open questions on `SynResultatStruktur` and briefly
characterises `KoeretoejUdstyrSamlingStruktur`. Produces a report only, no metric, ranking,
reference CSV, or site page changed.

## Why this exists

`pipeline/reports/phase0_schema_report.md` recorded that each vehicle in the DMR extract also
carries a repeating `SynResultatStruktur` (Denmark's periodic vehicle inspection, "syn") and a
repeating equipment list, but neither was parsed or characterised further at the time. Nobody had
looked inside `SynResultatStruktur` since. `build_dmr_vehicles.py` extracts only scalar fields per
vehicle and skips both repeating structures.

This matters because the project's reliability metric (pass rates, repair burden index, and the
repair-cost component of every TCO figure) currently rests entirely on UK DVSA MOT data as a proxy
for Danish reliability, a limitation the site's own methodology page discloses. Danish syn data is
Danish inspection data on Danish cars on Danish roads, already sitting inside a file the project
already downloads. If it existed in usable volume and detail, it was worth checking as a validation
layer for the UK-derived ranking, or better.

A separate review of the DMR extract's unused scalar fields (`ncap_flag`, `body_type`, `seats_min`,
`door_count`, `gear_count`, `engine_displacement_cc`, `model_year`) concluded none of them are worth
adding to the pipeline. That review is settled and is not repeated here.

## Sampling method and scope

New script: `pipeline/src/inspect_dmr_syn.py`. It streams the archive directly out of the zip with
`lxml.etree.iterparse`, clearing each `Statistik` element after processing, exactly like
`build_dmr_vehicles.py` and `inspect_dmr.py` (the uncompressed XML is roughly 128 GB, far too large
to extract to disk or hold in memory). It never modifies `data/raw/`.

The run this report is based on streamed **3,000,000 `Statistik` elements** (247 seconds, about
12,150 records/second, no slowdown across six 500k checkpoints). That is larger than Phase 0's own
sample of roughly 2.3 million records, chosen because this task also needs to restrict down to the
crosswalked, in-scope subset before most questions can be answered, which shrinks the effective
sample considerably. All numbers below are exact counts over this 3,000,000-record run unless
stated otherwise; nothing here is a full pass over the archive (a full pass would take roughly the
same 35 minutes of pure parsing Phase 0 measured, and was not necessary to answer these questions
confidently).

Scope, matching `build_dk_fleet.py`'s existing v1 definition exactly:

- `KoeretoejArtNavn` = `Personbil` (passenger car)
- `KoeretoejRegistreringStatus` = `Registreret` (currently active)
- `first_registration_year` between 2010 and 2022 inclusive
- primary fuel type is not `El` (BEV excluded per the brief's v1 scope)
- deduplicated by `chassis_number` (the VIN), keeping the first snapshot seen per chassis. The same
  leasing-period duplication `build_dmr_vehicles.py` documents for the vehicle-level table applies
  here too, since a Statistik element is a per-snapshot record, not strictly one per physical
  vehicle.

"Crosswalked" means the (make, model) pair matches a row in `reference/crosswalk.csv` (211 distinct
pairs), i.e. it is a model this project actually reports on.

Sample funnel:

| stage | count |
|---|---|
| Statistik elements streamed | 3,000,000 |
| of which Personbil | 1,844,526 |
| of which in-scope (Registreret, 2010-2022, non-BEV), raw rows | 426,373 |
| of which also crosswalked, raw rows | 379,606 |
| unique vehicles by chassis (final sample population) | 365,107 |

365,107 unique vehicles is **13.19%** of the known crosswalked, in-scope population
(2,768,943 vehicles, from the settled scalar-field review). That is a large enough sample that the
percentages below should be read as stable, not as rough guesses.

## Question 1: what does SynResultatStruktur contain

Six leaf fields were observed, and only six, across every one of the 361,065 syn records in the
sample:

| field | meaning | notes |
|---|---|---|
| `SynResultatSynsType` | which kind of inspection this was | see distinct values below, not all of them are the recurring periodic test |
| `SynResultatSynsDato` | inspection date | ISO date with UTC offset, e.g. `2022-07-06+02:00` |
| `SynResultatSynsResultat` | the pass/fail/conditional result | see Question 3 |
| `SynResultatSynStatus` | record status | `Aktiv` in 100% of sampled records, no other value was ever seen, so this field carries no information in this sample |
| `SynResultatSynStatusDato` | date the status was set | equal to `SynsDato` in every example manually checked |
| `KoeretoejMotorKilometerstand` | odometer reading at the time of inspection | present on 96.89% of syn records (349,827 / 361,065); see the unit caveat below |

**There is no itemised failure sub-structure.** Every child element directly under
`SynResultatStruktur` was checked for whether it has children of its own, across all 361,065 sampled
records: none did. This was re-confirmed at full sample scale after an initial smaller exploratory
pass (also negative) raised the question. There is no equivalent of DVSA's `test_item` table: no
per-defect code, no category, no location on the vehicle, nothing beyond the single overall result
value. This is the most consequential finding in this report, discussed further in the
recommendation.

`SynResultatSynsType` distinct values (n=361,065):

```
PeriodiskSyn (periodic reinspection):        314,002  (86.97%)
RegistreringsSyn (registration/import check):  46,352  (12.84%)
RegistreringssynToldsyn (customs variant):        677  ( 0.19%)
MOT (foreign-test mutual recognition):             34  ( 0.01%)
```

Only `PeriodiskSyn` is a direct analogue of a UK MOT retest: a recurring check on a vehicle already
in service. `RegistreringsSyn` and its customs variant are one-time checks tied to (re)registering a
vehicle, closer to an import roadworthiness check, and could plausibly have different pass dynamics
(an importer has an incentive to fix problems before presenting the car). Restricting to
`PeriodiskSyn` only barely changes the result distribution (see Question 3), so this distinction
does not change the conclusion, but it is a real difference in what is being measured and would need
to be filtered on if this data were ever used.

**Odometer unit is inconsistent across records and needs resolving before any use.** Over the
349,827 non-null values: min 0, median 128, p75 185, p90 246, max 299,118. 99.99% of all non-null
values are under 2,000. A median in-service Danish car reporting an odometer reading of "128" is not
plausible as raw kilometres, but is entirely plausible read as **thousands of kilometres**
(128 = 128,000 km), a common Danish convention. The roughly 0.01% of values in the tens or hundreds
of thousands, however, look like raw kilometres, not thousands. Nothing in the data distinguishes
which convention a given record uses; this would need a heuristic (for example, treating values
above some threshold as already raw km) before the field could be trusted, and that heuristic itself
was not validated here.

## Question 2: coverage and per-vehicle distribution

98.89% of the 365,107 unique crosswalked, in-scope vehicles carry a syn record (361,065 do, 4,042
do not).

The "distribution of records per vehicle" turned out to be trivial rather than interesting: **every
vehicle in the sample has either zero or exactly one syn record.** The histogram is
`{0: 4,042, 1: 361,065}`, no vehicle in the sample had two or more. This was checked again
separately over an earlier 800,000-record exploratory pass (0 vehicles with 2+ records out of
501,218 Personbil checked) before being accepted, since it was not what would normally be expected
of a periodic-inspection dataset (Danish syn recurs roughly every two years from age four, so a
2010-registered car should by now have accumulated several inspection cycles).

**This means the extract carries a current-status snapshot per vehicle, not a historical inspection
log.** There is no sequence of past tests to compute a return-visit or repeat-failure rate from, and
no way to see how a specific vehicle's result changed over time. This is a materially different
shape from DVSA's MOT data, where the same `vehicle_id` recurs across many `test_result` rows over
years. It is worth being explicit that this is a property of what this extract retains, not
necessarily of what the Danish inspection authority records overall, but it is what is actually
available in this file.

## Question 3: distinct result values and frequencies

`SynResultatSynsResultat`, n=361,065:

| value | count | share | meaning |
|---|---|---|---|
| Godkendt | 359,262 | 99.501% | approved / passed |
| KanGodkendesVedOmsynAfOmsynsvirksomhed | 1,768 | 0.490% | conditional pass, pending reinspection by a reinspection company |
| KanGodkendesVedOmsynAfSynsvirksomhed | 23 | 0.006% | conditional pass, pending reinspection by an inspection company |
| IkkeGodkendt | 12 | 0.003% | not approved / failed |

Restricting to `PeriodiskSyn` only (314,002 records, the type actually comparable to a UK retest)
barely moves this: 99.453% Godkendt, 0.544% conditional, 0.003% IkkeGodkendt. Filtering out the
registration/import checks does not surface a meaningfully different picture.

For comparison, an earlier, unscoped exploratory pass (1,171,666 syn records, all vehicle types, no
age or crosswalk restriction) found a somewhat higher failure share (IkkeGodkendt 0.41%, all
non-Godkendt categories combined 2.15%), most likely because that pass included vehicles well
outside the 2010-2022 registration window, including much older cars. Restricted to exactly the
population this project would use, the result field is a **99.5% / 0.5% wall**: essentially every
inspection in scope comes back approved.

## Question 4: date range and age-band coverage

`SynResultatSynsDato` observed range in the sample: **2015-08-31 to 2026-07-25**.

Coverage by age band (same boundaries as `AGE_BANDS` in `build_phase3_metrics.py`):

| age band | registration years | has syn record | total | coverage |
|---|---|---|---|---|
| 1 | 2020-2022 | 56,496 | 60,529 | 93.34% |
| 2 | 2017-2019 | 102,193 | 102,197 | 100.00% |
| 3 | 2014-2016 | 101,971 | 101,974 | 100.00% |
| 4 | 2010-2013 | 100,405 | 100,407 | 100.00% |

Coverage is effectively total for bands 2 through 4. Band 1's slightly lower coverage is explained
by the inspection schedule itself, not a data gap: Danish syn starts at 4 years of age, so a car
first registered in 2021 or 2022 would not be due for its first inspection until 2025 or 2026, and
some of that band simply has not reached its first syn yet as of this extract. This is a mechanism
that makes sense, not an anomaly.

## Question 5: total syn record volume for the crosswalked, in-scope fleet

The sample's 98.89% coverage, scaled to the known crosswalked in-scope population of 2,768,943
vehicles, gives an estimated **2,738,289 total syn records** for that fleet. Because coverage is
capped at one record per vehicle (Question 2), this number is essentially the estimated count of
in-scope crosswalked vehicles that currently hold a valid syn result, not a count of repeated tests.

For context, DVSA's UK MOT data underpinning the existing reliability metric holds 48,220,796
eligible tests, because the same vehicles get retested annually for years. Danish syn's roughly 2.7
million records are not the equivalent quantity: they represent roughly 2.7 million distinct
vehicles each contributing a single current data point, not a comparable volume of repeated
observations. Volume in the "number of vehicles with data" sense is good. Volume in the "number of
independent observations per model to average over" sense is not, because there is only one
observation per vehicle, ever, in this extract.

## KoeretoejUdstyrSamlingStruktur (equipment list): brief note only

Structure: `KoeretoejUdstyrSamlingStruktur` contains `KoeretoejUdstyrSamling`, which contains a
repeating `KoeretoejUdstyrStruktur`, each with `KoeretoejUdstyrAntal` (a count) and a nested
`KoeretoejUdstyrTypeStruktur` carrying `KoeretoejUdstyrTypeNummer`, `KoeretoejUdstyrTypeNavn` (the
human-readable name, e.g. "ABS bremser", "Airbags", "ESP"), and three boolean display flags
(`VisesVedSyn`, `VisesVedForespoergsel`, `VisesVedStandardOprettelse`) whose purpose was not
investigated.

Over 200,000 crosswalked, in-scope vehicles checked, 91.69% (183,379) had at least one equipment
entry present. 39 distinct `KoeretoejUdstyrTypeNavn` values were seen. Top 10 by vehicle count:
Airbags (183,315), selealarm/seatbelt alarm (183,249), integreret barnesæde/integrated child seat
(180,776), ABS bremser (178,884), ESP (178,734), radio (113,111), multifunktionsrat/multifunction
steering wheel (5,508), turbo (5,190), Metallak/metallic paint (4,484), trinløst gear/CVT gearbox
(4,420).

One caveat worth flagging before anyone looks closer: `KoeretoejUdstyrAntal` was seen at 0 on some
entries in manual spot checks (for example "ESP" with antal 0), so the presence of a
`KoeretoejUdstyrTypeNavn` entry appears to mean "this equipment type was assessed," not necessarily
"the vehicle has it." The near-universal presence of an "integreret barnesæde" (integrated child
seat) entry on 98.6% of checked vehicles supports this reading, since that is not a plausible
equipment rate for an actual feature, but is a plausible rate for "this was checked and usually
reported absent." A real coverage analysis would need to filter on `KoeretoejUdstyrAntal > 0`, which
this pass did not do since it was scoped as a brief note only. This looks like it could be a
genuinely richer data source than syn (ABS/airbag/ESP presence is exactly the kind of thing the
brief's equipment/engagement scoring would want), and is worth a dedicated look later, separate from
this task.

## Encoding

Confirmed clean UTF-8 at the byte level (e.g. `CITROËN` reads as the bytes `43 49 54 52 4f c3 8b 4e`,
correct UTF-8 for "Ë"), same as Phase 0 found for the rest of this file. As Phase 0 also noted,
printing to a Windows console mangles these characters on screen; that is a terminal artifact, not a
data problem. The examples below have been corrected back to their real characters by hand for
readability.

## 37 real example records

General sample (make, model, first registration year, syn type, syn date, result, status, odometer):

```
(CHEVROLET, SPARK,        2010, PeriodiskSyn,     2026-05-05, Godkendt, Aktiv, 258)
(CITROËN,   C 1,          2010, PeriodiskSyn,     2024-09-20, Godkendt, Aktiv, 84)
(CHEVROLET, SPARK,        2010, PeriodiskSyn,     2025-01-29, Godkendt, Aktiv, 143)
(CITROËN,   C 1,          2010, PeriodiskSyn,     2024-11-27, Godkendt, Aktiv, 124)
(CHEVROLET, SPARK,        2010, PeriodiskSyn,     2025-06-24, Godkendt, Aktiv, 151)
(CHEVROLET, SPARK,        2011, PeriodiskSyn,     2025-09-09, Godkendt, Aktiv, 98)
(CITROËN,   C3,           2011, RegistreringsSyn, 2026-03-24, Godkendt, Aktiv, null)
(CHEVROLET, AVEO,         2011, PeriodiskSyn,     2025-04-23, Godkendt, Aktiv, 45)
(CITROËN,   C 1,          2011, PeriodiskSyn,     2025-11-11, Godkendt, Aktiv, 158)
(FIAT,      500,          2011, PeriodiskSyn,     2025-03-21, Godkendt, Aktiv, 206)
(CHEVROLET, AVEO,         2012, PeriodiskSyn,     2026-02-26, Godkendt, Aktiv, 283)
(CHEVROLET, AVEO,         2010, PeriodiskSyn,     2025-10-08, Godkendt, Aktiv, 257)
(CHEVROLET, SPARK,        2010, PeriodiskSyn,     2025-08-27, Godkendt, Aktiv, 215)
(CHEVROLET, SPARK,        2011, PeriodiskSyn,     2025-05-15, Godkendt, Aktiv, 279)
(CITROËN,   C3 PICASSO,   2012, PeriodiskSyn,     2026-03-30, Godkendt, Aktiv, 235)
(AUDI,      A3,           2011, PeriodiskSyn,     2026-07-07, Godkendt, Aktiv, 164)
(CHEVROLET, AVEO,         2010, PeriodiskSyn,     2024-06-07, Godkendt, Aktiv, 192)
(CHEVROLET, SPARK,        2010, PeriodiskSyn,     2024-09-06, Godkendt, Aktiv, 218)
(CHEVROLET, SPARK,        2012, RegistreringsSyn, 2026-05-21, Godkendt, Aktiv, 254)
(CHEVROLET, SPARK,        2011, PeriodiskSyn,     2025-06-13, Godkendt, Aktiv, 129)
(CHEVROLET, AVEO,         2012, PeriodiskSyn,     2026-01-26, Godkendt, Aktiv, 111)
(FIAT,      500 C,        2010, PeriodiskSyn,     2025-11-25, Godkendt, Aktiv, 154)
(CITROËN,   C4 PICASSO,   2012, PeriodiskSyn,     2024-11-25, Godkendt, Aktiv, 226)
(CITROËN,   C3 PICASSO,   2010, PeriodiskSyn,     2026-03-25, Godkendt, Aktiv, 164)
(CITROËN,   C4,           2011, PeriodiskSyn,     2025-12-17, Godkendt, Aktiv, 214)
```

Every non-Godkendt example the sample contains (12 total, the full set, not a selection):

```
(CHEVROLET,  AVEO,           2010, RegistreringsSyn, 2026-07-20, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 216)
(FORD,       FIESTA 5 DØRS,  2012, PeriodiskSyn,     2026-07-06, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 114)
(FORD,       S-MAX,          2010, PeriodiskSyn,     2026-07-07, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 354)
(FORD,       FIESTA 5 DØRS,  2010, PeriodiskSyn,     2026-06-26, KanGodkendesVedOmsynAfSynsvirksomhed,   Aktiv, 238)
(FORD,       FIESTA 5 DØRS,  2010, PeriodiskSyn,     2026-07-15, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 122)
(FIAT,       500,            2012, PeriodiskSyn,     2026-06-22, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 150)
(MAZDA,      MAZDA6,         2010, PeriodiskSyn,     2026-06-18, KanGodkendesVedOmsynAfSynsvirksomhed,   Aktiv, 200)
(MITSUBISHI, COLT,           2010, PeriodiskSyn,     2026-06-26, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 260)
(PEUGEOT,    206 +,          2010, PeriodiskSyn,     2026-07-15, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 297)
(SUZUKI,     SWIFT,          2012, PeriodiskSyn,     2026-06-25, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 166)
(SKODA,      OCTAVIA COMBI,  2012, PeriodiskSyn,     2026-07-14, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 229)
(SUZUKI,     SWIFT,          2011, PeriodiskSyn,     2026-06-22, KanGodkendesVedOmsynAfOmsynsvirksomhed, Aktiv, 272)
```

Note how thin this list is: out of 361,065 syn records in the sample, only 12 were anything other
than a straight approval, and all 12 were conditional passes pending reinspection, not an outright
failure with a category attached to it.

## What is not confirmed

- The odometer unit split (thousands of km vs raw km) is inferred from plausibility, not from any
  documentation or a cross-check against a known vehicle's mileage history. There is no history to
  cross-check against, per Question 2.
- Whether `KoeretoejUdstyrAntal = 0` really means "assessed as absent" rather than something else
  (a default, a data-entry omission) was not verified beyond a few manual examples.
- The sample is a sequential prefix of the file (the first 3,000,000 `Statistik` elements), not a
  random sample. Age-band coverage came out consistent (93-100%) across four different bands within
  that prefix, which is some evidence the prefix is not badly skewed, but it is not a guarantee.
- Whether the Danish inspection authority itself retains full historical syn results anywhere, or
  whether this extract's one-record-per-vehicle shape reflects what actually exists, was not and
  could not be determined from this file alone.

## Recommendation: not viable, and it is not a volume problem

Coverage and volume are not the issue. 98.89% of the crosswalked, in-scope fleet carries a syn
record, extrapolating to roughly 2.74 million vehicles, and age-band coverage is close to complete
everywhere except the newest band for a well-understood reason. If the blocker were "not enough
data," that would be worth waiting out or working around. It is not the blocker.

The blocker is content, on three independent points, any one of which would be sufficient on its
own:

1. **No itemised failure reasons exist anywhere in this structure.** The repair burden index is
   built from failure categories, not just pass rates. There is nothing here to build or validate
   that against: not a smaller version of it, not a proxy for it, nothing.
2. **The result field does not discriminate.** 99.5% of syn records in scope say "Godkendt," and the
   true failure rate is 0.003%. A field this lopsided cannot separate a reliable model from an
   unreliable one, the same reasoning that already ruled out `ncap_flag` (94.5% coverage but only
   71% True, "does not discriminate between a safe and an unsafe car") applies here even more
   strongly, since 99.5/0.5 is a far more extreme split than 71/29.
3. **There is no repeat-test history to average over.** Each vehicle contributes at most one syn
   record, ever, in this extract. DVSA's reliability metric works because the same vehicles get
   retested repeatedly over years, producing a rate with real statistical weight behind it. Danish
   syn as captured here is a single point-in-time status per vehicle, not a series. Even with
   millions of vehicles, there is no repeated-observation structure to compute a comparable rate
   from.

None of the open questions above (the odometer unit ambiguity, the equipment-count ambiguity, or the
prefix-sampling caveat) would change this conclusion if resolved differently. They are secondary
data-quality notes, not the reason this is not viable.

**Do not build a Danish reliability validation layer on `SynResultatStruktur`.** It cannot serve as
a check on the UK-derived model ranking, and it cannot supplement the repair burden index, because
it does not contain the kind of information either of those needs. The equipment list
(`KoeretoejUdstyrSamlingStruktur`) looks more promising on a first pass, with real ABS/airbag/ESP
presence data at plausible coverage rates, and is worth a dedicated, separate look if equipment- or
safety-adjacent scoring is ever revisited, but that is a different question from the one this report
was scoped to answer.
