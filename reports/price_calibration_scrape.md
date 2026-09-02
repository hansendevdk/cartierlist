# Real DBA/Bilbasen anchors for the 23 brand-pooled price cells

Status: complete for this run. New script (`pipeline/src/scrape_calibration_listings.py`),
177 new rows in `pipeline/reference/calibration_prices.csv`, full pipeline rerun through the site
JSON. 36 of 37 in-scope (model, age_band) cells now have 3+ real Danish anchors of their own; 0
rows anywhere in `model_bracket_rankings.csv` lost confidence.

## Why this was needed

`pipeline/reference/model_bracket_rankings.csv` prices 23 models by borrowing their brand's
average price correction rather than their own (`price_pooled_at_brand == "True"`), because none
of them had enough real Danish asking prices to stand on their own. For some of these the borrowed
correction is wildly wrong in an obvious direction: AUDI A1 SPORTBACK band 1's pre-calibration
estimate was 749,967 DKK, inherited from Audi's brand-average curve dominated by A5/Q2/Q3 -- a
number no one would recognise as a used A1 Sportback's price. This run went and found real asking
prices for those cells directly.

## The mechanism (already built, not touched by this run)

`calibrate_price_estimates.py` and `build_phase4_rankings.py` already contained the fix this run
depends on, reviewed and committed separately from this work: any (make, model, age_band) cell
with 3+ real Danish listings of its own now gets its own correction ratio
(`price_anchor_source = "own_cell"` in `price_estimates_calibrated.csv`) instead of the
brand-pooled or global fallback. `price_confidence` blends this in without ever lowering a row's
existing confidence: 5+ own anchors with tight spread (coefficient of variation <= 30%) earns
"high" outright, 3+ earns at least "medium". This run's only job was supplying the anchors; the
calibration logic itself was not changed.

## Scope: 15 of the 23 models were actually reachable this run

Verified live against `model_bracket_rankings.csv` (`price_pooled_at_brand == "True"` and
`excluded_from_rank == "False"`), not assumed from the task description:

**5 models structurally out of scope.** SUZUKI (Baleno, Celerio, Ignis, Swift) and DS (DS 3) are
not priced through `price_estimates.csv` at all -- `build_suzuki_ds_prices.py` prices them from a
completely separate file (`suzuki_ds_price_anchors.csv`, schema `real_price_dkk` not
`real_asking_price_dkk`) using a donor-curve shape plus a hand-collected level, and hardcodes
`price_pooled_at_brand = True` and therefore `price_confidence = "low"` for every row it produces
-- there is no own-cell upgrade path for them at all in the current pipeline. A row added to
`calibration_prices.csv` for one of these five makes would never be read by anything (its key
never appears in `price_estimates.csv`), while still getting pooled into the global/split fallback
ratio used by every other model's fallback correction -- adding noise for zero benefit. So these
five were left out on purpose. Real Danish anchors for them belong in
`suzuki_ds_price_anchors.csv` instead; that is separate, explicitly out-of-scope work.

**3 models have nothing to backfill right now.** MAZDA Mazda CX-30 and TOYOTA Toyota C-HR are
still brand-pooled but both of their pooled bands are `excluded_from_rank`; CITROËN Grand C4
SpaceTourer is the same (both its bands excluded). None currently has a rankable band, so there
was nothing to attempt for them this run. This is re-checked from the live CSV every run, not
hardcoded, so a future change in exclusion status picks them up automatically.

**15 models, 37 (model, age_band) cells, were the actual target**, and all 37 were attempted in
this one run:

AUDI (A1 Sportback, A5 Sportback, Q2, Q3), CHEVROLET (Spark), CITROËN (C1, DS3, Grand C4 Picasso),
FIAT (Punto S7), HYUNDAI (Ioniq), KIA (Niro), MAZDA (Mazda6), PEUGEOT (206+), SKODA (Rapid, Rapid
Spaceback).

## Search method

`pipeline/src/scrape_calibration_listings.py` ports the logic (not the code) of the sibling
BestDeals project's `dba.ts` and `bilbasen.ts` adapters:

- **DBA (primary):** plain HTTP fetch (Python stdlib `urllib`) + `lxml.html`, no browser. DBA's
  `robots.txt` was fetched live and confirmed to permit the general `/mobility/search/car` path
  this script uses -- it only disallows account pages, messaging, and a couple of internal API
  paths.
- **Bilbasen (secondary, lower volume):** Playwright navigates the real, server-rendered
  `/brugt/bil?free=...` search page and reads the server-embedded `__NEXT_DATA__` payload, exactly
  like the TypeScript adapter. `/api/search/by-request` was never called, even though prior
  research in `BestDeals/API-RESEARCH.md` shows it works technically -- Bilbasen's `robots.txt`
  explicitly disallows both `/api/` and effectively all query-string search URLs (`Disallow: *?*`
  with only a `page=` carve-out), so only the rendered-page pattern is in scope. Chromium was
  already installed in this environment (`playwright install chromium` confirmed a working browser
  before any scrape request was made).
- The first navigation to a Bilbasen search URL comes back as an AWS WAF interstitial (HTTP 202)
  that a real browser clears client-side; the adapter re-navigates once when that happens, matching
  what was observed live during this run and in the prior research. A visible CAPTCHA/Turnstile
  challenge (checked by scanning the rendered page text for verification-challenge language) would
  raise and stop the whole run rather than attempt a workaround -- this never triggered.

**Search terms** are the plain Danish-market names a seller would actually type (e.g. "fiat punto",
"peugeot 206"), not DMR's internal generation codes ("Punto S7", "206 +") -- those codes are not
search terms a seller would use; the year-band filter (`year_from`/`year_to` on DBA,
`yearfrom`/`yearto` on Bilbasen, taken directly from `model_bracket_rankings.csv`'s own
`band_years` column) does the generation disambiguation instead of guessing a code.

**No mileage filter was applied to the search request itself.** An early manual test
(`AUDI A1 SPORTBACK` band 1, mileage 60,000-150,000 km + year 2020-2022) returned zero results on
both sites; dropping the mileage filter and validating post-hoc was necessary to find the one real
listing that does exist for that cell. Every model/band combination instead pulls one page of
results filtered only by year, then a validation pass keeps or rejects each listing:

- price present and between 8,000 and 1,500,000 DKK (an absolute sanity band, deliberately **not**
  relative to the cell's own pre-calibration `our_estimate_dkk` -- several target cells have a
  badly wrong `our_estimate_dkk` precisely because they are brand-pooled, so bounding plausibility
  against that number would have rejected the real listings this run exists to find),
  registration year inside the requested band, mileage present, not VAT-excluded (`ekskl. moms`),
  not a leasing offer,
- the make token present in the listing's title/variant (DBA) or structured `make`/`model`/
  `variant` fields (Bilbasen), ascii-folded so "Citroën"/"Citroen"/"CITROËN" compare equal,
- model-specific require/exclude keywords catching the real collisions each model is prone to:
  "sportback" required for AUDI A1/A5 Sportback (both also sell as coupe/non-Sportback body
  styles), "s1"/"s5"/"rs5"/"sq2"/"sq3"/"rs q3" excluded from the Audi searches (performance trims
  at a different price tier), "spaceback" required for SKODA Rapid Spaceback and excluded from
  plain SKODA Rapid, "grand" required for CITROËN Grand C4 Picasso, "ioniq 5"/"ioniq 6" excluded
  from HYUNDAI Ioniq (a different, newer EV platform Hyundai gave a similar name to, not the same
  DMR line).

Up to 5 passing listings per cell were kept, spread across the mileage range (lowest, highest, and
evenly-spaced points between) rather than just the first 5 found, so the mileage-vs-price fit in
`calibrate_price_estimates.py` has a real spread to fit against.

## Request budget

**DBA: capped at 45 requests/run.** Justification: 37 target cells, and DBA returns a full page of
results per search (not one request per listing), so one request per cell was normally enough to
find several usable anchors -- 45 covers all 37 cells once plus a handful of second attempts, and
sits comfortably inside the 30-60 range this task specified. **Bilbasen: capped at 25
requests/run**, lower than DBA's, because it is explicitly the secondary, lower-volume source and
each request costs a real browser navigation (including the WAF-clear round trip) rather than a
plain fetch -- it was only used to top up cells DBA came up short on.

**Actual usage this run: 37/45 DBA requests, 11/25 Bilbasen requests.** Every one of the 37 target
cells was reached and attempted in this single run; the caps were headroom, not a wall this run hit.
State is tracked per-cell in `pipeline/data/raw/dba_bilbasen/scrape_state.json` (gitignored, see
below) specifically so a future run would skip cells already attempted and pick up wherever the
last one left off -- with everything already attempted, a rerun today would find nothing pending.

## Results: 36 of 37 cells now have 3+ real anchors

177 new rows were added to `calibration_prices.csv` (145 from dba.dk, 32 from bilbasen.dk), on top
of its existing 28 hand-collected rows (28 of which already covered other, unrelated models --
CITROËN C1 band 2 was the one overlap, which already had 2 real anchors; 3 more were added there to
reach 5).

| Model | Bands attempted | Anchors per band |
|---|---|---|
| AUDI A1 Sportback | 1, 2, 3, 4 | 1, 5, 5, 5 |
| AUDI A5 Sportback | 1, 2, 3, 4 | 5, 5, 5, 5 |
| AUDI Q2 | 1 | 5 |
| AUDI Q3 | 1, 2, 3, 4 | 5, 5, 5, 5 |
| CHEVROLET Spark | 3, 4 | 5, 5 |
| CITROËN C1 | 1, 2, 3, 4 | 5, 5, 5, 5 |
| CITROËN DS3 | 3, 4 | 5, 5 |
| CITROËN Grand C4 Picasso | 3, 4 | 5, 5 |
| FIAT Punto S7 | 2, 3, 4 | 4, 5, 5 |
| HYUNDAI Ioniq | 1 | 5 |
| KIA Niro | 1 | 5 |
| MAZDA Mazda6 | 1, 2, 3, 4 | 5, 5, 5, 5 |
| PEUGEOT 206+ | 4 | 5 |
| SKODA Rapid | 2, 3 | 5, 5 |
| SKODA Rapid Spaceback | 2, 3 | 5, 5 |

36 of these 37 cells cleared the 3-anchor own-cell threshold. The one exception: **AUDI A1
SPORTBACK band 1** (2020-2022 registration) found only a single valid listing on either site after
validation. This appears to be genuine market thinness, not a search or filter problem -- a manual
check outside the script confirmed zero DBA results for that exact year range even without a
mileage filter narrower than the one request already used, consistent with a 3-5 year old niche
supermini simply not turning over on the resale market yet in meaningful volume. That single row
still feeds the pipeline's global/split fallback pool (any real anchor helps there), it just does
not clear the 3+ threshold for its own `own_cell` correction on its own -- band 1 still falls back
to the pooled correction, same as before this run, not worse.

## Verification

**`price_anchor_source == "own_cell"` and confidence >= medium, for every qualifying cell.**
`calibrate_price_estimates.py`'s own summary confirms 36 rows in `price_estimates_calibrated.csv`
now carry `price_anchor_source = "own_cell"` -- exactly the 36 cells that reached the 3+ threshold
above, a clean 1:1 match.

**No row anywhere lost confidence.** The full chain (`calibrate_price_estimates.py` ->
`build_suzuki_ds_prices.py` -> `build_phase4_rankings.py` -> `site/scripts/sync-data.mjs`) was run
twice: once against the pre-scrape `calibration_prices.csv` (28 rows, matching the last committed
state) to get a true "before" `model_bracket_rankings.csv`, then again against the final,
177-row-larger file to get "after". Diffing `price_confidence` cell-by-cell across all 621 rows:

- **0 rows regressed** (no row moved from high to medium/low, or medium to low).
- **36 rows improved**, exactly the 36 own-cell-qualified cells -- 23 went straight to "high"
  (5 anchors, tight spread), 13 landed at "medium".
- Confidence distribution across all 621 rows: **before** high 426 / medium 76 / low 119; **after**
  high 449 / medium 89 / low 83.

**Site data regenerated.** `site/src/data/rankings.json`, `sources.json`, and `methodology.json`
were rewritten by `npm run sync-data` against the final pipeline output (621 ranked rows, same
count as before -- no rows added or dropped, only corrected).

## A second finding, unrelated to scraping: the live site was already stale on 4 models

The "0 rows regressed" check above compares two runs of the full chain against the same,
already-current `price_estimates.csv`, which isolates what the scraping itself changed. That is
not the same question as "did anything change versus what is live on the site right now," and
checking that separately turned up something real.

Diffing the regenerated `model_bracket_rankings.csv` against the actually-committed one (HEAD at
the time this run started) shows 16 cells moving down, not up: Fiat 500C, Mazda2, Mazda3, and
Renault Ny Clio, all four age bands each. None of these four models were touched by this session's
scraping. The cause: `price_estimates.csv` (the Polish-listings match, untouched by this session,
file-dated 2026-08-12) already recorded these four models as brand-pooled with a much larger
listing count than the committed `model_bracket_rankings.csv` showed --for example Mazda3 band 1:
`price_estimates.csv` says `n_listings=559, pooled_at_brand=True`; the committed rankings file
said `91, False`. All 16 cells match `price_estimates.csv` exactly once corrected, with no
exceptions, which rules out a bug introduced by this session's own code changes.

The likely history: these four models were affected by an earlier phase's DMR spelling-merge fix
(Mazda 2/MAZDA2, Mazda 3/MAZDA3, and Renault CLIO/Ny Clio are named directly in that fix's own
commit message), which changes what counts as "this model" for the Polish-listings match and
correctly pushed these four to brand-pooled. `build_price_estimates.py` was rerun after that fix
landed (hence the current, correct `price_estimates.csv`), but `calibrate_price_estimates.py` and
`build_phase4_rankings.py` were not rerun end-to-end again until this session, so the committed
rankings file kept serving pre-merge numbers for these four models in the meantime.

This is not a badge-only issue. `entry_price_dkk` moved too: Mazda3 band 1 was showing 216,078 kr,
now 167,784 kr (-22%); Fiat 500C band 1 was 167,033 kr, now 112,792 kr (-32%); Renault Ny Clio
band 1 was 96,518 kr, now 109,174 kr (+13%). The site has been showing a materially wrong price
and an overstated confidence badge for these four popular models since the spelling-merge fix
landed, independent of anything this task did. This run's full pipeline re-execution corrected it
as a side effect. Whether any other model has drifted the same way was not checked here; it would
need a standing check (a diff-and-alert step, or simply rerunning the full price chain whenever
`crosswalk.csv` or the model-spelling reference files change) rather than relying on someone
noticing during an unrelated task.

## One bug caught and fixed during verification

`csv.writer`'s default line terminator is `\r\n`; the existing `calibration_prices.csv` uses bare
`\n` throughout. Appending rows with the default terminator produced a file with mixed line
endings, which made `site/scripts/sync-data.mjs`'s CSV parser (`csv-parse`, which auto-detects the
record delimiter) choke on the first appended row with `CsvError: Invalid Closing Quote`. Fixed by
normalizing the file to bare `\n` once, and by adding `lineterminator="\n"` to the script's
`csv.DictWriter` call so a future run does not reintroduce the mismatch.

## Raw data handling

Scraped HTML/JSON payloads are cached under `pipeline/data/raw/dba_bilbasen/` for debugging and
resumability. The repo-root `.gitignore`'s existing `data/raw/` line is anchored to the repo root
by its own inner slash and does not reach `pipeline/data/raw/` -- confirmed live with
`git check-ignore` before this was noticed, `pipeline/data/raw/price_reference/poland_all.csv` is
in fact tracked in git today despite the intent stated in `.gitignore`'s own comment. Rather than
widen the existing pattern (out of scope, and would not retroactively untrack anything already
committed), a specific line, `pipeline/data/raw/dba_bilbasen/`, was added to `.gitignore` and
confirmed with `git check-ignore -v` and `git status` that the cache directory no longer appears as
untracked.

## Continuing the backfill

Every in-scope cell was reached in this single run (37/37 attempted, well under both request caps),
so `scrape_calibration_listings.py`'s own pending-cell list is currently empty -- rerunning it today
would find nothing to do. Two ways to extend this further:

1. **Re-attempt AUDI A1 SPORTBACK band 1** once more real 2020-2022 listings appear on either site.
   Its state entry (`partial_below_threshold`) does not currently get retried automatically; delete
   that one entry from `pipeline/data/raw/dba_bilbasen/scrape_state.json` and rerun the script to
   attempt it again without re-attempting anything else.
2. **Suzuki/Baleno/Celerio/Ignis/Swift and DS "DS 3"** were excluded on purpose (see Scope above).
   Extending real-anchor coverage to them means hand-collecting listings into
   `pipeline/reference/suzuki_ds_price_anchors.csv` (schema: `dmr_make,dmr_model,age_band,
   real_price_dkk,real_mileage_km`) and rerunning `build_suzuki_ds_prices.py`, not this script --
   and note that pipeline's `price_confidence` is hardcoded to "low" for every row it produces
   regardless of anchor count, so a confidence upgrade for those five would itself require a
   deliberate design decision this task did not make.
