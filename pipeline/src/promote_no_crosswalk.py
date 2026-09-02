"""Stage C promotion for the Norway crosswalk: reads no_crosswalk_review.csv
after decisions are filled in and writes reference/no_crosswalk.csv, the
version-controlled, confirmed DK-to-NO mapping build_norway_metrics.py joins
against. Mirrors promote_crosswalk.py exactly.

Only decision == 'y' rows are promoted. Blank, 'n', or anything else is
excluded -- no unreviewed row feeds the Norwegian metrics or the agreement
study, enforced structurally by only reading from this output file.
"""

from __future__ import annotations

import csv
from pathlib import Path

REVIEW_CSV = Path(__file__).resolve().parents[1] / "reference" / "no_crosswalk_review.csv"
CROSSWALK_CSV = Path(__file__).resolve().parents[1] / "reference" / "no_crosswalk.csv"


def main() -> None:
    with open(REVIEW_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    confirmed = [r for r in rows if r["decision"].strip().lower() == "y"]
    rejected = [r for r in rows if r["decision"].strip().lower() == "n"]
    unreviewed = [r for r in rows if r["decision"].strip().lower() not in ("y", "n")]

    with open(CROSSWALK_CSV, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "dmr_make", "dmr_model", "dk_vehicle_count",
            "proposed_no_make", "proposed_no_model_token", "no_inspection_count",
            "confidence", "rule_fired",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(confirmed)

    covered_models = {(r["dmr_make"], r["dmr_model"]) for r in confirmed}
    covered_fleet = sum(
        int(next(r["dk_vehicle_count"] for r in confirmed if (r["dmr_make"], r["dmr_model"]) == key))
        for key in covered_models
    )

    print(f"confirmed (y): {len(confirmed)} rows across {len(covered_models)} DK models")
    print(f"confirmed DK fleet coverage: {covered_fleet:,} vehicles")
    print(f"rejected (n): {len(rejected)} rows")
    print(f"unreviewed (blank/?): {len(unreviewed)} rows -- these will NOT appear in no_crosswalk.csv")
    print(f"wrote {CROSSWALK_CSV}")


if __name__ == "__main__":
    main()
