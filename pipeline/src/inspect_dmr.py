"""Phase 0 reconnaissance for the DMR statistics extract: stream the XML straight
out of the zip (the uncompressed file is ~128 GB, far too large to extract to disk
or hold in memory) with lxml.etree.iterparse, counting records, tag presence, and
sampling real make/model/variant values.

Pass --limit N to stop after N <Statistik> records, for a quick throughput/shape
check before committing to a full pass.
"""

from __future__ import annotations

import argparse
import time
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "dmr"
ZIP_PATH = RAW / "ESStatistikListeModtag-20260726-153441.zip"
XML_MEMBER = "ESStatistikListeModtag.xml"
NS = "{http://skat.dk/dmr/2007/05/31/}"
STATISTIK_TAG = f"{NS}Statistik"

# fields of interest per the project brief, as (label, relative xpath from Statistik)
FIELDS_OF_INTEREST = {
    "KoeretoejArtNavn": f"{NS}KoeretoejArtNavn",
    "FoersteRegistreringDato": f".//{NS}KoeretoejOplysningFoersteRegistreringDato",
    "MaerkeTypeNavn (make)": f".//{NS}KoeretoejMaerkeTypeNavn",
    "ModelTypeNavn (model)": f".//{NS}Model/{NS}KoeretoejModelTypeNavn",
    "VariantTypeNavn (variant)": f".//{NS}Variant/{NS}KoeretoejVariantTypeNavn",
    "DrivkraftTypeNavn (fuel type)": f".//{NS}DrivkraftTypeNavn",
    "KoeretoejMotorKmPerLiter (consumption)": f".//{NS}KoeretoejMotorKmPerLiter",
    "EgenVaegt (kerb weight)": f".//{NS}KoeretoejOplysningEgenVaegt",
    "StoersteEffekt (engine power)": f".//{NS}KoeretoejMotorStoersteEffekt",
    "CylinderAntal (cylinder count)": f".//{NS}KoeretoejMotorCylinderAntal",
    "NCAPTest (euro ncap flag)": f".//{NS}KoeretoejOplysningNCAPTest",
    "OplysningStatus (record status)": f".//{NS}KoeretoejOplysningStatus",
    "RegistreringStatus": f"{NS}KoeretoejRegistreringStatus",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    z = zipfile.ZipFile(ZIP_PATH)
    stream = z.open(XML_MEMBER)

    context = etree.iterparse(stream, events=("end",), tag=STATISTIK_TAG)

    record_count = 0
    personbil_count = 0
    null_counts: Counter = Counter()
    personbil_null_counts: Counter = Counter()
    art_navn_values: Counter = Counter()
    fuel_values: Counter = Counter()
    status_values: Counter = Counter()
    make_model_variant_samples: set[tuple[str, str, str]] = set()
    all_second_level_tags: set[str] = set()

    start = time.time()
    for _, elem in context:
        record_count += 1

        for child in elem:
            all_second_level_tags.add(etree.QName(child).localname)

        art_navn = elem.findtext(f"{NS}KoeretoejArtNavn")
        if art_navn:
            art_navn_values[art_navn] += 1
        is_personbil = art_navn == "Personbil"
        if is_personbil:
            personbil_count += 1

        for label, path in FIELDS_OF_INTEREST.items():
            found = elem.find(path)
            is_null = found is None or found.text is None or found.text == ""
            if is_null:
                null_counts[label] += 1
                if is_personbil:
                    personbil_null_counts[label] += 1

        status = elem.findtext(f".//{NS}KoeretoejOplysningStatus")
        if status:
            status_values[status] += 1

        for drivkraft in elem.iter(f"{NS}DrivkraftTypeNavn"):
            if drivkraft.text:
                fuel_values[drivkraft.text] += 1

        if len(make_model_variant_samples) < 500:
            make = elem.findtext(f".//{NS}KoeretoejMaerkeTypeNavn") or ""
            model = elem.findtext(f".//{NS}Model/{NS}KoeretoejModelTypeNavn") or ""
            variant = elem.findtext(f".//{NS}Variant/{NS}KoeretoejVariantTypeNavn") or ""
            if make and model:
                make_model_variant_samples.add((make, model, variant))

        # bound memory: drop the element and its now-unneeded preceding siblings
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

        if record_count % 500_000 == 0:
            elapsed = time.time() - start
            print(f"  ... {record_count:,} records in {elapsed:.1f}s ({record_count / elapsed:.0f} rec/s)")

        if args.limit and record_count >= args.limit:
            break

    elapsed = time.time() - start
    print(f"\ntotal records: {record_count:,} in {elapsed:.1f}s ({record_count / elapsed:.0f} rec/s)")

    print("\nsecond-level tag names observed (union across sampled records):")
    for t in sorted(all_second_level_tags):
        print(f"  {t}")

    print("\nnull/missing rate for fields of interest (all vehicle types):")
    for label in FIELDS_OF_INTEREST:
        n = null_counts.get(label, 0)
        pct = n / record_count * 100 if record_count else 0
        print(f"  {label}: {n:,} ({pct:.3f}%)")

    print(f"\nnull/missing rate for fields of interest (Personbil only, n={personbil_count:,}):")
    for label in FIELDS_OF_INTEREST:
        n = personbil_null_counts.get(label, 0)
        pct = n / personbil_count * 100 if personbil_count else 0
        print(f"  {label}: {n:,} ({pct:.3f}%)")

    print(f"\nKoeretoejArtNavn distinct values: {dict(art_navn_values)}")
    print(f"\nDrivkraftTypeNavn (fuel) distinct values: {dict(fuel_values)}")
    print(f"\nKoeretoejOplysningStatus distinct values: {dict(status_values)}")

    print(f"\n20 of {len(make_model_variant_samples)} sampled distinct (make, model, variant):")
    for mmv in list(make_model_variant_samples)[:20]:
        print(f"  {mmv}")


if __name__ == "__main__":
    main()
