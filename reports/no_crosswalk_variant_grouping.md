# Norwegian variant-code crosswalk: what was already grouped, what was broken, and whether fixing it closes the band 1/2 gap

Status: complete. Grouping rules frozen and written to disk before any correlation was computed, per
the brief's scientific-integrity requirement. Three concrete defects found and fixed, all in the
Norwegian path. `crosswalk.csv`, `model_age_band_metrics.csv`, `model_bracket_rankings.csv`, and every
site file are unchanged (verified by file timestamp below, not just by intent).

**Correction applied to this report after review**: a first draft of "The re-run agreement study"
below used a stricter sample-size threshold than the comparison it was reproducing, which shrank the
variant-code group enough to flip the sign of its band 1/2 correlation from small-and-positive to
small-and-negative. That was a threshold choice, not a bug in `build_agreement_study.py`, and it has
been corrected throughout; see that section for the full explanation and the reconciled figures, which
are now verified to match two independent recomputations.

**Answer to the question this phase exists to test: no, not for the bands that matter most.** The
crosswalk *was* missing real grouping, but not in the place the brief's framing assumed, and fixing
what was actually broken did not meaningfully improve band 1 or band 2 for the variant-code makes, which
remain close to zero rank agreement versus the clean-name makes' 0.77-0.86 in the same bands. That is
reported here as a genuine result, not engineered away.

## Correcting the starting premise first

The brief states "the Norwegian crosswalk has no equivalent rule" to the DVSA side's
`family_series_literal` / `family_series_sibling` grouping. That was true when
`reports/norway_pkk_report.md` began, but by the time this phase started, `pipeline/src/
build_no_crosswalk_review.py` already existed and already imported `match_model`,
`best_prefix_identity`, `family_series_digit`, and `strip_klasse_suffix` from
`build_crosswalk_review.py` **unchanged**, exactly as the brief instructs. Checked directly against
`no_crosswalk_review.csv` before touching anything:

- BMW `3-Serie` already drew on Norwegian siblings `320`(17,606) `318`(8,228) `316`(5,807) `330`(5,397)
  `325`(1,248) `328`(313) `335`(261), all `high / family_series_sibling`, confirmed `y`.
- BMW `1-Serie`, `2-Serie`, `4-serie`, `5-Serie` were grouped the same way. `X1`, `X3`, `X5` were each
  matched by `exact / prefix_identity` on their own code, correctly kept separate from the numbered
  sedans.
- Mercedes `A-Klasse`/`B-Klasse`/`C-Klasse`/`E-Klasse` already resolved to bare `A`/`B`/`C`/`E` by
  `exact / prefix_identity`, and `CLA`/`GLA`/`GLC`/`GLE` matched their own multi-letter names.
- Case (`X3 XDRIVE20D` vs `X3 xDRIVE20d`) was already a non-issue: `normalize()` uppercases
  unconditionally, so both spellings were already landing in the same bucket.
- Trailing drivetrain/trim tokens (`4MATIC`, `xDrive`, `iPerformance`, `quattro`) were already handled:
  `leading_code()`/`first_token()` only look at the leading token, so anything after it is ignored by
  construction. Verified directly: `X3 2.0D` and `X3 XDRIVE20D` both classify to `X3`; `225xe
  iPerformance` classifies to code `225`, which correctly joins the `2-Serie` family
  (`family_series_sibling`, digit `2`, second digit `2`).

So the port the brief describes had already happened for BMW and Mercedes. This phase's real
contribution turned out to be three narrower, concrete defects the port didn't catch, found by
inspecting the raw Norwegian strings directly rather than trusting that "grouping exists" meant
"grouping works."

## The three defects, frozen before any correlation was computed

Written to `pipeline/src/build_no_crosswalk_review.py` and `pipeline/src/build_norway_metrics.py`.
Every rule below is justified on what the physical car is, verified against raw counts, not on
whichever grouping would score best.

### Defect 1: multi-word nameplate tokens linked to zero raw strings (the big one)

`build_norway_metrics.py`'s `build_link_table()` resolved a confirmed crosswalk row's
`proposed_no_model_token` back to actual raw Norwegian strings by calling `classify_model_token(raw,
make_norm) == token`. `classify_model_token` always collapses a code-like string down to its single
**leading** token (`"A3 SPORTBACK"` classifies to `"A3"`, same as bare `"A3"`), which is correct for a
bare nameplate but can never equal a **multi-word** token. Any confirmed row whose token has a space in
it (a genuine `prefix_identity` match on a multi-token DVSA-style prefix, e.g. Audi `A3 Sportback` ->
`"A3 SPORTBACK"`) therefore linked **zero** raw strings and produced **zero** metrics cells, silently.

Confirmed by checking `model_age_band_metrics_no.csv` directly before touching any code: Audi had 14
cells across 4 models (`Q2`, `Q3`, `Q5`, `A3`) and not one Sportback/Avant/Limousine/Cabriolet cell,
despite `no_crosswalk_review.csv` carrying confirmed (`y`) rows for all seven of them with real inspection
counts behind each (`A3 Sportback` 21,874, `A4 Avant` 6,599, `A6 Avant` 3,997, `A1 Sportback` 5,479,
`A5 Sportback` 1,449, `A3 Limousine` 790, `A3 Cabriolet` 326). The bug was invisible in the review file
(candidate generation, which uses `best_prefix_identity` against `prefix_counts`, was already correct)
and only showed up at the metrics-build step.

This is not Audi-specific: 30 confirmed rows across many makes carried multi-word tokens (VW
`T-Roc`/`T-Cross`/`Golf Sportsvan`, Mazda `CX-5`/`CX-3`/`CX-30`, Honda `CR-V`, Nissan `X-Trail`, Ford
`C-MAX`/`S-MAX`/`B-MAX`, Citroen `C4 Cactus`/`C3 Picasso`/`C3 Aircross`/`C5 Aircross`/`C4 Picasso`,
Opel `Crossland X`/`Grandland X`/`Astra Sports Tourer`, Mitsubishi `Space Star`, Suzuki `SX4
S-Cross`, Toyota `C-HR`/`Yaris Cross`), all silently zeroed the same way. All of them are on the
Norwegian path (`build_norway_metrics.py`), so fixing the general bug was in scope and fixed once for
everyone rather than patched per-make.

**Fix**: bucket membership for a multi-word token is now the same normalized-string prefix test that
produced the token's own count in the first place (a raw string belongs to the bucket if its
normalized, make-stripped form equals the token or starts with `token + " "`), not a single-token
classification equality. Single-word tokens and `family_series_literal` tokens are untouched, since
those were already working.

### Defect 2: Audi's comma-joined dual designation

Norway's own PKK data records some Audi rows with both the base model and its S-line sibling in one
string, comma-separated: `AUDI A4, S4` (4,169 inspections), `AUDI A3, S3` (3,292), `AUDI A6, S6`
(2,102). The shared `normalize()` treats `-` and `/` as separators but has no reason to know about this
Norwegian-specific comma convention, since Danish DMR strings never carry it. Without handling it, the
first token after make-stripping is `"A3,"` with a trailing comma, which is code-like-shaped-but-not
(`is_code_like` requires only letters/digits) and therefore lands in an unreachable name bucket that no
DK model's token ever equals: ~9,500 inspections silently dropped across the three rows.

**Fix**: a Norwegian-only `normalize_no_raw()` treats a comma the same way the shared `normalize()`
already treats a hyphen, collapsing it to a space before classification. `AUDI A3, S3` now classifies
to the same `A3` bucket as bare `A3` and `AUDI A3` -- the honest default for an ambiguous/dual
designation, and consistent with the UK side, where DVSA doesn't distinguish Audi body styles at all
(`A3`, `A3 Sportback`, `A3 Limousine`, `A3 Cabriolet` all resolve to the identical DVSA test pool of
1,007,746 tests -- checked directly in `crosswalk.csv`).

### Defect 3: Volvo's spacing-accident duplicate codes

Norway writes some Volvo model codes with a stray space: `V 70` (2,915 insp.), `V 40` (140), `XC 90`
(84), alongside the far higher-volume glued forms `V70` (45,991), `V40` (15,145), `XC90` (15,792).
`is_code_like()`'s bare-single-letter branch (needed for Mercedes' `A`/`B`/`C`/`E`) means `"V 70"`
classifies to a bare code `"V"` -- a bucket no DK Volvo model (`V40`...`XC90`, `S40`...`S80`) ever
targets, since Volvo has no bare single-letter nameplate of its own.

**Fix**: a small, explicit, hand-verified table (`SPACED_CODE_GLUE`), scoped make-by-make and
code-by-code, glues exactly these token pairs before classification. This is deliberately **not** a
general letter+digit glue rule: Mercedes' `A 200` / `C 180` (class letter, space, engine number) is the
correct and *only* convention on that make, where `A` is itself a real nameplate and gluing would
invent a fake code (`A200`) that appears nowhere in the data. The table only touches Volvo's `V`/`XC`
prefixes against the specific trailing digits verified as spacing accidents of an already-dominant
glued form.

**A finding worth reporting honestly, not hiding**: checking *why* Norway writes `V 70` at all showed
every one of those 2,915 rows is a 1997-2001-registration first-generation V70, inspected in
2023-2025, making it 22-28 years old -- entirely outside this project's 4-16-year age-band window. The
fix is correct and the code (`V70` current-generation, 2007-2016) is the same nameplate family, but its
practical yield is negligible: net effect across all four Volvo age bands, +6 tests total (all on
`XC90`). Reported as designed and verified, not oversold.

### What did *not* need a fix, per the brief's checklist

- **Case inconsistency**: already handled by the shared `normalize()`. No change needed.
- **Trailing drivetrain/trim tokens**: already handled by leading-token extraction. No change needed.
- **BMW numeric-series vs X<n>/i<n>**: verified directly (`X3 2.0D` and `X3 XDRIVE20D` both classify to
  `X3`; `225xe iPerformance` correctly joins the `2-Serie` family via its leading code `225`). No
  change needed.
- **Mercedes letter-only vs multi-letter nameplates**: `GLA`/`GLB`/`GLC`/`GLE`/`CLA` are multi-letter,
  fail `is_code_like`, and correctly fall into the name path as their own buckets, distinct from the
  single-letter `A`/`B`/`C`/`E` class code path. No change needed.
- **Audi and Volvo "already nameplate-clean"**: **false for Audi, true for Volvo** (beyond the minor
  spacing accident above). Audi's raw strings are genuinely fragmented by body style and by the
  make-prefix pattern (`AUDI A4` 12,799 vs `A4` 5,229 vs `A4 allroad quattro` 6,649, etc.), which is
  exactly what Defects 1 and 2 above address. Volvo's raw strings are essentially clean nameplate codes
  already (`V70`, `XC60`, ...); the DK crosswalk's 8 confirmed Volvo models all resolved by
  `exact / prefix_identity` before this phase touched anything.
- **Make-prefixed duplicates for BMW and Mercedes specifically**: checked directly (`BMW 320D` /
  `MERCEDES BENZ 280S` style rows) -- all under 20 inspections each, historic classic-car strings, no
  material volume. Not worth a rule.

## Coverage: before and after

### Crosswalk universe (the confirmed DK-to-Norway model list)

| | before | after |
|---|---:|---:|
| DK models fully auto-settled | 188 / 211 | 189 / 211 |
| DK fleet coverage | 1,494,263 (93.6% of the UK-crosswalk universe) | 1,498,160 (94.2%) |
| left for human review (unchanged, see below) | 7 | 7 |
| no usable Norwegian match | 16 | 15 |

(The one newly-settled model, Hyundai Kona, cleared the noise floor as an incidental side effect of
the comma/despace fixes touching its own raw strings; not investigated further since it is outside the
four target makes and the change is small.)

### (model, age band) metrics cells, the four target makes

| make | cells before | cells after | models before | models after | total Periodisk tests before | total after |
|---|---:|---:|---:|---:|---:|---:|
| BMW | 30 | 30 | 8 | 8 | 141,425 | 141,425 (unchanged) |
| MERCEDES-BENZ | 36 | 36 | 10 | 10 | 151,086 | 151,086 (unchanged) |
| AUDI | 14 | **41** | 4 | **11** | 56,014 | **96,319** (+72%) |
| VOLVO | 25 | 25 | 8 | 8 | 194,084 | 194,090 (+6) |

Confirms the "what did not need a fix" section above by construction: BMW and Mercedes are
bit-for-bit unchanged (every raw string they carry was already reaching the right bucket), Volvo
changes by a rounding error, and Audi is where nearly all of this phase's coverage gain lives.

Newly appearing Audi (model, age band) cells, all previously silently absent:

| model | band 1 | band 2 | band 3 | band 4 |
|---|---:|---:|---:|---:|
| A1 Sportback | 902 | 1,299 | **3,090** | 183 |
| A3 Sportback | **3,698** | **8,901** | **9,047** | 227 |
| A3 Limousine | 109 | 290 | 391 | -- |
| A3 Cabriolet | 7 | 39 | 103 | 166 |
| A4 Avant | 1,533 | 1,848 | **2,969** | 152 |
| A5 Sportback | 233 | 267 | 880 | 69 |
| A6 Avant | 526 | 1,067 | 2,163 | 143 |

**Bold** cells clear the n>=2,500 ranking-stability floor for the first time: 5 newly ranking-eligible
Audi cells (A1 Sportback band 3, A3 Sportback bands 1-3, A4 Avant band 3) where there were previously
none for these body styles at all.

Pipeline-wide (all makes, not just the four targets, since Defect 1 was general): `model_age_band_metrics_no.csv`
grew from 556 to 650 (model, age band) cells, 157 to 189 distinct DK models, and the attributed-inspection
row count from 2,382,720 to 2,598,693 (+215,973, +9.1%). Spot-checked three of the newly-recovered
non-target models (VW T-Roc, Mazda CX-5, Honda CR-V) for plausibility: pass rates in the ordinary 0.42-0.87
range with the expected age gradient, no sign of corruption.

## Sanity checks that do not touch the correlation

Per the brief, checked whether each new or fixed group's first-registration year range and fuel mix are
consistent with one nameplate, queried directly from `no_eligible_tests` (age band 4-16 window):

| make | model | year range | n raw strings folded in | % diesel | % petrol |
|---|---|---|---:|---:|---:|
| AUDI | A1 Sportback | 2011-2021 | 3 | 7.6% | 92.4% |
| AUDI | A3 Sportback | 2012-2020 | 6 | 15.3% | 84.7% |
| AUDI | A3 Cabriolet | 2008-2018 | 3 | 37.8% | 62.2% |
| AUDI | A3 Limousine | 2013-2019 | 2 | 24.8% | 75.2% |
| AUDI | A4 Avant | 2012-2021 | 2 | 60.3% | 39.7% |
| AUDI | A5 Sportback | 2011-2020 | 2 | 51.6% | 48.4% |
| AUDI | A6 Avant | 2012-2021 | 3 | 91.6% | 8.4% |
| VOLVO | V70 | 2007-2016 | 2 | 98.9% | 1.1% |
| VOLVO | V50 | 2007-2012 | 3 | 98.6% | 1.4% |
| VOLVO | XC40 | 2018-2021 | 2 | 50.5% | 49.5% |
| BMW | 3-Serie | 2007-2021 | 75 | 64.3% | 35.7% |

All of these read as one coherent nameplate, not a grouping error: `V70`'s year range (2007-2016)
matches its actual production run before Volvo discontinued it in 2016; `V50` (2007-2012) matches its
own discontinuation; `XC40` (2018-2021) matches its 2017/2018 launch; the Audi Sportback/Avant/Cabriolet
body styles each span a plausible single-generation window rather than jumping between unrelated cars.
Fuel mixes are unremarkable for each body style (estates diesel-heavy, small hatches petrol-heavy). No
group bundles a city car with an SUV, and no group spans an implausible multi-decade year range. `3-Serie`'s
wide 2007-2021 span and 75 folded raw strings is expected for a long-running, many-generation nameplate
grouped by design (`family_series_sibling`), not a defect.

No sanity-check failure found. This does not by itself prove the groupings are optimal, but it rules out
the "grouping error" failure mode the brief specifically asked this step to catch.

## Ambiguous rows: still routed to a human, not auto-accepted

Re-running `build_no_crosswalk_review.py` and `auto_decide_no_crosswalk.py` fresh (required, since the
new candidate-generation logic changes counts for the affected rows) reproduced the **same 7 models**
left with a blank `decision` as before this phase started, none of them among the four target makes:

| DK model | DK fleet | status |
|---|---:|---|
| SEAT MII | 11,905 | no candidate found automatically |
| OPEL KARL | 8,920 | no candidate found automatically |
| SUZUKI Celerio | 8,391 | no candidate found automatically |
| RENAULT TWINGO | 7,445 | exact match exists but only 20 inspections, below the noise floor |
| CITROEN GRAND C4 PICASSO | 6,346 | no candidate found automatically |
| RENAULT GRAND SCENIC | 5,269 | fuzzy `SCENIC` candidate (135 insp., medium confidence), an inference not an identity |
| CITROEN Grand C4 SpaceTourer | 1,762 | no candidate found automatically |

None of the three new fixes changed anything about these rows -- they remain genuinely unresolved and
are left for a human, exactly as the brief requires.

## The re-run agreement study

Frozen grouping was written to disk first (`no_crosswalk.csv`, `no_crosswalk_review.csv`,
`model_age_band_metrics_no.csv`); the correlation below was computed only after that, and nothing was
moved between groups in response to it.

**A correction was made to this section after a first draft.** The first draft applied
`build_agreement_study.py`'s own PRIMARY ranking-eligibility threshold (UK n>=2,000, Norway n>=2,500)
to the make-group breakdown below. That threshold is legitimate and correctly computed for what it is
(it is the same one `reports/norway_pkk_report.md` uses for its own headline table), but it is a
*stricter* bar than the one the comparison this phase is built on (`reports/failure_category_agreement_test.md`'s
0.11/0.00/0.47/0.67 table) actually used, which only required a cell to clear its own source's basic
stability check (each source's `standardized_pass_rate` being populated at all, i.e. not
`unstable`/`unstable_all`), not the additional 2,000/2,500 ranking floor. Applying the stricter
threshold shrank the variant-code group from 27-34 cells per band down to 15-20, and at that smaller,
differently-composed size the correlation was unstable enough to flip sign in bands 1 and 2 (small-n
noise from an inappropriate threshold choice, not a coding defect). Reproducing the coordinator's own
two independent checks against `build_agreement_study.py`'s unmodified `spearman()`,
`dedupe_signature()`, and `within_band_pooled()` functions, without the extra threshold, matches their
figures to 3-4 decimal places, which confirms **the bug was in this report's threshold choice, not in
`build_agreement_study.py` itself** -- that module's own PRIMARY-threshold output elsewhere in this
project (the norway_pkk_report.md headline table, and the ALL-MAKES/CLEAN-MAKES tables it produces on
request) is unaffected and remains correct for the threshold it documents.

The table below uses one consistent methodology throughout: each cell individually clears its own
source's basic stability check (not `unstable_all`, i.e. `model_age_band_metrics_category_split.csv`
and `model_age_band_metrics_category_split_no.csv`'s `standardized_rate_all` is populated), no
additional 2,000/2,500 ranking floor, within-band percentile pooling to remove the shared age-trend
confound, de-duplicated for bit-identical spelling-split pairs. "Before" is this session's starting
state (already includes the pre-existing `family_series_sibling`/`prefix_identity` grouping),
reconstructed by temporarily reverting this phase's three fixes and rerunning the full pipeline (it
reproduces `norway_pkk_report.md`'s and `failure_category_agreement_test.md`'s own historical numbers
exactly, confirming it is a faithful baseline); "after" includes this phase's three fixes.

### All makes

| age band | n before | rho before | n after | rho after |
|---|---:|---:|---:|---:|
| 1 | 105 | 0.522 | 127 | **0.568** |
| 2 | 127 | 0.679 | 149 | **0.695** |
| 3 | 133 | 0.812 | 152 | **0.827** |
| 4 | 122 | 0.805 | 133 | 0.820 |
| pooled, within-band corrected | 487 | 0.713 | 561 | **0.732** |

### Variant-code makes (BMW, Mercedes-Benz, Audi, Volvo)

| age band | n before | rho before | n after | rho after |
|---|---:|---:|---:|---:|
| 1 | 27 | 0.107 | 32 | **0.119** |
| 2 | 28 | 0.000 | 34 | **0.077** |
| 3 | 25 | 0.467 | 31 | **0.558** |
| 4 | 21 | 0.667 | 25 | 0.617 (slightly lower: the new Audi band-4 cells that clear this looser floor, e.g. `A3 Sportback` at n=227, correlate worse than the pre-existing ones) |
| pooled, within-band corrected | 101 | 0.276 | 122 | 0.321 |

The `before` row here reproduces `failure_category_agreement_test.md`'s own published table
(0.11/0.00/0.47/0.67) almost exactly, which is the check that this reconstruction is sound.

### BMW and Mercedes-Benz only, separated from Audi and Volvo

Requested separately because Audi and Volvo changed composition during this phase (Audi gained 27
cells, Volvo gained none materially) while BMW and Mercedes-Benz did not change at all: **identical
cell-for-cell before and after**, confirming directly that nothing in this phase touched their grouping.

| age band | n (unchanged) | rho (unchanged) |
|---|---:|---:|
| 1 | 17 | 0.219 |
| 2 | 18 | 0.214 |
| 3 | 16 | 0.525 |
| 4 | 12 | 0.796 |
| pooled, within-band corrected | 63 | 0.395 |

### Clean-name makes (Skoda, Peugeot, Volkswagen, Toyota), for reference

| age band | n before | rho before | n after | rho after |
|---|---:|---:|---:|---:|
| 1 | 32 | 0.770 | 36 | 0.769 |
| 2 | 36 | 0.790 | 39 | 0.825 |
| 3 | 38 | 0.854 | 39 | 0.862 |
| 4 | 34 | 0.788 | 34 | 0.788 (unchanged) |
| pooled, within-band corrected | 140 | 0.806 | 148 | 0.813 |

(Clean-makes moved slightly because VW's `T-Roc`/`T-Cross` were also silently zeroed by Defect 1 and are
now recovered; unrelated to the four variant-code target makes.)

### Reading this honestly

The overall (all-makes) figures show this phase did something worth recording even outside the four
target makes: band 1 moved from 0.522 to 0.568 and band 3 from 0.812 to 0.827, with paired cell counts
rising across the board (band 1 from 105 to 127) -- the Audi recovery and the 23 other non-target-make
rows Defect 1 fixed, showing up in the pooled statistic.

For the variant-code makes specifically, the corrected numbers change the story from the first draft in
an important way: **bands 1 and 2 were never negative.** Both before and after this phase, they sit
near zero and positive (before: 0.107 / 0.000; after: 0.119 / 0.077) -- meaning Norway shows close to no
rank relationship with the UK for these four makes in the two youngest bands, not the reversed ordering
a negative correlation would imply. That correction matters for interpretation even though it does not
change the substantive conclusion: **bands 1 and 2 did not meaningfully improve.** Band 1 moved from
0.107 to 0.119 and band 2 from 0.000 to 0.077 -- both still a small fraction of the clean-makes level in
the same bands (0.769 and 0.825). Band 3 did genuinely improve (0.467 -> 0.558), driven by the
newly-available Audi Sportback/Avant cells. Band 4 moved slightly the *other* way (0.667 -> 0.617),
because the newly-recovered Audi band-4 cells that clear this looser floor correlate somewhat worse than
the pre-existing ones, not because of any regression in the fix.

This is a real result, not a failure to engineer away, per the brief's own instruction. It means: the
grouping defects this phase found and fixed were real, verifiable, and worth fixing (Audi coverage alone
grew 72%, and the general multi-word-token bug would have kept silently corrupting any future confirmed
crosswalk row with a multi-word DVSA-style prefix, for any make). But they are **not** the explanation
for why BMW/Mercedes/Audi/Volvo correlate barely above zero in the youngest two age bands. The BMW+MB-only
figures make this cleanest: those two makes are byte-for-byte unaffected by anything in this phase (30
newly-linked rows across the pipeline, and all three defects fixed, none of them touched a single BMW or
Mercedes raw string) and still sit at 0.219 and 0.214 in bands 1 and 2, versus clean-makes' 0.769 and
0.825 in the same bands. **Crosswalk grouping quality cannot be the (complete) explanation for the weak
young-car correlation** the previous phase reported, since the makes least affected by any grouping
question at all show the same weakness as the makes this phase changed the most.

What could explain it instead is not established here. Two candidates, offered as open questions for a
later phase, not conclusions:

1. **Small-n instability alone does not obviously distinguish the two groups.** Variant-code n after the
   fix is 25-34 per band, close in magnitude to clean-makes' 32-39, which correlates at 0.77-0.86 in the
   same bands. If thin samples were the whole story, clean-makes should be similarly unstable and it is not.
2. **A genuine cross-market divergence for premium marques**, unrelated to how the crosswalk groups model
   strings -- ownership patterns, dealer-network servicing behaviour, or a different age-linked defect
   profile for BMW/Mercedes/Audi/Volvo specifically in the two youngest bands, in both the UK and Norway.
   The "largest disagreements" table in `no_uk_agreement.csv`, still dominated by band-4 BMW/Mercedes rows
   running 30+ points below the UK level, is consistent with this but does not prove it.

A supplementary cross-check against the previous phase's mechanical/consumable defect-category split
(`build_failure_category_agreement_study.py`, same looser join, variant-code makes only, after this
phase's fixes) shows the same overall pattern holds regardless of which defects are counted: band 1 sits
near zero under all three variants (all-defects 0.118, mechanical 0.027, consumable 0.027); band 2 is
weakly negative under mechanical-only (-0.125) and moderately positive under consumable-only (0.431).
Nothing in this breakdown turns bands 1-2 into a clean success under any defect-category choice, which
rules out "wrong defect category" as an explanation for the same reason the BMW+MB comparison rules out
"ungrouped crosswalk": whatever is driving the weak young-car correlation for these four makes is not a
crosswalk-grouping or defect-category artefact this phase can locate.

## The A-CLASS vs A question

Checked directly against `mot_tests`: DVSA carries `A-CLASS` (1,161,517 tests) as a literal separate
model string from bare `A` (336,632) and the various `A 2xx ...` trim strings. `normalize()` converts
the hyphen to a space (`A-CLASS` -> `A CLASS`), so `first_token()` extracts `A` for both, and
`code_counts["A"]` / `prefix_counts["A"]` already sum every `A`-prefixed DVSA string including
`A-CLASS`. Confirmed the actual crosswalk row: `MERCEDES-BENZ A-Klasse -> A`, `rule_fired =
prefix_identity`. **`A-CLASS` is folded into `A` correctly. No tests are being dropped.** Same
mechanism, same answer, for `B-CLASS` (316,731 tests) versus bare `B` (28,290): confirmed folded the
same way. This is not a defect; the recorded `uk_test_count` for these rows is simply stale (see next
section), not wrong in kind.

## The stale `uk_test_count` question

`crosswalk.csv` was built against the 2-year DVSA warehouse; the warehouse now holds four years.
Recomputed the current count for all 245 confirmed rows using the same matching logic
(`build_dvsa_prefix_index` / `build_dvsa_index`, applied per the row's own `rule_fired`) against the
current 4-year `mot_tests` table, and compared against the stored `uk_test_count`.

**Answer: cosmetic, confirmed by direct check rather than assumption.** Counts are up 2.0x-2.7x across
the board (e.g. `A-Klasse -> A`: 839,051 recorded vs ~1.5M current; `BMW 5-Serie`: 30,447 vs 70,685;
`OPEL ZAFIRA`: 482,890 vs 1,104,253), consistent with roughly double the years of data. **Zero of the
245 rows cross the 2,000-test stability threshold in either direction** -- every row that was above 2,000
before is still comfortably above it now, and every row below stays below. No decision recorded in
`crosswalk.csv` would flip if it were rebuilt against the current warehouse. `crosswalk.csv` itself is
untouched by this phase, per the brief's instruction not to rebuild it without asking first.

## Files

New or Norwegian-path files changed by this phase:

- `pipeline/src/build_no_crosswalk_review.py`: added `normalize_no_raw()` (comma handling),
  `despace_known_code()` + `SPACED_CODE_GLUE` (Volvo spacing fix), applied inside `classify_model_token()`
  and `build_no_index()`.
- `pipeline/src/build_norway_metrics.py`: `build_link_table()` now branches on whether a confirmed
  token contains a space; multi-word tokens use a prefix test against the corrected normalization instead
  of the single-token `classify_model_token()` equality that was silently matching nothing.
- `pipeline/reference/no_crosswalk_review.csv`, `no_crosswalk.csv`: regenerated (277 rows, 208 confirmed
  across 189 models, same 7 left blank for human review).
- `pipeline/reference/model_age_band_metrics_no.csv`, `model_age_band_reliability_strata_no.csv`,
  `model_age_band_category_failure_rates_no.csv`: regenerated (650 cells, up from 556).
- `pipeline/reference/model_age_band_metrics_category_split_no.csv`: regenerated via a standalone script
  that calls only the Norwegian-side functions of `build_failure_category_metrics.py`
  (`build_link_table`, `build_eligible_tests`, `compute_no_three_way`), deliberately avoiding that
  module's combined `main()` so the UK-side `model_age_band_metrics_category_split.csv` (unrelated to
  this phase, last touched the day before this session per its file timestamp) was not rewritten.
- `pipeline/reference/no_uk_agreement.csv`, `failure_category_agreement.csv`: regenerated by
  `build_agreement_study.py` and `build_failure_category_agreement_study.py` respectively, both run
  unmodified.

Not touched: `crosswalk.csv`, `crosswalk_review.csv`, `model_age_band_metrics.csv`,
`model_age_band_category_failure_rates.csv`, `model_bracket_rankings.csv`, anything under `site/`.
