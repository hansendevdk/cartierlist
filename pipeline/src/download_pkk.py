"""Fetch Norway's periodic vehicle inspection data (PKK / EU-kontroll),
published by Statens vegvesen as quarterly CSV zips, licence CC BY 4.0.

Source repo: https://github.com/vegvesen/periodisk-kjoretoy-kontroll
Raw files served from the repo's `master` branch via raw.githubusercontent.com.

Twelve files, 2023 through 2025. The filename CASE changes between years --
verified directly, not assumed: 2023 and 2024 files are `PKK-<year>-kvartal<n>.zip`
(capital PKK), 2025 files are `pkk-2025-kvartal<n>.zip` (lowercase pkk). This
mirrors download_dvsa.py's own per-year naming table rather than templating a
single pattern that would 404 on half the years.

Mirrors download_dvsa.py's caching behaviour: skip files already on disk,
download to a `.part` file and rename only on success, so a killed download
never leaves a file that looks complete but isn't.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/vegvesen/periodisk-kjoretoy-kontroll/master"

FILES = {
    # 2023 -- capital PKK
    "PKK-2023-kvartal1.zip": f"{BASE}/PKK-2023-kvartal1.zip",
    "PKK-2023-kvartal2.zip": f"{BASE}/PKK-2023-kvartal2.zip",
    "PKK-2023-kvartal3.zip": f"{BASE}/PKK-2023-kvartal3.zip",
    "PKK-2023-kvartal4.zip": f"{BASE}/PKK-2023-kvartal4.zip",
    # 2024 -- capital PKK
    "PKK-2024-kvartal1.zip": f"{BASE}/PKK-2024-kvartal1.zip",
    "PKK-2024-kvartal2.zip": f"{BASE}/PKK-2024-kvartal2.zip",
    "PKK-2024-kvartal3.zip": f"{BASE}/PKK-2024-kvartal3.zip",
    "PKK-2024-kvartal4.zip": f"{BASE}/PKK-2024-kvartal4.zip",
    # 2025 -- lowercase pkk
    "pkk-2025-kvartal1.zip": f"{BASE}/pkk-2025-kvartal1.zip",
    "pkk-2025-kvartal2.zip": f"{BASE}/pkk-2025-kvartal2.zip",
    "pkk-2025-kvartal3.zip": f"{BASE}/pkk-2025-kvartal3.zip",
    "pkk-2025-kvartal4.zip": f"{BASE}/pkk-2025-kvartal4.zip",
}

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "pkk"


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cartierlist-pipeline/0.1"})
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as fh:
        total = resp.getheader("Content-Length")
        total = int(total) if total else None
        written = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            written += len(chunk)
            if total:
                print(f"\r  {written * 100 // total}% ({written}/{total} bytes)", end="", flush=True)
    part.rename(dest)
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
