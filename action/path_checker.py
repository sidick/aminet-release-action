"""Opt-in HTTP existence check for readme fields whose values are Aminet
file paths — currently `Requires:` and `Replaces:`.

Per the wiki:
- `Requires:` may mix file paths and free-text requirements (`1MB RAM`).
- `Replaces:` is file paths with Unix wildcards allowed (`util/misc/foo*.lha`).
- Multiple entries are separated by semicolons in both fields.

We only HEAD entries that look like a concrete file path: contains `/`, ends
in an accepted upload extension, and contains no `*`/`?` wildcards. Everything
else is skipped silently so memory/chipset requirements and wildcard patterns
don't produce noise.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable

from readme_validator import ACCEPTED_EXTENSIONS, Issue

DEFAULT_BASE_URL = "https://aminet.net"

HeadFn = Callable[[str, float], int]


def _looks_like_file_path(entry: str) -> bool:
    """An entry is checkable if it's a concrete category/file path.

    Skips entries without a `/` (free-text like `1MB RAM`), entries
    containing Unix wildcards (`util/misc/foo*.lha` — we can't meaningfully
    HEAD a glob), and entries without a recognised file extension.
    """
    if "/" not in entry:
        return False
    if "*" in entry or "?" in entry:
        return False
    lower = entry.lower()
    return any(lower.endswith(ext) for ext in ACCEPTED_EXTENSIONS)


def _head(url: str, timeout: float) -> int:
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "aminet-release-action")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def check(
    field_value: str,
    field_line: int | None = None,
    *,
    field_name: str = "Requires",
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 10.0,
    head: HeadFn | None = None,
) -> list[Issue]:
    """Return validator-style Issues for each checkable entry in a path field.

    `field_name` is used in Issue messages (so `Replaces: "..." returned 404`
    reads naturally). `head` is injectable so tests can avoid real network I/O.
    """
    do_head = head or _head
    issues: list[Issue] = []

    for raw in field_value.split(";"):
        entry = raw.strip()
        if not entry or not _looks_like_file_path(entry):
            continue
        url = f"{base_url.rstrip('/')}/{entry.lstrip('/')}"
        try:
            status = do_head(url, timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                issues.append(
                    Issue(
                        "error",
                        f'{field_name}: "{entry}" does not exist on Aminet (HTTP 404)',
                        field_line,
                    )
                )
            else:
                issues.append(
                    Issue(
                        "warning",
                        f'Could not verify {field_name}: "{entry}" — HTTP {e.code}',
                        field_line,
                    )
                )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            issues.append(
                Issue(
                    "warning",
                    f'Could not verify {field_name}: "{entry}" — {e}',
                    field_line,
                )
            )
        else:
            if status >= 400:
                issues.append(
                    Issue(
                        "warning",
                        f'{field_name}: "{entry}" returned HTTP {status}',
                        field_line,
                    )
                )

    return issues
