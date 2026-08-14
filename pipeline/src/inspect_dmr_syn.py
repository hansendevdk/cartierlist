"""Reconnaissance on SynResultatStruktur (Denmark's periodic vehicle inspection,
"syn") and, briefly, KoeretoejUdstyrSamlingStruktur (the equipment list), inside
the DMR statistics extract. Neither is parsed by build_dmr_vehicles.py.

This streams the archive with lxml.etree.iterparse, exactly like
build_dmr_vehicles.py and inspect_dmr.py, and never loads the file into memory:
the uncompressed XML is ~128 GB. Sampling is deliberate, not a full pass -- see
pipeline/reports/phase0b_dmr_syn_report.md for how many records a given run
covered and what that implies for the numbers reported.

Scope mirrors build_dk_fleet.py's v1 definition of "in scope": Personbil,
registration_status Registreret, first_registration_year in [2010, 2022],
fuel_type_primary != 'El', deduped on chassis_number (the same leasing-snapshot
duplication build_dmr_vehicles.py documents applies here too). "Crosswalked"
means the (make_name, model_name) pair appears in reference/crosswalk.csv,
i.e. it is a model this project actually reports on.

CROSSWALKED_IN_SCOPE_TOTAL is the full, already-known population size for that
scope (from the settled scalar-field review), used only to scale a sampled
share into a total estimate -- this script does not attempt to recompute that
figure by re-running the full crosswalk/dedupe pipeline itself.
"""

from __future__ import annotations

import argparse
import csv
import time
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "dmr"
ZIP_PATH = RAW / "ESStatistikListeModtag-20260726-153441.zip"
XML_MEMBER = "ESStatistikListeModtag.xml"
NS = "{http://skat.dk/dmr/2007/05/31/}"
STATISTIK_TAG = f"{NS}Statistik"
SYN_TAG = f"{NS}SynResultatStruktur"
EQUIP_TYPE_NAME_TAG = f"{NS}KoeretoejUdstyrTypeStruktur/{NS}KoeretoejUdstyrTypeNavn"

CROSSWALK_CSV = ROOT / "pipeline" / "reference" / "crosswalk.csv"

# (band, reg_year_min, reg_year_max) -- same boundaries as AGE_BANDS in
# build_phase3_metrics.py, duplicated here rather than imported since this
# script only reads that shape, it doesn't depend on the metrics pipeline.
AGE_BANDS = [
    (1, 2020, 2022),
    (2, 2017, 2019),
    (3, 2014, 2016),
    (4, 2010, 2013),
]

# Known size of the crosswalked, in-scope population (Personbil, Registreret,
# 2010-2022, non-BEV, deduped by chassis, model in reference/crosswalk.csv),
# established by the settled scalar-field review. Used only to scale a
# sampled share into a whole-fleet estimate for question 5.
CROSSWALK_IN_SCOPE_TOTAL = 2_768_943

EXAMPLE_LIMIT = 25
NONPASS_EXAMPLE_LIMIT = 12
EQUIPMENT_SAMPLE_LIMIT = 200_000


def load_crosswalk_pairs() -> set[tuple[str, str]]:
    pairs = set()
    with open(CROSSWALK_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pairs.add((row["dmr_make"], row["dmr_model"]))
    return pairs


def age_band(year: int | None) -> int | None:
    if year is None:
        return None
    for band, ymin, ymax in AGE_BANDS:
        if ymin <= year <= ymax:
            return band
    return None


def fuel_type_primary(elem) -> str | None:
    """Same logic as build_dmr_vehicles.py: a vehicle can carry multiple
    DrivmiddelStruktur entries, one flagged primary. Fall back to the first
    entry if none is explicitly flagged, matching that file's behaviour so
    scope filtering here agrees with what dk_fleet would compute."""
    fuels = []
    for drivmiddel in elem.iter(f"{NS}DrivmiddelStruktur"):
        name = drivmiddel.findtext(f"{NS}DrivkraftTypeStruktur/{NS}DrivkraftTypeNavn")
        primaer = drivmiddel.findtext(f"{NS}KoeretoejMotorDrivmiddelPrimaer")
        is_primary = primaer is not None and primaer.strip().lower() == "true"
        fuels.append((name, is_primary))
    if not fuels:
        return None
    primary = next((f for f in fuels if f[1]), fuels[0])
    return primary[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3_000_000,
                     help="stop after this many <Statistik> elements streamed (default 3,000,000)")
    args = ap.parse_args()

    crosswalk_pairs = load_crosswalk_pairs()
    print(f"loaded {len(crosswalk_pairs):,} crosswalked (make, model) pairs from {CROSSWALK_CSV.name}")

    z = zipfile.ZipFile(ZIP_PATH)
    stream = z.open(XML_MEMBER)
    context = etree.iterparse(stream, events=("end",), tag=STATISTIK_TAG)

    total_statistik = 0
    personbil_count = 0
    in_scope_raw = 0
    crosswalked_in_scope_raw = 0

    seen_chassis: set[str] = set()
    unique_crosswalked_in_scope = 0

    syn_count_hist: Counter = Counter()
    result_counts: Counter = Counter()
    type_counts: Counter = Counter()
    type_result_crosstab: Counter = Counter()
    status_counts: Counter = Counter()
    km_values: list[float] = []
    km_null = 0

    date_min: str | None = None
    date_max: str | None = None

    age_band_total: Counter = Counter()
    age_band_has_syn: Counter = Counter()

    # safety net: re-confirm at full sample scale that no child of
    # SynResultatStruktur ever has its own children (i.e. no itemised
    # failure sub-structure), rather than trusting the small exploratory
    # pass alone.
    syn_leaf_tags: set[str] = set()
    syn_struct_tags: set[str] = set()

    examples_general: list[tuple] = []
    examples_nonpass: list[tuple] = []

    equipment_checked = 0
    equipment_has = 0
    equipment_type_counts: Counter = Counter()

    start = time.time()

    for _, elem in context:
        total_statistik += 1

        art_navn = elem.findtext(f"{NS}KoeretoejArtNavn")
        if art_navn == "Personbil":
            personbil_count += 1

            chassis = elem.findtext(f".//{NS}KoeretoejOplysningStelNummer")
            reg_status = elem.findtext(f"{NS}KoeretoejRegistreringStatus")
            make_name = elem.findtext(f".//{NS}KoeretoejMaerkeTypeNavn")
            model_name = elem.findtext(f".//{NS}Model/{NS}KoeretoejModelTypeNavn")
            first_reg = elem.findtext(f".//{NS}KoeretoejOplysningFoersteRegistreringDato")
            first_reg_year = int(first_reg[:4]) if first_reg and first_reg[:4].isdigit() else None
            fuel_primary = fuel_type_primary(elem)

            in_scope = (
                reg_status == "Registreret"
                and first_reg_year is not None
                and 2010 <= first_reg_year <= 2022
                and fuel_primary != "El"
                and chassis is not None
            )

            if in_scope:
                in_scope_raw += 1
                if (make_name, model_name) in crosswalk_pairs:
                    crosswalked_in_scope_raw += 1

                    if chassis not in seen_chassis:
                        seen_chassis.add(chassis)
                        unique_crosswalked_in_scope += 1

                        band = age_band(first_reg_year)
                        syn_list = elem.findall(f".//{SYN_TAG}")
                        n_syn = len(syn_list)
                        syn_count_hist[n_syn] += 1

                        if band is not None:
                            age_band_total[band] += 1
                            if n_syn >= 1:
                                age_band_has_syn[band] += 1

                        for s in syn_list:
                            for child in s:
                                local = etree.QName(child).localname
                                if len(child) > 0:
                                    syn_struct_tags.add(local)
                                else:
                                    syn_leaf_tags.add(local)

                            syn_type = s.findtext(f"{NS}SynResultatSynsType")
                            syn_date = s.findtext(f"{NS}SynResultatSynsDato")
                            result = s.findtext(f"{NS}SynResultatSynsResultat")
                            status = s.findtext(f"{NS}SynResultatSynStatus")
                            km_txt = s.findtext(f"{NS}KoeretoejMotorKilometerstand")

                            if syn_type:
                                type_counts[syn_type] += 1
                            if result:
                                result_counts[result] += 1
                            if status:
                                status_counts[status] += 1
                            if syn_type and result:
                                type_result_crosstab[(syn_type, result)] += 1

                            if syn_date:
                                d10 = syn_date[:10]
                                if date_min is None or d10 < date_min:
                                    date_min = d10
                                if date_max is None or d10 > date_max:
                                    date_max = d10

                            if km_txt:
                                try:
                                    km_values.append(float(km_txt))
                                except ValueError:
                                    pass
                            else:
                                km_null += 1

                            record = (make_name, model_name, first_reg_year, syn_type, syn_date, result, status, km_txt)
                            if len(examples_general) < EXAMPLE_LIMIT:
                                examples_general.append(record)
                            if result and result != "Godkendt" and len(examples_nonpass) < NONPASS_EXAMPLE_LIMIT:
                                examples_nonpass.append(record)

                        if equipment_checked < EQUIPMENT_SAMPLE_LIMIT:
                            equipment_checked += 1
                            equip_items = elem.findall(f".//{EQUIP_TYPE_NAME_TAG}")
                            if equip_items:
                                equipment_has += 1
                                for e in equip_items:
                                    if e.text:
                                        equipment_type_counts[e.text] += 1

        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]

        if total_statistik % 500_000 == 0:
            elapsed = time.time() - start
            print(
                f"  ... {total_statistik:,} statistik records ({personbil_count:,} personbil, "
                f"{unique_crosswalked_in_scope:,} unique crosswalked in-scope) in {elapsed:.0f}s "
                f"({total_statistik / elapsed:.0f} rec/s)",
                flush=True,
            )

        if args.limit and total_statistik >= args.limit:
            break

    elapsed = time.time() - start
    print(f"\nDONE: {total_statistik:,} statistik records streamed in {elapsed:.0f}s "
          f"({total_statistik / elapsed:.0f} rec/s)")
    print(f"personbil: {personbil_count:,}")
    print(f"in-scope personbil (Registreret, 2010-2022, non-El), raw rows: {in_scope_raw:,}")
    print(f"crosswalked in-scope personbil, raw rows: {crosswalked_in_scope_raw:,}")
    print(f"crosswalked in-scope personbil, unique by chassis: {unique_crosswalked_in_scope:,}")

    has_syn = sum(n for count, n in syn_count_hist.items() if count >= 1)
    coverage_pct = has_syn / unique_crosswalked_in_scope * 100 if unique_crosswalked_in_scope else 0
    print(f"\nQ2: share of unique crosswalked in-scope vehicles with >=1 syn record: "
          f"{has_syn:,} / {unique_crosswalked_in_scope:,} ({coverage_pct:.2f}%)")
    print(f"records-per-vehicle histogram: {dict(sorted(syn_count_hist.items()))}")

    print(f"\nQ1: leaf tag names seen directly under SynResultatStruktur: {sorted(syn_leaf_tags)}")
    print(f"Q1: tags with children under SynResultatStruktur (possible itemised sub-structure): "
          f"{sorted(syn_struct_tags) if syn_struct_tags else 'NONE FOUND'}")

    total_syn_seen = sum(result_counts.values())
    print(f"\nQ3: SynResultatSynsResultat distinct values (n={total_syn_seen:,} syn records):")
    for val, n in result_counts.most_common():
        print(f"  {val}: {n:,} ({n / total_syn_seen * 100:.3f}%)")

    print(f"\nSynResultatSynsType distinct values:")
    for val, n in type_counts.most_common():
        print(f"  {val}: {n:,} ({n / total_syn_seen * 100:.3f}%)")

    print(f"\nSynResultatSynStatus distinct values:")
    for val, n in status_counts.most_common():
        print(f"  {val}: {n:,}")

    print(f"\ntype x result crosstab:")
    for (t, r), n in type_result_crosstab.most_common(30):
        print(f"  {t} / {r}: {n:,}")

    print(f"\nQ4: SynResultatSynsDato range observed: {date_min} to {date_max}")
    print("Q4: coverage by age band (band: has_syn / total, pct):")
    for band, ymin, ymax in AGE_BANDS:
        total = age_band_total.get(band, 0)
        has = age_band_has_syn.get(band, 0)
        pct = has / total * 100 if total else 0
        print(f"  band {band} ({ymin}-{ymax}): {has:,} / {total:,} ({pct:.2f}%)")

    if km_values:
        km_sorted = sorted(km_values)
        n = len(km_sorted)
        print(f"\nKoeretoejMotorKilometerstand (odometer): n={n:,} non-null, "
              f"null={km_null:,} ({km_null / (n + km_null) * 100:.2f}% of syn records with this field checked)")
        print(f"  min={km_sorted[0]:.0f} p25={km_sorted[int(n*0.25)]:.0f} p50={km_sorted[n//2]:.0f} "
              f"p75={km_sorted[int(n*0.75)]:.0f} p90={km_sorted[int(n*0.9)]:.0f} max={km_sorted[-1]:.0f}")
        under_2000 = sum(1 for v in km_sorted if v < 2000)
        print(f"  share of non-null values under 2000: {under_2000:,} / {n:,} ({under_2000 / n * 100:.2f}%)")

    est_total = coverage_pct / 100 * CROSSWALK_IN_SCOPE_TOTAL
    print(f"\nQ5: sampled coverage {coverage_pct:.2f}% scaled to the known crosswalked in-scope "
          f"population ({CROSSWALK_IN_SCOPE_TOTAL:,}) gives an estimated "
          f"{est_total:,.0f} total syn records for the crosswalked in-scope fleet "
          f"(at most 1 record per vehicle, so this equals the estimated vehicle count with a record).")
    print(f"sample represents {unique_crosswalked_in_scope / CROSSWALK_IN_SCOPE_TOTAL * 100:.2f}% "
          f"of the known crosswalked in-scope population.")

    print(f"\nequipment: checked {equipment_checked:,} crosswalked in-scope vehicles, "
          f"{equipment_has:,} had at least one KoeretoejUdstyrTypeStruktur entry "
          f"({equipment_has / equipment_checked * 100:.2f}%)" if equipment_checked else "")
    print(f"equipment: {len(equipment_type_counts):,} distinct KoeretoejUdstyrTypeNavn values seen")
    print("equipment: top 20 by vehicle-count:")
    for name, n in equipment_type_counts.most_common(20):
        print(f"  {name}: {n:,}")

    print(f"\n{len(examples_general)} example syn records (make, model, first_reg_year, "
          f"syn_type, syn_date, result, status, km):")
    for r in examples_general:
        print(f"  {r}")

    print(f"\n{len(examples_nonpass)} example non-Godkendt syn records:")
    for r in examples_nonpass:
        print(f"  {r}")


if __name__ == "__main__":
    main()
