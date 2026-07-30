"""Single full streaming pass over the 127.8 GB DMR XML (from Phase 0 recon).

Does three things in one pass, since a second 30+ minute pass would be wasteful:
  1. Writes one Parquet row per Personbil (passenger car) vehicle record, with the
     fields of interest flattened out of the deeply nested XML.
  2. Collects the full leaf-tag vocabulary across ALL vehicle types (not just
     Personbil) to definitively settle whether CO2 / door-count fields exist
     anywhere in this source -- Phase 0 only sampled ~2.3M records and found
     neither.
  3. Re-measures null rates for the fields of interest restricted to the v1 scope
     (Personbil, first registration 2010-2022, currently Registreret) rather than
     across all history back to the 1970s, since Phase 0 flagged the all-history
     null rates (up to ~50%) as possibly not representative of the in-scope slice.

KoeretoejOplysningGrundStruktur was confirmed (300k-record check) to never repeat
within a Statistik element, so there's no history-versioning to resolve there.
But the top-level KoeretoejRegistreringStatus and the nested KoeretoejOplysningStatus
disagree 17.9% of the time -- top-level is treated as authoritative for "is this
vehicle currently active" (it's the broad Registreret/Afmeldt category), the nested
one is kept as a supplementary detail field (specifies *why* if not registered:
exported, scrapped, etc).

IMPORTANT: KoeretoejIdent is NOT a reliable one-row-per-vehicle key. A 200k-record
spot check found ~4.4% of idents recurring with identical chassis number and
registration number but different LeasingGyldigFra/Til dates -- a Statistik element
looks to be emitted per leasing-period snapshot for leased vehicles, not strictly
once per physical vehicle. This table's true grain is "one row per Statistik
element" (roughly: per vehicle, except multiple rows for vehicles with more than
one recorded leasing period). Downstream fleet-count aggregation (dk_fleet) must
dedupe on chassis_number (the VIN, KoeretoejOplysningStelNummer), not on
vehicle_ident or row count, or leased vehicles get overcounted.
"""

from __future__ import annotations

import argparse
import time
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "dmr"
ZIP_PATH = RAW / "ESStatistikListeModtag-20260726-153441.zip"
XML_MEMBER = "ESStatistikListeModtag.xml"
NS = "{http://skat.dk/dmr/2007/05/31/}"
STATISTIK_TAG = f"{NS}Statistik"

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "interim"
VEHICLES_PARQUET = OUT_DIR / "dmr_vehicles.parquet"
TAG_VOCAB_OUT = OUT_DIR / "dmr_tag_vocabulary.txt"
NULL_RATE_OUT = OUT_DIR / "dmr_null_rates_in_scope.txt"

BATCH_SIZE = 100_000
SCOPE_YEAR_MIN = 2010
SCOPE_YEAR_MAX = 2022

SCHEMA = pa.schema(
    [
        ("vehicle_ident", pa.string()),
        # KoeretoejIdent is NOT a reliable dedup key: spot-checking showed the
        # same ident recurring with different LeasingGyldigFra/Til dates and
        # reordered equipment lists but the same chassis number -- a Statistik
        # element appears to be emitted per leasing-period snapshot for leased
        # vehicles, not strictly once per physical vehicle. chassis_number
        # (StelNummer, the VIN) is the trustworthy unique-vehicle key; dedupe on
        # that, not on vehicle_ident, when counting fleet size downstream.
        ("chassis_number", pa.string()),
        ("registration_number", pa.string()),
        ("registration_status", pa.string()),
        ("oplysning_status", pa.string()),
        ("status_dato", pa.string()),
        ("leasing_gyldig_fra", pa.string()),
        ("leasing_gyldig_til", pa.string()),
        ("make_id", pa.string()),
        ("make_name", pa.string()),
        ("model_id", pa.string()),
        ("model_name", pa.string()),
        ("variant_id", pa.string()),
        ("variant_name", pa.string()),
        ("type_id", pa.string()),
        ("type_name", pa.string()),
        ("first_registration_date", pa.string()),
        ("first_registration_year", pa.int32()),
        # two non-equivalent weight fields kept separate, not coalesced: EgenVaegt
        # ("own/kerb weight") is used by older records, KoereklarVaegtMinimum
        # ("mass in running order", EU-style, includes near-full tank) by newer
        # ones, and sampling shows the latter runs ~8-10% heavier for the same
        # vehicle where both are present -- merging them would quietly bias any
        # weight-based metric depending on which field a given record happened to
        # report. Phase 3 needs to pick a standardization approach deliberately.
        ("egen_vaegt_kg", pa.float64()),
        ("koereklar_vaegt_min_kg", pa.float64()),
        ("engine_power", pa.float64()),
        ("engine_displacement_cc", pa.float64()),
        ("cylinder_count", pa.int32()),
        ("gear_count", pa.int32()),
        ("seats_min", pa.int32()),
        ("door_count", pa.int32()),
        ("body_type", pa.string()),
        ("model_year", pa.int32()),
        ("ncap_flag", pa.bool_()),
        ("fuel_count", pa.int32()),
        ("fuel_type_primary", pa.string()),
        ("km_per_liter_primary", pa.float64()),
        # CO2 g/km, reported per fuel entry (same level as km_per_liter). A
        # reported 0.0 is suspicious for a combustion fuel (seen on non-electric
        # entries in spot checks) and may mean "not measured" rather than a true
        # zero -- treat 0.0 as suspect, not authoritative, until cross-checked.
        ("co2_primary", pa.float64()),
        ("fuel_type_secondary", pa.string()),
        ("km_per_liter_secondary", pa.float64()),
        ("co2_secondary", pa.float64()),
    ]
)

FIELDS_OF_INTEREST_PATHS = {
    "first_registration_date": f".//{NS}KoeretoejOplysningFoersteRegistreringDato",
    "make_name": f".//{NS}KoeretoejMaerkeTypeNavn",
    "model_name": f".//{NS}Model/{NS}KoeretoejModelTypeNavn",
    "variant_name": f".//{NS}Variant/{NS}KoeretoejVariantTypeNavn",
    "fuel_type_primary": f".//{NS}DrivkraftTypeNavn",
    "km_per_liter": f".//{NS}KoeretoejMotorKmPerLiter",
    "egen_vaegt_kg": f".//{NS}KoeretoejOplysningEgenVaegt",
    "koereklar_vaegt_min_kg": f".//{NS}KoeretoejOplysningKoereklarVaegtMinimum",
    "engine_power": f".//{NS}KoeretoejMotorStoersteEffekt",
    "cylinder_count": f".//{NS}KoeretoejMotorCylinderAntal",
    "door_count": f".//{NS}KoeretoejOplysningAntalDoere",
    "model_year": f".//{NS}KoeretoejOplysningModelAar",
    "ncap_flag": f".//{NS}KoeretoejOplysningNCAPTest",
}


def _f(v: str | None) -> float | None:
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _i(v: str | None) -> int | None:
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _b(v: str | None) -> bool | None:
    if v is None or v == "":
        return None
    return v.strip().lower() == "true"


def extract_row(elem) -> dict:
    ident = elem.findtext(f"{NS}KoeretoejIdent")
    chassis_number = elem.findtext(f".//{NS}KoeretoejOplysningStelNummer")
    reg_no = elem.findtext(f"{NS}RegistreringNummerNummer")
    reg_status = elem.findtext(f"{NS}KoeretoejRegistreringStatus")
    oplysning_status = elem.findtext(f".//{NS}KoeretoejOplysningStatus")
    status_dato = elem.findtext(f".//{NS}KoeretoejOplysningStatusDato")
    leasing_fra = elem.findtext(f".//{NS}LeasingGyldigFra")
    leasing_til = elem.findtext(f".//{NS}LeasingGyldigTil")

    make_id = elem.findtext(f".//{NS}KoeretoejMaerkeTypeNummer")
    make_name = elem.findtext(f".//{NS}KoeretoejMaerkeTypeNavn")
    model_id = elem.findtext(f".//{NS}Model/{NS}KoeretoejModelTypeNummer")
    model_name = elem.findtext(f".//{NS}Model/{NS}KoeretoejModelTypeNavn")
    variant_id = elem.findtext(f".//{NS}Variant/{NS}KoeretoejVariantTypeNummer")
    variant_name = elem.findtext(f".//{NS}Variant/{NS}KoeretoejVariantTypeNavn")
    type_id = elem.findtext(f".//{NS}Type/{NS}KoeretoejTypeTypeNummer")
    type_name = elem.findtext(f".//{NS}Type/{NS}KoeretoejTypeTypeNavn")

    first_reg = elem.findtext(f".//{NS}KoeretoejOplysningFoersteRegistreringDato")
    first_reg_year = None
    if first_reg and len(first_reg) >= 4 and first_reg[:4].isdigit():
        first_reg_year = int(first_reg[:4])

    egen_vaegt = _f(elem.findtext(f".//{NS}KoeretoejOplysningEgenVaegt"))
    koereklar_vaegt_min = _f(elem.findtext(f".//{NS}KoeretoejOplysningKoereklarVaegtMinimum"))
    power = _f(elem.findtext(f".//{NS}KoeretoejMotorStoersteEffekt"))
    displacement = _f(elem.findtext(f".//{NS}KoeretoejMotorSlagVolumen"))
    cylinders = _i(elem.findtext(f".//{NS}KoeretoejMotorCylinderAntal"))
    gears = _i(elem.findtext(f".//{NS}KoeretoejOplysningAntalGear"))
    seats = _i(elem.findtext(f".//{NS}KoeretoejOplysningSiddepladserMinimum"))
    doors = _i(elem.findtext(f".//{NS}KoeretoejOplysningAntalDoere"))
    body_type = elem.findtext(f".//{NS}KarrosseriTypeStruktur/{NS}KarrosseriTypeNavn")
    model_year = _i(elem.findtext(f".//{NS}KoeretoejOplysningModelAar"))
    ncap = _b(elem.findtext(f".//{NS}KoeretoejOplysningNCAPTest"))

    fuels = []
    for drivmiddel in elem.iter(f"{NS}DrivmiddelStruktur"):
        name = drivmiddel.findtext(f"{NS}DrivkraftTypeStruktur/{NS}DrivkraftTypeNavn")
        kmpl = _f(drivmiddel.findtext(f"{NS}KoeretoejBraendstofStruktur/{NS}KoeretoejMotorKmPerLiter"))
        co2 = _f(drivmiddel.findtext(f"{NS}KoeretoejBraendstofStruktur/{NS}KoeretoejMiljoeOplysningCO2Udslip"))
        primary = _b(drivmiddel.findtext(f"{NS}KoeretoejMotorDrivmiddelPrimaer"))
        fuels.append((name, kmpl, co2, primary))

    fuel_primary = next((f for f in fuels if f[3]), fuels[0] if fuels else (None, None, None, None))
    fuel_secondary_list = [f for f in fuels if f is not fuel_primary]
    fuel_secondary = fuel_secondary_list[0] if fuel_secondary_list else (None, None, None, None)

    return {
        "vehicle_ident": ident,
        "chassis_number": chassis_number,
        "registration_number": reg_no,
        "registration_status": reg_status,
        "oplysning_status": oplysning_status,
        "status_dato": status_dato,
        "leasing_gyldig_fra": leasing_fra,
        "leasing_gyldig_til": leasing_til,
        "make_id": make_id,
        "make_name": make_name,
        "model_id": model_id,
        "model_name": model_name,
        "variant_id": variant_id,
        "variant_name": variant_name,
        "type_id": type_id,
        "type_name": type_name,
        "first_registration_date": first_reg,
        "first_registration_year": first_reg_year,
        "egen_vaegt_kg": egen_vaegt,
        "koereklar_vaegt_min_kg": koereklar_vaegt_min,
        "engine_power": power,
        "engine_displacement_cc": displacement,
        "cylinder_count": cylinders,
        "gear_count": gears,
        "seats_min": seats,
        "door_count": doors,
        "body_type": body_type,
        "model_year": model_year,
        "ncap_flag": ncap,
        "fuel_count": len(fuels),
        "fuel_type_primary": fuel_primary[0],
        "km_per_liter_primary": fuel_primary[1],
        "co2_primary": fuel_primary[2],
        "fuel_type_secondary": fuel_secondary[0],
        "km_per_liter_secondary": fuel_secondary[1],
        "co2_secondary": fuel_secondary[2],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    z = zipfile.ZipFile(ZIP_PATH)
    stream = z.open(XML_MEMBER)
    context = etree.iterparse(stream, events=("end",), tag=STATISTIK_TAG)

    writer = pq.ParquetWriter(VEHICLES_PARQUET, SCHEMA, compression="zstd")
    batch: list[dict] = []

    tag_vocab: set[str] = set()

    total_records = 0
    personbil_count = 0
    in_scope_count = 0
    null_counts_in_scope: dict[str, int] = {k: 0 for k in FIELDS_OF_INTEREST_PATHS}

    start = time.time()

    def flush_batch():
        if not batch:
            return
        table = pa.Table.from_pylist(batch, schema=SCHEMA)
        writer.write_table(table)
        batch.clear()

    for _, elem in context:
        total_records += 1

        for descendant in elem.iter():
            tag_vocab.add(etree.QName(descendant).localname)

        art_navn = elem.findtext(f"{NS}KoeretoejArtNavn")
        if art_navn == "Personbil":
            personbil_count += 1
            row = extract_row(elem)
            batch.append(row)

            reg_status = row["registration_status"]
            year = row["first_registration_year"]
            in_scope = reg_status == "Registreret" and year is not None and SCOPE_YEAR_MIN <= year <= SCOPE_YEAR_MAX
            if in_scope:
                in_scope_count += 1
                for label, path in FIELDS_OF_INTEREST_PATHS.items():
                    found = elem.find(path)
                    if found is None or found.text is None or found.text == "":
                        null_counts_in_scope[label] += 1

            if len(batch) >= BATCH_SIZE:
                flush_batch()

        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

        if total_records % 1_000_000 == 0:
            elapsed = time.time() - start
            print(
                f"  ... {total_records:,} records ({personbil_count:,} Personbil, "
                f"{in_scope_count:,} in-scope) in {elapsed:.0f}s ({total_records / elapsed:.0f} rec/s)",
                flush=True,
            )

        if args.limit and total_records >= args.limit:
            break

    flush_batch()
    writer.close()

    elapsed = time.time() - start
    print(f"\nDONE: {total_records:,} total records, {personbil_count:,} Personbil, "
          f"{in_scope_count:,} in-scope (Registreret, {SCOPE_YEAR_MIN}-{SCOPE_YEAR_MAX}) "
          f"in {elapsed:.0f}s")

    with open(TAG_VOCAB_OUT, "w", encoding="utf-8") as f:
        for tag in sorted(tag_vocab):
            f.write(tag + "\n")
    print(f"tag vocabulary ({len(tag_vocab)} distinct tags) written to {TAG_VOCAB_OUT}")

    with open(NULL_RATE_OUT, "w", encoding="utf-8") as f:
        f.write(f"in-scope count (Personbil, Registreret, {SCOPE_YEAR_MIN}-{SCOPE_YEAR_MAX}): {in_scope_count:,}\n\n")
        for label in FIELDS_OF_INTEREST_PATHS:
            n = null_counts_in_scope[label]
            pct = n / in_scope_count * 100 if in_scope_count else 0
            line = f"{label}: {n:,} ({pct:.3f}%)"
            print(line)
            f.write(line + "\n")


if __name__ == "__main__":
    main()
