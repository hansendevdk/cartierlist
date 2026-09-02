"""One-time backfill scraper for reference/calibration_prices.csv.

Fills in real Danish asking-price anchors for the (make, model, age_band)
cells that are currently priced from a brand-pooled correction rather than
their own evidence (price_pooled_at_brand == "True" in
model_bracket_rankings.csv, restricted to rows that are actually ranked,
excluded_from_rank == "False"). Once 3+ real anchors exist for a cell,
calibrate_price_estimates.py's own-cell mechanism takes over for it
automatically -- this script's only job is to go find those anchors and
append them to calibration_prices.csv in its existing schema. It does not
touch the calibration/ranking logic itself.

SOURCES
DBA (dba.dk) is primary: plain HTTP fetch + lxml.html, no browser needed.
Its robots.txt permits the general search paths this script uses (verified
live, see reports/price_calibration_scrape.md).

Bilbasen (bilbasen.dk) is secondary and lower-volume: Playwright navigates
the real, server-rendered search page (never /api/, which robots.txt
disallows, and never a query-string search URL beyond the rendered-page
pattern this script already uses, for the same reason) and reads the
server-embedded __NEXT_DATA__ payload, exactly like the sibling BestDeals
project's TypeScript adapter does. The first navigation to a Bilbasen search
URL usually comes back as an AWS WAF interstitial (HTTP 202) that a real
browser clears on its own; this script re-navigates once when that happens,
matching what was observed live. If a REAL CAPTCHA/Turnstile challenge shows
up instead (visible human-verification text), BilbasenChallengeError is
raised and the whole run stops -- this script never attempts to solve one.

SCOPE NOTE -- Suzuki and DS excluded on purpose, not by omission.
Of the 23 models whose bracket rankings are currently brand-pooled, five
(SUZUKI Baleno/Celerio/Ignis/Swift, DS "DS 3") do not go through
price_estimates.csv / calibrate_price_estimates.py at all -- they're priced
entirely by build_suzuki_ds_prices.py from reference/suzuki_ds_price_anchors.csv
(a different schema: real_price_dkk, not real_asking_price_dkk), donor-curve
shape plus a hand-collected Danish level, with price_pooled_at_brand and
price_confidence hardcoded to always read "low" for every row that script
produces -- there is no own-cell upgrade path for them at all. A row added
here for one of those five makes would never be read by anything (its key
never appears in price_estimates.csv), yet would still get pooled into this
script's own group_results and skew the global/split fallback ratio used by
every OTHER pooled model. So they're excluded here structurally, not
guessed around; real Danish anchors for them belong in
suzuki_ds_price_anchors.csv instead, a separate and explicitly out-of-scope
piece of work.

Also naturally out of scope: MAZDA Mazda CX-30 (both its pooled bands are
excluded_from_rank) and TOYOTA Toyota C-HR (same) -- both are still
brand-pooled, but neither currently has a rankable band, so there is nothing
to backfill for them today. This is verified against the live CSV each run,
not hardcoded, so if that ever changes a future run picks them up.

RESUMABILITY
Every (make, model, age_band) cell this script decides to attempt gets
recorded in RAW_DIR/scrape_state.json, whether it found 5 anchors, 1, or 0
-- the point is not to re-query the same cell on a later run, since a
second identical search burns budget for no new information. The per-run
request cap is what actually determines how much of the 37-cell backlog one
run clears; a run that stops partway through because it hit the cap is
success, not failure -- rerun this script later to keep going.
"""

from __future__ import annotations

import csv
import json
import random
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
REFERENCE = PIPELINE / "reference"
RANKINGS_CSV = REFERENCE / "model_bracket_rankings.csv"
PRICE_ESTIMATES_CSV = REFERENCE / "price_estimates.csv"
CALIBRATION_CSV = REFERENCE / "calibration_prices.csv"
RAW_DIR = PIPELINE / "data" / "raw" / "dba_bilbasen"
STATE_FILE = RAW_DIR / "scrape_state.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DELAY_MIN_S, DELAY_MAX_S = 1.0, 2.0

# Per-run request caps. DBA needs roughly one request per (model, band) cell
# (results come back as a full page of listings, so one search is normally
# enough to find several usable anchors) -- 37 target cells, so 45 covers
# every cell once plus a handful of second pages for thin ones, comfortably
# inside the requested 30-60 range. Bilbasen is secondary and only used to
# top up cells DBA came up short on, and each request costs a real browser
# navigation (WAF-clear round trip included) rather than a plain fetch, so
# it is given a smaller share of the same range: enough to matter, not so
# much that a lower-volume secondary source dominates the run.
DBA_REQUEST_CAP = 45
BILBASEN_REQUEST_CAP = 25

BAND_YEARS = {"1": (2020, 2022), "2": (2017, 2019), "3": (2014, 2016), "4": (2010, 2013)}

TARGET_PER_CELL = 5
MIN_USEFUL_PER_CELL = 3

# Absolute sanity bounds on a parsed asking price, not relative to our own
# pre-calibration estimate: several of the very cells this script targets
# have a badly-wrong our_estimate_dkk PRECISELY BECAUSE they're brand-pooled
# (e.g. a supermini inheriting a premium model's price curve), so bounding
# "plausible" against that number would reject the real listings this
# script exists to find. A wide, absolute used-car price band plus the
# keyword/body-style checks below catch parse errors and wrong-model
# contamination without leaning on the number under test.
MIN_PLAUSIBLE_PRICE_DKK = 8_000
MAX_PLAUSIBLE_PRICE_DKK = 1_500_000

STRUCTURALLY_EXCLUDED_MAKES = {"SUZUKI", "DS"}

SPEC_SEPARATOR = "∙"  # U+2219 BULLET OPERATOR, DBA's own field separator


def ascii_fold(text: str) -> str:
    """Lowercase and strip diacritics, so 'Citroën' / 'Citroen' / 'CITROËN'
    all compare equal without hardcoding every accented spelling variant."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


@dataclass
class ModelSearchDef:
    dba_query: str
    bilbasen_query: str
    make_tokens: tuple[str, ...]
    require_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()


# Search terms are the plain Danish-market names a seller would actually
# type (matching the style calibration_prices.csv's existing hand-collected
# rows already use, e.g. "vw up" for VOLKSWAGEN UP!), not the raw DMR
# strings -- DMR's "Punto S7" or "206 +" are internal generation codes, not
# search terms; the year-band filter does the generation disambiguation
# instead of guessing a code a seller wouldn't type. require/exclude
# keywords catch the specific body-style or trim collisions each model is
# actually prone to (checked against the DBA title+variant text or the
# Bilbasen structured make/model/variant fields, ascii-folded).
MODEL_DEFS: dict[tuple[str, str], ModelSearchDef] = {
    ("AUDI", "A1 SPORTBACK"): ModelSearchDef(
        "audi a1", "audi a1", ("audi",), require_keywords=("sportback",), exclude_keywords=("s1",)),
    ("AUDI", "A5 SPORTBACK"): ModelSearchDef(
        "audi a5", "audi a5", ("audi",), require_keywords=("sportback",), exclude_keywords=("s5", "rs5")),
    ("AUDI", "Q2"): ModelSearchDef(
        "audi q2", "audi q2", ("audi",), exclude_keywords=("sq2",)),
    ("AUDI", "Q3"): ModelSearchDef(
        "audi q3", "audi q3", ("audi",), exclude_keywords=("sq3", "rsq3", "rs q3")),
    ("CHEVROLET", "SPARK"): ModelSearchDef(
        "chevrolet spark", "chevrolet spark", ("chevrolet",)),
    ("CITROËN", "C1"): ModelSearchDef(
        "citroen c1", "citroen c1", ("citroen", "citroën")),
    ("CITROËN", "DS3"): ModelSearchDef(
        "citroen ds3", "citroen ds3", ("citroen", "citroën")),
    ("CITROËN", "GRAND C4 PICASSO"): ModelSearchDef(
        "citroen grand c4 picasso", "citroen grand c4 picasso", ("citroen", "citroën"),
        require_keywords=("grand",)),
    ("FIAT", "Punto S7"): ModelSearchDef(
        "fiat punto", "fiat punto", ("fiat",)),
    ("HYUNDAI", "Ioniq"): ModelSearchDef(
        "hyundai ioniq", "hyundai ioniq", ("hyundai",),
        exclude_keywords=("ioniq 5", "ioniq 6", "ioniq5", "ioniq6")),
    ("KIA", "Niro"): ModelSearchDef(
        "kia niro", "kia niro", ("kia",)),
    ("MAZDA", "MAZDA6"): ModelSearchDef(
        "mazda 6", "mazda 6", ("mazda",)),
    ("PEUGEOT", "206 +"): ModelSearchDef(
        "peugeot 206", "peugeot 206", ("peugeot",)),
    ("SKODA", "RAPID"): ModelSearchDef(
        "skoda rapid", "skoda rapid", ("skoda",), exclude_keywords=("spaceback",)),
    ("SKODA", "RAPID SPACEBACK"): ModelSearchDef(
        "skoda rapid spaceback", "skoda rapid spaceback", ("skoda",), require_keywords=("spaceback",)),
}


# ---------------------------------------------------------------------------
# target cell selection -- read live off the current CSVs, never hardcoded
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    make: str
    model: str
    band: str
    our_estimate_dkk: int
    existing_count: int


def load_target_cells() -> list[Cell]:
    with open(RANKINGS_CSV, encoding="utf-8") as f:
        rankings = list(csv.DictReader(f))
    with open(PRICE_ESTIMATES_CSV, encoding="utf-8") as f:
        price_rows = list(csv.DictReader(f))
    price_idx = {(r["dmr_make"], r["dmr_model"], r["age_band"]): r["estimated_value_dkk"] for r in price_rows}

    existing_counts: dict[tuple[str, str, str], int] = {}
    if CALIBRATION_CSV.exists():
        with open(CALIBRATION_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r.get("real_asking_price_dkk", "").strip():
                    continue
                key = (r["dmr_make"], r["dmr_model"], r["age_band"])
                existing_counts[key] = existing_counts.get(key, 0) + 1

    cells: list[Cell] = []
    skipped_structural: list[tuple[str, str, str]] = []
    for r in rankings:
        if r.get("price_pooled_at_brand") != "True":
            continue
        if r.get("excluded_from_rank") != "False":
            continue
        make, model, band = r["dmr_make"], r["dmr_model"], r["age_band"]
        if make in STRUCTURALLY_EXCLUDED_MAKES:
            skipped_structural.append((make, model, band))
            continue
        key = (make, model, band)
        our_est = price_idx.get(key)
        if our_est is None:
            # Shouldn't happen for a non-Suzuki/DS pooled row, but stay
            # honest rather than guessing a value if the CSVs ever drift.
            print(f"  SKIP {make} {model} band{band}: no row in price_estimates.csv, cannot set our_estimate_dkk")
            continue
        cells.append(Cell(make, model, band, int(our_est), existing_counts.get(key, 0)))

    if skipped_structural:
        print(f"{len(skipped_structural)} cell(s) structurally out of scope (Suzuki/DS pricing "
              f"pipeline has no own-cell mechanism -- see module docstring), not attempted:")
        for m, mo, b in skipped_structural:
            print(f"  {m} {mo} band{b}")

    return cells


# ---------------------------------------------------------------------------
# DBA adapter -- plain fetch + lxml, ported from BestDeals' dba.ts
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    source: str
    price_dkk: int
    mileage_km: int | None
    year: int | None
    match_text: str
    url: str


def sleep_politely() -> None:
    time.sleep(random.uniform(DELAY_MIN_S, DELAY_MAX_S))


def fetch_url(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "da-DK,da;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < 3:
                time.sleep(0.5 * attempt)
    raise RuntimeError(f"DBA request failed for {url} after 3 attempts: {last_err}")


def parse_dba_price(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_dba_search(html_text: str) -> list[dict]:
    from lxml import html as lxml_html

    doc = lxml_html.fromstring(html_text)
    articles = doc.xpath('//article[contains(@class,"sf-search-ad")]')
    out = []
    for art in articles:
        title_nodes = art.xpath(".//h2")
        title = title_nodes[0].text_content().strip() if title_nodes else ""

        variant_nodes = art.xpath(
            './/div[contains(@class,"text-caption") and contains(@class,"mb-4") and contains(@class,"s-text-subtle")]'
        )
        variant = variant_nodes[0].text_content().strip() if variant_nodes else ""

        spec_nodes = art.xpath(
            './/span[contains(@class,"text-caption") and contains(@class,"font-bold") '
            'and contains(@class,"inline-block") and contains(@class,"mb-8")]'
        )
        spec_text = spec_nodes[0].text_content().strip() if spec_nodes else ""

        year = None
        mileage_km = None
        for part in spec_text.split(SPEC_SEPARATOR):
            part = part.strip()
            if re.fullmatch(r"\d{4}", part):
                year = int(part)
            else:
                km_match = re.match(r"^([\d.]+)\s*km$", part, re.IGNORECASE)
                if km_match:
                    mileage_km = int(km_match.group(1).replace(".", ""))

        price_nodes = art.xpath('.//span[contains(@class,"t3") and contains(@class,"font-bold")]')
        price_text = price_nodes[0].text_content().strip() if price_nodes else ""
        price_dkk = parse_dba_price(price_text)

        price_container_text = ""
        if price_nodes:
            parent = price_nodes[0].getparent()
            if parent is not None:
                price_container_text = re.sub(r"\s+", " ", parent.text_content()).strip()
        excludes_vat = bool(re.search(r"ekskl\.?\s*moms", price_container_text, re.IGNORECASE))
        is_leasing = bool(re.search(r"kr\.?\s*/\s*md|md\.$", price_container_text, re.IGNORECASE))

        link_nodes = art.xpath('.//a[contains(@class,"sf-search-ad-link")]')
        href = link_nodes[0].get("href") if link_nodes else None
        url = href if (href and href.startswith("http")) else f"https://www.dba.dk{href or ''}"

        out.append({
            "title": title,
            "variant": variant,
            "year": year,
            "mileage_km": mileage_km,
            "price_dkk": price_dkk,
            "excludes_vat": excludes_vat,
            "is_leasing": is_leasing,
            "url": url,
        })
    return out


def dba_search(model_def: ModelSearchDef, year_from: int, year_to: int, budget: "Budget") -> list[Listing]:
    q = urllib.parse.quote(model_def.dba_query)
    url = f"https://www.dba.dk/mobility/search/car?q={q}&year_from={year_from}&year_to={year_to}"
    sleep_politely()
    html_text = fetch_url(url)
    budget.dba_used += 1
    (RAW_DIR / f"dba_{safe_name(model_def.dba_query)}_{year_from}_{year_to}.html").write_text(
        html_text, encoding="utf-8"
    )
    raw = parse_dba_search(html_text)
    out = []
    for r in raw:
        if r["price_dkk"] is None or r["excludes_vat"] or r["is_leasing"]:
            continue
        match_text = ascii_fold(f"{r['title']} {r['variant']}")
        out.append(Listing(
            source="dba.dk", price_dkk=r["price_dkk"], mileage_km=r["mileage_km"],
            year=r["year"], match_text=match_text, url=r["url"],
        ))
    return out


# ---------------------------------------------------------------------------
# Bilbasen adapter -- Playwright, rendered page only, reads __NEXT_DATA__
# ---------------------------------------------------------------------------

class BilbasenChallengeError(Exception):
    """Raised when Bilbasen shows a real, unsolvable CAPTCHA/Turnstile --
    not the silent AWS WAF interstitial a real browser clears on its own.
    The scrape must stop, not attempt to work around it."""


def assert_no_visible_challenge(page) -> None:
    try:
        body_text = page.evaluate("() => document.body.innerText")
    except Exception:
        body_text = ""
    if re.search(r"verify you are human|are you human|captcha|complete the security check", body_text, re.IGNORECASE):
        raise BilbasenChallengeError(
            "Bilbasen presented a visible human-verification challenge (CAPTCHA/Turnstile). "
            "Refusing to attempt to solve it; stopping the scrape."
        )


def bilbasen_search(page, model_def: ModelSearchDef, year_from: int, year_to: int, budget: "Budget") -> list[Listing]:
    free = urllib.parse.quote(model_def.bilbasen_query)
    url = (
        f"https://www.bilbasen.dk/brugt/bil?free={free}&pricetype=Retail"
        f"&yearfrom={year_from}&yearto={year_to}"
    )

    sleep_politely()
    resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    budget.bilbasen_used += 1
    assert_no_visible_challenge(page)

    data = _read_bilbasen_next_data(page)
    if data is None:
        # Likely still on the WAF interstitial -- re-navigate once, matching
        # what was observed live (first GET 202, second GET 200 with data).
        sleep_politely()
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        budget.bilbasen_used += 1
        assert_no_visible_challenge(page)
        data = _read_bilbasen_next_data(page)

    if data is None:
        status = resp.status if resp else "(no response)"
        raise RuntimeError(f"Bilbasen: could not read __NEXT_DATA__ for {url} (last HTTP status {status})")

    listings_raw = data.get("listings") or []
    (RAW_DIR / f"bilbasen_{safe_name(model_def.bilbasen_query)}_{year_from}_{year_to}.json").write_text(
        json.dumps(data, ensure_ascii=False)[:2_000_000], encoding="utf-8"
    )

    out = []
    for raw in listings_raw:
        price = (raw.get("price") or {}).get("price")
        price_type = (raw.get("price") or {}).get("priceType")
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        if price_type not in (None, "Retail"):
            continue
        props = raw.get("properties") or {}
        mileage_text = ((props.get("mileage") or {}).get("displayTextLong"))
        mileage_km = None
        if isinstance(mileage_text, str):
            digits = re.sub(r"[^\d]", "", mileage_text)
            mileage_km = int(digits) if digits else None
        reg_text = ((props.get("firstregistrationdate") or {}).get("displayTextLong"))
        year = None
        if isinstance(reg_text, str):
            m = re.match(r"^\d{1,2}/(\d{4})$", reg_text.strip())
            if m:
                year = int(m.group(1))
        match_text = ascii_fold(
            f"{raw.get('make', '')} {raw.get('model', '')} {raw.get('variant', '')}"
        )
        url_ = raw.get("uri") or ""
        out.append(Listing(
            source="bilbasen.dk", price_dkk=int(price), mileage_km=mileage_km,
            year=year, match_text=match_text, url=url_,
        ))
    return out


def _read_bilbasen_next_data(page) -> dict | None:
    try:
        page.wait_for_selector("#__NEXT_DATA__", timeout=12000, state="attached")
    except Exception:
        return None
    text = page.locator("#__NEXT_DATA__").text_content()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    queries = (((parsed.get("props") or {}).get("pageProps") or {}).get("dehydratedState") or {}).get("queries")
    if not isinstance(queries, list):
        return None
    for q in queries:
        d = ((q or {}).get("state") or {}).get("data")
        if isinstance(d, dict) and isinstance(d.get("listings"), list):
            return d
    return None


# ---------------------------------------------------------------------------
# shared validation / selection
# ---------------------------------------------------------------------------

def safe_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", ascii_fold(s)).strip("_")


def validate_listing(listing: Listing, model_def: ModelSearchDef, band_years: tuple[int, int]) -> str | None:
    """Returns None if the listing passes every check, else a short reason
    string explaining why it was rejected (logged, not raised)."""
    if listing.price_dkk < MIN_PLAUSIBLE_PRICE_DKK or listing.price_dkk > MAX_PLAUSIBLE_PRICE_DKK:
        return f"price {listing.price_dkk} outside plausible range"
    if listing.mileage_km is None:
        return "no mileage on listing"
    if listing.year is not None and not (band_years[0] <= listing.year <= band_years[1]):
        return f"year {listing.year} outside band {band_years}"
    if not any(tok in listing.match_text for tok in model_def.make_tokens):
        return "make token not found in listing text"
    for kw in model_def.require_keywords:
        if kw not in listing.match_text:
            return f"missing required keyword '{kw}'"
    for kw in model_def.exclude_keywords:
        if kw in listing.match_text:
            return f"excluded keyword '{kw}' present"
    return None


def select_spread(listings: list[Listing], n: int) -> list[Listing]:
    """Picks up to n listings spread across the mileage range rather than
    just the first n, so the mileage-vs-price fit in calibrate_price_estimates.py
    has something to fit against instead of a cluster of near-identical mileages."""
    if len(listings) <= n:
        return listings
    ordered = sorted(listings, key=lambda x: x.mileage_km or 0)
    step = (len(ordered) - 1) / (n - 1) if n > 1 else 0
    picked_idx = sorted({round(i * step) for i in range(n)})
    return [ordered[i] for i in picked_idx]


@dataclass
class Budget:
    dba_used: int = 0
    bilbasen_used: int = 0


# ---------------------------------------------------------------------------
# state file
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cells": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def cell_key(make: str, model: str, band: str) -> str:
    return f"{make}|{model}|{band}"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    budget = Budget()
    today = date.today().isoformat()

    cells = load_target_cells()
    pending = [c for c in cells if cell_key(c.make, c.model, c.band) not in state["cells"]]
    already_done = len(cells) - len(pending)
    print(f"{len(cells)} target cell(s) in scope, {already_done} already attempted in a prior run, "
          f"{len(pending)} pending.\n")

    if not pending:
        print("Nothing pending -- every in-scope cell has already been attempted. "
              "Nothing to do this run.")
        return

    new_rows: list[dict] = []

    # Bilbasen's Playwright context is expensive to spin up -- only do it if
    # we actually reach a cell that needs a top-up, and reuse it after that.
    playwright_ctx = {"pw": None, "browser": None, "page": None}

    def get_bilbasen_page():
        if playwright_ctx["page"] is not None:
            return playwright_ctx["page"]
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="da-DK")
        page = context.new_page()
        playwright_ctx.update(pw=pw, browser=browser, page=page)
        return page

    try:
        for cell in pending:
            if budget.dba_used >= DBA_REQUEST_CAP and budget.bilbasen_used >= BILBASEN_REQUEST_CAP:
                print(f"\nBoth request caps reached (dba={budget.dba_used}/{DBA_REQUEST_CAP}, "
                      f"bilbasen={budget.bilbasen_used}/{BILBASEN_REQUEST_CAP}). Stopping cleanly.")
                break

            model_def = MODEL_DEFS.get((cell.make, cell.model))
            if model_def is None:
                print(f"SKIP {cell.make} {cell.model} band{cell.band}: no search definition -- "
                      f"cannot confidently translate this DMR model string to a search term without "
                      f"guessing. Leaving unattempted (not marked done) for manual follow-up.")
                continue

            band_years = BAND_YEARS[cell.band]

            print(f"\n=== {cell.make} {cell.model} band{cell.band} ({band_years[0]}-{band_years[1]}, "
                  f"our_estimate={cell.our_estimate_dkk:,} DKK, {cell.existing_count} existing anchor(s)) ===")

            collected: list[Listing] = []
            rejected_reasons: dict[str, int] = {}

            if budget.dba_used < DBA_REQUEST_CAP:
                try:
                    dba_listings = dba_search(model_def, band_years[0], band_years[1], budget)
                except Exception as e:
                    print(f"  DBA search failed: {e}")
                    dba_listings = []
                for l in dba_listings:
                    reason = validate_listing(l, model_def, band_years)
                    if reason is None:
                        collected.append(l)
                    else:
                        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                print(f"  dba.dk: {len(dba_listings)} raw result(s), {len(collected)} passed validation "
                      f"(request {budget.dba_used}/{DBA_REQUEST_CAP})")
            else:
                print("  dba.dk: skipped, request cap already reached")

            still_needed = max(0, TARGET_PER_CELL - cell.existing_count - len(collected))
            if still_needed > 0 and budget.bilbasen_used < BILBASEN_REQUEST_CAP:
                try:
                    page = get_bilbasen_page()
                    bb_listings = bilbasen_search(page, model_def, band_years[0], band_years[1], budget)
                except BilbasenChallengeError:
                    raise
                except Exception as e:
                    print(f"  Bilbasen search failed: {e}")
                    bb_listings = []
                bb_passed = []
                for l in bb_listings:
                    reason = validate_listing(l, model_def, band_years)
                    if reason is None:
                        bb_passed.append(l)
                    else:
                        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                collected.extend(bb_passed)
                print(f"  bilbasen.dk: {len(bb_listings)} raw result(s), {len(bb_passed)} passed validation "
                      f"(request {budget.bilbasen_used}/{BILBASEN_REQUEST_CAP})")
            elif still_needed > 0:
                print("  bilbasen.dk: skipped, request cap already reached")

            if rejected_reasons:
                print("  rejected: " + ", ".join(f"{n}x {r}" for r, n in sorted(rejected_reasons.items())))

            chosen = select_spread(collected, min(TARGET_PER_CELL - cell.existing_count, TARGET_PER_CELL))
            total_after = cell.existing_count + len(chosen)

            for l in chosen:
                new_rows.append({
                    "dmr_make": cell.make, "dmr_model": cell.model, "age_band": cell.band,
                    "our_estimate_dkk": cell.our_estimate_dkk,
                    "real_asking_price_dkk": l.price_dkk,
                    "real_mileage_km": l.mileage_km,
                    "source_note": f"{l.source}, {today}",
                })

            if total_after == 0:
                status = "no_supply_found"
                note = "zero valid listings found for this cell's year band"
            elif total_after >= MIN_USEFUL_PER_CELL:
                status = "own_cell_qualified"
                note = f"{total_after} total anchor(s) -- meets the 3+ own-cell threshold"
            else:
                status = "partial_below_threshold"
                note = f"{total_after} total anchor(s) -- below the 3+ own-cell threshold, still feeds the pooled fallback"

            print(f"  -> {status}: added {len(chosen)} new row(s), {total_after} total for this cell")

            state["cells"][cell_key(cell.make, cell.model, cell.band)] = {
                "status": status, "note": note,
                "existing_before": cell.existing_count, "added_this_run": len(chosen),
                "total_after": total_after, "date": today,
            }
            save_state(state)

            if new_rows:
                append_calibration_rows(new_rows)
                new_rows = []

    finally:
        if playwright_ctx["browser"] is not None:
            playwright_ctx["browser"].close()
        if playwright_ctx["pw"] is not None:
            playwright_ctx["pw"].stop()

    print(f"\nRun finished. Requests used: dba={budget.dba_used}/{DBA_REQUEST_CAP}, "
          f"bilbasen={budget.bilbasen_used}/{BILBASEN_REQUEST_CAP}.")
    remaining = [c for c in cells if cell_key(c.make, c.model, c.band) not in state["cells"]]
    if remaining:
        print(f"{len(remaining)} cell(s) still pending for a future run:")
        for c in remaining:
            print(f"  {c.make} {c.model} band{c.band}")
    else:
        print("Every in-scope cell has now been attempted at least once.")


def append_calibration_rows(rows: list[dict]) -> None:
    fieldnames = ["dmr_make", "dmr_model", "age_band", "our_estimate_dkk",
                  "real_asking_price_dkk", "real_mileage_km", "source_note"]
    file_exists = CALIBRATION_CSV.exists()
    # lineterminator="\n": the existing file uses bare LF throughout (no
    # carriage returns); csv.writer's default is \r\n, and mixing the two
    # within one file confused csv-parse on the site side (auto-detected \n
    # as the record delimiter from the bulk of the file, then choked on a
    # stray \r immediately after an appended row's closing quote).
    with open(CALIBRATION_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        if not file_exists:
            w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
