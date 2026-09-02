"""Stage B + C of the Norway crosswalk: match Denmark's confirmed DMR model
universe (reference/crosswalk.csv, the same 245 rows Phase 2 already reviewed
and promoted for the UK match) against Norwegian PKK model strings, and emit
no_crosswalk_review.csv for human review. Nothing here is auto-accepted by
this script -- auto_decide_no_crosswalk.py handles the narrow, no-inference
auto-confirmations, mirroring the UK pipeline's own two-step split.

Reuses pipeline/src/crosswalk_normalize.py and the matching primitives from
build_crosswalk_review.py (dmr_probes, best_prefix_identity, match_model)
UNCHANGED, per the phase brief's explicit instruction to reuse the existing
machinery rather than invent a parallel mechanism. Those functions are pure
string/count-dict logic with no DVSA-specific assumption baked in, so pointing
them at a Norwegian (code_counts, name_counts, family_series_counts, prefix_counts)
index built from pkk_inspections instead of mot_tests works unchanged.

What IS new here, because Norway's hazard is structurally different from the
UK one (see reports/norway_pkk_report.md, "the hazard" section):

  - Norwegian raw model strings carry their own make-name-prefix duplicate
    problem ('RAV4' vs 'TOYOTA RAV4', both real, both high-volume) -- on the
    UK side this never happens; DVSA's own model field is always make-free.
    So NO model strings are make-prefix-stripped BEFORE being folded into the
    code/name index, the same rule build_crosswalk_review.py's match_model()
    already applies when scrubbing DMR's glued 'MAZDA2'-style strings, just
    applied here on the candidate-index side instead of the query side.
  - Norwegian make strings need NO alias table at all: verified all 26 DK
    makes in crosswalk.csv have an exact normalize()-identical Norwegian make
    string present in the data (no Opel/Vauxhall-style rebrand exists in a
    Norwegian market), so the DK make name is used as the NO make lookup key
    directly.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_crosswalk_review import best_prefix_identity, match_model  # noqa: E402
from crosswalk_normalize import first_token, is_code_like, leading_code, normalize  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
DK_CROSSWALK_CSV = ROOT / "pipeline" / "reference" / "crosswalk.csv"
REVIEW_CSV = ROOT / "pipeline" / "reference" / "no_crosswalk_review.csv"

# Noise floor for candidate generation only (NOT the final ranking stability
# floor, which is computed separately in build_norway_metrics.py from Norway's
# own observed pass-rate variance). This threshold exists purely to stop a
# handful of stray mis-keyed PKK rows from being proposed as if they were a
# real model bucket -- same purpose as build_crosswalk_review.py's
# STABILITY_THRESHOLD, set far lower because Norway's total scoped volume
# (2.83M) is about 4% of the UK's, so reusing 2000 here would silently starve
# candidate generation, not just gate ranking eligibility.
MATCH_NOISE_FLOOR = 30

# The same final scope build_norway_metrics.py uses: PERSONBIL, Periodisk only
# (initial tests), non-BEV/hydrogen. Fixed here too so the counts driving
# match confidence are the same population the metrics are computed from, not
# some other slice.
SCOPE_SQL = """
    gruppeavgift = 'PERSONBIL'
    AND kontrolltype = 'Periodisk'
    AND fuel IS NOT NULL AND fuel NOT IN ('Elektrisk', 'Hydrogen')
"""


def strip_make_prefix(model_norm: str, make_norm: str) -> str:
    """'TOYOTA RAV4' -> 'RAV4' when the model string is make-prefixed with a
    space; 'MAZDA2' -> '2' when glued directly with no space. Mirrors the
    identical two-branch rule in build_crosswalk_review.match_model()'s own
    DMR-side prefix handling, applied here to Norwegian model strings instead."""
    if model_norm == make_norm:
        return model_norm
    if model_norm.startswith(make_norm + " "):
        return model_norm[len(make_norm) + 1:]
    if model_norm.startswith(make_norm) and len(model_norm) > len(make_norm):
        return model_norm[len(make_norm):]
    return model_norm


def normalize_no_raw(s: str) -> str:
    """Normalizes one Norwegian Kjoretoy Modell string, on top of the shared
    normalize(). Norway's own data carries a comma-separated secondary
    type-approval designation the shared normalize() has no reason to strip,
    since Danish DMR model strings never carry this pattern: 'AUDI A4, S4'
    records the A4 and its S4 performance sibling under one type-approval
    string. Verified directly against the data: without this, 'AUDI A4, S4'
    (4,169 inspections), 'AUDI A3, S3' (3,292), 'AUDI A6, S6' (2,102)
    classify to a dangling first token with a trailing comma ('A3,') that
    matches no DK model at all, silently dropping ~9,500 Audi inspections.
    Treating the comma the same as normalize() already treats '-' and '/'
    (collapse to a space) folds these into the base nameplate's own bucket."""
    return normalize(s.replace(",", " "))


# Norway writes a handful of its own alphanumeric model codes both glued
# ('V70') and with a stray space ('V 70') -- confirmed directly in the data:
# each glued form here is independently the dominant, far-higher-volume
# spelling for the same make, and the make carries no bare single-letter DK
# model of its own. This is NOT a general letter+digit glue rule: Mercedes
# writes 'A 200' / 'C 180' (class letter, space, engine number) as its
# correct and ONLY convention, where 'A' is itself a real nameplate
# ('A-Klasse') and gluing would invent a fake code ('A200') that appears
# nowhere else in the data. So this table is scoped make-by-make and
# code-by-code to entries verified as spacing accidents, never inferred.
SPACED_CODE_GLUE = {
    ("VOLVO", "V"): {"70", "40"},  # 'V 70' (2,915 insp.) / 'V 40' (140) vs 'V70' (45,991) / 'V40' (15,145) unspaced
    ("VOLVO", "XC"): {"90"},       # 'XC 90' (84 insp.) vs 'XC90' (15,792) unspaced
}


def despace_known_code(norm: str, make_norm: str) -> str:
    """Glues the first two tokens together when they match a verified
    spacing-accident entry in SPACED_CODE_GLUE ('V 70' -> 'V70'). A no-op for
    everything else, including every Mercedes class-letter string."""
    toks = norm.split(" ", 2)
    if len(toks) >= 2:
        glue_set = SPACED_CODE_GLUE.get((make_norm, toks[0]))
        if glue_set and toks[1] in glue_set:
            rest = toks[2:] if len(toks) > 2 else []
            return " ".join([toks[0] + toks[1]] + rest)
    return norm


def classify_model_token(model_raw: str, make_norm: str) -> str | None:
    """Returns the single bucket key one Norwegian raw model string resolves
    to: a bare family-series digit's '{d} SERIES' literal, a short code
    ('320', 'X3', 'C'), or a name token (first word of a multi-word model).
    None if the string is empty after make-prefix stripping.

    This is THE classification rule, used both when aggregating counts to
    build the per-make match index (build_no_index) and, unchanged, when
    build_norway_metrics.py resolves which actual raw model strings a
    confirmed crosswalk row's proposed_no_model_token covers -- one function,
    so the two can never silently drift apart."""
    if not model_raw:
        return None
    norm = normalize(strip_make_prefix(normalize_no_raw(model_raw), make_norm))
    if not norm:
        return None
    norm = despace_known_code(norm, make_norm)
    tok = first_token(norm)
    if len(tok) == 1 and tok.isdigit() and norm == f"{tok} SERIES":
        return tok  # bare family digit, matching family_series_counts' own key convention
    code = leading_code(norm)
    if code is not None and is_code_like(tok):
        return code
    if not is_code_like(tok):
        return tok
    return None


def build_no_index(con: duckdb.DuckDBPyConnection, no_make: str):
    """Returns (code_counts, name_counts, family_series_counts, prefix_counts)
    for one Norwegian make, built the same way build_crosswalk_review.py
    builds them for a DVSA make -- classify each (already make-prefix-
    stripped) normalized model string as a short code, a bare family-series
    digit, or a name token, and separately build a token-prefix index for
    exact-identity matching."""
    rows = con.execute(
        f"SELECT model_raw, COUNT(*) c FROM pkk_inspections WHERE make = ? AND {SCOPE_SQL} GROUP BY 1",
        [no_make],
    ).fetchall()

    make_norm = normalize(no_make)
    code_counts: dict[str, int] = defaultdict(int)
    name_counts: dict[str, int] = defaultdict(int)
    family_series_counts: dict[str, int] = defaultdict(int)
    prefix_counts: dict[str, int] = defaultdict(int)

    for raw_model, count in rows:
        if not raw_model:
            continue
        norm = normalize(strip_make_prefix(normalize_no_raw(raw_model), make_norm))
        if not norm:
            continue
        norm = despace_known_code(norm, make_norm)

        tokens = norm.split(" ")
        for i in range(1, len(tokens) + 1):
            prefix_counts[" ".join(tokens[:i])] += count

        key = classify_model_token(raw_model, make_norm)
        if key is None:
            continue
        tok = first_token(norm)
        if len(tok) == 1 and tok.isdigit() and norm == f"{tok} SERIES":
            family_series_counts[key] += count
        elif is_code_like(tok):
            code_counts[key] += count
        else:
            name_counts[key] += count

    return code_counts, name_counts, family_series_counts, dict(prefix_counts)


def build_no_make_lookup(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """normalize(no_make) -> actual NO make string, so a DK make string that
    differs only by diacritic or punctuation ('CITROËN' vs Norwegian data's
    plain 'CITROEN') still resolves to the real NO make string for the SQL
    lookup below, instead of requiring byte-for-byte identity."""
    rows = con.execute(f"SELECT DISTINCT make FROM pkk_inspections WHERE gruppeavgift = 'PERSONBIL'").fetchall()
    out = {}
    for (m,) in rows:
        if m:
            out[normalize(m)] = m
    return out


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    no_make_lookup = build_no_make_lookup(con)

    with open(DK_CROSSWALK_CSV, encoding="utf-8") as f:
        dk_rows = list(csv.DictReader(f))

    # One row per distinct (dmr_make, dmr_model) -- crosswalk.csv repeats a
    # model across several proposed_dvsa_model_token rows (one-to-many UK
    # matches), but we only need to run the NO match once per Danish model.
    seen = set()
    dk_models = []
    for r in dk_rows:
        key = (r["dmr_make"], r["dmr_model"])
        if key in seen:
            continue
        seen.add(key)
        dk_models.append((r["dmr_make"], r["dmr_model"], int(r["dk_vehicle_count"])))
    dk_models.sort(key=lambda x: -x[2])

    no_index_cache: dict[str, tuple] = {}
    out_rows = []
    no_make_missing = []

    for dmr_make, dmr_model, dk_count in dk_models:
        no_make = no_make_lookup.get(normalize(dmr_make))  # verified: normalize()-identical match exists for all 26 DK makes
        if no_make is None:
            no_index_cache.setdefault(f"__missing__{dmr_make}", None)
            no_make_missing.append((dmr_make, dmr_model, dk_count))
            out_rows.append(dict(
                dmr_make=dmr_make, dmr_model=dmr_model, dk_vehicle_count=dk_count,
                proposed_no_make="", proposed_no_model_token="", no_inspection_count=0,
                confidence="no-make-in-no-data", rule_fired="", match_score="",
                decision="", decision_basis="",
            ))
            continue
        if no_make not in no_index_cache:
            present = con.execute(
                f"SELECT COUNT(*) FROM pkk_inspections WHERE make = ? AND {SCOPE_SQL}", [no_make]
            ).fetchone()[0]
            if present == 0:
                no_index_cache[no_make] = None
            else:
                no_index_cache[no_make] = build_no_index(con, no_make)

        idx = no_index_cache[no_make]
        if idx is None:
            no_make_missing.append((dmr_make, dmr_model, dk_count))
            out_rows.append(dict(
                dmr_make=dmr_make, dmr_model=dmr_model, dk_vehicle_count=dk_count,
                proposed_no_make="", proposed_no_model_token="", no_inspection_count=0,
                confidence="no-make-in-no-data", rule_fired="", match_score="",
                decision="", decision_basis="",
            ))
            continue

        code_counts, name_counts, family_series_counts, prefix_counts = idx
        dmr_norm = normalize(dmr_model)
        make_norm = normalize(dmr_make)

        identity_hit = best_prefix_identity(dmr_norm, make_norm, prefix_counts, MATCH_NOISE_FLOOR)
        candidates = None
        if identity_hit:
            tok, count = identity_hit
            if count >= MATCH_NOISE_FLOOR:
                candidates = [(tok, count, "exact", "prefix_identity", 1.0)]
        if candidates is None:
            candidates = match_model(dmr_norm, make_norm, code_counts, name_counts, family_series_counts)

        if not candidates:
            out_rows.append(dict(
                dmr_make=dmr_make, dmr_model=dmr_model, dk_vehicle_count=dk_count,
                proposed_no_make=no_make, proposed_no_model_token="", no_inspection_count=0,
                confidence="no-candidate", rule_fired="", match_score="",
                decision="", decision_basis="",
            ))
        else:
            seen_tok = set()
            for tok, count, confidence, rule, score in sorted(candidates, key=lambda c: -c[1]):
                if tok in seen_tok:
                    continue
                seen_tok.add(tok)
                out_rows.append(dict(
                    dmr_make=dmr_make, dmr_model=dmr_model, dk_vehicle_count=dk_count,
                    proposed_no_make=no_make, proposed_no_model_token=tok, no_inspection_count=count,
                    confidence=confidence, rule_fired=rule, match_score=round(score, 4),
                    decision="", decision_basis="",
                ))

    fieldnames = [
        "dmr_make", "dmr_model", "dk_vehicle_count",
        "proposed_no_make", "proposed_no_model_token", "no_inspection_count",
        "confidence", "rule_fired", "match_score", "decision", "decision_basis",
    ]
    with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    n_models = len(dk_models)
    n_no_candidate = sum(1 for r in out_rows if r["confidence"] == "no-candidate")
    n_no_make = sum(1 for r in out_rows if r["confidence"] == "no-make-in-no-data")
    n_exact = sum(1 for r in out_rows if r["confidence"] == "exact")
    print(f"DK models processed: {n_models}")
    print(f"review rows written: {len(out_rows)}")
    print(f"  exact: {n_exact}")
    print(f"  no-candidate: {n_no_candidate}")
    print(f"  no-make-in-no-data: {n_no_make}")
    if no_make_missing:
        print("\nDK makes with zero rows in Norwegian PERSONBIL/Periodisk scope:")
        for m, mo, c in no_make_missing[:20]:
            print(f"  {m} {mo} ({c:,} DK vehicles)")
    print(f"\nwrote {REVIEW_CSV}")

    con.close()


if __name__ == "__main__":
    main()
