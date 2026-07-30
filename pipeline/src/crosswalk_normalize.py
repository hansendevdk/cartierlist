"""Shared normalization + classification rules for the Phase 2 crosswalk.

These are hand-authored rules with a stated reason each (per the strategy doc),
not a learned or generic fuzzy-matching setup. The key idea: some model tokens
are "code-like" (short alphanumeric strings such as "320", "208", "2008", "X5",
"C") where a one-character difference means a completely different car, and for
those, only exact equality is ever proposed as a candidate -- similarity scoring
is not applied to them at all, because on strings this short it actively picks
the wrong answer (verified: "C-Klasse" scores higher against "CLA"/"CLK"/"CLS"
than against the correct target "C", because length-ratio dominates).
"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")
_FAMILY_SERIES_RE = re.compile(r"^(\d)(ER|SERIE)")
_SHORT_CODE_RE = re.compile(r"^[A-Z]?\d{1,4}[A-Z]{0,2}$")
_LEADING_CODE_RE = re.compile(r"^([A-Z]?\d{1,4})")


def strip_diacritics(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize(s: str) -> str:
    """Uppercase, strip diacritics, collapse whitespace/hyphens/quotes to single
    spaces. Used before any comparison, on both DMR and DVSA strings."""
    s = strip_diacritics(s).upper()
    s = s.replace("`", "'")
    s = re.sub(r"[\-']", " ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def strip_ny_prefix(s: str) -> str:
    """DMR carries the Danish word for "new" as a model-name prefix, e.g. 'Ny
    Clio' (26,976 vehicles -- Denmark's 14th largest model). Strip it before
    any comparison; DVSA has no equivalent convention."""
    if s.startswith("NY "):
        return s[3:].strip()
    return s


def strip_klasse_suffix(s: str) -> str | None:
    """'C-Klasse' -> 'C'. Returns None if the pattern doesn't apply. DVSA's own
    convention for these is the bare letter (verified: DVSA Mercedes-Benz model
    'C' has 854,856 tests), not '-CLASS'."""
    m = re.match(r"^([A-Z]) KLASSE$", s)
    return m.group(1) if m else None


def family_series_digit(s: str) -> str | None:
    """Detects BMW-style family notation: '3-Serie', '3 SERIE', '3'ER',
    '3'ER-SERIE', '1'ER REIHE', '5`ER TOURING', etc. all collapse to family
    digit '3', '1', '5'. Returns None for specific numbered models like
    '320 D' or '520D', which must NOT match this (verified against all
    observed BMW model_name values in Phase 1 data)."""
    compact = _NON_ALNUM_RE.sub("", s)
    m = _FAMILY_SERIES_RE.match(compact)
    return m.group(1) if m else None


def is_code_like(token: str) -> bool:
    """True for short alphanumeric strings where a single-character difference
    means a different car: '320', '520D', '118I', 'X5', '208', '2008', or a
    bare single letter like 'C' (Mercedes class). These never get fuzzy-scored
    -- only exact equality proposes a candidate (hard rule R1 in the strategy
    doc).

    The alpha branch is deliberately restricted to exactly one letter, not two:
    a first cut allowed two-letter words and it silently caught the Danish
    prefix "NY" (as in "Ny Clio") as if it were a model code like "DS", which
    routed those models into the exact-code path and made them permanently
    unmatchable -- verified by 'Ny Clio' and 'Ny Focus' both showing up as
    no-candidate. No real single-model bare-letter code longer than one letter
    has been observed in this data, so there's nothing to lose."""
    t = token.strip()
    if not t:
        return False
    if len(t) == 1 and t.isalpha():
        return True
    return bool(_SHORT_CODE_RE.fullmatch(t))


def leading_code(s: str) -> str | None:
    """Extracts the leading alphanumeric code from a token, dropping trailing
    trim letters: '520D' -> '520', '118I' -> '118', 'X5' -> 'X5', '320' ->
    '320'. Applied to the first whitespace-separated word of a normalized
    string so it works whether the source wrote '320 D' or '520D'.

    Also handles a bare single letter with no digit at all ('C'), since
    Mercedes' bare-letter model names ('C', 'E', 'A', 'B') would otherwise
    never be extractable -- the digit-requiring regex alone would silently
    fail to find DVSA's own 'C' model, breaking the '-Klasse' exact match
    entirely. Deliberately not extended to two letters -- see is_code_like's
    docstring for why that caught "NY" as a false code."""
    first_word = s.split(" ", 1)[0]
    if len(first_word) == 1 and first_word.isalpha():
        return first_word
    m = _LEADING_CODE_RE.match(first_word)
    return m.group(1) if m else None


def first_token(s: str) -> str:
    """Collapses DVSA trim tails to the model token: 'CORSA ELITE NAV PREMIUM
    TURBO' -> 'CORSA'. A candidate generator, not a decision rule -- known to
    over-collapse in some cases (e.g. 'GRAND C4 PICASSO' -> 'GRAND'), which is
    fine since nothing here auto-accepts."""
    return s.split(" ", 1)[0]
