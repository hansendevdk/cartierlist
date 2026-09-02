"""Merges (make, model) rows in model_age_band_metrics.csv that are the same
real car split into two DMR spellings -- formatting noise (case, stray
whitespace), not a genuine model difference. Found while building the site:
Astro's static router collapsed two rows to the same URL slug and refused to
build one of them, which is what surfaced FORD "FOCUS" vs "Focus" first.
A full scan (comparing DVSA-side stats, see below) turned up three more:
CITROËN "C1"/"C 1", FIAT "500C"/"500 C", HYUNDAI "I10"/"I 10".

WHY THIS IS SAFE TO AUTOMATE: a spelling pair is only merged if every
DVSA-derived field (n_nt_tests, pass rates, repair burden index) is IDENTICAL
between the two rows at every age band they share. Two rows only produce
identical DVSA figures if both spellings resolved to the exact same UK test
pool (see build_crosswalk_dvsa_match.py) -- which can only happen if they are
the same real car. A genuinely different model/variant (e.g. "AYGO" vs
"AYGO 3/5-DØRS", which really are recorded separately in DMR and do carry
different stats) will fail that check and is left untouched, not merged.
This is a real ranking-correctness bug, not a cosmetic one: vehicle-count
and vehicle-attribute figures (fuel cost, weight, engagement) were each
computed from two artificially split, smaller samples instead of one
correct one, and the affected car showed up twice in bracket rankings as if
it were two different cars.

MERGE RULE, per age band, applied to any group of rows sharing (make,
lowercased model with whitespace removed, age band):
  dk_vehicle_count: summed (no data lost).
  n_nt_tests and every DVSA-derived field (pass rates, repair burden):
    asserted equal across the whole group before merging. If they ever
    aren't, this script stops rather than silently picking one.
  Every DMR-vehicle-derived field (fuel cost, ejerafgift, weight,
    power-to-weight, engagement and its percentile components): recomputed
    as a dk_vehicle_count-weighted average across the group's medians. This
    is an approximation -- averaging medians is not the same as the true
    median of the pooled vehicles -- but is far closer to correct than
    keeping contradictory rows or arbitrarily discarding one.

CANONICAL SPELLING IS CHOSEN ONCE PER GROUP, ACROSS ALL BANDS -- NOT PER
BAND. THIS IS BAND-INVARIANT ON PURPOSE, AND GETTING IT WRONG IS A REAL BUG,
NOT A COSMETIC ONE. An earlier version of this script picked the canonical
spelling independently in each band (whichever variant had the most vehicles
IN THAT BAND). That is a reasonable rule for which spelling's PRICE VALUE to
prefer per band in dedupe_price_estimates below (kept, see that function),
but it is the wrong rule for the row's IDENTITY, because build_phase4_rankings.py
looks up a model's later-age-band price with an exact (make, model,
age_band) string match (HORIZON_SPEC's exit-band lookup: band 1 -> exit
band 3, band 2 -> exit band 4, band 3 -> exit band 4). A model that answers
to "FIESTA" at band 2 and "FIESTA 5 DØRS" at band 4 -- both true per-band
vehicle-count leaders -- makes that lookup miss, and the row gets wrongly
excluded as no_exit_band_data even though both bands are the exact same
real car with real data. Caught in review after this file's first version
shipped: 15 common cars (Fiesta, Ceed, C-Klasse, E-Klasse, Mazda2/3, Clio,
Ibiza, i30 Stc.) silently lost rank-eligibility this way. Fixed by choosing
ONE spelling per (make, merge group), by total vehicle count summed across
EVERY band the group appears in, and using it as every band's `dmr_model`
-- see choose_canonical_spellings(). The per-band price-VALUE preference
(choose_band_preference()) is a separate, still band-local decision that
never changes which label gets written out.

EXTENSION (coverage_audit.md finding 1, "Real findings" item 1): the
whitespace/case normalize key above only catches spelling noise that
survives stripping non-alphanumeric characters -- it cannot know that
"MAZDA2" and bare "2" are the same car, because those strings share almost
no characters. That is a fact about the two spellings resolving to the same
DVSA crosswalk target, not a fact recoverable from the strings themselves,
so no amount of further string-heuristic widening fixes it (and the task
this was written for explicitly rules that out: it would eventually merge
things like FABIA/FABIA COMBI, which are a genuinely different body style
sharing a UK test pool, not a spelling duplicate).

So this now merges on TWO independent keys, tried in order for each row:
  1. reference/model_spelling_aliases.csv -- a version-controlled,
     human-confirmed list of (make, model) -> alias_group, the same
     source-of-truth pattern crosswalk.csv already uses. Pre-populated with
     the 15 groups coverage_audit.md confirmed (see that file's own
     per-group basis notes, including one explicit judgement-call flag on
     Suzuki SX4/SX4 COMBIBACK that could not be independently confirmed).
  2. Falling back to the original normalize_key, for anything not listed.

A pair belonging to the SAME alias_group but landing in different
normalize_key buckets now merges (e.g. "2" and "MAZDA2"); the
DVSA-field-equality assertion below still runs on every merge, aliased or
not, so a group wrongly added to the aliases file would fail loudly here
rather than silently corrupting the output.

Separately, this also now WRITES reference/model_spelling_review.csv: any
(make, model) pair that shares identical DVSA fields at some age band --
the same technical signal a confirmed pair has -- but is NOT already
resolved by either key above. This is the surfacing mechanism the task
requires: a share of DVSA signature is necessary but not sufficient for
"same car" (FABIA/FABIA COMBI share one precisely because DVSA doesn't split
hatch from estate, and they are NOT the same car), so nothing in that file
is ever auto-merged -- it exists purely so a human notices instead of the
split staying invisible.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"
METRICS_CSV = REFERENCE / "model_age_band_metrics.csv"
PRICE_CSV = REFERENCE / "price_estimates_calibrated.csv"
ALIASES_CSV = REFERENCE / "model_spelling_aliases.csv"
REVIEW_CSV = REFERENCE / "model_spelling_review.csv"

DVSA_FIELDS = [
    "n_nt_tests", "meets_stability_floor", "raw_pass_rate", "standardized_pass_rate",
    "reliability_unstable", "repair_burden_index",
]
WEIGHTED_FIELDS = [
    "median_annual_fuel_cost_dkk", "median_annual_ejerafgift_dkk",
    "median_power_to_weight_wkg", "median_weight_kg", "median_cylinder_count",
    "engagement_score", "engagement_pct_power_to_weight",
    "engagement_pct_cylinder_count", "engagement_pct_weight_inverted",
]


def normalize_key(model: str) -> str:
    # Whitespace-only stripping missed the Kia Cee'd SW case: "CEE'D SW" vs
    # "CEED SW" differ only by an apostrophe, so they never even landed in the
    # same group to be considered for merging, a narrower kind of duplicate
    # than the case/whitespace pairs already handled (FOCUS/Focus, C1/C 1,
    # 500C/500 C, I10/I 10). Stripping all non-alphanumeric characters covers
    # that case too. This is still safe: the normalized key only decides who
    # gets compared, the DVSA-field-equality assertion below decides who
    # actually merges, so a coincidental key collision between two genuinely
    # different cars would still be caught rather than silently merged.
    return re.sub(r"[^a-z0-9]", "", model.lower())


def load_spelling_aliases() -> dict[tuple[str, str], str]:
    """(dmr_make, dmr_model) -> alias_group, from the confirmed, human-curated
    reference/model_spelling_aliases.csv. Missing file is not an error (the
    whole extension degenerates to the original normalize_key-only
    behaviour) -- callers get an empty dict."""
    if not ALIASES_CSV.exists():
        return {}
    with open(ALIASES_CSV, encoding="utf-8") as f:
        return {
            (row["dmr_make"], row["dmr_model"]): row["alias_group"]
            for row in csv.DictReader(f)
        }


def build_merge_groups(
    pairs: set[tuple[str, str]], aliases: dict[tuple[str, str], str]
) -> dict[tuple[str, str], str]:
    """Assigns every (make, model) pair in `pairs` a merge-group id, by
    transitively unioning TWO relations rather than picking one key with the
    other as a fallback:
      (a) same (make, normalize_key(model)) -- the original case/whitespace
          rule (FOCUS/Focus, C1/C 1, 500C/500 C, I10/I 10).
      (b) same (make, alias_group) -- the confirmed reference/model_spelling_aliases.csv
          groups, which catch spellings normalize_key cannot (MAZDA2/2).

    UNION, NOT PRIORITY, MATTERS HERE. An earlier version tried alias_group
    first, normalize_key only as a fallback for pairs with no alias entry --
    that silently broke FORD FOCUS/Focus, which had merged correctly via
    normalize_key since this script's very first version: once "FOCUS" also
    needed an alias entry (to reach "NY Focus", a spelling normalize_key
    cannot bridge), it started resolving to the alias key while plain
    "Focus" -- never listed in the aliases file itself, since it was already
    handled -- kept resolving to its normalize_key, and the two diverged.
    Caught by an actual site build: a leftover 'FORD,Focus' row with no price
    produced an unpriced.json entry that collided with the ranked FOCUS
    page's slug, and Astro's build refused to render one of them -- the
    exact failure mode this script was originally written to prevent (see
    module docstring). Unioning both relations into one connected component
    means a model's alias-group membership can never silently detach it from
    a case-only sibling it used to merge with before aliases existed.
    """
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(x: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_norm: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    by_alias: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for make, model in pairs:
        find((make, model))  # ensure every pair is registered, even singletons
        by_norm[(make, normalize_key(model))].append((make, model))
        group = aliases.get((make, model))
        if group is not None:
            by_alias[(make, group)].append((make, model))

    for members in by_norm.values():
        for i in range(1, len(members)):
            union(members[0], members[i])
    for members in by_alias.values():
        for i in range(1, len(members)):
            union(members[0], members[i])

    components: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for p in pairs:
        components[find(p)].append(p)

    result: dict[tuple[str, str], str] = {}
    for members in components.values():
        alias_names = sorted({aliases[m] for m in members if m in aliases})
        # stable, human-readable group id: the alias_group name(s) if any
        # member of the component carries one, else the normalize_key --
        # either way, prefixed by make so it can never collide across makes.
        if alias_names:
            gid = f"{members[0][0]}|alias:{'+'.join(alias_names)}"
        else:
            gid = f"{members[0][0]}|norm:{normalize_key(members[0][1])}"
        for m in members:
            result[m] = gid
    return result


def choose_canonical_spellings(
    rows: list[dict], merge_groups: dict[tuple[str, str], str]
) -> dict[tuple[str, str], str]:
    """GLOBAL identity label per (make, merge_group): the spelling with the
    largest dk_vehicle_count TOTAL summed across EVERY age band the group
    appears in -- not the per-band leader. This is the row's real identity,
    used as the `dmr_model` value for every band's output row (metrics AND
    price, see dedupe_price_estimates), and it MUST be band-invariant: see
    the module docstring for why picking it per band silently broke
    build_phase4_rankings.py's exit-band lookup for 15 common cars."""
    totals: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        key = (r["dmr_make"], merge_groups[(r["dmr_make"], r["dmr_model"])])
        totals[key][r["dmr_model"]] += int(r["dk_vehicle_count"])
    return {key: max(spellings.items(), key=lambda kv: kv[1])[0] for key, spellings in totals.items()}


def choose_band_preference(
    rows: list[dict], merge_groups: dict[tuple[str, str], str]
) -> dict[tuple[str, str, str], str]:
    """Per (make, merge_group, age_band): the raw spelling with the most
    dk_vehicle_count IN THAT BAND SPECIFICALLY. Deliberately separate from
    choose_canonical_spellings' global identity label -- this only decides
    which of several differently-priced spellings' PRICE VALUE to prefer
    for a given band in dedupe_price_estimates (the FIAT 500C case: band 4
    has more "500 C"-spelled vehicles than "500C", so band 4's real-listing
    price is the more representative one to keep for band 4, even though
    "500C" is the group's identity label everywhere because it wins the
    all-bands total). The result of this function is NEVER written out as
    a `dmr_model` value -- only choose_canonical_spellings' output is."""
    per_band: dict[tuple[str, str, str], list[tuple[str, int]]] = defaultdict(list)
    for r in rows:
        key = (r["dmr_make"], merge_groups[(r["dmr_make"], r["dmr_model"])], r["age_band"])
        per_band[key].append((r["dmr_model"], int(r["dk_vehicle_count"])))
    return {key: max(spellings, key=lambda x: x[1])[0] for key, spellings in per_band.items()}


def find_unresolved_shared_signature_groups(
    rows: list[dict], merge_groups: dict[tuple[str, str], str]
) -> list[dict]:
    """Surfaces (make, model) pairs that share identical DVSA fields at some
    age band -- the same technical signal a confirmed alias pair has -- but
    are not already resolved by either merge key. Never merges anything;
    only reports, per the task's explicit instruction not to auto-merge on
    DVSA signature alone (FABIA/FABIA COMBI is the standing counter-example:
    same signature, genuinely different cars).

    Detection: two DISTINCT (make, model) pairs are linked if some age band
    has both present with every DVSA_FIELDS value equal. Links are then
    unioned into connected components per make (so a three-way split like
    the Hyundai i30 group, if it hadn't already been aliased, would surface
    as one group rather than three separate pairwise rows). A component is
    only written out if it contains at least two DIFFERENT merge_groups()
    ids -- i.e., it is not already fully handled by the alias file or the
    normalize_key fallback (see build_merge_groups()).
    """
    by_make_band: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_make_band[(r["dmr_make"], r["age_band"])].append(r)

    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(x: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    shared_band_evidence: dict[tuple[tuple[str, str], tuple[str, str]], set[str]] = defaultdict(set)
    for (make, band), members in by_make_band.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if a["dmr_model"] == b["dmr_model"]:
                    continue
                if all(a[field] == b[field] for field in DVSA_FIELDS):
                    node_a, node_b = (make, a["dmr_model"]), (make, b["dmr_model"])
                    union(node_a, node_b)
                    key = tuple(sorted([node_a, node_b]))
                    shared_band_evidence[key].add(band)

    components: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for node in parent:
        components[find(node)].add(node)

    review_rows = []
    for members in components.values():
        if len(members) < 2:
            continue
        member_group_ids = {merge_groups.get((make, model), f"{make}|unknown:{model}") for make, model in members}
        if len(member_group_ids) <= 1:
            continue  # already fully resolved by one alias group or one normalize_key
        make = next(iter(members))[0]
        models = sorted(model for _, model in members)
        bands = sorted(
            {b for pair, bands_ in shared_band_evidence.items() for b in bands_
             if pair[0] in members and pair[1] in members}
        )
        review_rows.append({
            "dmr_make": make,
            "dmr_models": "; ".join(models),
            "shared_dvsa_signature_bands": "; ".join(bands),
            "note": "shares identical DVSA fields (n_nt_tests, pass rates, repair_burden_index) "
                    "at the listed band(s) but is not in model_spelling_aliases.csv -- confirm by "
                    "hand whether this is a spelling duplicate (add to the aliases file) or a "
                    "genuinely different body style/variant sharing one UK test pool (leave split).",
        })
    return sorted(review_rows, key=lambda r: (r["dmr_make"], r["dmr_models"]))


def main() -> None:
    with open(METRICS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    aliases = load_spelling_aliases()
    metrics_pairs = {(r["dmr_make"], r["dmr_model"]) for r in rows}
    merge_groups = build_merge_groups(metrics_pairs, aliases)
    identity_label = choose_canonical_spellings(rows, merge_groups)

    review_rows = find_unresolved_shared_signature_groups(rows, merge_groups)
    with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["dmr_make", "dmr_models", "shared_dvsa_signature_bands", "note"])
        w.writeheader()
        w.writerows(review_rows)
    print(f"{len(review_rows)} unresolved shared-DVSA-signature group(s) written to {REVIEW_CSV} "
          f"for human review (not merged).")

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["dmr_make"], merge_groups[(r["dmr_make"], r["dmr_model"])], r["age_band"])].append(r)

    out_rows = []
    n_merged_groups = 0
    for (make, group_id, band), members in groups.items():
        label = identity_label[(make, group_id)]

        if len(members) == 1:
            # Still relabelled, even though there's nothing to merge in THIS
            # band: a group with only one spelling present at this band must
            # still answer to the group's global identity, or this band's
            # row would carry a different `dmr_model` than a sibling band
            # that DID merge -- the exact band-invariance bug this rewrite
            # exists to prevent, just via the singleton path instead of the
            # merge path.
            row = dict(members[0])
            row["dmr_model"] = label
            out_rows.append(row)
            continue

        identical = all(
            all(m[field] == members[0][field] for field in DVSA_FIELDS) for m in members
        )
        if not identical:
            spellings = sorted(set(m["dmr_model"] for m in members))
            print(f"NOT merging {make} {spellings} band {band}: DVSA stats differ, "
                  "treating as genuinely different variants, not a formatting duplicate.")
            # Left un-relabelled deliberately: the DVSA-equality proof that
            # would justify claiming these rows are the same car FAILED at
            # this band, so asserting the group's shared identity onto them
            # here would be claiming something just shown not to hold.
            out_rows.extend(members)
            continue

        n_merged_groups += 1
        total = sum(int(m["dk_vehicle_count"]) for m in members)
        canonical = max(members, key=lambda m: int(m["dk_vehicle_count"]))
        merged = dict(canonical)  # DVSA fields (identical across members, any one will do)
        merged["dmr_model"] = label  # GLOBAL identity, not this band's vehicle-count leader
        merged["dk_vehicle_count"] = total
        for field in WEIGHTED_FIELDS:
            values = [(m.get(field), int(m["dk_vehicle_count"])) for m in members]
            if any(v in (None, "") for v, _ in values):
                merged[field] = next((v for v, _ in values if v not in (None, "")), "")
                continue
            merged[field] = round(sum(float(v) * c for v, c in values) / total, 4)
        out_rows.append(merged)
        counts = ", ".join(f"{m['dmr_model']!r}={m['dk_vehicle_count']}" for m in members)
        print(f"merged {make} band {band}: {counts} -> {total} vehicles, "
              f"identity {label!r} (global canonical for this group)")

    with open(METRICS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n{n_merged_groups} case/whitespace-duplicate row groups merged. "
          f"{len(rows)} rows -> {len(out_rows)} rows. Wrote {METRICS_CSV}")

    # Passing the RAW pre-merge rows, not out_rows: dedupe_price_estimates
    # needs each individual spelling's own per-band dk_vehicle_count to
    # compute both its global identity label and its band-local price-value
    # preference (see that function's docstring) -- out_rows has already
    # collapsed that per-spelling detail away.
    dedupe_price_estimates(rows, aliases)


def dedupe_price_estimates(raw_metrics_rows: list[dict], aliases: dict[tuple[str, str], str]) -> None:
    """price_estimates_calibrated.csv is keyed off the same crosswalk model
    strings, so it carries the identical formatting-duplicate split -- but
    since price comes from a foreign-listing match keyed on the exact
    spelling, NOT case/whitespace-insensitive, the two spellings can get
    priced completely differently: one matches its own Poland listings
    directly (pooled_at_brand=False), the other's internal space breaks the
    match and it silently falls back to a brand-wide pooled curve. Found via
    HYUNDAI "I10" (own curve, 70,242 DKK) vs "I 10" (pooled across all of
    Hyundai, including far pricier SUVs, 172,241 DKK) for the identical car
    -- 2.5x apart, not noise. This is a real gap in build_price_estimates.py's
    model matcher, worth fixing there directly at some point; this script
    works around it for the site by always preferring a non-pooled match
    when the group has one, since that's real model-specific data outranking
    a brand-wide fallback. Only averages when every spelling in the group
    pooled the same way (seen for CITROËN "C1"/"C 1", both pooled, ~0.5%
    apart -- a genuine small CO2-median difference between the two DMR-side
    vehicle subsets, not a matching failure).

    price_estimates_calibrated.csv can carry (make, model) spellings the
    metrics file doesn't (or vice versa), so the merge-group graph is
    rebuilt here from the UNION of both files' pairs, not reused from
    main()'s -- a price-only spelling still needs to land in the same group
    as its metrics-side canonical spelling, or it silently keeps its own
    unmerged price entry forever. See build_merge_groups() for why this is a
    union of the normalize_key and alias relations, not one with the other
    as a fallback.

    TWO SEPARATE DECISIONS PER (make, merge_group, age_band), NOT ONE:
    which spelling's PRICE VALUE to prefer for this band (band-local: FIAT
    500C's band 4 has more "500 C"-spelled vehicles than "500C", so band 4's
    real listing is the more representative one to keep, even though the
    other bands lean the other way), versus which spelling to WRITE OUT as
    `dmr_model` (global: must be the exact same string
    choose_canonical_spellings() gave the metrics file, band-invariant, or
    Phase 4's exit-band join breaks -- see module docstring). Conflating
    these into one per-band choice was the original bug; keep them separate
    even though both ultimately come from choose_band_preference() /
    choose_canonical_spellings() run over the same raw per-spelling counts."""
    with open(PRICE_CSV, encoding="utf-8") as f:
        price_rows = list(csv.DictReader(f))
        price_fieldnames = list(price_rows[0].keys())

    all_pairs = {(r["dmr_make"], r["dmr_model"]) for r in raw_metrics_rows} | {
        (r["dmr_make"], r["dmr_model"]) for r in price_rows
    }
    merge_groups = build_merge_groups(all_pairs, aliases)
    identity_label = choose_canonical_spellings(raw_metrics_rows, merge_groups)
    band_preference = choose_band_preference(raw_metrics_rows, merge_groups)

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in price_rows:
        groups[(r["dmr_make"], merge_groups[(r["dmr_make"], r["dmr_model"])], r["age_band"])].append(r)

    kept, n_dropped = [], 0
    for (make, group_id, band), members in groups.items():
        # Which spelling's VALUE to prefer, band-local (see docstring).
        preferred_value_spelling = band_preference.get((make, group_id, band))
        chosen = dict(next((m for m in members if m["dmr_model"] == preferred_value_spelling), members[0]))
        if len(members) > 1:
            n_dropped += len(members) - 1
            non_pooled = [m for m in members if m["pooled_at_brand"] == "False"]
            if non_pooled:
                # a real model-specific match beats a brand-wide fallback,
                # regardless of which spelling triggered which
                best = non_pooled[0]
                chosen["estimated_value_dkk"] = best["estimated_value_dkk"]
                chosen["n_listings"] = best["n_listings"]
                chosen["pooled_at_brand"] = "False"
            else:
                values = [float(m["estimated_value_dkk"]) for m in members]
                if max(values) - min(values) > 0.15 * min(values):
                    raise ValueError(f"price gap too large to average for {make}/{group_id}/{band}: {values}")
                chosen["estimated_value_dkk"] = round(sum(values) / len(values))
        # Which LABEL to write out, global and band-invariant (see
        # docstring) -- independent of which spelling's value was chosen
        # above, and applied even when len(members) == 1, so a band with
        # only one priced spelling still answers to the group's identity.
        chosen["dmr_model"] = identity_label.get((make, group_id), chosen["dmr_model"])
        kept.append(chosen)

    with open(PRICE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=price_fieldnames)
        w.writeheader()
        w.writerows(kept)
    print(f"price_estimates_calibrated.csv: dropped {n_dropped} formatting-duplicate rows "
          f"(preferred non-pooled matches where available), {len(price_rows)} -> {len(kept)} rows")


if __name__ == "__main__":
    main()
