"""Fetches current Danish petrol/diesel pump prices and writes
reference/fuel_prices.csv, per the brief's "fetch once per build, cache"
instruction.

fuelprices.dk (the brief's named primary source) is dead: connection failure
on the bare domain, and /api returns 404 (checked 2026-07-30). This uses the
brief's own named fallback instead -- Circle K -- via a real public API found
in a linked PDF on circlek.dk/priser ("DK Fuel Prices API doc"), not a
scrape: `GET https://api.circlek.com/eu/prices/v1/fuel/countries/DK`, header
`X-App-Name: PRICES`. No key required, CORS-open, returns every DK station's
live prices. Confirmed live 2026-07-31 (403 stations).

Circle K sells several petrol/diesel grades per station under a "miles" /
"miles+" / plain-brand naming split (loyalty-tier pricing, not different
fuel). Only the BASE grades are used -- miles+ / "PLUS" / "UPGRADE" variants
are premium fuel, out of scope for a standard-car cost model:
  petrol base grades: Blyfri 95, Benzin 95, miles 95, MILES 95
  diesel base grades: Diesel, miles diesel, MILES DIESEL

Reports the median price across all stations, not the mean, since a handful
of remote/airport stations price well above the national norm and would pull
a mean upward for no reason relevant to an ownership-cost model.

If the live fetch fails for any reason, falls back to the constant below --
itself a real median pulled from this same API on the date noted, not a
guess. Either way the output CSV records which source was actually used, so
the site can say so.
"""

from __future__ import annotations

import csv
import gzip
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median

OUT = Path(__file__).resolve().parents[1] / "reference" / "fuel_prices.csv"

API_URL = "https://api.circlek.com/eu/prices/v1/fuel/countries/DK"
API_HEADERS = {"X-App-Name": "PRICES"}

PETROL_BASE_GRADES = {"Blyfri 95", "Benzin 95", "miles 95", "MILES 95"}
DIESEL_BASE_GRADES = {"Diesel", "miles diesel", "MILES DIESEL"}

# Fallback constants: median of the same API's base grades, fetched
# 2026-07-31 (403 stations). Used only if the live fetch fails at build time.
FALLBACK = {
    "Benzin": {"price_dkk_per_litre": 16.69, "station_count": 405},
    "Diesel": {"price_dkk_per_litre": 17.49, "station_count": 399},
}
FALLBACK_DATE = "2026-07-31"


def fetch_live() -> dict[str, dict] | None:
    req = urllib.request.Request(API_URL, headers=API_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            # server sends gzip regardless of Accept-Encoding; urllib doesn't
            # auto-decompress the way browsers/curl --compressed do.
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"live fetch failed: {e}")
        return None

    petrol_prices, diesel_prices = [], []
    for site in data.get("sites", []):
        for fp in site.get("fuelPrices", []):
            name = fp.get("displayName")
            price = fp.get("price")
            if price is None:
                continue
            if name in PETROL_BASE_GRADES:
                petrol_prices.append(price)
            elif name in DIESEL_BASE_GRADES:
                diesel_prices.append(price)

    if not petrol_prices or not diesel_prices:
        print(f"live fetch returned no usable prices (petrol={len(petrol_prices)}, diesel={len(diesel_prices)})")
        return None

    return {
        "Benzin": {"price_dkk_per_litre": round(median(petrol_prices), 2), "station_count": len(petrol_prices)},
        "Diesel": {"price_dkk_per_litre": round(median(diesel_prices), 2), "station_count": len(diesel_prices)},
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    fetched_at = datetime.now(timezone.utc).isoformat()

    live = fetch_live()
    if live is not None:
        source = "circlek_live_api"
        prices = live
        print(f"live fetch OK: petrol {prices['Benzin']['price_dkk_per_litre']} DKK/l "
              f"({prices['Benzin']['station_count']} stations), "
              f"diesel {prices['Diesel']['price_dkk_per_litre']} DKK/l "
              f"({prices['Diesel']['station_count']} stations)")
    else:
        source = f"fallback_constant_verified_{FALLBACK_DATE}"
        prices = FALLBACK
        print("using committed fallback constant (live fetch unavailable)")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fuel_type", "price_dkk_per_litre", "station_count", "source", "fetch_date_utc", "build_date"])
        for fuel, vals in prices.items():
            w.writerow([fuel, vals["price_dkk_per_litre"], vals["station_count"], source, fetched_at, today])

    print(f"wrote {OUT} (source={source})")


if __name__ == "__main__":
    main()
