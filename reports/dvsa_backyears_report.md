# DVSA back-year extension: what four years bought over two

Status: complete. Warehouse extended from 2024/2025 to 2022-2025, Phase 3 metrics and Phase 4
rankings regenerated, site data resynced, site builds clean (1,286 pages). No crosswalk, make
alias, scoring, or metric-definition file was touched. Pre-change `pipeline/reference/` and
`site/src/data/` backed up to
`C:\Users\Markus\AppData\Local\Temp\claude\C--Users-Markus-Desktop-apps-projekt-cartierlist\9ab39029-6632-4a8b-8ccc-85e0481851dc\scratchpad\backup_20260901_144939`
before anything was regenerated.

## Downloads

All four files verified byte-exact against the sizes confirmed by HTTP HEAD before download:

| file | bytes |
|---|---|
| results_2022.zip | 1,164,809,596 |
| failure_item_2022.zip | 435,454,025 |
| results_2023.zip | 1,192,881,905 |
| failure_item_2023.zip | 460,112,607 |

`pipeline/src/download_dvsa.py` now fetches eight files (four years x results/failure-item) plus
the lookup tables and user guide. 2022/2023 use the plain `dft_test_result_<year>.zip` naming
(confirmed: the `_extracts_` naming used by 2025 404s/403s for these two years).

## The trap: the smaller zip size was compression, not less data, but the file shape underneath is genuinely different

The working hypothesis going in (deflate-compressed vs. stored-uncompressed, purely a compression
difference) was wrong on two counts, found by two separate verification passes before anything was
loaded.

**Pass 1 (structural, `pipeline/src/verify_dvsa_backyears.py`)** found the 2022/2023 results zips
use zip compression method 9 (Deflate64 / "Enhanced Deflate"), which Python's stdlib `zipfile`
cannot decompress at all. Worse: once readable, the files turned out to be **pipe-delimited, not
comma-delimited**, with **14 columns instead of 15** (no `completed_date`) on the results side, and
**5 columns instead of 6** (no `completed_date`, and the location column named `location_id` rather
than `mot_test_rfr_location_type_id`) on the failure-item side. This is a genuine schema difference,
not a compression quirk, and the run was stopped for review at this point rather than coerced.

**Pass 2 (value-domain, `pipeline/src/verify_dvsa_backyears_valuedomain.py`)** checked whether,
underneath the structural difference, the actual *values* meant the same thing -- the dangerous
class of difference, since it fails silently instead of loudly. Seven checks, both years, all
clean:

1. **`rfr_type_code`** -- same four codes (`A`, `F`, `M`, `P`) both years, no unknowns.
2. **`test_type`** -- `NT` is the dominant code both years, same spelling the metric filters on.
3. **`test_result`** -- all six known codes (`P`, `F`, `PRS`, `ABR`, `ABA`, `ABRVE`) present with
   identical spelling, no unknown values.
4. **`location_id` vs `mot_test_rfr_location_type_id`** -- both years carry exactly 60 distinct
   values, all 60 present in 2025's domain and all 60 resolve against the lookup table
   (`mdr_rfr_location.csv` in `lookup_tables.zip`; no file literally named
   `dft_mdr_rfr_location_extract.csv` was found, and `mdr_rfr_location.csv` is what
   `mot_test_rfr_location_type_id` already resolves against). Same code domain -- a rename, not a
   remap.
5. **make/model overlap (highest-risk check)** -- top 200 (make, model) pairs by test count: 92.5%
   overlap 2022 vs 2025, 94.5% 2023 vs 2025. Every non-overlapping pair on both sides is explained
   by ordinary fleet turnover across a 3-year gap (Vauxhall Vectra, Citroen Xsara, Mercedes CLK,
   Jaguar X-Type, Peugeot 307 aged out; Tesla Model 3, Skoda Kodiaq/Karoq, Hyundai Ioniq, Nissan
   Leaf, newer Ford Transit variants weren't yet volume in 2022/2023) -- no case of the same car
   spelled two different ways across vintages.
6. **date format and mileage units** -- `test_date`/`first_use_date` are `YYYY-MM-DD` both years.
   `test_mileage` mean is 74,302 (2022) / 75,734 (2023) against 77,716 (2025) -- same order of
   magnitude, same units (miles), consistent with an older cohort observed earlier in its mileage
   life, not a unit mismatch.
7. **`vehicle_id` stability across publication years (the other decisive check)** -- 25,390,457
   vehicle_ids appear in both 2022 and 2025 (81.8% of 2022's class-4 population); of those, 99.23%
   agree simultaneously on make, model, `first_use_date`, and `cylinder_capacity` (100.00% on make
   alone). 2023 vs 2025: 27,105,325 shared ids, 98.90% full agreement. Within a single year's own
   file, 0 vehicle_ids show internally inconsistent attributes. **`vehicle_id` is the same
   identifier space across publication vintages** -- the clocking filter in
   `build_phase3_metrics.py` does not need a within-year restriction.

One more quirk surfaced while running pass 2: both results files contain a handful of rows with a
literal, **unescaped** double-quote character inside the model field (32 rows in 2022, 40 in 2023 --
e.g. a vintage Hupmobile recorded as model `"A"  COUPE`), unlike 2024/2025's backslash-escaped
convention (confirmed 0 backslash-quote occurrences in either back year). Reading with quoting
disabled entirely (`quote=''`, since no field legitimately needs to embed a literal `|`) handles it.

**Deflate64 handling**: rather than shelling out to 7-Zip (which works, but only reproduces on a
machine with it on PATH), the `zipfile-deflate64` package was added to `pipeline/pyproject.toml`.
Importing it patches stdlib `zipfile` in place to add method-9 support, so
`build_dvsa_warehouse.py`'s plain `zipfile.ZipFile(...)` calls work unchanged for both vintages. If
the import ever fails, the script exits loudly naming the fix (`cd pipeline && uv sync`) rather than
silently falling back to a partial extraction.

## Per-year row counts

| year | raw rows (all classes) | class-4 scoped | class-4 share | date range | failure-item rows (raw) |
|---|---:|---:|---:|---|---:|
| 2022 | 41,632,878 | 39,314,756 | 94.4% | 2022-01-01 to 2022-12-31 | 86,352,508 |
| 2023 | 42,216,721 | 39,834,324 | 94.4% | 2023-01-01 to 2023-12-31 | 89,302,632 |
| 2024 | 42,637,055 | 40,204,815 | 94.3% | 2024-01-01 to 2024-12-31 | 91,827,424 |
| 2025 | 42,728,066 | 40,213,008 | 94.1% | 2025-01-01 to 2025-12-30 | 92,473,454 |

All four years are complete, full-year extracts of comparable size (41.6M-42.7M raw rows each),
same ~94% class-4 share. 2022/2023 are not partial years or a shifted window.

## Warehouse rebuild

`mot_tests` grew from 80,417,823 rows (2024+2025) to **159,566,903 rows** (2022-2025).
`mot_failures` grew from 175,088,297 to **341,795,992** (scoped from 359,956,018 raw, 0.10%
uncategorised -- unchanged from before, so the new years' failure items resolve against the lookup
table exactly as well as the old ones do).

A hard per-year row-count assertion now runs immediately after `mot_tests` is built, checked against
the exact numbers verified above -- the generalised version of what `compare_dvsa_2024.py` exists to
catch for 2024 specifically, so a future silent republish of any year fails the load immediately
instead of producing quiet nonsense downstream:

```
2022: expected 39,314,756, got 39,314,756 [OK]
2023: expected 39,834,324, got 39,834,324 [OK]
2024: expected 40,204,815, got 40,204,815 [OK]
2025: expected 40,213,008, got 40,213,008 [OK]
```

Warehouse file grew from ~14 GB to ~22.7 GB. 250 GB remained free afterward.

## Total tests behind the metrics, before and after

| | before (2024+2025) | after (2022-2025) |
|---|---:|---:|
| total `n_nt_tests` summed across all (model, age band) cells | 47,854,279 | 94,284,324 |
| median `n_nt_tests` per cell | 48,866 | 93,980 |
| 10th-percentile `n_nt_tests` per cell | 2,308 | 3,341 |
| (model, age band) cells, post-dedup | 635 | 635 |

Volume behind the median cell essentially doubled (1.92x), as expected. The 10th percentile moved
less (1.45x) -- the thin cells are dominated by newly-launched models (see below), which don't gain
proportionally from adding older years because the car didn't exist yet in 2022/2023.

Note on the "32 unstable" figure in the brief: the actual pre-change count in the working tree at
the start of this session was **63** `reliability_unstable` rows in `model_age_band_metrics.csv`
(22 of those also carry `exclusion_reason = reliability_unstable` specifically in
`model_bracket_rankings.csv` -- the rest are excluded from ranking for a different, higher-priority
reason first, such as `no_exit_band_data`). The 32 figure predates other in-flight work already
reflected in the dirty working tree at session start; 63 is what this extension was actually
measured against.

## Which of the 63 unstable cells clear the 2,000-test floor

**5 of 63.** All five gained enough volume from the two extra years to cross `RANKING_FLOOR_TESTS`:

| make | model | age band | tests before | tests after |
|---|---|---|---:|---:|
| Citroen | Grand C4 Picasso | 3 | 1,755 | 8,680 |
| Fiat | 500C | 1 | 1,778 | 10,627 |
| Suzuki | Ignis | 4 | 576 | 5,671 |
| Suzuki | Vitara | 3 | 1,946 | 2,144 |
| Volkswagen | California | 4 | 1,753 | 2,276 |

The other 58 stayed unstable. Most did not gain volume proportional to the doubled raw data because
they are dominated by recently-launched models (Kia Niro, Hyundai Tucson newest generation, Skoda
Kamiq/Kodiaq/Scala, Toyota Aygo X, Seat Ateca) that simply didn't exist as registered vehicles, or
existed only in small numbers, back in 2022/2023 -- two extra years of an older market don't help a
car that wasn't on sale yet. A handful of genuinely rare or unusual models (BMW 4-serie, Mercedes
CLA, Audi Q2 at 0-3 tests) stayed at effectively zero regardless of window length; that is a real
scarcity in the UK MOT record for those (model, age band) cells, not a coverage gap this extension
could fix.

## Rankings: before and after

| | before | after |
|---|---:|---:|
| total rows in `model_bracket_rankings.csv` | 621 | 621 |
| rank-eligible (`excluded_from_rank = False`) | 471 | 474 |
| excluded: `reliability_unstable` | 22 | 19 |
| excluded: `no_exit_band_data` | 86 | 86 (unchanged) |
| excluded: `insufficient_dk_fleet` | 37 | 37 (unchanged) |
| excluded: `non_positive_depreciation` | 5 | 5 (unchanged) |

**3 rows newly entered the rankings** (of the 5 that cleared the floor, 2 were still excluded for a
different reason -- Suzuki Vitara band 3 and Suzuki Ignis band 4 remain excluded on
`no_exit_band_data`/`insufficient_dk_fleet` grounds):

- Citroen Grand C4 Picasso, age band 3 (2014-2016)
- Fiat 500C, age band 1 (2020-2022)
- Volkswagen California, age band 4 (2010-2013)

No row dropped out of the rankings, and no row changed price bracket.

## The test-year mix per age band

Pooling four test years pools across model generations at a given age: a car observed at age 5 in
2022 is a 2017 car; at age 5 in 2025 it is a 2020 car. The pipeline matches on age at test (never on
registration year), so this is arithmetically fine, but the resulting rate now averages over a wider
generation span. Share of eligible tests by test year, within each age band:

| age band | 2022 | 2023 | 2024 | 2025 | total tests |
|---|---:|---:|---:|---:|---:|
| 1 (age 4-7) | 27.3% | 26.4% | 24.5% | 21.8% | 21,612,400 |
| 2 (age 7-10) | 23.4% | 25.2% | 26.1% | 25.4% | 22,941,630 |
| 3 (age 10-13) | 22.5% | 23.4% | 25.6% | 28.5% | 17,773,465 |
| 4 (age 13-17) | 23.0% | 24.8% | 25.7% | 26.4% | 15,344,231 |

The mix is close to even across all four years in every band (roughly 22-28%, no year dominating
any band), with a mild, expected drift: band 1 (the youngest cars) skews slightly toward the older
test years (27.3% 2022, 21.8% 2025) because a car that was 4-7 years old in 2022 was a newer,
smaller model-year cohort than one that's 4-7 in 2025 and had more calendar time to accumulate
tests; band 3 shows the mirror pattern (22.5% 2022, 28.5% 2025). The effect is real but modest --
no band is dominated by a single test year, so the generation-span widening this pooling causes is
visible but not severe.

## Ranking stability under doubled data

**Stable.** Comparing `cost_rank_in_group` for every row present in both the before and after
rankings: **no row moved more than 10 positions**, and the two largest movements (both exactly 10)
were BMW X3 band 4 (rank 36 -> 46) and Volkswagen Golf Variant band 4 (rank 42 -> 52). No row
changed price bracket. The next-largest movements were single digits:

| make | model | age band | before rank | after rank | delta |
|---|---|---|---:|---:|---:|
| BMW | X3 | 4 | 36 | 46 | +10 |
| Volkswagen | Golf Variant | 4 | 42 | 52 | +10 |
| Audi | A4 Avant | 4 | 95 | 103 | +8 |
| MINI | Cooper | 4 | 45 | 53 | +8 |
| Audi | A3 Sportback | 4 | 61 | 69 | +8 |
| Kia | Ceed | 3 | 32 | 39 | +7 |
| Fiat | Punto S7 | 3 | 50 | 43 | -7 |

If the ranking is stable under a doubling of the underlying test volume, that is itself a useful
finding: it says the 2024/2025-only ranking was not an artefact of a thin sample that would have
reshuffled with more data. This is worth stating plainly rather than treating a null result as
nothing happened.

## Data-quality surprises, summarised

1. **Deflate64 compression** on the 2022/2023 results zips (not the failure-item zips, which use
   standard Deflate) -- unreadable by Python's stdlib `zipfile`, worked around with the
   `zipfile-deflate64` package rather than a 7-Zip subprocess dependency.
2. **Pipe delimiter, not comma**, on both 2022 and 2023, both file types.
3. **No `completed_date` column** in either file type for the older vintage -- confirmed unused
   anywhere else in the repo (grepped `pipeline/src`, `site/`, no SQL references it) before treating
   its absence as harmless; synthesized as `NULL` in the loader.
4. **`location_id` instead of `mot_test_rfr_location_type_id`** in the failure-item file -- verified
   same 60-value code domain before aliasing it across.
5. **No backslash-quote-escaping convention** in the older vintage, but 32 (2022) / 40 (2023) rows
   carry a literal, unescaped quote character inside a model name -- handled by disabling quote
   interpretation (`quote=''`) for these files rather than treating it as CSV quoting.
6. **Zero embedded header-echo rows** in either back year (2024/2025 have ~180) -- the quirk
   `build_dvsa_warehouse.py` already filters for does not recur in the older publication, but the
   filter is harmless to leave in place.

None of these affected a single value once the loader was adapted -- every one is a parsing-layer
difference, not a semantic one, confirmed by the seven value-domain checks and the hard row-count
assertion.

## Files changed

- `pipeline/src/download_dvsa.py` -- four back-year files added, docstring rewritten to describe
  the four-year window.
- `pipeline/src/build_dvsa_warehouse.py` -- `RESULTS_ZIPS`/`FAILURE_ZIPS` extended to four years
  each; loading restructured around an explicit `RESULTS_FILE_PROPS`/`FAILURE_FILE_PROPS` table
  (delimiter, quote setting, `completed_date` presence, location column name) keyed by zip
  filename, so a shape difference is a table entry, not a year-number branch; hard per-year
  row-count assertion added after `mot_tests` loads.
- `pipeline/src/verify_dvsa_backyears.py` (new) -- structural verification pass.
- `pipeline/src/verify_dvsa_backyears_valuedomain.py` (new) -- value-domain verification pass
  (the seven checks above).
- `pipeline/pyproject.toml` / `pipeline/uv.lock` -- `zipfile-deflate64` added as a dependency.
- Regenerated, not hand-edited: `pipeline/reference/model_age_band_metrics.csv`,
  `model_age_band_category_failure_rates.csv`, `model_age_band_reliability_strata.csv`,
  `model_bracket_rankings.csv`, `methodology_counts.csv`, and `site/src/data/rankings.json`,
  `unpriced.json`, `methodology.json`.

Not touched: `crosswalk.csv`, `crosswalk_dvsa_match.csv`, `crosswalk_review.csv`,
`model_spelling_aliases.csv`, make aliases, any scoring formula, or any Phase 3/4 metric
definition. Confirmed byte-identical to the session-start backup.

## Acceptance criteria

1. Four years present in the warehouse, each independently verified before loading: **yes** -- two
   verification passes (structural, then value-domain), both years, before `build_dvsa_warehouse.py`
   was changed.
2. Metrics and rankings regenerated, pre-change state backed up: **yes** -- backup at the path
   above, taken before any regeneration.
3. Report exists and answers every question with real numbers: **yes**, this document.
4. Nothing outside the DVSA ingest path changed: **yes**, confirmed by diff against the
   session-start backup for crosswalk/scoring files, and by `git status`.
