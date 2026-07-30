"""Fetch the latest DMR statistics extract from the FTP drop and cache it locally.

The FTP host has no uptime guarantee and the brief asks us not to re-fetch on
every run, so we skip the download entirely if the target file already exists.

The connection stalled silently once (socket sat open with no data for 10+
minutes, at 99.9998% complete) rather than erroring, so a timeout and a
resume-on-retry loop are load-bearing here, not defensive dead code.
"""

from __future__ import annotations

import ftplib
import socket
import sys
import time
from pathlib import Path

FTP_HOST = "5.44.137.84"
FTP_USER = "dmr-ftp-user"
FTP_PASS = "dmrpassword"
REMOTE_DIR = "ESStatistikListeModtag"
SOCKET_TIMEOUT_S = 120
MAX_ATTEMPTS = 8

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "dmr"


def connect() -> ftplib.FTP:
    ftp = ftplib.FTP(FTP_HOST, timeout=SOCKET_TIMEOUT_S)
    ftp.login(FTP_USER, FTP_PASS)
    return ftp


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

    ftp = connect()
    remote_path = latest_remote_file(ftp)
    filename = remote_path.rsplit("/", 1)[-1]
    local_path = RAW_DIR / filename

    if local_path.exists():
        print(f"already cached: {local_path}")
        ftp.close()
        return

    size = ftp.size(remote_path)
    tmp_path = local_path.with_suffix(".zip.part")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        resume_at = tmp_path.stat().st_size if tmp_path.exists() else 0
        if resume_at >= size:
            break
        print(f"attempt {attempt}/{MAX_ATTEMPTS}: {remote_path} from byte {resume_at}/{size} -> {tmp_path}")

        written = resume_at

        def progress(chunk: bytes) -> None:
            nonlocal written
            written += len(chunk)
            fh.write(chunk)
            print(f"\r{written * 100 // size}% ({written}/{size} bytes)", end="", flush=True)

        try:
            with open(tmp_path, "ab") as fh:
                ftp.retrbinary(f"RETR {remote_path}", progress, rest=resume_at or None)
            print()
            break
        # ftplib.all_errors is itself a tuple; Python 3.11+ except clauses no
        # longer allow a tuple nested inside another tuple, so flatten it.
        except (socket.timeout, ConnectionError, EOFError, *ftplib.all_errors) as e:
            print(f"\ntransfer stalled/failed ({e!r}); reconnecting to resume")
            try:
                ftp.close()
            except Exception:
                pass
            time.sleep(5)
            ftp = connect()
    else:
        raise RuntimeError(f"gave up after {MAX_ATTEMPTS} attempts, {tmp_path.stat().st_size}/{size} bytes")

    ftp.close()
    if tmp_path.stat().st_size != size:
        raise RuntimeError(f"incomplete download: {tmp_path.stat().st_size}/{size} bytes")
    tmp_path.rename(local_path)
    print(f"done: {local_path}")


if __name__ == "__main__":
    sys.exit(main())
