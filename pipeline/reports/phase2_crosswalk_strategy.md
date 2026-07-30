# Phase 2 — Crosswalk strategy

Written before implementation, from direct inspection of both sources' actual strings.
Implementation follows this document; deviations from it are decisions, not details,
and should come back for review.

## The headline finding: this is not one fuzzy-matching problem

Naive string similarity does not merely underperform here. On the highest-volume
makes it ranks the **correct answer last** and a **statistically poisonous answer
first**. Three concrete cases found in the data:

**1. Opel/Vauxhall is a trap, not a gap.** Opel is Denmark's 11th largest make
(76,480 vehicles, ~4.3% of the in-scope fleet). The same cars are sold in the UK
as Vauxhall. Critically, DVSA *does* contain a make literally spelled `OPEL`:

| DVSA make | tests |
|---|---|
| `VAUXHALL` | 7,270,458 |
| `OPEL` | 2,526 |

Both carry the same model names. `CORSA` appears as `VAUXHALL` (2,306,909 tests)
and as `OPEL` (287 tests, grey imports). An exact make match would silently join
Danish Opel Corsa to 287 UK grey-import tests, return a plausible-looking pass
rate built on noise, and never announce that it did so. That is the exact
silent-corruption mode the brief warns about, and it would pass any "did we find
a match?" check.

**2. Mercedes: similarity ranks the right answer dead last.** Danish
`C-Klasse` (12,063 vehicles). UK candidates under Mercedes-Benz:

| UK model string | tests |
|---|---|
| `C` | 854,856 |
| `CLA` | 139,648 |
| `CLK` | 68,136 |
| `CLS` | 55,275 |
| `CITAN` | 46,016 |

The correct target is `C`. Every common similarity metric scores `C-Klasse`
against the three-letter candidates higher than against the one-letter `C`,
because length ratio dominates on short strings. The right answer is the worst
scoring one.

**3. Numeric model names have tiny edit distance and no semantic relation.**
Peugeot alone, all high volume and all distinct vehicles:

`107` `108` `206` `207` `208` `2008` `307` `308` `3008` `407` `508` `5008`

`208` (supermini hatchback, 521,212 tests) and `2008` (crossover SUV, 331,689
tests) are one character apart. Same for `308`/`3008`, `508`/`5008`. BMW is worse:
`316` `318` `320` `330` `420` `430` `435` `520` `525` `530` are separate strings,
one digit apart, different cars. Fuzzy matching cannot be trusted anywhere near
these, at any threshold.

## Approach: three stages, only one of which is fuzzy

### Stage A — make-level alias table (hand-authored, versioned)

A closed set of roughly 40 to 60 makes. Small enough to author by hand, high
enough stakes to never guess. Treated as source code, exactly like the Phase 3
parts-cost multiplier table.

`reference/make_aliases.csv`, columns: `dmr_make_name`, `dvsa_make`, `basis`.

Entries known to be needed from inspection so far:

| dmr_make_name | dvsa_make | basis |
|---|---|---|
| `OPEL` | `VAUXHALL` | Same vehicles, GM Europe/Stellantis UK brand. Must NOT map to DVSA's tiny `OPEL` grey-import make. |
| `CITROËN` | `CITROEN` | Diacritic only. |
| `VW` | `VOLKSWAGEN` | DMR-internal inconsistency: DMR carries both `VOLKSWAGEN` (225,002) and `VW` (4,632). |

The table must also record makes with **no UK equivalent** explicitly, as a
positive assertion rather than an absence, so that a missing mapping is
distinguishable from an unreviewed one.

Rule: a Danish make with no row in this table does not proceed to Stage B. No
implicit fallback to string equality, because string equality is precisely what
produces the Opel failure.

### Stage B — candidate generation (the only fuzzy step)

Runs **within** an already-resolved make pair, never across makes.

*Normalization applied to both sides before any comparison.* Each rule is
hand-authored with a stated reason, not learned:

- Unicode NFD, strip combining marks, uppercase (`CITROËN` → `CITROEN`).
- Strip the Danish prefix `NY ` (Danish for "new"): DMR carries `Ny Clio`,
  `Ny Mondeo`, `Ny C-Max`, `Ny Berlingo` as model names. `Ny Clio` alone is
  26,976 vehicles, Denmark's 14th largest model.
- `-KLASSE` → `-CLASS` → bare letter, to reach DVSA's convention
  (`C-Klasse` → `C`).
- BMW/Mercedes series notation: DMR carries `3'ER`, `` 3`ER ``, `3-serie`,
  `3 SERIE`, `3'ER-SERIE`, `1'ER REIHE` (German leaking in) for what DVSA calls
  `3 SERIES`. Normalize the family to a single canonical form.
- Collapse DVSA trim tails to the model token (`CORSA ELITE NAV PREMIUM TURBO`
  → `CORSA`). First-token split is an effective *candidate generator*: it
  collapses 47 distinct Peugeot strings into `208`, 84 into `308`. It is not a
  decision rule, and has known failures (`GRAND C4 PICASSO` → `GRAND`;
  `ASTRAVAN` is a van, not an `ASTRA`), which is why nothing auto-accepts.

*Hard rules that override the similarity score entirely.* These are gates, not
weights, and no threshold tuning can substitute for them:

- **R1 — numeric tokens require exact equality.** If either side's normalized
  model token matches `^[0-9]+[A-Z]?$`, only exact string equality may be
  proposed above `low` confidence. `208` never proposes against `2008` at any
  score.
- **R2 — one-to-many is expected and must be representable.** Danish
  `BMW 3-serie` legitimately covers UK `3 SERIES` *and* `316`, `318`, `320`,
  `330`. Matching only `3 SERIES` discards 180,000+ tests. The output schema
  must allow several UK tokens per Danish model.
- **R3 — regression fixtures, not hope.** The known collision set is committed
  as test cases the pipeline must pass: `208`/`2008`, `308`/`3008`,
  `508`/`5008`, `316`/`318`/`320`, `C3`/`C4`/`C5`, `ASTRA`/`ASTRAVAN`,
  `CORSA`(Vauxhall)/`CORSA`(Opel grey import). A build that mismatches any of
  these fails.

### Stage C — human review, nothing auto-accepted

Per the brief, no fuzzy match is silently accepted. Output is
`crosswalk_review.csv`, **sorted by Danish fleet count descending**, with enough
context to judge each row without opening the database:

`dmr_make`, `dmr_model`, `dk_vehicle_count`, `dk_sample_variants` (3 real
variant strings), `proposed_dvsa_make`, `proposed_dvsa_model_token`,
`uk_test_count`, `confidence`, `rule_fired`, `decision` (blank for you to fill:
`y` / `n` / `?`).

Confidence tiers, all of which still require review:

| tier | meaning |
|---|---|
| `exact` | normalized strings identical, no hard rule implicated |
| `high` | token-boundary prefix relationship |
| `medium` | above similarity threshold, no hard rule fired |
| `collision-risk` | a hard rule fired; proposed only for visibility, expected to be rejected |

Confirmed rows are promoted into `crosswalk.csv` (version controlled, treated as
source code per the brief). Every row carries `y`, `n`, or `unreviewed`, and
**`unreviewed` rows are excluded from all downstream metrics** by construction,
not by convention: the Phase 3 join reads only `decision = 'y'`.

## Coverage: do not accept 83.5%

Correcting the number from our exchange: the figure is **83.5%**, not 93%, and
it sits *below* the brief's ≥85% bar rather than above it. It also is not a
constraint we are stuck with. It is simply what the top 150 models happen to
cover, and nothing requires stopping at 150:

| models reviewed | fleet coverage |
|---|---|
| 150 | 83.5% |
| **163** | **85.0%** (clears the brief's bar) |
| 191 | 88.0% |
| **214** | **90.0%** (recommended target) |
| 335 | 95.0% |

**Recommendation: build the review file to 214 models (90%).** The extra 64 rows
over the brief's 150 are cheap to review because the file is sorted by fleet
count, and the headroom matters: some Danish models will legitimately have no UK
counterpart, and starting at exactly 85% leaves no room to lose any without
falling under. Review stops when cumulative *confirmed* coverage passes the
target, so the tail costs nothing if the bar is met early.

## Threshold for statistical stability

The brief requires setting this explicitly. For a pass rate near 0.75, standard
error is `sqrt(0.75 × 0.25 / n)`:

| n tests | SE |
|---|---|
| 500 | 1.94 pp |
| 1,000 | 1.37 pp |
| **2,000** | **0.97 pp** |
| 5,000 | 0.61 pp |

**Proposed: n ≥ 2,000 initial (NT) tests per (model, age band)**, giving under
one percentage point of standard error. Since the output is ordinal, the
question is whether adjacent ranks are distinguishable, and sub-1pp noise
against typical between-model spreads of 5 to 20pp is comfortable. Models below
threshold are **excluded from ranking rather than displayed with wide error
bars**, since the site presents a tier list and a visibly uncertain tier is
worse than an absent one. Final call belongs to Phase 3; flagging the arithmetic
now because it determines which crosswalk rows are worth your review time.

## Risks to surface now, per the brief

**Variant-mix divergence is a real threat and subtler than model divergence.**
The brief asks me to flag models where UK and Danish variants differ
mechanically. The sharper version of that problem is when the *model* matches
but the *mix within it* does not. Denmark's single largest Ford Kuga variant is
`2.5 Plug-in Hybrid (225 HK)` (12,560 vehicles, 6th largest Danish variant
overall). If UK Kuga tests are predominantly 2.0 diesel, the model-level match
is correct while the reliability transfer is not. This cannot be resolved in
Phase 2 because DVSA has no variant field to compare against, only
`cylinder_capacity` and `fuel_type`. **Recommendation for Phase 3:** compare
Danish variant fuel-mix against DVSA `fuel_type` distribution per matched model
and flag divergent ones, rather than assuming transfer holds.

**Opel model names may diverge inside the make rebrand.** Verified: Danish
`OPEL KARL` (8,920 vehicles) has zero UK Vauxhall tests under `KARL`, because
the UK sells that car as the Vauxhall **Viva** (87,941 tests). So the alias
problem recurs one level down, and a make-level alias alone will not catch it.
Model-level renames must be reviewable in Stage C, which the review-file format
supports (you can correct a proposed token by hand).

## Handover

Implementation goes to **Sonnet 5**. The decisions above are settled; the
mechanics of normalization, scoring, and CSV generation are not judgement calls
and should not be re-litigated during implementation. Two things must come back
to review before Phase 3 consumes any of this:

1. The completed `make_aliases.csv` (I have seeded three entries; the rest need
   authoring against the actual make list).
2. Confirmed coverage after your review pass, measured as a percentage of the
   Danish fleet by vehicle count, counting only `decision = 'y'` rows.
