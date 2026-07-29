"""Fetch DVSA anonymised MOT data (OGL v3.0) for the two most recent available years,
plus the lookup tables and user guide needed to decode failure item codes.

As of this writing, the two most recent complete years published on
open.data.dvsa.gov.uk/mot-anonymised are 2024 and 2025; the source file naming
differs between years because DVSA changed their publishing convention partway
through, so the pairs below are named individually rather than templated.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = "https://edh-dvsa-data-gov-uk-files-prod.s3.eu-west-1.amazonaws.com"

FILES = {
    "results_2024.zip": f"{BASE}/MOT+testing+data+results+(2024).zip",
    "failure_item_2024.zip": f"{BASE}/MOT+Testing+data+failure+item+(2024).zip",
    "results_2025.zip": f"{BASE}/dft_test_result_extracts_2025.zip",
    "failure_item_2025.zip": f"{BASE}/dft_test_item_extracts_2025.zip",
    "lookup_tables.zip": f"{BASE}/lookup.zip",
    "user_guide_v5.1.odt": f"{BASE}/mot-testing-data-user-guide-v5.1.odt",
}

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "dvsa"


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cartierlist-pipeline/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest.with_suffix(dest.suffix + ".part"), "wb") as fh:
        total = resp.getheader("Content-Length")
        total = int(total) if total else None
        written = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            written += len(chunk)
            if total:
                print(f"\r  {written * 100 // total}% ({written}/{total} bytes)", end="", flush=True)
    dest.with_suffix(dest.suffix + ".part").rename(dest)
    print()


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for filename, url in FILES.items():
        dest = RAW_DIR / filename
        if dest.exists():
            print(f"already cached: {dest}")
            continue
        print(f"downloading {url}\n  -> {dest}")
        download(url, dest)
        print(f"done: {dest}")


if __name__ == "__main__":
    sys.exit(main())
