"""Stage C promotion: reads reference/crosswalk_review.csv after you've filled in
the 'decision' column (y / n / ?) and writes reference/crosswalk.csv, the
version-controlled, human-confirmed mapping Phase 3 will actually join against.

Only decision == 'y' rows are promoted. Everything else (blank, 'n', '?') is
excluded -- per the brief, no unreviewed row feeds downstream metrics. This is
enforced structurally: Phase 3's join reads crosswalk.csv, which physically
cannot contain a row you didn't mark 'y'.
"""

from __future__ import annotations

import csv
from pathlib import Path

REVIEW_CSV = Path(__file__).resolve().parents[1] / "reference" / "crosswalk_review.csv"
CROSSWALK_CSV = Path(__file__).resolve().parents[1] / "reference" / "crosswalk.csv"


def main() -> None:
    with open(REVIEW_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    confirmed = [r for r in rows if r["decision"].strip().lower() == "y"]
    rejected = [r for r in rows if r["decision"].strip().lower() == "n"]
    unreviewed = [r for r in rows if r["decision"].strip().lower() not in ("y", "n")]

    with open(CROSSWALK_CSV, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "dmr_make", "dmr_model", "dk_vehicle_count",
            "proposed_dvsa_make", "proposed_dvsa_model_token", "uk_test_count",
            "confidence", "rule_fired",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(confirmed)

    covered_models = {(r["dmr_make"], r["dmr_model"]) for r in confirmed}
    # dk_vehicle_count is per-model, repeated across each model's candidate rows,
    # so sum it once per distinct model, not once per row.
    covered_fleet = sum(
        int(next(r["dk_vehicle_count"] for r in confirmed if (r["dmr_make"], r["dmr_model"]) == key))
        for key in covered_models
    )

    print(f"confirmed (y): {len(confirmed)} rows across {len(covered_models)} models")
    print(f"confirmed fleet coverage: {covered_fleet:,} vehicles")
    print(f"rejected (n): {len(rejected)} rows")
    print(f"unreviewed (blank/?): {len(unreviewed)} rows -- these will NOT appear in crosswalk.csv")
    print(f"wrote {CROSSWALK_CSV}")


if __name__ == "__main__":
    main()
