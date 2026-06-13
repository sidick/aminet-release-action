"""Minimal GitHub Releases API client.

Uses stdlib urllib to avoid adding `requests` to the container.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://api.github.com"


class ReleaseError(RuntimeError):
    pass


def _request(
    url: str,
    token: str,
    *,
    data: bytes | None = None,
    content_type: str = "application/json",
    method: str | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "aminet-release-action",
    }
    if data is not None:
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(data))
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise ReleaseError(f"GitHub API {e.code} on {url}: {body[:500]}") from e
    except urllib.error.URLError as e:
        raise ReleaseError(f"GitHub API request failed for {url}: {e.reason}") from e
    if not body:
        return {}
    return json.loads(body)


def find_release_by_tag(repo: str, tag: str, token: str) -> dict | None:
    """Return the release for `tag`, or None if no such release exists."""
    url = f"{API_BASE}/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}"
    try:
        return _request(url, token)
    except ReleaseError as e:
        if " 404 " in f" {e} ":
            return None
        raise


def upload_asset(upload_url_template: str, path: Path, token: str) -> dict:
    """Upload `path` as a release asset.

    `upload_url_template` is the `upload_url` field from a release object,
    which looks like `https://uploads.github.com/.../assets{?name,label}`.
    """
    base = upload_url_template.split("{", 1)[0]
    query = urllib.parse.urlencode({"name": path.name})
    url = f"{base}?{query}"
    data = path.read_bytes()
    return _request(url, token, data=data, content_type="application/octet-stream", method="POST")
