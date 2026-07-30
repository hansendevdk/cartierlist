"""Build dk_fleet (one row per Danish variant, with count of registered vehicles)
from dmr_vehicles.parquet, and emit crosswalk-prep data for Phase 2.

Dedup key is chassis_number (the VIN), not vehicle_ident or row count -- see
build_dmr_vehicles.py's docstring: Statistik rows recur per leasing-period
snapshot for leased vehicles, so counting rows directly overstates fleet size.
Where the same chassis has multiple snapshots, the most recent by status_dato
is kept; make/model/variant don't vary across a single chassis's snapshots.

Scope: registration_status = 'Registreret' (currently active/available),
first_registration_year in [2010, 2022], per the brief's v1 scope.

Also emits, for Opus's Phase 2 handoff: top-150 models counted two ways --
grouped by (make_id, model_id) vs by (make_name, model_name) -- since DMR's
make/model spelling is inconsistent (Phase 0/1 found "BMW 3 SERIE" vs
"BMW 3'ER-SERIE" as distinct strings) and the two groupings can disagree on
which 150 models make the cut.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

INTERIM = Path(__file__).resolve().parents[2] / "data" / "interim"
VEHICLES_PARQUET = INTERIM / "dmr_vehicles.parquet"
WAREHOUSE = Path(__file__).resolve().parents[2] / "data" / "warehouse.duckdb"
REPORTS = Path(__file__).resolve().parents[2] / "reports"


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))

    con.execute(f"CREATE OR REPLACE VIEW dmr_vehicles AS SELECT * FROM read_parquet('{VEHICLES_PARQUET}')")

    n_total = con.execute("SELECT COUNT(*) FROM dmr_vehicles").fetchone()[0]
    print(f"dmr_vehicles: {n_total:,} rows (Personbil, all history)")

    con.execute(
        """
        CREATE OR REPLACE VIEW dmr_vehicles_scoped AS
        WITH deduped AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY chassis_number
                       ORDER BY status_dato DESC NULLS LAST
                   ) AS rn
            FROM dmr_vehicles
            WHERE registration_status = 'Registreret'
              AND first_registration_year BETWEEN 2010 AND 2022
              AND chassis_number IS NOT NULL
        )
        SELECT * EXCLUDE (rn) FROM deduped WHERE rn = 1
        """
    )
    n_scoped = con.execute("SELECT COUNT(*) FROM dmr_vehicles_scoped").fetchone()[0]
    n_no_chassis = con.execute(
        """
        SELECT COUNT(*) FROM dmr_vehicles
        WHERE registration_status = 'Registreret'
          AND first_registration_year BETWEEN 2010 AND 2022
          AND chassis_number IS NULL
        """
    ).fetchone()[0]
    print(f"in-scope deduped vehicles (Registreret, 2010-2022, unique chassis): {n_scoped:,}")
    print(f"in-scope rows dropped for missing chassis_number: {n_no_chassis:,} "
          f"({n_no_chassis / (n_scoped + n_no_chassis) * 100:.3f}%)")

    print("building dk_fleet (one row per variant)...")
    con.execute(
        """
        CREATE OR REPLACE TABLE dk_fleet AS
        SELECT
            make_id, make_name, model_id, model_name, variant_id, variant_name,
            COUNT(*) AS vehicle_count,
            MIN(first_registration_year) AS min_reg_year,
            MAX(first_registration_year) AS max_reg_year,
            approx_quantile(koereklar_vaegt_min_kg, 0.5) AS median_koereklar_vaegt_kg,
            approx_quantile(km_per_liter_primary, 0.5) AS median_km_per_liter
        FROM dmr_vehicles_scoped
        GROUP BY make_id, make_name, model_id, model_name, variant_id, variant_name
        ORDER BY vehicle_count DESC
        """
    )
    n_variants = con.execute("SELECT COUNT(*) FROM dk_fleet").fetchone()[0]
    print(f"dk_fleet: {n_variants:,} variant rows, {n_scoped:,} total vehicles")

    print("\ntop 20 variants by vehicle_count:")
    for row in con.execute(
        "SELECT make_name, model_name, variant_name, vehicle_count FROM dk_fleet ORDER BY vehicle_count DESC LIMIT 20"
    ).fetchall():
        print(" ", row)

    # --- crosswalk prep: top 150 models, counted two ways ---
    con.execute(
        """
        CREATE OR REPLACE TABLE top_models_by_id AS
        SELECT make_id, make_name, model_id, model_name, SUM(vehicle_count) AS vehicle_count
        FROM dk_fleet
        GROUP BY make_id, make_name, model_id, model_name
        ORDER BY vehicle_count DESC
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE top_models_by_name AS
        SELECT make_name, model_name, SUM(vehicle_count) AS vehicle_count
        FROM dk_fleet
        GROUP BY make_name, model_name
        ORDER BY vehicle_count DESC
        """
    )

    n_by_id = con.execute("SELECT COUNT(*) FROM top_models_by_id").fetchone()[0]
    n_by_name = con.execute("SELECT COUNT(*) FROM top_models_by_name").fetchone()[0]
    print(f"\ndistinct models by (make_id, model_id): {n_by_id:,}")
    print(f"distinct models by (make_name, model_name): {n_by_name:,}")
    print(f"difference (spelling/ID splits): {n_by_id - n_by_name:,}")

    top150_names = con.execute(
        "SELECT make_name, model_name, vehicle_count FROM top_models_by_name ORDER BY vehicle_count DESC LIMIT 150"
    ).fetchall()

    top150_id_fleet_share = con.execute(
        "SELECT SUM(vehicle_count) FROM (SELECT vehicle_count FROM top_models_by_id ORDER BY vehicle_count DESC LIMIT 150)"
    ).fetchone()[0]

    print(f"\ntop 150 (by model_id) fleet coverage: {top150_id_fleet_share:,} / {n_scoped:,} "
          f"({top150_id_fleet_share / n_scoped * 100:.1f}%)")

    with open(REPORTS / "phase1_crosswalk_prep.md", "w", encoding="utf-8") as f:
        f.write("# Phase 1 -> Phase 2 crosswalk prep\n\n")
        f.write(f"In-scope Danish fleet (Personbil, Registreret, 2010-2022, deduped by chassis): "
                f"**{n_scoped:,} vehicles** across **{n_variants:,} variant rows**.\n\n")
        f.write(f"Distinct models grouped by (make_id, model_id): **{n_by_id:,}**\n\n")
        f.write(f"Distinct models grouped by (make_name, model_name) string: **{n_by_name:,}**\n\n")
        f.write(f"Difference: **{n_by_id - n_by_name:,}** -- this many model_id groupings collapse into "
                f"fewer distinct name strings, or vice versa (spelling variants of the same model_id, or "
                f"the same name string covering multiple model_ids).\n\n")
        f.write(f"Top 150 by (make_id, model_id) covers {top150_id_fleet_share:,} / {n_scoped:,} "
                f"vehicles ({top150_id_fleet_share / n_scoped * 100:.1f}% of in-scope fleet).\n\n")
        f.write("## Top 50 models by model_id grouping\n\n")
        f.write("| make | model | vehicle_count |\n|---|---|---|\n")
        for r in con.execute(
            "SELECT make_name, model_name, vehicle_count FROM top_models_by_id ORDER BY vehicle_count DESC LIMIT 50"
        ).fetchall():
            f.write(f"| {r[0]} | {r[1]} | {r[2]:,} |\n")
        f.write("\n## Top 50 models by name-string grouping\n\n")
        f.write("| make | model | vehicle_count |\n|---|---|---|\n")
        for r in top150_names[:50]:
            f.write(f"| {r[0]} | {r[1]} | {r[2]:,} |\n")

    print(f"\ncrosswalk prep report written to {REPORTS / 'phase1_crosswalk_prep.md'}")
    con.close()


if __name__ == "__main__":
    main()
