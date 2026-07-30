"""Fills the `decision` column in crosswalk_review.csv for rows that require no
human judgement, leaving genuinely ambiguous rows blank.

The brief says not to silently auto-accept fuzzy matches. This does not do that.
It auto-accepts only rows where NO inference was made -- where some faithful form
of the Danish model name is *literally* a DVSA model-name prefix (match_score
1.0), or where the match is a researched fact recorded in the source. Rows that
required a similarity judgement are left for a human, always.

Every auto-decision writes its reasoning into `decision_basis`, so the whole set
is auditable and reversible: re-running after editing the rules regenerates the
column, and any row can be overridden by hand.

Rules, in order:
  1. score < 1.0                  -> leave blank. An inference was made.
  2. uk_test_count < threshold    -> 'n'. Below the statistical-stability floor,
                                    so unusable downstream even if correct.
                                    Rejecting is not a claim that it is wrong.
  3. prefix_identity / *_exact    -> 'y'. Literal string identity.
  4. known-rename                 -> 'y'. Researched and recorded in-source.
  5. family_series_literal        -> 'y'. "3-Serie" -> DVSA's own "3 SERIES".
  6. family_series_sibling        -> 'y'. A numbered member of the same family
                                    ("320" for "3-Serie"), structurally implied
                                    rather than inferred from string shape.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

REVIEW_CSV = Path(__file__).resolve().parents[1] / "reference" / "crosswalk_review.csv"
STABILITY_THRESHOLD = 2000

IDENTITY_RULES = {"prefix_identity", "code_exact", "short_code_exact"}
STRUCTURAL_RULES = {"family_series_literal", "family_series_sibling"}


def decide(row: dict) -> tuple[str, str]:
    score = float(row["match_score"]) if row["match_score"] else 0.0
    uk = int(row["uk_test_count"]) if row["uk_test_count"] else 0
    rule = row["rule_fired"]
    confidence = row["confidence"]

    if confidence == "known-rename":
        if uk < STABILITY_THRESHOLD:
            return "n", f"researched rename but only {uk:,} UK tests, below {STABILITY_THRESHOLD:,} floor"
        return "y", "researched model-level rename recorded in source, not a string guess"

    if score < 1.0:
        return "", f"similarity {score:.2f} is an inference, not an identity -- needs a human"

    if uk < STABILITY_THRESHOLD:
        return "n", (
            f"exact match but only {uk:,} UK tests, below the {STABILITY_THRESHOLD:,} "
            f"stability floor -- unusable downstream, not necessarily wrong"
        )

    if rule in IDENTITY_RULES:
        return "y", f"literal string identity ({rule}), {uk:,} UK tests"

    if rule in STRUCTURAL_RULES:
        return "y", f"structural family membership ({rule}), {uk:,} UK tests"

    return "", f"unrecognised rule {rule!r} -- needs a human"


def main() -> None:
    with open(REVIEW_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    for r in rows:
        if r["decision"].strip():
            continue  # never overwrite a human decision
        d, basis = decide(r)
        r["decision"] = d
        r["decision_basis"] = basis

    with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    by_model = defaultdict(list)
    for r in rows:
        by_model[(r["dmr_make_id"], r["dmr_model_id"])].append(r)

    n_y = sum(1 for r in rows if r["decision"] == "y")
    n_n = sum(1 for r in rows if r["decision"] == "n")
    n_blank = sum(1 for r in rows if not r["decision"])

    def fleet(models):
        return sum(int(by_model[m][0]["dk_vehicle_count"]) for m in models)

    all_models = set(by_model)
    settled = {m for m, g in by_model.items() if any(r["decision"] == "y" for r in g)
               and not any(not r["decision"] for r in g)}
    needs_human = {m for m, g in by_model.items() if any(not r["decision"] for r in g)}
    no_usable = {m for m, g in by_model.items()
                 if all(r["decision"] == "n" for r in g)}

    total_fleet = fleet(all_models)
    print(f"rows: {len(rows)}   auto-y: {n_y}   auto-n: {n_n}   left blank: {n_blank}")
    print()
    print(f"models fully settled automatically : {len(settled):>4}  "
          f"({fleet(settled):>9,} vehicles, {fleet(settled)/total_fleet*100:.1f}%)")
    print(f"models with no usable UK match     : {len(no_usable):>4}  "
          f"({fleet(no_usable):>9,} vehicles, {fleet(no_usable)/total_fleet*100:.1f}%)")
    print(f"models still needing a human       : {len(needs_human):>4}  "
          f"({fleet(needs_human):>9,} vehicles, {fleet(needs_human)/total_fleet*100:.1f}%)")

    if needs_human:
        print("\nrows left for you, by fleet size:")
        for m in sorted(needs_human, key=lambda m: -int(by_model[m][0]["dk_vehicle_count"])):
            g = by_model[m]
            head = g[0]
            print(f"\n  {int(head['dk_vehicle_count']):>7,}  {head['dmr_make']} {head['dmr_model']}")
            for r in g:
                mark = {"y": "Y", "n": "n", "": "?"}[r["decision"]]
                print(f"      [{mark}] {r['proposed_dvsa_model_token']:<20} "
                      f"uk={int(r['uk_test_count']):>9,}  score={r['match_score']}")

    if no_usable:
        print("\nmodels with no usable UK equivalent (excluded, not matched):")
        for m in sorted(no_usable, key=lambda m: -int(by_model[m][0]["dk_vehicle_count"])):
            head = by_model[m][0]
            best = max(int(r["uk_test_count"]) for r in by_model[m])
            print(f"  {int(head['dk_vehicle_count']):>7,}  {head['dmr_make']} {head['dmr_model']:<24} "
                  f"best UK candidate had {best:,} tests")


if __name__ == "__main__":
    main()
