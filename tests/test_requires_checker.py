"""Tests for the opt-in Requires: existence checker.

All network access is monkeypatched. We test the URL construction,
which entries are eligible (file path heuristic), and how HEAD outcomes
map to Issue levels.
"""

from __future__ import annotations

import urllib.error
from typing import Any

import pytest

from requires_checker import check


def make_head(responses: dict[str, Any]):
    """Build a fake HEAD callable backed by a {url: status_or_exc} table.

    A value that's an Exception (or Exception class) is raised; otherwise
    it's returned as the status code.
    """
    seen: list[str] = []

    def fake(url, timeout):  # signature must match _head
        seen.append(url)
        result = responses.get(url)
        if result is None:
            raise AssertionError(f"unexpected HEAD: {url}")
        if isinstance(result, Exception):
            raise result
        if isinstance(result, type) and issubclass(result, Exception):
            raise result("fake")
        return result

    return fake, seen


# --------------------------------------------------------------------------
# Eligibility heuristic
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        "1MB RAM",
        "OS 3.0",
        "AGA chipset",
        "no-slashes-here.lha",  # has extension but no /
        "util/sys/no-extension",  # has / but no recognised extension
        "util/sys/foo.unknown",  # / but bad extension
    ],
)
def test_non_file_entries_are_skipped(entry):
    fake, seen = make_head({})
    issues = check(entry, head=fake)
    assert seen == [], f"should not have HEADed anything; got {seen}"
    assert issues == []


@pytest.mark.parametrize(
    "entry",
    [
        "util/sys/foo.lha",
        "biz/dbase/bar.tar.gz",
        "pix/icon/baz.png",
    ],
)
def test_file_entries_are_checked(entry):
    url = f"https://aminet.net/{entry}"
    fake, seen = make_head({url: 200})
    issues = check(entry, head=fake)
    assert seen == [url]
    assert issues == []


# --------------------------------------------------------------------------
# Multi-entry value: skip free-text, check file paths
# --------------------------------------------------------------------------


def test_mixed_value_only_checks_file_paths():
    value = "1MB RAM; util/sys/foo.lha; AGA chipset; util/misc/bar.zip"
    fake, seen = make_head(
        {
            "https://aminet.net/util/sys/foo.lha": 200,
            "https://aminet.net/util/misc/bar.zip": 200,
        }
    )
    issues = check(value, head=fake)
    assert sorted(seen) == [
        "https://aminet.net/util/misc/bar.zip",
        "https://aminet.net/util/sys/foo.lha",
    ]
    assert issues == []


# --------------------------------------------------------------------------
# HTTP outcomes → Issue level
# --------------------------------------------------------------------------


def test_404_is_an_error():
    url = "https://aminet.net/util/sys/missing.lha"
    err = urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    fake, _ = make_head({url: err})
    issues = check("util/sys/missing.lha", head=fake, requires_line=7)
    assert len(issues) == 1
    assert issues[0].level == "error"
    assert "404" in issues[0].message
    assert issues[0].line == 7


def test_other_http_status_is_a_warning():
    url = "https://aminet.net/util/sys/foo.lha"
    err = urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
    fake, _ = make_head({url: err})
    issues = check("util/sys/foo.lha", head=fake)
    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "503" in issues[0].message


def test_network_failure_is_a_warning():
    url = "https://aminet.net/util/sys/foo.lha"
    err = urllib.error.URLError("connection refused")
    fake, _ = make_head({url: err})
    issues = check("util/sys/foo.lha", head=fake)
    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "connection refused" in issues[0].message


def test_timeout_is_a_warning():
    url = "https://aminet.net/util/sys/foo.lha"
    fake, _ = make_head({url: TimeoutError("read timed out")})
    issues = check("util/sys/foo.lha", head=fake)
    assert len(issues) == 1
    assert issues[0].level == "warning"


def test_4xx_other_than_404_via_status_is_a_warning():
    """If the HEAD returns 4xx without raising, treat as warning."""
    url = "https://aminet.net/util/sys/foo.lha"
    fake, _ = make_head({url: 403})
    issues = check("util/sys/foo.lha", head=fake)
    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "403" in issues[0].message


# --------------------------------------------------------------------------
# Base URL override
# --------------------------------------------------------------------------


def test_base_url_can_be_overridden():
    fake, seen = make_head({"http://localhost/util/sys/foo.lha": 200})
    issues = check("util/sys/foo.lha", head=fake, base_url="http://localhost")
    assert seen == ["http://localhost/util/sys/foo.lha"]
    assert issues == []
