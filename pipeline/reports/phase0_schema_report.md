# Phase 0 — Schema report

Status: complete. Both sources downloaded and characterised.

## DVSA anonymised MOT data

Source: `open.data.dvsa.gov.uk/mot-anonymised`. Licence: Open Government Licence v3.0.
Downloaded the two most recent complete years (2024, 2025), the lookup tables zip, and the
user guide (v5.1, `.odt`). All six files verified against `Content-Length` after download.

DVSA changed their file-naming and packaging convention between 2024 and 2025:
2024 files are deflate-compressed zips built on a Mac (each contains a parallel
`__MACOSX/` tree of AppleDouble resource-fork junk with the same `.csv` extension,
which must be filtered out by path, not just extension). 2025 files are **stored**
(uncompressed) zips with no Mac cruft, which is also why the 2025 zip is larger on
disk than 2024 despite covering a similar number of rows.

### `test_result_*.csv` (one row per MOT test)

Delimiter: comma. Encoding: UTF-8 (clean in the real CSVs; only the `__MACOSX` junk
files in the 2024 zip fail UTF-8 decode, and those aren't data).

| field | type | notes |
|---|---|---|
| test_id | integer | primary key for a test |
| vehicle_id | integer | stable per physical vehicle across tests |
| test_date | date (YYYY-MM-DD) | |
| test_class_id | small int, values seen: 1,2,3,4,5,7 | MOT vehicle class. Class 4 dominates (~94% of 2024 rows, ~94% of 2025) and is the passenger-car class; 1/2 are motorcycles, 7 is larger passenger vehicles. Scope filtering to decide in Phase 1. |
| test_type | code, e.g. NT (normal test) | see `mdr_test_type.csv` in lookup tables |
| test_result | code: P, F, PRS, ABR, ABA, ABRVE | P=pass, F=fail, PRS=pass after rectification (brief says treat as failure), ABR/ABA/ABRVE=aborted variants — see `mdr_test_outcome.csv` |
| test_mileage | float, odometer reading | 0.8% null in 2024, 0% null in 2025 |
| postcode_area | string, e.g. "OX" | UK postcode area, not useful for Danish matching |
| make | string, e.g. "PORSCHE" | free text, all-caps |
| model | string | **inconsistent granularity** — see examples below |
| colour | string | |
| fuel_type | code, e.g. "PE" | see `mdr_fuel_types.csv` |
| cylinder_capacity | integer, cc | 1.2–1.9% null (electric/some motorcycles) |
| first_use_date | date | |
| completed_date | ISO 8601 datetime | |

Row counts (real data rows, excluding header and `__MACOSX` junk):

- `results_2024.zip`: **66,857,535** rows across 12 monthly files (+ 12 junk entries, correctly skipped)
- `results_2025.zip`: **42,728,066** rows across 12 monthly files (2025 is a partial/complete year depending on when DVSA last published; verify before treating as a full year)

**Data quality issue found:** the 2024 files contain **180 duplicate embedded header
rows** scattered through the real CSVs (i.e. the literal string `"test_result"` appears
180 times as a data value, same for `"test_class_id"`). Negligible in volume
(180 / 66.8M ≈ 0.0003%) but must be filtered by value, not assumed absent, when
loading into DuckDB in Phase 1. Not present in the 2025 files.

**Data quality issue found:** at least one model name contains a literal double-quote
escaped with a backslash rather than doubled per RFC 4180 (e.g.
`PEUGEOT,"STREETZONE 50 2T 12\"",GREEN`, a scooter with a 12" wheel size). Standard
`csv.reader` treats this as an unterminated quoted field and merges subsequent lines
into one giant field until it either hits a later stray quote or exceeds Python's
default field-size limit. Fix: parse with `escapechar='\\'`. Likely to affect a small
number of Danish DMR variant strings too if a similar export tool wrote them — check
in the DMR section.

### 20 real make/model examples (test_class_id = 4, i.e. cars), from `results_2025.zip`

```
('ALFA ROMEO', '147')
('ALFA ROMEO', '159')
('BMW', '1 SERIES')
('BMW', '116')
('BMW', '118')
('BMW', '120')
('BMW', '218')
('BMW', '220I M SPORT AUTO')
('LAND ROVER', '109')
('LAND ROVER', '110')
('MAZDA', '2')
('MAZDA', '3')
('PEUGEOT', '107')
('PEUGEOT', '108')
('PEUGEOT', '2008')
('PEUGEOT', '2008 GT PREMIUM PURETECH S/S A')
('PEUGEOT', '206')
('PEUGEOT', '207')
('PEUGEOT', '208')
('ROVER', '25')
```

**Important for Phase 2 (crosswalk):** the `model` field is not a consistent grain.
Sometimes it's a bare model line (`208`, `3`, `118`), sometimes it embeds trim,
engine, and transmission (`2008 GT PREMIUM PURETECH S/S A`, `220I M SPORT AUTO`).
Any string-similarity matching against DMR will need to normalise/truncate these
before comparing, and that normalisation step is itself a judgement call that
should go through the human-reviewed crosswalk file, not be silently automated.

### `test_item_*.csv` (one row per failure/advisory item on a test)

Delimiter: comma. Same encoding profile as results (2024 has `__MACOSX` junk + UTF-8
decode errors on the junk only; 2025 is clean).

| field | type | notes |
|---|---|---|
| test_id | integer | foreign key to test_result.test_id |
| rfr_id | integer | foreign key to `item_detail.csv` (reason-for-rejection detail) |
| rfr_type_code | code: A, P, M, F | see below |
| mot_test_rfr_location_type_id | integer | foreign key to `mdr_rfr_location.csv` |
| dangerous_mark | string, almost always empty | ~96% null — sparse by design, only populated when an item is flagged dangerous, not a data quality problem |
| completed_date | ISO 8601 datetime | |

`rfr_type_code` distinct values and approximate share (2024): A (advisory) 66%,
F (fail) 23%, M (minor, post-May-2018 category) 8%, P (prohibition/dangerous) 3%.
The brief says exclude advisories from failure counts — that's a filter on
`rfr_type_code != 'A'` (need to confirm M/P/F categorisation against the user
guide in Phase 3, not guessed here).

Row counts:

- `failure_item_2024.zip`: **109,170,012** rows (also has 180 embedded duplicate headers, same pattern as results)
- `failure_item_2025.zip`: **92,473,454** rows (clean)

### Lookup tables (`lookup_tables.zip`, pipe-delimited `|`, not comma)

| file | rows | purpose |
|---|---|---|
| item_detail.csv | 21,070 | rfr_id -> category/description, links failure items to human-readable reasons |
| item_group.csv | 4,137 | test_item_id hierarchy (parent/child grouping of inspection items) |
| mdr_fuel_types.csv | 15 | fuel type code -> name (e.g. DI = Diesel) |
| mdr_rfr_location.csv | 130 | location id -> lateral/longitudinal/vertical position on the vehicle |
| mdr_test_outcome.csv | 8 | test_result code -> name (confirms PRS = "Passed after rectification at station") |
| mdr_test_type.csv | 7 | test_type code -> name |

All six are ASCII, clean, no nulls observed, no size concerns (largest is 3.6 MB).

### User guide

`user_guide_v5.1.odt` downloaded, not yet read in full — needed in Phase 1/3 to
correctly interpret `rfr_deficiency_category` and the M/P/F split introduced
post-May-2018.

---

## DMR statistics extract

Source: FTP drop at `5.44.137.84`, file `ESStatistikListeModtag-20260726-153441.zip`
(this week's Monday refresh, downloaded 2026-07-30). The zip is 6.7 GB compressed but
holds a single **127.8 GB uncompressed XML file** — far too large to extract to disk
(185 GB free on the machine) or hold in memory. All inspection here streams directly
out of the zip with `lxml.etree.iterparse`, clearing each element after processing.

The download itself was unreliable: the FTP server stalled silently (open socket, no
data, no error) at 99.9998% complete on the first attempt, and a background-task
interruption (unrelated: the machine was shut down mid-run) killed a second attempt.
Neither lost any downloaded bytes — `download_dmr.py` now sets a socket timeout and
resumes from the last written byte offset on retry, and the final file's size was
verified against the FTP server's reported size before being treated as complete.
This matches the brief's warning that this host has "no support, no uptime guarantee."

### Structure

One XML document, root `<ns:ESStatistikListeModtag_I>`, namespace
`http://skat.dk/dmr/2007/05/31/`, containing a flat sequence of repeating
`<ns:Statistik>` elements — **one element per vehicle**, not per model. This is a
materially different grain from what Phase 1's `dk_fleet` table wants ("one row per
Danish variant, with count of registered vehicles") — Phase 1 will need to aggregate
by (make, model, variant) and count, not load rows 1:1.

Each `Statistik` element is deeply nested. Fields relevant to the brief, with their
path from `Statistik` (namespace prefix omitted for readability):

| brief field | actual XML path | notes |
|---|---|---|
| vehicle type | `KoeretoejArtNavn` | e.g. "Personbil" — see distinct values below, **the file is not passenger-cars-only** |
| make | `.../KoeretoejBetegnelseStruktur/KoeretoejMaerkeTypeNavn` | free text, e.g. "CITROËN", "BMW" |
| model | `.../KoeretoejBetegnelseStruktur/Model/KoeretoejModelTypeNavn` | e.g. "XANTIA", "3 SERIE" |
| variant | `.../KoeretoejBetegnelseStruktur/Variant/KoeretoejVariantTypeNavn` | e.g. "2,0 HDI", "320I AUT." — Danish decimal commas, mixed trim/engine/gearbox text similar to DVSA's `model` field |
| first registration date | `.../KoeretoejOplysningFoersteRegistreringDato` | date, e.g. `1999-12-08+01:00` (has explicit UTC offset) |
| fuel type | `.../DrivmiddelStruktur/DrivkraftTypeStruktur/DrivkraftTypeNavn` | e.g. "Diesel", "Benzin" (petrol) — see distinct values below |
| fuel consumption | `.../DrivmiddelStruktur/KoeretoejBraendstofStruktur/KoeretoejMotorKmPerLiter` | **already km/l**, no mpg conversion needed for this source |
| CO2 | not found in ~2.3M sampled records | not observed in any sampled record; may be present only for newer type-approvals, or under a tag not yet seen. Needs a targeted search before Phase 1, not assumed absent |
| kerb weight | `.../KoeretoejOplysningEgenVaegt` | kg |
| engine power | `.../KoeretoejMotorStruktur/KoeretoejMotorStoersteEffekt` | unit not confirmed from data alone (likely kW) — cross-check against a known model in Phase 1 |
| cylinder count | `.../KoeretoejMotorStruktur/KoeretoejMotorCylinderAntal` | integer |
| door count | not found in ~2.3M sampled records | not observed; may not exist in this source at all — flag to you rather than assume |
| Euro NCAP flag | `.../KoeretoejOplysningNCAPTest` | boolean, matches brief directly |

A vehicle can have **multiple** `DrivmiddelStruktur` entries (a repeating group), each
flagged `KoeretoejMotorDrivmiddelPrimaer` true/false — this is almost certainly how
hybrids are represented (primary + secondary fuel), not a separate "Hybrid" fuel-type
label. No fuel-type value literally says "Hybrid" in the sample. This needs confirming
against real hybrid vehicles in Phase 1/2, flagged here rather than assumed.

Each vehicle also carries a repeating `SynResultatStruktur` (Denmark's periodic
vehicle inspection, "syn" — the closest domestic equivalent to the UK's MOT, though
the brief's reliability backbone is DVSA, not this) and a repeating equipment list
(`KoeretoejUdstyrSamlingStruktur`) with things like ABS, airbags, ESP — a possible
future input for the engagement/equipment scoring but out of scope for the metrics
listed in the brief.

### Row counts and sampling

A full single-pass count was not run in Phase 0 — at the sustained throughput
measured (~7,300 records/sec), a full pass over the estimated ~15M records would take
roughly 35 minutes of pure parsing time, which is Phase 1's job (building the actual
Parquet-backed tables), not schema reconnaissance. Instead:

- Timed a clean 2,000,000-record sample (273.8s, 7,303 rec/s sustained, no slowdown
  across four 500k checkpoints — the rate looks stable, not front-loaded).
- Estimated total record count by dividing the file's known uncompressed size
  (127,779,440,161 bytes) by the average bytes/record measured over a 300,000-record
  sample (8,566 bytes/record): **≈ 14.9 million vehicle records total**, of which
  **≈ 61% are `Personbil`** in the sampled proportion (61.4% in the 2M sample) →
  **≈ 9.1 million passenger-car records**, spanning all history (active,
  deregistered, scrapped, exported) — not 9.1 million *available* used cars.

This estimate is good enough to confirm DuckDB is the right tool (brief already
assumed "30M+ rows," this is in the same order of magnitude) and to size Phase 1's
ingestion job. Phase 1 will produce the exact count as a byproduct of loading.

### Null rates for fields of interest

Measured over the 2,000,000-record sample, both across all vehicle types and
restricted to `Personbil` only (the restriction matters a lot — trailers and mopeds
don't have engines, so pooling them with cars understates how complete the *car* data
actually is):

| field | null rate, all types | null rate, Personbil only |
|---|---|---|
| first registration date | 0.008% | 0.009% |
| make | 0.000% | 0.000% |
| model | 0.000% | 0.000% |
| variant | 0.000% | 0.000% |
| fuel type | 5.927% | 0.000% |
| fuel consumption (km/l) | 47.783% | 25.164% |
| kerb weight | 42.270% | 48.858% |
| engine power | 53.510% | 42.186% |
| cylinder count | 58.565% | 47.989% |
| Euro NCAP flag | 62.844% | 46.048% |

**This is the single biggest risk surfaced in Phase 0.** Even restricted to
passenger cars, kerb weight, engine power, cylinder count, and the NCAP flag are each
missing on roughly **half** of all records. Fuel consumption (needed for the fuel-cost
and ejerafgift metrics) is missing on a quarter of Personbil records. This is very
likely concentrated in older vehicles (data entry requirements tightened over time —
note record 1 in the manual sample, a 1999 Citroën, is missing several of these
fields that record 2, a 2006 Citroën, has), which may be tolerable if the v1 model-year
scope (2010–2022) is much more complete than the full historical dump. **This needs to
be re-measured restricted to 2010–2022 first-registration dates before Phase 3 metrics
are built on top of it** — flagging now rather than discovering it after the crosswalk
work in Phase 2 is done.

### Distinct values found

`KoeretoejArtNavn` (vehicle type), 2M sample — **the raw file is not passenger-cars-only**,
Phase 1/2 must filter on this field:

```
Personbil (passenger car): 1,228,678 (61.4%)
Varebil (van): 216,069
Paahaengsvogn (trailer): 275,184
Motorcykel (motorcycle): 49,235
Traktor: 40,833
Campingvogn (caravan): 42,857
Lastbil (truck): 36,747
Saettevogn (semi-trailer): 28,559
Lille knallert (small moped): 34,788
Stor knallert (large moped): 26,299
Stor personbil (large passenger car): 7,288
Paahaengsredskab: 8,882
Traktorpaahaengsvogn: 2,771
Motorredskab: 1,479
Blokvogn: 230
Motordrevet blokvogn: 101
```

`DrivkraftTypeNavn` (fuel type), 2M sample:

```
Benzin (petrol): 1,267,243
Diesel: 544,760
El (electric — excluded from v1 per brief): 122,230
F-Gas (LPG): 498
Brint (hydrogen): 78
N-Gas (natural gas): 175
Petroleum: 23
```

`KoeretoejOplysningStatus` (record lifecycle status), 2M sample — only `Registreret`
is a currently-active vehicle; the rest are historical:

```
Registreret (active): 867,166 (43.4%)
Afmeldt (deregistered): 781,173
Skrottet (scrapped): 233,149
Eksporteret (exported): 118,305
Oprettet (created, not yet active): 135
HarGennemfoertRegistreringssyn: 72
```

The full historical dump (registered/deregistered/scrapped/exported all mixed
together) means Phase 1/2 must filter to `Registreret` to represent cars actually
available in the Danish market today — using the raw record count would badly
overstate current fleet size.

### 20 real make/model/variant examples

```
('BMW', '3 SERIE', '320I')
('CHRYSLER', 'GRAND VOYAGER VAN', '2,5 CRD')
('AUDI', 'A4', '2,6 AUT.')
('BMW', '5`ER', '525 I AUT.')
('CITROËN', 'GRAND C4 PICASSO', 'HDI 110 AUT.')
('FIAT', 'MULTIPLA', '1,6')
('CHEVROLET', 'CRUZE', '1,6')
('CITROËN', 'ZX', '1,4')
('AUDI', 'A4 AVANT', '2,5 TDI')
('BMW', "3'ER-SERIE", '320 I')
('CITROËN', 'C5', 'HDI 140')
('FIAT', 'PUNTO', 'CABRIO 90')
('FIAT', 'RITMO', 'UOPLYST')
('CITROËN', 'C 4', '1,6 HDI AUT.')
('FIAT', 'CROMA', 'I.E. KAT.')
('AUDI', 'A6', '3,0 TDI AVANT')
('ALFA ROMEO', '159 SPORT WAGON', '1,9 JTDM AUT.')
('AUDI', 'A 4', '1,6 LIMOUSINE')
('CITROËN', 'C3', 'E-HDI 70 AUT.')
('AUSTIN', 'METRO', 'UOPLYST')
```

Notable for Phase 2 (crosswalk): make spelling is inconsistent even within one
source — "BMW 3 SERIE" vs "BMW 3'ER-SERIE" vs "BMW 3`ER" (three different strings
for the same model line, including a stray backtick used as an apostrophe).
`UOPLYST` ("not specified") appears as a variant value meaning "unknown," not a real
trim name — needs to be treated as null, not as data, in Phase 2/3. Danish decimal
commas in variant strings (`2,5 CRD`, `1,9 JTDM`) will need locale-aware parsing if
displacement is ever extracted from free text.

### Encoding

Confirmed clean UTF-8 **at the byte level** — verified by reading raw bytes around
Danish characters (ø, æ, Ë) and finding correct UTF-8 sequences (e.g. `\xc3\x8b` for
Ë). Important caveat for anyone re-running this inspection: **printing to a Windows
git-bash console renders these as `�` even though the underlying data is correct** —
the mangled output seen during interactive inspection was a terminal/codepage
artifact, not a real encoding problem. Don't trust what the console shows for
non-ASCII text; check bytes directly if in doubt.

### What's not yet confirmed

- **CO2 and door count**: not observed in ~2.3M sampled records combined across two
  inspection runs. Either genuinely absent from this source (plausible — Denmark's
  vehicle tax has historically been based on km/l and weight, not CO2 directly, unlike
  many EU markets) or present under a tag name not yet triggered by the sample. Needs
  a targeted full-tag-vocabulary scan before concluding CO2 must come from elsewhere.
- **Engine power units**: assumed kW from context (Danish/EU convention) but not
  confirmed against a known reference vehicle.
- **Hybrid representation**: inferred from the repeating `DrivmiddelStruktur` +
  primary-fuel-flag structure, not confirmed against an actual hybrid vehicle record.
- **Exact full-file row count**: only extrapolated from a byte-size sample, not
  measured by a full pass (see Row counts section above).
