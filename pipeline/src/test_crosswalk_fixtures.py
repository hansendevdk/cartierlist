"""Regression fixtures for the crosswalk normalization/classification rules (R3
in phase2_crosswalk_strategy.md). These are the known collision cases found by
direct data inspection before writing any matching code -- a change that breaks
any of these has broken the crosswalk, not just failed a style check.

Run directly: uv run python src/test_crosswalk_fixtures.py
"""

from __future__ import annotations

import sys

from crosswalk_normalize import (
    family_series_digit,
    is_code_like,
    leading_code,
    normalize,
    strip_klasse_suffix,
    strip_ny_prefix,
)

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


# --- R1: numeric/code tokens must never be treated as fuzzy-equivalent ---
# 208 vs 2008 (Peugeot supermini vs crossover -- one digit apart, different cars)
check("is_code_like(208)", is_code_like("208"), True)
check("is_code_like(2008)", is_code_like("2008"), True)
check("leading_code 208 != leading_code 2008", leading_code("208") != leading_code("2008"), True)

# 308 vs 3008, 508 vs 5008
check("leading_code(308)", leading_code("308"), "308")
check("leading_code(3008)", leading_code("3008"), "3008")
check("leading_code(508)", leading_code("508"), "508")
check("leading_code(5008)", leading_code("5008"), "5008")

# BMW 316/318/320/330 must all extract to distinct codes
codes = {leading_code(normalize(m)) for m in ["316", "318", "320", "330", "320 D", "330E"]}
check("BMW 3-series codes all present and distinct", {"316", "318", "320", "330"} <= codes, True)
check("320 and 320D collapse to same code (trim suffix stripped)", leading_code(normalize("320 D")), "320")

# --- Mercedes: 'C' must not be reachable via fuzzy scoring against CLA/CLK/CLS ---
check("strip_klasse_suffix('C-Klasse' normalized)", strip_klasse_suffix(normalize("C-Klasse")), "C")
check("strip_klasse_suffix('A-Klasse' normalized)", strip_klasse_suffix(normalize("A-Klasse")), "A")
check("leading_code('C') bare letter", leading_code("C"), "C")
check("is_code_like('C')", is_code_like("C"), True)
check("is_code_like('CLA')", is_code_like("CLA"), False)  # CLA must NOT be treated as a bare code
check("strip_klasse_suffix('CLA') is None (not a Klasse form)", strip_klasse_suffix("CLA"), None)

# --- BMW family-series detection: must catch all observed DMR spellings ---
family_forms = [
    "3-Serie", "1-Serie", "5-Serie", "4-serie", "2-Serie",
    "5 SERIE", "3 SERIE", "1 SERIE",
    "3'ER", "3'ER-SERIE", "1'ER REIHE", "5`ER", "5`ER TOURING",
    "3`ER CABRIO", "3`ER TOURING",
]
for form in family_forms:
    digit = family_series_digit(normalize(form))
    check(f"family_series_digit({form!r})", digit is not None, True)

check("family_series_digit('3-Serie') == 3", family_series_digit(normalize("3-Serie")), "3")
check("family_series_digit('5`ER TOURING') == 5", family_series_digit(normalize("5`ER TOURING")), "5")

# specific numbered models must NOT be classified as family series
specific_forms = ["320 D", "520D", "118i", "X5 xDrive45e", "X5", "X1", "i3", "530e"]
for form in specific_forms:
    digit = family_series_digit(normalize(form))
    check(f"family_series_digit({form!r}) is None (specific model, not family)", digit, None)

# --- Danish 'Ny' prefix ---
check("strip_ny_prefix('NY CLIO')", strip_ny_prefix("NY CLIO"), "CLIO")
check("strip_ny_prefix('CLIO') unchanged", strip_ny_prefix("CLIO"), "CLIO")

# --- diacritics ---
check("normalize('CITROËN')", normalize("CITROËN"), "CITROEN")

# --- ASTRA vs ASTRAVAN must not collide (van, not a car variant) ---
check("ASTRA != ASTRAVAN as strings", normalize("ASTRA") != normalize("ASTRAVAN"), True)
check("is_code_like('ASTRA') False (name path, not code path)", is_code_like("ASTRA"), False)
check("is_code_like('ASTRAVAN') False", is_code_like("ASTRAVAN"), False)

# --- X-series letter+digit codes ---
check("is_code_like('X5')", is_code_like("X5"), True)
check("is_code_like('X1')", is_code_like("X1"), True)
check("leading_code('X5') != leading_code('X1')", leading_code("X5") != leading_code("X1"), True)

if failures:
    print(f"{len(failures)} FIXTURE FAILURES:")
    for f in failures:
        print(f"  FAIL: {f}")
    sys.exit(1)
else:
    print(f"all fixtures passed ({33} checks)")
