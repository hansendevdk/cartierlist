# PROJECT BRIEF — Danish Car Value Index

## Role

You are implementing a data pipeline and static site. Work **one phase at a time**. At the end of each phase, stop, report against the acceptance criteria, and wait for review before starting the next phase. Do not scaffold future phases early.

## Objective

Produce a tier list of used cars available in Denmark, ranked by real cost of ownership within price brackets, so that a buyer can see where the value curve peaks. Output is **ordinal** — ranking correctly matters, quoting exact kroner does not.

## Non-negotiable constraints

- Metric units throughout. Prices in DKK. Consumption in km/l (convert from mpg where needed).
- **Do not scrape Bilbasen, DBA, or any classifieds site.** No official API exists and their listing databases are protected under EU Directive 96/9/EC.
- **Do not extract TÜV Report or ADAC Pannenstatistik tables.** Copyright and database right. You may reference published headline figures in prose only.
- Attribute DVSA data as required by Open Government Licence v3.0.
- Prefer EU/Danish sources. No US retailer references in output copy.
- Target runtime environment: my own machine for the pipeline, Cloudflare Pages for the site. No paid services in v1.

## Stack

| Layer | Choice | Reason |
|---|---|---|
| Bulk processing | **DuckDB** | Reads CSV/Parquet directly, handles 30M+ rows locally, no server. Do not load raw MOT data into Postgres. |
| Aggregate storage | Supabase Postgres | Only final per-model aggregates (~150 rows × ~30 columns). Free tier is 500 MB — raw data will not fit and must not be pushed. |
| Site | Astro, static output | Data refreshes annually. No SSR, no runtime API calls. |
| Hosting | Cloudflare Pages | Existing account. |
| Language | TypeScript for site, Python for pipeline | |

## Scope for v1

- Market: Denmark.
- Vehicle class: passenger cars (personbiler), petrol / diesel / hybrid. Exclude BEV from v1 (insufficient age-band data).
- Model years: 2010–2022.
- Universe: top 150 models by count in the Danish fleet.
- Price brackets: five, boundaries determined from data in Phase 4, not hardcoded up front.

## Data sources

### DMR statistics extract — Danish vehicle fleet and technical specs
- FTP: `ftp://dmr-ftp-user:dmrpassword@5.44.137.84`
- Username `dmr-ftp-user`, password `dmrpassword`
- Files named `ESStatistikListeModtag-<timestamp>.zip`, refreshed weekly on Monday
- Very large. Expect XML. Use a **streaming parser** (`lxml.etree.iterparse` or equivalent) — do not load into memory
- Free, no support, no uptime guarantee. Cache the download locally; do not re-fetch on every run
- Fields of interest include: make, model, variant, first registration date, fuel type, fuel consumption, CO2, kerb weight, engine power, cylinder count, door count, Euro NCAP flag

### DVSA anonymised MOT data — reliability backbone
- Index: `https://open.data.dvsa.gov.uk/mot-anonymised/index.html`
- Download `MOT testing data results (<year>)` and `MOT testing data failure item (<year>)` for the two most recent available years
- Also download `MOT testing data lookup tables` (ZIP) and the post-May-2018 user guide — the failure item codes are meaningless without them
- Licence: Open Government Licence v3.0. Commercial use permitted with attribution
- Treat `PRS` (pass after rectification at station) as a failure. Exclude advisory items from failure counts
- Only include models with a sufficient test count for statistical stability — set the threshold explicitly and document it

### Fuel prices
- `fuelprices.dk` public JSON API, or OK / Circle K public endpoints
- Fetch once per build, cache

## Phase plan

### Phase 0 — Acquisition and reconnaissance
Download both datasets. Do not transform anything yet. Produce a written schema report: actual field names, types, row counts, null rates, and any encoding problems. Identify how make/model/variant is represented in each source, with 20 real examples from each.

**Acceptance:** schema report exists; both datasets are on disk; I can read the report and understand what the model-name strings actually look like in each source.

### Phase 1 — Local warehouse
Load both sources into DuckDB as Parquet-backed tables. Build derived tables:
- `dk_fleet` — one row per Danish variant, with count of registered vehicles
- `mot_tests` — one row per test
- `mot_failures` — one row per failure item, joined to its category via the lookup tables

**Acceptance:** all four tables queryable; row counts reconcile against the source files; a query for "pass rate by make for 8–10 year old cars" returns plausible results in under 10 seconds.

### Phase 2 — Crosswalk (HARD — expect this to dominate the timeline)
Build a mapping between DMR model identities and DVSA make/model strings.

Approach: generate candidate pairs by normalised string similarity, then emit a **review file** (CSV) of candidates ranked by confidence for me to confirm or reject by hand. Do not silently auto-accept fuzzy matches. Store confirmed mappings in a version-controlled `crosswalk.csv` that is treated as source code, not generated output.

Cover the top 150 Danish models by fleet count. Report coverage as a percentage of the Danish fleet, not as a percentage of models.

**Acceptance:** `crosswalk.csv` covers ≥85% of the Danish passenger-car fleet by vehicle count; every row is either human-confirmed or flagged `unreviewed`; no unreviewed rows feed downstream metrics.

### Phase 3 — Metrics
Compute per model per age band:

1. **Reliability index** — pass rate, plus failure rate by category. Normalise for average odometer reading, since a model driven 20,000 km/year is not comparable to one driven 8,000.
2. **Repair burden index** — failure frequency by category × a per-make parts-cost multiplier. The multiplier table is a hand-authored reference file of ~40 entries (one per make, roughly 0.7 for Dacia to 2.6 for Land Rover). Hardcode it as versioned reference data with a comment explaining the basis. Do **not** attempt per-model parts pricing in v1.
3. **Fuel cost per year** — km/l from DMR × 15,000 km × current fuel price.
4. **Grøn ejerafgift** — computed from fuel consumption per current Danish law. Look up the live rate bands; do not guess them.
5. **Depreciation** — fit from DMR first-registration date distributions against new-price data where available. If new-price data is unobtainable, state that and use a published Danish depreciation curve instead, clearly flagged as an assumption.
6. **Engagement score** — kW/kg, kerb weight, cylinder count. Label it explicitly in the output as computed and subjective, not sourced.

**Acceptance:** a single table with one row per (model, age band) and all six metrics populated; every metric has a documented formula; obviously wrong outliers investigated and explained, not silently clipped.

### Phase 4 — Brackets and tiers
Determine five price brackets from the actual distribution of the eligible fleet. Within each bracket, rank by total annual cost of ownership and assign tiers (S/A/B/C/D or similar). Identify and highlight the bracket where cost-per-utility is minimised — this is the headline finding of the site.

**Acceptance:** bracket boundaries justified from data; tier assignments reproducible from a single script; results pass a sanity check against my own intuition about the Danish market, which I will apply.

### Phase 5 — Site
Astro, static, no client-side data fetching. Pages: overview with the value curve, one page per bracket, one page per model. Include a prominent methodology page covering data sources, licences, the UK-market caveat, and the limits of the repair index.

**Acceptance:** builds clean; deploys to Cloudflare Pages; Lighthouse accessibility 100; methodology page is honest about limitations.

## Known risks to surface early, not paper over

- UK MOT data reflects UK-market variants, UK roads and UK salt. Model-level *relative* reliability transfers; absolute failure rates do not. If you find a model where UK and Danish variants clearly differ mechanically, flag it rather than including it.
- Used prices are the weakest input. If the depreciation model looks unreliable, say so loudly — the entire bracket axis depends on it.
- Danish tax law changes. Any hardcoded rate needs a comment with the date it was verified.

## Working style

- Small commits, one concern each.
- Every non-obvious decision gets a comment explaining *why*, not what.
- If a phase's acceptance criteria cannot be met, stop and tell me what is blocking rather than lowering the bar and continuing.
- If you find yourself about to fuzzy-match, estimate, or interpolate something that materially affects the ranking, stop and ask.
