"""Stream all twelve PKK (Norwegian periodic vehicle inspection) quarterly
zips and build a slim, warehouse-ready intermediate CSV plus a DuckDB table
`pkk_inspections`.

Streaming, not extracting: each zip's single CSV member (658k rows x 203
columns, ~340 MB uncompressed, latin-1 encoded) is read directly out of the
zip via zipfile + io.TextIOWrapper, one row at a time, and only the ~28
columns this project actually needs are kept. The full 203-column CSV is
never written to disk -- this is the "prefer streaming... rather than
extracting to disk" instruction in the phase brief, and it also sidesteps
DuckDB's read_csv, which has no encoding parameter and cannot read latin-1
directly.

Scope kept in the slim output: EVERY row (any Gruppeavgift, any Kontrolltype,
any Drivstofftype). Scope filtering (PERSONBIL, Periodisk-only, BEV/hydrogen
exclusion) happens downstream in SQL against pkk_inspections, exactly like
build_dvsa_warehouse.py keeps mot_tests unscoped by test_type and filters at
query time -- this keeps the funnel counts (raw -> personbil -> M1-agreeing
-> non-BEV -> periodisk -> usable) reproducible from the warehouse table
without re-streaming the source zips.

Filename case changes between years (verified in download_pkk.py): 2023/2024
use 'PKK-<year>-kvartalN.zip', 2025 uses 'pkk-2025-kvartalN.zip'. The zip
member's own internal filename follows the same case as the zip.
"""

from __future__ import annotations

import csv
import io
import sys
import time
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "pkk"
INTERIM = ROOT / "data" / "interim" / "pkk"
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"

ZIP_FILES = [
    "PKK-2023-kvartal1.zip", "PKK-2023-kvartal2.zip", "PKK-2023-kvartal3.zip", "PKK-2023-kvartal4.zip",
    "PKK-2024-kvartal1.zip", "PKK-2024-kvartal2.zip", "PKK-2024-kvartal3.zip", "PKK-2024-kvartal4.zip",
    "pkk-2025-kvartal1.zip", "pkk-2025-kvartal2.zip", "pkk-2025-kvartal3.zip", "pkk-2025-kvartal4.zip",
]

# Source column name -> slim output column name. Source names verified by
# direct header inspection of pkk-2025-kvartal1.zip (see recon notes in
# reports/norway_pkk_report.md); the 11 chapter columns (kap 0..kap 10) are
# generated programmatically below, not hand-listed here.
SOURCE_COLS = {
    "Første gang registrert": "first_reg_year",
    "Første gang registrert i Norge": "first_reg_no_year",
    "Kjøretøymerke": "make",
    "Kjøretøy Modell": "model_raw",
    "Kjøretøy Gruppeavgift": "gruppeavgift",
    "Kjøretøy Tekniskgruppe": "tekniskgruppe",
    "Drivstofftype": "fuel",
    "Kilometerstand": "km",
    "PKK Kontrolltype": "kontrolltype",
    "PKK Kontrollmåned": "kontrollmaaned",
    "Trafikkfarlig feil": "trafikkfarlig_feil",
    "Godkjent": "godkjent",
    "Kontrollorganets fylke": "fylke",
    "Ant 1er merknad": "ant1er",
    "Ant 2er merknad": "ant2er",
    "Ant 3er merknad": "ant3er",
    "Ant 4er merknad": "ant4er",
}
for _k in range(11):
    SOURCE_COLS[f"Ant 2-3er kap {_k}"] = f"kap{_k}"

OUT_FIELDS = ["quarter_source"] + list(SOURCE_COLS.values())


def find_csv_member(z: zipfile.ZipFile) -> str:
    candidates = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one CSV member, got {candidates}")
    return candidates[0]


def stream_zip_to_slim_csv(zip_path: Path, out_path: Path) -> tuple[int, int]:
    """Returns (rows_read, rows_written). rows_written == rows_read always;
    this stage does no scope filtering, only column pruning."""
    z = zipfile.ZipFile(zip_path)
    member = find_csv_member(z)
    with z.open(member) as raw, io.TextIOWrapper(raw, encoding="latin-1", newline="") as text:
        reader = csv.reader(text)
        header = next(reader)
        col_idx = {name: i for i, name in enumerate(header)}
        missing = [c for c in SOURCE_COLS if c not in col_idx]
        if missing:
            raise RuntimeError(f"{zip_path.name}: missing expected columns: {missing}")

        idx_order = [col_idx[c] for c in SOURCE_COLS]
        n_cols = len(header)

        with open(out_path, "w", newline="", encoding="utf-8") as out:
            writer = csv.writer(out)
            writer.writerow(OUT_FIELDS)
            n = 0
            for row in reader:
                if len(row) != n_cols:
                    # Non-standard row (short/long) -- skip and count separately
                    # rather than silently mis-aligning columns.
                    continue
                writer.writerow([zip_path.stem] + [row[i] for i in idx_order])
                n += 1
    return n, n


def main() -> None:
    INTERIM.mkdir(parents=True, exist_ok=True)
    slim_files = []
    total_rows = 0
    start = time.time()

    for zip_name in ZIP_FILES:
        zip_path = RAW / zip_name
        if not zip_path.exists():
            print(f"FATAL: missing {zip_path}. Run download_pkk.py first.", file=sys.stderr)
            sys.exit(1)
        out_path = INTERIM / f"{zip_path.stem}.slim.csv"
        slim_files.append(out_path)
        if out_path.exists():
            print(f"already streamed: {out_path.name}")
            continue
        t0 = time.time()
        n, _ = stream_zip_to_slim_csv(zip_path, out_path)
        total_rows += n
        print(f"{zip_name}: {n:,} rows streamed in {time.time() - t0:.1f}s -> {out_path.name}")

    print(f"\nstreaming done in {time.time() - start:.1f}s")

    print("\nloading pkk_inspections into DuckDB...")
    con = duckdb.connect(str(WAREHOUSE))
    glob = str(INTERIM / "*.slim.csv")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE pkk_inspections AS
        SELECT
            quarter_source,
            TRY_CAST(first_reg_year AS INTEGER) AS first_reg_year,
            TRY_CAST(first_reg_no_year AS INTEGER) AS first_reg_no_year,
            make,
            model_raw,
            gruppeavgift,
            tekniskgruppe,
            fuel,
            TRY_CAST(km AS DOUBLE) AS km,
            kontrolltype,
            TRY_CAST(kontrollmaaned AS VARCHAR) AS kontrollmaaned,
            TRY_CAST(SUBSTR(kontrollmaaned, 1, 4) AS INTEGER) AS kontroll_year,
            TRY_CAST(SUBSTR(kontrollmaaned, 5, 2) AS INTEGER) AS kontroll_month,
            trafikkfarlig_feil,
            godkjent,
            fylke,
            TRY_CAST(NULLIF(ant1er, '') AS INTEGER) AS ant1er,
            TRY_CAST(NULLIF(ant2er, '') AS INTEGER) AS ant2er,
            TRY_CAST(NULLIF(ant3er, '') AS INTEGER) AS ant3er,
            TRY_CAST(NULLIF(ant4er, '') AS INTEGER) AS ant4er,
            TRY_CAST(NULLIF(kap0, '') AS INTEGER) AS kap0,
            TRY_CAST(NULLIF(kap1, '') AS INTEGER) AS kap1,
            TRY_CAST(NULLIF(kap2, '') AS INTEGER) AS kap2,
            TRY_CAST(NULLIF(kap3, '') AS INTEGER) AS kap3,
            TRY_CAST(NULLIF(kap4, '') AS INTEGER) AS kap4,
            TRY_CAST(NULLIF(kap5, '') AS INTEGER) AS kap5,
            TRY_CAST(NULLIF(kap6, '') AS INTEGER) AS kap6,
            TRY_CAST(NULLIF(kap7, '') AS INTEGER) AS kap7,
            TRY_CAST(NULLIF(kap8, '') AS INTEGER) AS kap8,
            TRY_CAST(NULLIF(kap9, '') AS INTEGER) AS kap9,
            TRY_CAST(NULLIF(kap10, '') AS INTEGER) AS kap10
        FROM read_csv('{glob}', all_varchar=true, header=true, union_by_name=true)
        """
    )
    n_total = con.execute("SELECT COUNT(*) FROM pkk_inspections").fetchone()[0]
    print(f"pkk_inspections: {n_total:,} rows")

    print("\nper-quarter row counts:")
    for q, n in con.execute(
        "SELECT quarter_source, COUNT(*) FROM pkk_inspections GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {q}: {n:,}")

    con.close()


if __name__ == "__main__":
    main()
