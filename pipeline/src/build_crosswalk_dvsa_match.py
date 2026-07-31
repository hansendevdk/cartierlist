"""Resolves crosswalk.csv's (proposed_dvsa_make, proposed_dvsa_model_token)
pairs down to the actual DVSA (make, model) strings in mot_tests, and writes
reference/crosswalk_dvsa_match.csv -- the table Phase 3 metrics actually join
against.

WHY THIS EXISTS SEPARATELY FROM crosswalk.csv
`proposed_dvsa_model_token` is not itself a DVSA model string in most rows --
it is a token PREFIX (see build_crosswalk_review.py's best_prefix_identity),
a leading numeric/alpha CODE, or a literal family-series string, depending on
which rule matched. Re-deriving "which raw DVSA rows does this token cover"
at query time with a SQL LIKE would silently diverge from what Stage B
actually counted, because the matching rule differs by `rule_fired` (a
`LIKE 'token%'` is right for prefix_identity but wrong for code_exact, which
must match on the model's leading numeric code after stripping trim letters,
not on the string prefix). This script re-runs the SAME classification
functions from crosswalk_normalize.py that Stage B used, so the DVSA rows a
model resolves to here are provably the same set Stage B counted -- verified
below by recomputing each model's total test count and diffing it against
crosswalk.csv's own recorded `uk_test_count`. Any mismatch fails the build
loudly instead of silently joining the wrong tests into a metric.

RULE -> MEMBERSHIP TEST (mirrors build_crosswalk_review.py exactly):
  confidence == 'known-rename'   : raw model's first space-separated token
                                    equals the token, verbatim (matches the
                                    literal `split_part(model, ' ', 1) = ?`
                                    query the original script used -- no
                                    normalization applied there, so none here).
  rule_fired == 'family_series_literal' : normalize(model) == token exactly
                                    (token is the literal '{d} SERIES' string).
  rule_fired in ('code_exact', 'family_series_sibling') :
                                    is_code_like(first_token(normalize(model)))
                                    and leading_code(normalize(model)) == token.
  rule_fired == 'prefix_identity' (the vast majority of rows) :
                                    normalize(model) == token, or
                                    normalize(model) starts with token + ' '
                                    (token-boundary prefix, not a raw substring).

A model can have more than one confirmed crosswalk.csv row (BMW's family-series
models list a sibling row per numbered variant: 316/318/320/330 all under
"3-Serie"), so this script accumulates DVSA matches across every row for the
same (dmr_make, dmr_model) rather than assuming one row per model, and dedupes
the resulting (dvsa_make, dvsa_model) pairs so a model matched by two rules
that happen to reach the same raw DVSA row isn't double-counted.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import duckdb

from crosswalk_normalize import first_token, is_code_like, leading_code, normalize

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
CROSSWALK_CSV = ROOT / "pipeline" / "reference" / "crosswalk.csv"
OUT_CSV = ROOT / "pipeline" / "reference" / "crosswalk_dvsa_match.csv"


def matches(rule: str, confidence: str, raw_model: str, norm: str, token: str) -> bool:
    if confidence == "known-rename":
        return raw_model.split(" ", 1)[0] == token
    if rule == "family_series_literal":
        return norm == token
    if rule in ("code_exact", "family_series_sibling"):
        tok = first_token(norm)
        return is_code_like(tok) and leading_code(norm) == token
    if rule == "prefix_identity":
        return norm == token or norm.startswith(token + " ")
    raise ValueError(f"unhandled rule_fired {rule!r} (confidence={confidence!r})")


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)

    with open(CROSSWALK_CSV, encoding="utf-8") as f:
        cw_rows = list(csv.DictReader(f))

    makes_needed = sorted({r["proposed_dvsa_make"] for r in cw_rows})
    placeholders = ",".join(["?"] * len(makes_needed))
    dist = con.execute(
        f"SELECT make, model, COUNT(*) AS c FROM mot_tests WHERE make IN ({placeholders}) GROUP BY 1, 2",
        makes_needed,
    ).fetchall()

    by_make: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for make, model, count in dist:
        by_make[make].append((model, count, normalize(model)))

    # expected total per (dmr_make, dmr_model), for the reconciliation check
    expected_total: dict[tuple[str, str], int] = {}
    for r in cw_rows:
        key = (r["dmr_make"], r["dmr_model"])
        expected_total[key] = int(r["uk_test_count"])

    match_pairs: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for r in cw_rows:
        key = (r["dmr_make"], r["dmr_model"])
        dvsa_make = r["proposed_dvsa_make"]
        token = r["proposed_dvsa_model_token"]
        rule = r["rule_fired"]
        confidence = r["confidence"]
        for raw_model, count, norm in by_make.get(dvsa_make, []):
            if matches(rule, confidence, raw_model, norm, token):
                match_pairs[key].add((dvsa_make, raw_model))

    # reconciliation: recompute each row's own test count (not the deduped
    # per-model union) against crosswalk.csv's recorded uk_test_count, so a
    # BMW-style multi-row model still gets checked row by row.
    mismatches = []
    for r in cw_rows:
        dvsa_make = r["proposed_dvsa_make"]
        token = r["proposed_dvsa_model_token"]
        rule = r["rule_fired"]
        confidence = r["confidence"]
        total = sum(
            count for raw_model, count, norm in by_make.get(dvsa_make, [])
            if matches(rule, confidence, raw_model, norm, token)
        )
        expected = int(r["uk_test_count"])
        if total != expected:
            mismatches.append((r["dmr_make"], r["dmr_model"], dvsa_make, token, rule, expected, total))

    out_rows = []
    for (dmr_make, dmr_model), pairs in match_pairs.items():
        for dvsa_make, dvsa_model in sorted(pairs):
            out_rows.append((dmr_make, dmr_model, dvsa_make, dvsa_model))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dmr_make", "dmr_model", "dvsa_make", "dvsa_model"])
        w.writerows(out_rows)

    n_models = len(match_pairs)
    n_no_match = sum(1 for v in match_pairs.values() if not v)
    print(f"models resolved: {n_models}")
    print(f"DVSA (make, model) pairs written: {len(out_rows)}")
    print(f"models with zero resolved DVSA rows: {n_no_match}")
    if mismatches:
        print(f"\nRECONCILIATION FAILURES: {len(mismatches)} crosswalk.csv rows' recomputed "
              f"test count disagrees with the recorded uk_test_count:")
        for m in mismatches[:20]:
            print(f"  {m[0]} {m[1]} -> {m[2]} {m[3]!r} ({m[4]}): expected {m[5]:,}, recomputed {m[6]:,}")
        raise SystemExit(1)
    print("reconciliation OK: every row's recomputed DVSA test count matches crosswalk.csv exactly")
    print(f"wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
