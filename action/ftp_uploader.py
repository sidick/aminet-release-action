"""Anonymous FTP upload via lftp.

Procedure: https://wiki.aminet.net/Uploading_instructions
"""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_HOST = "main.aminet.net"
UPLOAD_DIR = "/new"


class UploadError(RuntimeError):
    pass


def upload(
    upload_file: Path,
    readme: Path,
    email: str,
    host: str = DEFAULT_HOST,
) -> None:
    """Upload `upload_file` and `readme` via anonymous FTP.

    The password (email address) is piped through stdin rather than placed on
    the command line so it doesn't appear in process listings.
    """
    for p in (upload_file, readme):
        if not p.is_file():
            raise UploadError(f"file does not exist: {p}")

    script_lines = [
        "set ftp:passive-mode true",
        "set net:max-retries 3",
        "set net:reconnect-interval-base 5",
        "set net:timeout 30",
        f"open --user anonymous --password {email} {host}",
        f"cd {UPLOAD_DIR}",
        f'put "{upload_file}"',
        f'put "{readme}"',
        "bye",
    ]
    script = "\n".join(script_lines) + "\n"

    try:
        result = subprocess.run(
            ["lftp"],
            input=script,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError as e:
        raise UploadError("lftp is not installed in the container") from e
    except subprocess.TimeoutExpired as e:
        raise UploadError("lftp timed out after 600 seconds") from e

    if result.returncode != 0:
        # lftp tends to write errors to stderr; fall back to stdout.
        detail = (result.stderr or result.stdout or "").strip()
        raise UploadError(f"lftp exited with code {result.returncode}: {detail}")
