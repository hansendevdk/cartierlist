"""Build dk_fleet (one row per Danish variant, with count of registered vehicles)
from dmr_vehicles.parquet, and emit crosswalk-prep data for Phase 2.

Dedup key is chassis_number (the VIN), not vehicle_ident or row count -- see
build_dmr_vehicles.py's docstring: Statistik rows recur per leasing-period
snapshot for leased vehicles, so counting rows directly overstates fleet size.
Where the same chassis has multiple snapshots, the most recent by status_dato
is kept; make/model/variant don't vary across a single chassis's snapshots.

Scope: registration_status = 'Registreret' (currently active/available),
first_registration_year in [2010, 2022], fuel_type_primary != 'El' (the brief
excludes BEV from v1), per the brief's v1 scope.

IMPORTANT, flagged for Phase 3: this source has no literal "Hybrid" fuel-type
label, and a targeted check found zero vehicles with one El and one combustion
DrivmiddelStruktur entry -- hybrids are apparently recorded under their
combustion fuel type alone (e.g. a plug-in hybrid shows as fuel_type_primary =
'Benzin', identical to a non-hybrid petrol car; the only clue is free text in
variant_name, e.g. "2.5 Plug-in Hybrid (225 HK)"). This means petrol/diesel and
hybrid variants of the same model are NOT distinguishable via fuel_type_primary
in dk_fleet as built here -- the brief's "petrol / diesel / hybrid" scope is
satisfied (nothing hybrid is excluded), but hybrids cannot currently be pulled
out as their own category. Isolating hybrids would need free-text matching on
variant_name, which is exactly the kind of fuzzy judgement call the brief says
to flag rather than silently do -- deferring to Phase 3 for a decision.

Also emits, for Opus's Phase 2 handoff: top-150 models counted two ways --
grouped by (make_id, model_id) vs by (make_name, model_name) -- since DMR's
make/model spelling is inconsistent (Phase 0/1 found "BMW 3 SERIE" vs
"BMW 3'ER-SERIE" as distinct strings) and the two groupings can disagree on
which 150 models make the cut.

MAKE FOLD: DMR "VW" -> "VOLKSWAGEN" (coverage_audit.md finding 5)
make_aliases.csv already maps both DMR make strings to the same DVSA make,
but that only affects the DVSA side of the crosswalk -- the 4,632 Danish
vehicles filed under the DMR make string "VW" (as opposed to "VOLKSWAGEN")
never had their make_name folded, so each of VW's models (VW PASSAT 1,082,
VW GOLF 764, VW POLO 233, ...) was individually far too small to reach the
top-214 universe cut and all of them fell out of the crosswalk review
entirely. Folded here, at the SAME `dmr_vehicles_scoped` view Phase 3 later
queries by make_name/model_name string equality against crosswalk.csv's
covered_models -- so the fold benefits both this script's top_models_by_*
tables AND Phase 3's per-vehicle join, from one edit.

Only make_name is folded, not make_id: VW's DMR-internal make_id ('15401')
and VOLKSWAGEN's ('10279') are different codes tied to different original
model_id namespaces (VW POLO's model_id is not the same number as
VOLKSWAGEN POLO's), so overwriting make_id would fabricate a false model_id
association for no benefit -- nothing downstream joins on make_id, only on
the (make_name, model_name) strings crosswalk.csv keys off.

This merges into an EXISTING crosswalk.csv row wherever the post-fold
model_name string is an exact match for a model crosswalk.csv already
covers under "VOLKSWAGEN" (e.g. "POLO", "GOLF", "PASSAT", "PASSAT VARIANT",
"TIGUAN", "TOURAN", "CADDY", "CALIFORNIA", "UP!", "GOLF VARIANT") --
Phase 3's join is a plain string match, so those vehicles simply start
counting once the make_name lines up. It does NOT create new crosswalk
coverage for VW-only model spellings crosswalk.csv has no row for at all
(e.g. "BEETLE", "SHARAN", "MULTIVAN", "T5") or for spellings that differ
from the existing VOLKSWAGEN row only by case ("T-ROC" vs crosswalk's
"T-Roc", "GOLF SPORTSVAN" vs "Golf Sportsvan", "T-CROSS" vs "T-Cross") --
per the task scope, crosswalk_review.csv is not being regenerated and no
new row is being auto-added, so those model_name strings are printed below
for the record and left uncovered, exactly as they were before the fold.
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

INTERIM = Path(__file__).resolve().parents[2] / "data" / "interim"
VEHICLES_PARQUET = INTERIM / "dmr_vehicles.parquet"
WAREHOUSE = Path(__file__).resolve().parents[2] / "data" / "warehouse.duckdb"
REPORTS = Path(__file__).resolve().parents[2] / "reports"
CROSSWALK_CSV = Path(__file__).resolve().parents[1] / "reference" / "crosswalk.csv"


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))

    con.execute(f"CREATE OR REPLACE VIEW dmr_vehicles AS SELECT * FROM read_parquet('{VEHICLES_PARQUET}')")

    n_total = con.execute("SELECT COUNT(*) FROM dmr_vehicles").fetchone()[0]
    print(f"dmr_vehicles: {n_total:,} rows (Personbil, all history)")

    SCOPE_WHERE = """
        registration_status = 'Registreret'
        AND first_registration_year BETWEEN 2010 AND 2022
        AND fuel_type_primary != 'El'
    """

    n_bev = con.execute(
        f"""
        SELECT COUNT(*) FROM dmr_vehicles
        WHERE registration_status = 'Registreret'
          AND first_registration_year BETWEEN 2010 AND 2022
          AND fuel_type_primary = 'El'
        """
    ).fetchone()[0]
    print(f"BEV vehicles excluded per brief's v1 scope (fuel_type_primary = 'El'): {n_bev:,}")

    con.execute(
        f"""
        CREATE OR REPLACE VIEW dmr_vehicles_scoped AS
        WITH deduped AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY chassis_number
                       ORDER BY status_dato DESC NULLS LAST
                   ) AS rn
            FROM dmr_vehicles
            WHERE {SCOPE_WHERE}
              AND chassis_number IS NOT NULL
        )
        SELECT * EXCLUDE (rn) REPLACE (
            CASE WHEN make_name = 'VW' THEN 'VOLKSWAGEN' ELSE make_name END AS make_name
        ) FROM deduped WHERE rn = 1
        """
    )
    n_scoped = con.execute("SELECT COUNT(*) FROM dmr_vehicles_scoped").fetchone()[0]
    n_no_chassis = con.execute(
        f"""
        SELECT COUNT(*) FROM dmr_vehicles
        WHERE {SCOPE_WHERE}
          AND chassis_number IS NULL
        """
    ).fetchone()[0]
    print(f"in-scope deduped vehicles (Registreret, 2010-2022, non-BEV, unique chassis): {n_scoped:,}")
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

    # --- VW -> VOLKSWAGEN make fold report ---------------------------------
    # make_id still distinguishes former-VW rows ('15401') from
    # always-VOLKSWAGEN rows ('10279') even after the make_name fold above,
    # since only make_name was overwritten. Used here only for this report,
    # not for any join.
    crosswalk_volkswagen_models: set[str] = set()
    if CROSSWALK_CSV.exists():
        with open(CROSSWALK_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["dmr_make"] == "VOLKSWAGEN":
                    crosswalk_volkswagen_models.add(row["dmr_model"])

    vw_fold_rows = con.execute(
        """
        SELECT model_name, SUM(vehicle_count) AS vehicle_count
        FROM dk_fleet
        WHERE make_id = '15401' AND make_name = 'VOLKSWAGEN'
        GROUP BY model_name
        ORDER BY vehicle_count DESC
        """
    ).fetchall()
    n_vw_total = sum(r[1] for r in vw_fold_rows)
    vw_merged = [(m, c) for m, c in vw_fold_rows if m in crosswalk_volkswagen_models]
    vw_orphaned = [(m, c) for m, c in vw_fold_rows if m not in crosswalk_volkswagen_models]

    print(f"\nVW make fold: {n_vw_total:,} vehicles across {len(vw_fold_rows)} model spellings "
          f"folded from make_name 'VW' into 'VOLKSWAGEN'")
    print(f"  merged into an existing crosswalk.csv VOLKSWAGEN row "
          f"({sum(c for _, c in vw_merged):,} vehicles, {len(vw_merged)} model spellings):")
    for m, c in vw_merged:
        print(f"    {m}: {c:,}")
    print(f"  NOT covered by any existing crosswalk.csv VOLKSWAGEN row -- not auto-added, "
          f"reported here per the task's scope limit "
          f"({sum(c for _, c in vw_orphaned):,} vehicles, {len(vw_orphaned)} model spellings):")
    for m, c in vw_orphaned:
        print(f"    {m}: {c:,}")

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
        f.write("## VW -> VOLKSWAGEN make fold (coverage_audit.md finding 5)\n\n")
        f.write(f"{n_vw_total:,} vehicles across {len(vw_fold_rows)} model spellings folded from "
                f"DMR make string \"VW\" into \"VOLKSWAGEN\".\n\n")
        f.write(f"Merged into an existing crosswalk.csv VOLKSWAGEN row "
                f"({sum(c for _, c in vw_merged):,} vehicles, {len(vw_merged)} model spellings):\n\n")
        f.write("| model_name | vehicle_count |\n|---|---|\n")
        for m, c in vw_merged:
            f.write(f"| {m} | {c:,} |\n")
        f.write(f"\nNot covered by any existing crosswalk.csv VOLKSWAGEN row, not auto-added per the "
                f"task's scope limit (crosswalk_review.csv is not being regenerated): "
                f"{sum(c for _, c in vw_orphaned):,} vehicles, {len(vw_orphaned)} model spellings.\n\n")
        f.write("| model_name | vehicle_count |\n|---|---|\n")
        for m, c in vw_orphaned:
            f.write(f"| {m} | {c:,} |\n")
        f.write("\n## Top 50 models by model_id grouping\n\n")
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
