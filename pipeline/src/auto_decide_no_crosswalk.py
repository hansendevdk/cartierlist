"""Fills the `decision` column in no_crosswalk_review.csv for rows that
require no human judgement, leaving genuinely ambiguous rows blank. Mirrors
auto_decide_crosswalk.py's own rule set and reasoning exactly, applied to the
Norway review file instead of the UK one.

Per the phase brief: "ambiguous rows routed to human review rather than
auto-accepted". This auto-accepts only rows where no inference was made
(match_score 1.0: literal prefix identity or structural family-series
membership) and that clear a minimum-volume noise floor. Every other row --
medium/low string-similarity guesses, and the handful of no-candidate rows --
is left blank for a human to decide by hand, exactly like the UK pipeline.

NOISE_FLOOR is deliberately NOT the final per-(model, age_band) statistical
ranking floor (that is computed separately in build_norway_metrics.py from
Norway's own observed pass-rate variance, since Norway's total scoped volume
is roughly 4% of the UK's and reusing the UK's 2,000-test floor here would
reject nearly everything). It exists only to keep obvious junk out of the
crosswalk: family_series_sibling proposes every numbered BMW code sharing a
family digit with no volume floor at all (by design, matching
build_crosswalk_review.py's own behaviour), which surfaced a handful of
1-to-20-count entries that are almost certainly mis-keyed model-year strings
sitting in the model field ('1969', '3200', '1995'), not real cars.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

REVIEW_CSV = Path(__file__).resolve().parents[1] / "reference" / "no_crosswalk_review.csv"
NOISE_FLOOR = 200

IDENTITY_RULES = {"prefix_identity", "code_exact", "short_code_exact"}
STRUCTURAL_RULES = {"family_series_literal", "family_series_sibling"}


def decide(row: dict) -> tuple[str, str]:
    score = float(row["match_score"]) if row["match_score"] else 0.0
    no_count = int(row["no_inspection_count"]) if row["no_inspection_count"] else 0
    rule = row["rule_fired"]
    confidence = row["confidence"]

    if confidence in ("no-candidate", "no-make-in-no-data"):
        return "", f"{confidence}: no Norwegian equivalent found automatically -- needs a human"

    if score < 1.0:
        return "", f"similarity {score:.2f} is an inference, not an identity -- needs a human"

    if no_count < NOISE_FLOOR:
        return "n", (
            f"exact/structural match but only {no_count:,} Norwegian inspections, below the "
            f"{NOISE_FLOOR:,} noise floor -- likely a mis-keyed stray record, not a real model bucket"
        )

    if rule in IDENTITY_RULES:
        return "y", f"literal string identity ({rule}), {no_count:,} Norwegian inspections"

    if rule in STRUCTURAL_RULES:
        return "y", f"structural family membership ({rule}), {no_count:,} Norwegian inspections"

    return "", f"unrecognised rule {rule!r} -- needs a human"


def main() -> None:
    with open(REVIEW_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    for r in rows:
        if r["decision"].strip():
            continue
        d, basis = decide(r)
        r["decision"] = d
        r["decision_basis"] = basis

    with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    by_model = defaultdict(list)
    for r in rows:
        by_model[(r["dmr_make"], r["dmr_model"])].append(r)

    n_y = sum(1 for r in rows if r["decision"] == "y")
    n_n = sum(1 for r in rows if r["decision"] == "n")
    n_blank = sum(1 for r in rows if not r["decision"])

    def fleet(models):
        return sum(int(by_model[m][0]["dk_vehicle_count"]) for m in models)

    all_models = set(by_model)
    settled = {m for m, g in by_model.items() if any(r["decision"] == "y" for r in g)
               and not any(not r["decision"] for r in g)}
    needs_human = {m for m, g in by_model.items() if any(not r["decision"] for r in g)}
    no_usable = {m for m, g in by_model.items() if all(r["decision"] == "n" for r in g)}

    total_fleet = fleet(all_models)
    print(f"rows: {len(rows)}   auto-y: {n_y}   auto-n: {n_n}   left blank: {n_blank}")
    print()
    print(f"DK models fully settled automatically : {len(settled):>4}  "
          f"({fleet(settled):>9,} DK vehicles, {fleet(settled)/total_fleet*100:.1f}%)")
    print(f"DK models with no usable NO match      : {len(no_usable):>4}  "
          f"({fleet(no_usable):>9,} DK vehicles, {fleet(no_usable)/total_fleet*100:.1f}%)")
    print(f"DK models still needing a human         : {len(needs_human):>4}  "
          f"({fleet(needs_human):>9,} DK vehicles, {fleet(needs_human)/total_fleet*100:.1f}%)")

    if needs_human:
        print("\nrows left for human review, by DK fleet size:")
        for m in sorted(needs_human, key=lambda m: -int(by_model[m][0]["dk_vehicle_count"])):
            g = by_model[m]
            head = g[0]
            print(f"\n  {int(head['dk_vehicle_count']):>7,}  {head['dmr_make']} {head['dmr_model']}")
            for r in g:
                mark = {"y": "Y", "n": "n", "": "?"}[r["decision"]]
                print(f"      [{mark}] {r['proposed_no_model_token']:<20} "
                      f"no={r['no_inspection_count']:>9}  score={r['match_score']}  conf={r['confidence']}")


if __name__ == "__main__":
    main()
