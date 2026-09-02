"""Writes reference/model_segments.csv.

WHY THIS IS HAND-AUTHORED AND NOT SOURCED
No open dataset maps a Danish Motor Registry make/model string to its EU
market segment (A/B/C/D/E/F, plus the SUV and MPV body classes that don't
sort into a size letter). Unlike the parts-cost multiplier table, this one
isn't a judgement call: EU segment is a standard, widely agreed-on
classification for essentially every model on the Danish market, so each row
here is a lookup against that convention, not an estimate. A handful of rows
are genuinely ambiguous (a nameplate that changed body style across its
lifetime, or with no single settled classification); those are flagged below
so a reader can second-guess them specifically.

TAXONOMY
  A  mini / city car            (Aygo, Panda, Up!)
  B  small / supermini          (Polo, Clio, 208)
  C  medium / compact           (Golf, Focus, Octavia)
  D  large / family             (Passat, Mondeo, 3-Series)
  E  executive                  (5-Series, E-Klasse, V90)
  F  luxury                     (7-Series and above; none in this fleet yet)
  J  SUV / crossover, any size  (Qashqai, XC60, Tiguan)
  M  MPV / minivan / van-based  (Touran, Scenic, Caddy)

J and M take priority over a size letter when a model's body style, not its
footprint, is the reason someone would filter for or against it -- a Dacia
Duster and a Volvo XC90 are wildly different sizes but both "an SUV" in the
sense this filter exists for.

SCOPE
One row per (dmr_make, dmr_model) pair that appears in
model_bracket_rankings.csv (184 as of the crosswalk this was authored
against), keyed on that file's exact spelling so the join in
build_phase4_rankings.py is a plain string match, no normalisation needed.

FLAGGED / AMBIGUOUS
  PEUGEOT 5008    Sold as a 7-seat MPV through ~2016, then rebodied as a
                  compact SUV from 2017. This fleet's age bands span both
                  generations. Classified J (the newer, more common
                  generation in a used-car search today); worth a second
                  look if it skews the wrong way in results.
  CITROËN C4 Cactus  Marketed with crossover styling and raised ride height
                  but built on the C4 hatchback platform, not a true SUV
                  monocoque. Classified C rather than J on that basis.
"""

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reference" / "model_segments.csv"

# (dmr_make, dmr_model, segment) -- dmr_make/dmr_model spelling matches
# model_bracket_rankings.csv exactly.
ROWS = [
    ("ALFA ROMEO", "GIULIETTA", "C"),

    ("AUDI", "A1 SPORTBACK", "B"),
    ("AUDI", "A3", "C"),
    ("AUDI", "A3 CABRIOLET", "C"),
    ("AUDI", "A3 Limousine", "C"),
    ("AUDI", "A3 Sportback", "C"),
    ("AUDI", "A4 AVANT", "D"),
    ("AUDI", "A5 SPORTBACK", "D"),
    ("AUDI", "A6 AVANT", "E"),
    ("AUDI", "Q2", "J"),
    ("AUDI", "Q3", "J"),
    ("AUDI", "Q5", "J"),

    ("BMW", "1-Serie", "C"),
    ("BMW", "2-Serie", "C"),
    ("BMW", "3-Serie", "D"),
    ("BMW", "4-serie", "D"),
    ("BMW", "5-Serie", "E"),
    ("BMW", "X1", "J"),
    ("BMW", "X3", "J"),
    ("BMW", "X5", "J"),

    ("CHEVROLET", "AVEO", "B"),
    ("CHEVROLET", "SPARK", "A"),

    ("CITROËN", "BERLINGO", "M"),
    ("CITROËN", "C1", "A"),
    ("CITROËN", "C3", "B"),
    ("CITROËN", "C3 Aircross", "J"),
    ("CITROËN", "C3 PICASSO", "M"),
    ("CITROËN", "C4", "C"),
    ("CITROËN", "C4 Cactus", "C"),  # see FLAGGED above
    ("CITROËN", "C4 PICASSO", "M"),
    ("CITROËN", "C5 Aircross", "J"),
    ("CITROËN", "DS3", "B"),
    ("CITROËN", "GRAND C4 PICASSO", "M"),
    ("CITROËN", "Grand C4 SpaceTourer", "M"),

    ("DACIA", "Duster", "J"),
    ("DACIA", "Logan MCV", "B"),
    ("DACIA", "SANDERO", "B"),

    ("DS", "DS 3", "B"),

    ("FIAT", "500", "A"),
    ("FIAT", "500C", "A"),
    ("FIAT", "PANDA", "A"),
    ("FIAT", "Punto S7", "B"),

    ("FORD", "B-MAX", "M"),
    ("FORD", "C-MAX", "M"),
    ("FORD", "FIESTA", "B"),
    ("FORD", "FOCUS", "C"),
    ("FORD", "FOCUS STATIONSVOGN", "C"),
    ("FORD", "GALAXY", "M"),
    ("FORD", "KA", "A"),
    ("FORD", "KUGA", "J"),
    ("FORD", "MONDEO", "D"),
    ("FORD", "MONDEO STATIONCAR", "D"),
    ("FORD", "PUMA", "J"),
    ("FORD", "S-MAX", "M"),
    ("FORD", "Transit Custom Kombi", "M"),

    ("HONDA", "CIVIC", "C"),
    ("HONDA", "CR-V", "J"),
    ("HONDA", "JAZZ", "B"),

    ("HYUNDAI", "I10", "A"),
    ("HYUNDAI", "I20", "B"),
    ("HYUNDAI", "I30", "C"),
    ("HYUNDAI", "I40", "D"),
    ("HYUNDAI", "IX20", "M"),
    ("HYUNDAI", "Ioniq", "C"),
    ("HYUNDAI", "KONA", "J"),
    ("HYUNDAI", "Tucson", "J"),

    ("KIA", "CEED", "C"),
    ("KIA", "Niro", "J"),
    ("KIA", "Optima", "D"),
    ("KIA", "PICANTO", "A"),
    ("KIA", "RIO", "B"),
    ("KIA", "SPORTAGE", "J"),
    ("KIA", "Stonic", "J"),
    ("KIA", "VENGA", "M"),
    ("KIA", "XCeed", "J"),

    ("MAZDA", "CX-3", "J"),
    ("MAZDA", "CX-5", "J"),
    ("MAZDA", "MAZDA2", "B"),
    ("MAZDA", "MAZDA3", "C"),
    ("MAZDA", "MAZDA6", "D"),
    ("MAZDA", "Mazda CX-30", "J"),

    ("MERCEDES-BENZ", "A-Klasse", "C"),
    ("MERCEDES-BENZ", "B-Klasse", "M"),
    ("MERCEDES-BENZ", "C-Klasse", "D"),
    ("MERCEDES-BENZ", "CLA", "C"),
    ("MERCEDES-BENZ", "E-Klasse", "E"),
    ("MERCEDES-BENZ", "GLA", "J"),
    ("MERCEDES-BENZ", "GLB", "J"),
    ("MERCEDES-BENZ", "GLC", "J"),
    ("MERCEDES-BENZ", "GLE", "J"),

    ("MINI", "COOPER", "B"),

    ("MITSUBISHI", "ASX", "J"),
    ("MITSUBISHI", "COLT", "B"),
    ("MITSUBISHI", "OUTLANDER", "J"),
    ("MITSUBISHI", "SPACE STAR", "B"),

    ("NISSAN", "JUKE", "J"),
    ("NISSAN", "MICRA", "B"),
    ("NISSAN", "NOTE", "M"),
    ("NISSAN", "QASHQAI", "J"),
    ("NISSAN", "X-TRAIL", "J"),

    ("OPEL", "ASTRA", "C"),
    ("OPEL", "ASTRA SPORTS TOURER", "C"),
    ("OPEL", "CORSA", "B"),
    ("OPEL", "Crossland X", "J"),
    ("OPEL", "Grandland X", "J"),
    ("OPEL", "INSIGNIA", "D"),
    ("OPEL", "KARL", "A"),
    ("OPEL", "MERIVA", "M"),
    ("OPEL", "Mokka", "J"),
    ("OPEL", "ZAFIRA", "M"),

    ("PEUGEOT", "107", "A"),
    ("PEUGEOT", "108", "A"),
    ("PEUGEOT", "2008", "J"),
    ("PEUGEOT", "206 +", "B"),
    ("PEUGEOT", "207", "B"),
    ("PEUGEOT", "208", "B"),
    ("PEUGEOT", "3008", "J"),
    ("PEUGEOT", "308", "C"),
    ("PEUGEOT", "5008", "J"),  # see FLAGGED above
    ("PEUGEOT", "508", "D"),

    ("RENAULT", "Captur", "J"),
    ("RENAULT", "GRAND SCENIC", "M"),
    ("RENAULT", "Kadjar", "J"),
    ("RENAULT", "MEGANE", "C"),
    ("RENAULT", "MEGANE SPORT TOURER", "C"),
    ("RENAULT", "Ny Clio", "B"),
    ("RENAULT", "SCENIC", "M"),
    ("RENAULT", "TWINGO", "A"),

    ("SEAT", "Arona", "J"),
    ("SEAT", "Ateca", "J"),
    ("SEAT", "IBIZA", "B"),
    ("SEAT", "LEON", "C"),
    ("SEAT", "MII", "A"),
    ("SEAT", "TOLEDO", "C"),

    ("SKODA", "CITIGO", "A"),
    ("SKODA", "FABIA", "B"),
    ("SKODA", "FABIA COMBI", "B"),
    ("SKODA", "KAMIQ", "J"),
    ("SKODA", "KAROQ", "J"),
    ("SKODA", "KODIAQ", "J"),
    ("SKODA", "OCTAVIA", "C"),
    ("SKODA", "OCTAVIA COMBI", "C"),
    ("SKODA", "RAPID", "C"),
    ("SKODA", "RAPID SPACEBACK", "C"),
    ("SKODA", "SCALA", "C"),
    ("SKODA", "SUPERB", "D"),
    ("SKODA", "SUPERB COMBI", "D"),

    ("SUZUKI", "BALENO", "B"),
    ("SUZUKI", "Celerio", "A"),
    ("SUZUKI", "IGNIS", "A"),
    ("SUZUKI", "SWIFT", "B"),

    ("TOYOTA", "AURIS", "C"),
    ("TOYOTA", "AVENSIS", "D"),
    ("TOYOTA", "AVENSIS STW", "D"),
    ("TOYOTA", "AYGO", "A"),
    ("TOYOTA", "Aygo X", "A"),
    ("TOYOTA", "COROLLA", "C"),
    ("TOYOTA", "RAV4", "J"),
    ("TOYOTA", "RAV4 Plug in", "J"),
    ("TOYOTA", "Toyota C-HR", "J"),
    ("TOYOTA", "VERSO", "M"),
    ("TOYOTA", "YARIS", "B"),
    ("TOYOTA", "Yaris Cross", "J"),

    ("VOLKSWAGEN", "CADDY", "M"),
    ("VOLKSWAGEN", "CALIFORNIA", "M"),
    ("VOLKSWAGEN", "GOLF", "C"),
    ("VOLKSWAGEN", "GOLF VARIANT", "C"),
    ("VOLKSWAGEN", "Golf Sportsvan", "M"),
    ("VOLKSWAGEN", "PASSAT", "D"),
    ("VOLKSWAGEN", "PASSAT VARIANT", "D"),
    ("VOLKSWAGEN", "POLO", "B"),
    ("VOLKSWAGEN", "T-Cross", "J"),
    ("VOLKSWAGEN", "T-Roc", "J"),
    ("VOLKSWAGEN", "TIGUAN", "J"),
    ("VOLKSWAGEN", "TOURAN", "M"),
    ("VOLKSWAGEN", "UP!", "A"),

    ("VOLVO", "V40", "C"),
    ("VOLVO", "V50", "C"),
    ("VOLVO", "V60", "D"),
    ("VOLVO", "V70", "D"),
    ("VOLVO", "V90", "E"),
    ("VOLVO", "XC40", "J"),
    ("VOLVO", "XC60", "J"),
    ("VOLVO", "XC90", "J"),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dmr_make", "dmr_model", "segment"])
        w.writerows(ROWS)
    print(f"wrote {len(ROWS)} rows to {OUT}")
    seen = set((make, model) for make, model, _ in ROWS)
    if len(seen) != len(ROWS):
        print("WARNING: duplicate (dmr_make, dmr_model) rows in ROWS")
    from collections import Counter
    counts = Counter(seg for _, _, seg in ROWS)
    print("segment counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
