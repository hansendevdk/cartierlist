# Phase 0 — Schema report

Status: DVSA section complete. DMR section pending (large FTP download in progress).

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

Status: **pending** — the file is a ~6.7 GB zip on a low-throughput, unsupported FTP
server (observed ~2 MB/s, and the first attempt stalled silently at 99.9998% complete
with no error, so the download script now has a socket timeout and byte-offset resume
built in). This section will be filled in once the file finishes downloading and has
been stream-parsed with `lxml.etree.iterparse`.
