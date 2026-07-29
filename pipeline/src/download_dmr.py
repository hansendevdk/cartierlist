"""Fetch the latest DMR statistics extract from the FTP drop and cache it locally.

The FTP host has no uptime guarantee and the brief asks us not to re-fetch on
every run, so we skip the download entirely if the target file already exists.
"""

from __future__ import annotations

import ftplib
import sys
from pathlib import Path

FTP_HOST = "5.44.137.84"
FTP_USER = "dmr-ftp-user"
FTP_PASS = "dmrpassword"
REMOTE_DIR = "ESStatistikListeModtag"

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "dmr"


def latest_remote_file(ftp: ftplib.FTP) -> str:
    names = ftp.nlst(REMOTE_DIR)
    # names come back as "ESStatistikListeModtag/ESStatistikListeModtag-<timestamp>.zip"
    candidates = [n for n in names if n.rsplit("/", 1)[-1].startswith("ESStatistikListeModtag-")]
    if not candidates:
        raise RuntimeError(f"no ESStatistikListeModtag-*.zip files found in {REMOTE_DIR}")
    # the timestamp in the filename sorts lexicographically, so max() picks the newest
    return max(candidates, key=lambda n: n.rsplit("/", 1)[-1])


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    with ftplib.FTP(FTP_HOST) as ftp:
        ftp.login(FTP_USER, FTP_PASS)
        remote_path = latest_remote_file(ftp)
        filename = remote_path.rsplit("/", 1)[-1]
        local_path = RAW_DIR / filename

        if local_path.exists():
            print(f"already cached: {local_path}")
            return

        print(f"downloading {remote_path} -> {local_path}")
        size = ftp.size(remote_path)
        written = 0

        def progress(chunk: bytes) -> None:
            nonlocal written
            written += len(chunk)
            fh.write(chunk)
            if size:
                pct = written * 100 // size
                print(f"\r{pct}% ({written}/{size} bytes)", end="", flush=True)

        tmp_path = local_path.with_suffix(".zip.part")
        with open(tmp_path, "wb") as fh:
            ftp.retrbinary(f"RETR {remote_path}", progress)
        print()
        tmp_path.rename(local_path)
        print(f"done: {local_path}")


if __name__ == "__main__":
    sys.exit(main())
