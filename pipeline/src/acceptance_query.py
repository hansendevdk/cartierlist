"""Phase 1 acceptance test: pass rate by make for 8-10 year old cars, under 10s.

Methodology per Opus's Phase 1 handover (locked decisions, not to be improvised):
  - Initial tests only (test_type = 'NT') -- retests are conditional on an already-
    failed test, so pooling them inflates pass rates, more so for unreliable models.
  - PRS (pass after rectification) counts as a failure.
  - Aborted results (ABR/ABA/ABRVE) are excluded entirely -- they carry no signal
    about the vehicle.
  - Age computed from first_use_date to test_date.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

WAREHOUSE = Path(__file__).resolve().parents[2] / "data" / "warehouse.duckdb"

QUERY = """
    SELECT
        make,
        COUNT(*) AS n_tests,
        SUM(CASE WHEN test_result = 'P' THEN 1 ELSE 0 END) AS n_pass,
        ROUND(SUM(CASE WHEN test_result = 'P' THEN 1 ELSE 0 END)::DOUBLE / COUNT(*), 4) AS pass_rate
    FROM mot_tests
    WHERE test_type = 'NT'
      AND test_result IN ('P', 'F', 'PRS')
      AND first_use_date IS NOT NULL
      AND DATE_DIFF('year', first_use_date, test_date) BETWEEN 8 AND 10
    GROUP BY make
    HAVING COUNT(*) >= 500
    ORDER BY n_tests DESC
"""


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    start = time.time()
    rows = con.execute(QUERY).fetchall()
    elapsed = time.time() - start
    print(f"query returned {len(rows)} makes in {elapsed:.2f}s\n")
    print(f"{'make':<20} {'n_tests':>10} {'n_pass':>10} {'pass_rate':>10}")
    for r in rows[:25]:
        print(f"{r[0]:<20} {r[1]:>10,} {r[2]:>10,} {r[3]:>10.2%}")


if __name__ == "__main__":
    main()
