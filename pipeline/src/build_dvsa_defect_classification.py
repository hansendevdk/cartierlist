"""Builds pipeline/reference/dvsa_defect_classification.csv: a frozen mapping
from every DVSA MOT defect category (section, component_category) actually
observed in the class-4 (passenger car) failure data to one of three buckets:

  mechanical             -- structural/mechanical faults that measure how the
                             car was built and has held up (suspension, brakes
                             system, steering, body/chassis corrosion, seat
                             belts, emissions system, electrical devices)
  consumable              -- wear/consumable items that measure the previous
                             owner, the climate and the local testing regime
                             rather than the vehicle (tyres, wiper blades,
                             washer fluid/jets, bulbs, brake pads/discs/linings,
                             battery, stone-chip screen damage)
  administrative_or_other -- not a vehicle-condition finding at all (plates,
                             VIN, "not tested" measurement-incomplete flags,
                             fitment/spec mismatches, bus-only items)

WRITTEN AND FROZEN BEFORE ANY CORRELATION IN THIS PHASE WAS COMPUTED. Every
bucket assignment is justified from what the DVSA item hierarchy says the
component IS (see the `basis` column, mostly transcribed from actual
rfr_desc/rfr_insp_manual_desc wording), never from what it would do to any
downstream number. See reports/failure_category_agreement_test.md for the
prediction stated ahead of the correlation.

Method, per the phase brief:
  1. DVSA's own hierarchy is two-level for this purpose: a TOP-LEVEL section
     (item_detail.test_item_set_section_id -> item_group.item_name, e.g.
     "Brakes", "Suspension", "Tyres") and, within it, the existing
     `component_category` string already used throughout this project
     (mot_failures.component_category, the leaf RfR's immediate parent group
     name, e.g. "Coil spring", "Condition", "Tread depth").
  2. The user guide confirms DVSA's OWN effectiveness-report methodology
     already groups failures at the top-level-section grain ("Initial
     failures by defect category are calculated using ... the top-level
     items in the Test Item hierarchy"), so a section-level default bucket is
     not an invented grouping -- it is DVSA's own published grouping.
  3. `component_category` alone is not always resolvable to one bucket: the
     brief's own flagged case, "Condition", is the largest single category
     (6.9M real failures) and appears as the immediate parent under 25
     distinct test_item_id nodes across Suspension, Brakes, Tyres, Road
     Wheels and Seat Belts sections (verified directly against
     item_group.csv). Resolved through the hierarchy per component: tyre
     Condition is a wear reading (consumable), every other Condition
     instance (spring/valve/pedal/wheel/belt) is a structural fault
     (mechanical) -- exactly the section-level split below, so no leaf-level
     guess was needed for this one either.
  4. Every (section, component_category) pair that actually appears as a
     real (rfr_type_code IN ('F','P'), i.e. non-advisory) class-4 failure in
     the 2022-2025 warehouse is enumerated below explicitly -- 277 rows, none
     left to a silent default the reader cannot see. A handful of sections
     use the SAME bucket for every category in them (Suspension, Steering,
     Road Wheels, Seat Belts, Body/chassis/structure, Speedometer) because
     there is no genuine wear-vs-structural split inside them for this
     purpose; two sections (Brakes, Tyres) split a small number of scheduled
     wear items (pads/discs/linings; tread/condition/valve stem) out of an
     otherwise-mechanical or otherwise-consumable section; two sections
     (Lamps/electrical, Visibility) are genuinely mixed and get the most
     per-category overrides.
  5. "Not tested" / measurement-incomplete items (headlamp aim not tested,
     emissions not tested, brake performance not tested, the old-hierarchy
     "Items Not Tested" section) are routed to administrative_or_other, not
     guessed into mechanical or consumable -- the same principle the Norway
     phase applied to PKK's class-4 "not measurable due to climate" flag.
     These items still count as real DVSA failures for the all-defects
     reproduction check (administrative_or_other is a real bucket, summed
     into "all"), they are simply excluded from BOTH the mechanical-only and
     consumable-only subsets, same as every other administrative_or_other row.

This script only WRITES the classification. It does not touch mot_failures,
model_age_band_metrics.csv, or compute any rate -- that happens in
compute_failure_category_agreement.py, a separate, later step.
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
LOOKUP = ROOT / "data" / "interim" / "dvsa_lookup"
OUT_CSV = ROOT / "pipeline" / "reference" / "dvsa_defect_classification.csv"

MECHANICAL = "mechanical"
CONSUMABLE = "consumable"
OTHER = "administrative_or_other"

# Section-level default bucket, and the basis for that default. Applied to
# every (section, component_category) pair not named in OVERRIDES below.
SECTION_DEFAULT: dict[int, tuple[str, str]] = {
    5800: (OTHER, "Old (pre-2018) hierarchy remnant, 'Items Not Tested' -- a "
                   "measurement-incomplete marker, not a condition finding; "
                   "330 rows total in 2022-2025 class-4 data, immaterial"),
    20000: (OTHER, "Identification of the vehicle: plates and VIN. Not a "
                    "vehicle-condition finding of any kind"),
    20003: (MECHANICAL, "Brakes: hydraulic/pneumatic system integrity, "
                         "performance and structural mounting -- a defect "
                         "here reflects the braking SYSTEM's condition, not "
                         "a scheduled wear item (see per-row overrides for "
                         "the pads/discs/linings that ARE scheduled wear)"),
    20106: (MECHANICAL, "Steering: linkage, rack, column and box integrity "
                         "-- structural steering-system faults throughout, "
                         "no scheduled-wear item exists in this section"),
    20147: (CONSUMABLE, "Visibility: dominated by wiper blades and washer "
                         "fluid/jets, the textbook scheduled-maintenance "
                         "wear items (see overrides for the mounting/device "
                         "faults in this section that are not wear)"),
    20158: (CONSUMABLE, "Lamps, reflectors and electrical equipment: "
                         "dominated by bulb-type items (position/stop/"
                         "indicator/plate lamps) that burn out on a "
                         "predictable cycle unrelated to build quality (see "
                         "overrides for the device/switch/wiring faults in "
                         "this section that are not bulb wear)"),
    20218: (MECHANICAL, "Suspension: springs, joints, bushes, arms and "
                         "mountings -- structural/corrosion-driven "
                         "component failure, the section the brief's own "
                         "'how the car was built' framing describes most "
                         "directly"),
    20310: (MECHANICAL, "Body, chassis, structure: corrosion and structural "
                         "integrity of the body shell, seats, doors, "
                         "mountings and towbar -- the brief's own body-"
                         "corrosion example category"),
    20365: (MECHANICAL, "Speedometer and speed limiter: an "
                         "electronic/mechanical device malfunction, not "
                         "owner- or climate-driven wear"),
    20366: (MECHANICAL, "Seat belts and supplementary restraint systems: "
                         "structural restraint-system integrity (see "
                         "override for 'Requirements', a fitment/spec "
                         "mismatch rather than a condition fault)"),
    20385: (MECHANICAL, "Noise, emissions and leaks: catalyst/engine "
                         "management and fluid-seal integrity -- an "
                         "emissions or leak failure reflects the engine and "
                         "exhaust system's mechanical condition (see "
                         "override for 'Emissions not tested')"),
    20422: (OTHER, "Buses and coaches supplementary tests: passenger-door, "
                    "step and grab-handle hardware specific to buses/"
                    "coaches, not applicable to the ordinary passenger cars "
                    "this project ranks; 2,484 rows total, immaterial"),
    20431: (OTHER, "Seat belt installation check: a check of whether belts "
                    "were installed as originally type-approved, i.e. a "
                    "compliance/spec check, not a condition or wear finding"),
    20448: (MECHANICAL, "Road Wheels: wheel attachment, condition and hub "
                         "integrity -- structural wheel-fixing faults, not "
                         "a scheduled wear item (tyre wear is a separate "
                         "section, see 20449)"),
    20449: (CONSUMABLE, "Tyres: condition and tread depth are the textbook "
                         "scheduled wear item, replaced on a "
                         "mileage/exposure cycle regardless of the "
                         "vehicle's own build quality (see overrides for "
                         "TPMS and size/type, which are not tyre wear)"),
}

SECTION_NAMES = {
    5800: "Items Not Tested",
    20000: "Identification of the vehicle",
    20003: "Brakes",
    20106: "Steering",
    20147: "Visibility",
    20158: "Lamps, reflectors and electrical equipment",
    20218: "Suspension",
    20310: "Body, chassis, structure",
    20365: "Speedometer and speed limiter",
    20366: "Seat belts and supplementary restraint systems",
    20385: "Noise, emissions and leaks",
    20422: "Buses and coaches supplementary tests",
    20431: "Seat belt installation check",
    20448: "Road Wheels",
    20449: "Tyres",
}

# Per-(section_id, component_category) overrides where the section default
# would be wrong for that specific category. Every override is judged on
# what the component IS (per rfr_desc/rfr_insp_manual_desc, checked directly
# against mot_failures before this table was written), never on effect.
OVERRIDES: dict[tuple[int, str], tuple[str, str]] = {
    # --- Brakes (20003): scheduled wear items out of an otherwise-mechanical section
    (20003, "Brake pads"): (CONSUMABLE, "Scheduled wear item, replaced on a "
                             "mileage/usage cycle regardless of vehicle "
                             "build quality -- the brake-system analogue of "
                             "tyre tread"),
    (20003, "Brake discs"): (CONSUMABLE, "Scheduled wear item, same "
                              "wear cycle as pads"),
    (20003, "Brake linings"): (CONSUMABLE, "Drum-brake analogue of brake "
                                "pads, scheduled wear item"),
    (20003, "Brake performance not tested"): (OTHER, "rfr_desc 'unable to "
                              "be tested'/'not tested' -- measurement not "
                              "completed, not a defect finding"),
    # --- Steering (20106): none -- entire section is structural, no override needed
    # --- Visibility (20147): mounting/device faults out of an otherwise-consumable section
    (20147, "Mirrors"): (MECHANICAL, "MOT mirror failures are overwhelmingly "
                          "insecure mounting, not glass wear -- a structural "
                          "fault"),
    (20147, "Bonnet"): (MECHANICAL, "Catch/release mechanism security, a "
                         "structural safety-mechanism fault"),
    (20147, "Indirect vision devices"): (MECHANICAL, "Device (camera/mirror "
                                          "alternative) malfunction"),
    (20147, "Driver's view"): (OTHER, "Obstruction to view (stickers, "
                                "objects, tax disc holders) -- not a "
                                "vehicle-condition or wear finding"),
    # --- Lamps, reflectors and electrical equipment (20158): device/switch/wiring
    #     faults and measurement-incomplete flags out of an otherwise-consumable section
    (20158, "Headlamp aim not tested"): (OTHER, "Measurement not completed, "
                                          "not a defect finding"),
    (20158, "Headlamp levelling device"): (MECHANICAL, "Levelling motor/"
                                            "sensor device failure, distinct "
                                            "from the aim (alignment) "
                                            "reading itself"),
    (20158, "Switch"): (MECHANICAL, "Electrical switch component failure"),
    (20158, "Reversing lamp switch"): (MECHANICAL, "Electrical switch "
                                        "component failure"),
    (20158, "Front fog lamp switch"): (MECHANICAL, "Electrical switch "
                                        "component failure"),
    (20158, "Dipswitch"): (MECHANICAL, "Electrical switch component "
                            "failure"),
    (20158, "Electrical wiring "): (MECHANICAL, "Wiring damage/insecurity, "
                                     "a structural electrical fault, not "
                                     "bulb wear"),
    (20158, "Headlamp cleaning device"): (MECHANICAL, "Device (washer jet "
                                           "mechanism) failure"),
    (20158, "Horn"): (MECHANICAL, "Electrical component malfunction, not a "
                       "scheduled wear item"),
    (20158, "Trailer electrical socket"): (MECHANICAL, "Wiring/socket "
                                            "fault"),
    (20158, "Matched pair"): (OTHER, "Mismatched lamp type/colour across an "
                               "axle/pair -- a fitment finding, not a "
                               "condition fault"),
    # --- Suspension (20218): none -- entire section is structural, no override needed
    # --- Body, chassis, structure (20310): none -- entire section is structural
    # --- Seat belts (20366): fitment/spec mismatch out of an otherwise-mechanical section
    (20366, "Requirements"): (OTHER, "rfr_desc 'of the wrong type' -- a "
                               "fitment/spec mismatch, not a condition or "
                               "wear finding"),
    # --- Noise, emissions and leaks (20385): measurement-incomplete flag
    (20385, "Emissions not tested"): (OTHER, "Measurement not completed, "
                                       "not a defect finding"),
    # --- Road Wheels (20448): none -- entire section is structural
    # --- Tyres (20449): non-wear items out of an otherwise-consumable section
    (20449, "Tyre pressure monitoring system"): (MECHANICAL, "Electronic "
                                                  "sensor/system fault, "
                                                  "unrelated to tyre wear "
                                                  "itself"),
    (20449, "Size/type"): (OTHER, "Wrong tyre size/type/rating fitted -- a "
                            "fitment/spec mismatch, not a wear or condition "
                            "finding"),
}


def classify(section_id: int, category: str) -> tuple[str, str]:
    if (section_id, category) in OVERRIDES:
        return OVERRIDES[(section_id, category)]
    if section_id in SECTION_DEFAULT:
        return SECTION_DEFAULT[section_id]
    raise KeyError(f"no rule for section_id={section_id} ({category!r}) -- "
                    f"a new/unmapped DVSA section appeared; add it to "
                    f"SECTION_DEFAULT before running the agreement study")


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE idet AS
        SELECT CAST(rfr_id AS INTEGER) rfr_id,
               CAST(test_item_set_section_id AS INTEGER) section_id
        FROM read_csv('{(LOOKUP / "item_detail.csv").as_posix()}', delim='|', header=true)
        WHERE test_class_id = '4'
    """)
    rows = con.execute("""
        SELECT idet.section_id, fc.component_category, COUNT(*) AS n_failures
        FROM mot_failures f
        JOIN idet ON idet.rfr_id = f.rfr_id
        JOIN failure_categories fc ON fc.rfr_id = f.rfr_id AND fc.test_class_id = 4
        WHERE f.rfr_type_code IN ('F', 'P')
        GROUP BY 1, 2
        ORDER BY 1, 3 DESC
    """).fetchall()
    con.close()

    print(f"(section, component_category) pairs observed in real class-4 failures: {len(rows)}")

    out_rows = []
    bucket_totals: dict[str, int] = {MECHANICAL: 0, CONSUMABLE: 0, OTHER: 0}
    for section_id, category, n in rows:
        bucket, basis = classify(section_id, category)
        bucket_totals[bucket] += n
        out_rows.append({
            "section_id": section_id,
            "section_name": SECTION_NAMES[section_id],
            "component_category": category,
            "n_failures_2022_2025": n,
            "bucket": bucket,
            "basis": basis,
        })

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "section_id", "section_name", "component_category",
            "n_failures_2022_2025", "bucket", "basis",
        ])
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {OUT_CSV} ({len(out_rows)} rows)")

    total = sum(bucket_totals.values())
    print("\nbucket totals (real, non-advisory F/P failure items, 2022-2025 class-4 data):")
    for b, n in bucket_totals.items():
        print(f"  {b:<24} {n:>12,}  ({n/total*100:5.1f}%)")


if __name__ == "__main__":
    main()
