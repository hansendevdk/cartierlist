"""Download the alternate 2024 DVSA publication (dft_*_extracts_2024 naming, matching
the 2025 convention) to compare against the already-downloaded MOT+testing...(2024)
files, which look ~1.57x too large relative to 2025's row count for the same
12-month span -- suggesting we grabbed a superseded/duplicated publication.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = "https://edh-dvsa-data-gov-uk-files-prod.s3.eu-west-1.amazonaws.com"

FILES = {
    "results_2024_alt.zip": f"{BASE}/dft_test_result_extracts_2024.zip",
    "failure_item_2024_alt.zip": f"{BASE}/dft_test_item_extracts_2024.zip",
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
