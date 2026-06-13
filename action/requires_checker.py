"""Opt-in HTTP existence check for Requires: entries.

Per the Aminet wiki, the Requires: field is "Dependencies with full paths;
include memory/chipset requirements" — so entries can be either file paths
(`util/sys/foo.lha`) or free-text requirements (`1MB RAM`). We only check
the former; free-text entries are skipped silently.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Optional

from readme_validator import ACCEPTED_EXTENSIONS, Issue

DEFAULT_BASE_URL = "https://aminet.net"


def _looks_like_file_path(entry: str) -> bool:
    """A Requires: entry is checkable if it's a category/file path.

    Heuristic: contains a `/` and ends in an accepted upload extension.
    Memory/chipset requirements like `1MB RAM` or `OS 3.0` lack both."""
    if "/" not in entry:
        return False
    lower = entry.lower()
    return any(lower.endswith(ext) for ext in ACCEPTED_EXTENSIONS)


def _head(url: str, timeout: float) -> int:
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "aminet-release-action")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def check(
    requires_value: str,
    requires_line: Optional[int] = None,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 10.0,
    head: Optional[callable] = None,
) -> list[Issue]:
    """Return validator-style Issues for each checkable entry in a Requires: value.

    `head` is injectable so tests can avoid real network I/O.
    """
    do_head = head or _head
    issues: list[Issue] = []

    for raw in requires_value.split(";"):
        entry = raw.strip()
        if not entry or not _looks_like_file_path(entry):
            continue
        url = f"{base_url.rstrip('/')}/{entry.lstrip('/')}"
        try:
            status = do_head(url, timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                issues.append(Issue(
                    "error",
                    f'Requires: "{entry}" does not exist on Aminet (HTTP 404)',
                    requires_line,
                ))
            else:
                issues.append(Issue(
                    "warning",
                    f'Could not verify Requires: "{entry}" — HTTP {e.code}',
                    requires_line,
                ))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            issues.append(Issue(
                "warning",
                f'Could not verify Requires: "{entry}" — {e}',
                requires_line,
            ))
        else:
            if status >= 400:
                issues.append(Issue(
                    "warning",
                    f'Requires: "{entry}" returned HTTP {status}',
                    requires_line,
                ))

    return issues
