# Phase 1 — Local warehouse

Status: complete. All required tables built, queryable, and reconciled against source
files. See [phase1_crosswalk_prep.md](phase1_crosswalk_prep.md) for the Phase 2 handoff
data specifically.

## Tables built

| table | rows | grain |
|---|---|---|
| `dmr_vehicles` (view over Parquet) | 9,256,188 | one row per DMR Statistik element, Personbil only, all history |
| `dk_fleet` | 29,042 | one row per (make, model, variant), in-scope vehicle count |
| `mot_tests` | 80,417,823 | one row per MOT test, class 4 (passenger cars) only, 2024+2025 |
| `mot_failures` | 175,088,297 | one row per failure/advisory item, scoped to class-4 tests, joined to category |
| `failure_categories` | 21,069 | resolved item_detail x item_group lookup (the fourth table) |

`dmr_vehicles_scoped` is also present as an intermediate view (deduped by chassis,
BEV excluded, 2010-2022, Registreret) — `dk_fleet` is the aggregate on top of it.

## Reconciliation against source files

- **mot_tests**: 80,417,823 rows. Raw combined 2024+2025 results CSVs total
  85,365,121 rows across all vehicle classes; class 4 is ~94% of rows in both years
  per Phase 0 sampling, and 80.4M / 85.4M = 94.2% — reconciles.
- **mot_failures**: 175,088,297 of 184,300,878 raw failure-item rows retained
  (94.9%) after scoping to class-4 test_ids via the join to `mot_tests` — same
  ~94% proportion, reconciles.
- **dmr_vehicles**: 9,256,188 of 13,981,687 total DMR records are Personbil
  (66.2%), extracted and counted in the same single pass, self-consistent by
  construction. Total record count (13,981,687) is within 6% of Phase 0's
  byte-size extrapolation (~14.9M), which was always presented as an estimate.
- **dk_fleet**: 1,778,307 in-scope vehicles (from 2,006,766 deduped, minus BEV)
  aggregate to 29,042 variant rows — arithmetic checked directly against
  `dmr_vehicles_scoped`, no discrepancy.

## Decisions applied (per Opus's Phase 1 handover)

1. **Pass rate scoped to initial tests only.** The acceptance query filters
   `test_type = 'NT'`, treats `PRS` as a failure, and excludes aborted results
   (`ABR`/`ABA`/`ABRVE`) from the denominator entirely. Verified: 0.42s for the
   full pass-rate-by-make query (limit was 10s).
2. **`mot_tests` scoped to `test_class_id = 4`** at load time (passenger cars),
   not deferred to query time.
3. **`dmr_vehicles` kept at raw per-record grain; `dk_fleet` built as the
   aggregate on top**, exactly as specified — needed for Phase 3's depreciation
   work, which wants first-registration-date *distributions*, not just a
   variant-level count.
4. **`dk_fleet` filtered to `registration_status = 'Registreret'`** (currently
   active), not the full historical dump.

## Two bugs found and fixed during the build (not present in Phase 0's findings)

**DVSA 2024 has two publications; the one downloaded in Phase 0 was corrupt.**
Investigated the discrepancy Opus flagged (66.9M vs 42.7M rows for what should be
comparable years). Found a second file on the index page,
`dft_test_result_extracts_2024.zip` / `dft_test_item_extracts_2024.zip`, matching
2025's naming and packaging convention. Direct comparison on January 2024 alone:
the old-naming file has 6,140,788 rows but only 3,783,238 distinct `test_id`
values — the same test record (byte-identical, including the same `test_id`)
repeated up to 14+ times for a single vehicle in the worst case observed. The
new-naming file has zero duplication (rows == distinct test_ids) and 99.98%
vehicle_id overlap with the old file, confirming it's the same underlying data,
correctly exported. **Switched to the new-naming 2024 files as canonical**; the
old-naming ones are downloaded but unused.

**BEV vehicles were leaking into `dk_fleet`.** First build of the crosswalk
report showed Tesla Model 3 and Model Y in the top 50 models by fleet count —
the brief explicitly excludes BEV from v1 scope, and this filter had been
missed. Fixed: `dk_fleet` now excludes `fuel_type_primary = 'El'`
(245,323 vehicles, 12.2% of the pre-exclusion in-scope fleet). `dmr_vehicles`
itself is left inclusive of all fuel types, since it's the raw supporting table.

## Findings that materially change the DMR extraction (beyond Phase 0's report)

**Kerb weight is two different, non-interchangeable fields depending on
vehicle age**, not one field with a naming quirk. Phase 0 measured 48.9% null
on `KoeretoejOplysningEgenVaegt` across the full history and didn't investigate
further. Restricting to the v1 scope (2010-2022) made it *worse* (98.2% null),
which led to finding `KoeretoejOplysningKoereklarVaegtMinimum` — a newer field
used by ~99.4% of in-scope records, but **not a synonym**: it's the EU "mass in
running order" definition (includes near-full fuel tank), sampled at ~8-10%
heavier than `EgenVaegt` for the same vehicle where both are present. Both are
kept as separate columns (`egen_vaegt_kg`, `koereklar_vaegt_min_kg`) rather than
coalesced, since merging them would quietly bias any weight-based metric
depending on which field a given record happened to report. **Phase 3 needs to
pick a standardization approach deliberately** before computing anything
weight-dependent (repair burden, engagement score).

**CO2 and door count exist** — Phase 0 flagged both as "not found in ~2.3M
sampled records" and left it open. A full leaf-tag vocabulary scan (built into
this pass) found both: `KoeretoejMiljoeOplysningCO2Udslip` (CO2 g/km, nested per
fuel entry like consumption) and `KoeretoejOplysningAntalDoere` (door count).
Both are now in `dmr_vehicles`. One caveat: a `0.0` CO2 value showed up on
combustion-fuel entries in spot checks, which is implausible for a non-electric
car — treat `0.0` as "not measured," not a true zero, until cross-checked in
Phase 3. Also added as bonus fields (found during the same scan, cheap to
include): `model_year` (direct field, though 25.6% null in-scope — less
reliable than the derived `first_registration_year`) and `body_type` (e.g.
"Hatchback", "MPV", "Sedan").

**`Statistik` rows are not one-per-vehicle** — a 200k-record spot check found
~4.4% of `KoeretoejIdent` values recurring with the *same* chassis number and
registration number but *different* `LeasingGyldigFra`/`LeasingGyldigTil`
dates, and reordered (not differing) equipment lists. A `Statistik` element
looks to be emitted per leasing-period snapshot for leased vehicles. Left
unhandled, this would have overstated fleet counts by about 13.8% (2,329,048
raw in-scope rows vs. 2,006,766 after deduping by chassis number, before the
BEV fix). `dk_fleet` dedupes on `chassis_number` (the VIN), keeping the most
recent snapshot per vehicle by `status_dato`.

**Hybrids are not distinguishable from pure combustion vehicles via
`fuel_type_primary`.** Phase 0 hypothesized hybrids would show up as two
`DrivmiddelStruktur` entries (primary + secondary fuel). Checked directly: zero
vehicles in the in-scope population have one `El` and one combustion fuel
entry. Hybrids are apparently recorded under their combustion fuel type alone —
the only signal is free text in `variant_name` (e.g. "2.5 Plug-in Hybrid (225
HK)"). This means the brief's "petrol / diesel / hybrid" scope is *satisfied*
(nothing hybrid gets excluded), but hybrids can't currently be isolated as
their own category for any metric that needs to treat them differently.
Isolating them would mean free-text pattern matching on `variant_name` —
flagged rather than done, per the brief's rule on fuzzy judgement calls that
could affect the ranking.

## Flagged for Phase 2 (crosswalk), not resolved here

- **Top 150 models (grouped by `make_id`/`model_id`) cover 83.5% of the
  in-scope fleet by vehicle count** (1,484,195 / 1,778,307) — below the Phase 2
  acceptance target of ≥85% coverage. Close, but the crosswalk will need either
  more than 150 models, or a different grouping approach, to clear the bar
  cleanly. Full top-150 list is in `phase1_crosswalk_prep.md`.
- **Model counts by ID vs. by name-string split differently**: 5,188 distinct
  (make_id, model_id) pairs vs. 5,140 distinct (make_name, model_name) strings
  — a difference of 48, smaller than the "BMW 3 SERIE vs 3'ER-SERIE" spelling
  problem from Phase 0 might have suggested, but real and worth deciding on
  explicitly before matching starts.

## Acceptance criteria

- All four required tables (`dk_fleet`, `mot_tests`, `mot_failures`, plus the
  resolved failure-category lookup as the fourth) are queryable: confirmed.
- Row counts reconcile against source files: confirmed, see above.
- Pass rate by make for 8-10 year old cars returns plausible results in under
  10 seconds: confirmed, 0.42s, results pass a sanity check (Honda/Mini/BMW
  near the top, Dacia/Ford/Renault lower — consistent with general reputation).
