"""Tests for the GitHub Releases API client.

The network call lives behind `github_release._request`; tests monkeypatch
that attribute to inject canned responses or errors. We verify URL
construction, error mapping (404 → None vs 500 → raise), and that
upload_asset correctly massages the `upload_url` template into a real URL.
"""

from __future__ import annotations

import pytest

import github_release
from github_release import ReleaseError, find_release_by_tag, upload_asset

# --------------------------------------------------------------------------
# find_release_by_tag
# --------------------------------------------------------------------------


def test_find_release_returns_dict_on_success(monkeypatch):
    expected = {"id": 1, "name": "v1.0.0", "upload_url": "https://example.com/{?name}"}
    captured: dict = {}

    def fake_request(url, token, **kw):
        captured["url"] = url
        captured["token"] = token
        return expected

    monkeypatch.setattr(github_release, "_request", fake_request)

    result = find_release_by_tag("owner/repo", "v1.0.0", "ghp_tok")
    assert result == expected
    assert captured["url"] == "https://api.github.com/repos/owner/repo/releases/tags/v1.0.0"
    assert captured["token"] == "ghp_tok"


def test_find_release_returns_none_on_404(monkeypatch):
    def fake_request(url, token, **kw):
        raise ReleaseError("GitHub API 404 on ...", status=404)

    monkeypatch.setattr(github_release, "_request", fake_request)

    assert find_release_by_tag("owner/repo", "v9.9.9", "tok") is None


def test_find_release_reraises_on_non_404(monkeypatch):
    def fake_request(url, token, **kw):
        raise ReleaseError("GitHub API 500 on ...", status=500)

    monkeypatch.setattr(github_release, "_request", fake_request)

    with pytest.raises(ReleaseError):
        find_release_by_tag("owner/repo", "v1.0.0", "tok")


def test_find_release_reraises_on_transport_error(monkeypatch):
    """Network-level failures (status=None) must surface, not be swallowed."""

    def fake_request(url, token, **kw):
        raise ReleaseError("connection refused", status=None)

    monkeypatch.setattr(github_release, "_request", fake_request)

    with pytest.raises(ReleaseError):
        find_release_by_tag("owner/repo", "v1.0.0", "tok")


def test_find_release_url_encodes_special_chars_in_tag(monkeypatch):
    """A tag containing characters that need URL quoting should be encoded."""
    captured: dict = {}

    def fake_request(url, token, **kw):
        captured["url"] = url
        return {}

    monkeypatch.setattr(github_release, "_request", fake_request)

    find_release_by_tag("owner/repo", "release/1.0+rc1", "tok")
    # `/` and `+` both get quoted.
    assert "release%2F1.0%2Brc1" in captured["url"]


# --------------------------------------------------------------------------
# upload_asset
# --------------------------------------------------------------------------


def test_upload_asset_strips_template_and_appends_name_query(tmp_path, monkeypatch):
    file = tmp_path / "MyTool.lha"
    file.write_bytes(b"payload-bytes")

    captured: dict = {}

    def fake_request(url, token, *, data=None, content_type=None, method=None):
        captured.update(url=url, token=token, data=data, content_type=content_type, method=method)
        return {"id": 42}

    monkeypatch.setattr(github_release, "_request", fake_request)

    template = "https://uploads.github.com/repos/X/Y/releases/1/assets{?name,label}"
    result = upload_asset(template, file, "tok")

    assert captured["url"] == (
        "https://uploads.github.com/repos/X/Y/releases/1/assets?name=MyTool.lha"
    )
    assert captured["content_type"] == "application/octet-stream"
    assert captured["method"] == "POST"
    assert captured["data"] == b"payload-bytes"
    assert result == {"id": 42}


def test_upload_asset_uses_path_basename_not_full_path(tmp_path, monkeypatch):
    nested = tmp_path / "build" / "dist" / "MyTool.lha"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")

    captured: dict = {}
    monkeypatch.setattr(
        github_release,
        "_request",
        lambda url, token, **kw: captured.setdefault("url", url) or {},
    )

    upload_asset("https://uploads.example.com/assets{?name,label}", nested, "tok")
    # Only the basename, not the full path, appears in the upload URL.
    assert "name=MyTool.lha" in captured["url"]
    assert "build" not in captured["url"]


def test_upload_asset_url_encodes_filename(tmp_path, monkeypatch):
    """A filename with characters that need URL quoting should be encoded."""
    file = tmp_path / "with space+plus.lha"
    file.write_bytes(b"x")

    captured: dict = {}
    monkeypatch.setattr(
        github_release,
        "_request",
        lambda url, token, **kw: captured.setdefault("url", url) or {},
    )

    upload_asset("https://uploads.example.com/assets{?name,label}", file, "tok")
    # `urlencode` produces `+` for space and `%2B` for plus.
    assert "name=with+space%2Bplus.lha" in captured["url"]


# --------------------------------------------------------------------------
# ReleaseError carries status
# --------------------------------------------------------------------------


def test_release_error_carries_status_field():
    e = ReleaseError("oops", status=503)
    assert e.status == 503
    assert "oops" in str(e)


def test_release_error_status_optional():
    e = ReleaseError("transport failed")
    assert e.status is None
