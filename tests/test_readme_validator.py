"""Tests for the pure-logic readme validator."""

from __future__ import annotations

from pathlib import Path

import pytest

import readme_validator
from readme_validator import (
    Issue,
    inject_version,
    parse,
    validate,
    validate_filename,
    validate_upload_extension,
)

FIXTURES = Path(__file__).parent / "fixtures" / "readmes"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def has(issues: list[Issue], level: str, substring: str) -> bool:
    return any(i.level == level and substring in i.message for i in issues)


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


def warnings(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "warning"]


# --------------------------------------------------------------------------
# Valid fixtures
# --------------------------------------------------------------------------

def test_minimum_has_no_errors():
    parsed = parse(load("valid/minimum.readme"))
    issues = validate(parsed, "util/misc")
    assert errors(issues) == [], f"unexpected errors: {errors(issues)}"


def test_minimum_warns_about_recommended_fields():
    parsed = parse(load("valid/minimum.readme"))
    issues = validate(parsed, "util/misc")
    assert has(issues, "warning", "Missing recommended field: Author")
    assert has(issues, "warning", "Missing recommended field: Version")


def test_full_is_completely_clean():
    parsed = parse(load("valid/full.readme"))
    issues = validate(parsed, "util/misc")
    assert issues == [], f"expected zero issues, got: {issues}"


# --------------------------------------------------------------------------
# Invalid fixtures — one assertion per failure mode
# --------------------------------------------------------------------------

INVALID_CASES = [
    # (fixture, category, expected_level, expected_substring)
    ("invalid/missing_short.readme", "util/misc", "error", "Missing required field: Short"),
    ("invalid/missing_uploader.readme", "util/misc", "error", "Missing required field: Uploader"),
    ("invalid/missing_type.readme", "util/misc", "error", "Missing required field: Type"),
    ("invalid/missing_architecture.readme", "util/misc", "error", "Missing required field: Architecture"),
    ("invalid/short_too_long.readme", "util/misc", "error", "Short description is"),
    ("invalid/short_not_first.readme", "util/misc", "warning", "Short: should be the first line"),
    ("invalid/type_mismatch.readme", "util/misc", "error", "does not match the category"),
    ("invalid/unknown_architecture.readme", "util/misc", "error", "Unknown architecture"),
    ("invalid/malformed_architecture.readme", "util/misc", "error", "Cannot parse architecture"),
    ("invalid/bad_distribution.readme", "util/misc", "error", "Distribution"),
    ("invalid/long_body_line.readme", "util/misc", "warning", "Body line is"),
]


@pytest.mark.parametrize("fixture,category,level,substring", INVALID_CASES)
def test_invalid_fixture_triggers_expected_issue(fixture, category, level, substring):
    parsed = parse(load(fixture))
    issues = validate(parsed, category)
    assert has(issues, level, substring), (
        f"expected {level} containing {substring!r} in {fixture}; got: {issues}"
    )


# --------------------------------------------------------------------------
# CRLF: tested in-memory by mutating the minimum-valid fixture, so we don't
# have to manage CRLF bytes on disk.
# --------------------------------------------------------------------------

def test_crlf_produces_warning_not_error():
    crlf_text = load("valid/minimum.readme").replace("\n", "\r\n")
    parsed = parse(crlf_text)
    assert parsed.has_crlf is True
    issues = validate(parsed, "util/misc")
    assert has(issues, "warning", "CR+LF")
    # CRLF alone should not produce errors — body content is unchanged.
    assert errors(issues) == [], f"CRLF should not error, got: {errors(issues)}"


# --------------------------------------------------------------------------
# Architecture parsing — covered by fixtures above, but a few targeted
# cases for the multi-arch / version-modifier syntax that the fixtures
# don't exercise.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("arch_value", [
    "m68k-amigaos",
    "m68k-amigaos; ppc-amigaos",
    "ppc-morphos >= 1.4.0",
    "m68k-amigaos >= 2.0; ppc-amigaos",
    "generic",
])
def test_valid_architecture_strings(arch_value):
    text = (
        f"Short:        Architecture test\n"
        f"Uploader:     test@example.com\n"
        f"Type:         util/misc\n"
        f"Architecture: {arch_value}\n"
        f"\nBody.\n"
    )
    issues = validate(parse(text), "util/misc")
    arch_errors = [i for i in errors(issues) if "rchitecture" in i.message]
    assert arch_errors == [], f"unexpected architecture errors: {arch_errors}"


def test_empty_architecture_is_an_error():
    text = (
        "Short:        Empty arch\n"
        "Uploader:     test@example.com\n"
        "Type:         util/misc\n"
        "Architecture: \n"
        "\nBody.\n"
    )
    issues = validate(parse(text), "util/misc")
    assert has(issues, "error", "Architecture field is empty")


# --------------------------------------------------------------------------
# parse() basics
# --------------------------------------------------------------------------

def test_parse_extracts_header_with_line_numbers():
    text = (
        "Short:        Hello\n"
        "Uploader:     t@e.com\n"
        "Type:         util/misc\n"
        "Architecture: m68k-amigaos\n"
        "\n"
        "Body line one.\n"
        "Body line two.\n"
    )
    parsed = parse(text)
    assert parsed.header["Short"] == (1, "Hello")
    assert parsed.header["Uploader"] == (2, "t@e.com")
    assert parsed.header["Type"] == (3, "util/misc")
    assert parsed.header["Architecture"] == (4, "m68k-amigaos")
    assert "Body line one." in parsed.body
    assert "Body line two." in parsed.body
    assert parsed.short_on_first_line is True
    assert parsed.has_crlf is False


def test_parse_handles_missing_body():
    text = "Short: x\nUploader: y\nType: util/misc\nArchitecture: generic\n"
    parsed = parse(text)
    assert "Short" in parsed.header
    assert parsed.body == ""


def test_parse_detects_crlf():
    parsed = parse("Short: x\r\nUploader: y\r\n\r\nBody.\r\n")
    assert parsed.has_crlf is True


# --------------------------------------------------------------------------
# Filename validation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "MyTool.lha",
    "my_tool.lha",
    "my-tool.lha",
    "MyTool.tar.gz",
    "a" * 30,
])
def test_valid_filenames(name):
    assert validate_filename(name) == []


@pytest.mark.parametrize("name,expected_substring", [
    ("a" * 31, "max is 30"),
    ("My Tool.lha", "outside"),
    ("file/name.lha", "outside"),
    ("file?name.lha", "outside"),
    ("file\nname.lha", "outside"),
])
def test_invalid_filenames(name, expected_substring):
    issues = validate_filename(name)
    assert any(expected_substring in i.message for i in issues), (
        f"expected {expected_substring!r} in issues for {name!r}; got: {issues}"
    )


# --------------------------------------------------------------------------
# Upload extension validation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "foo.lha", "foo.zip", "foo.run",
    "foo.tar", "foo.tar.gz", "foo.tgz", "foo.tar.bz2",
    "foo.adf", "foo.adz",
    "foo.jpg", "foo.png", "foo.gif",
    "foo.pdf", "foo.txt",
    "foo.ogg", "foo.mp3",
    "foo.mpg",
])
def test_accepted_extensions(name):
    assert validate_upload_extension(name) == []


@pytest.mark.parametrize("name", [
    "foo.exe",
    "foo.rar",
    "foo.7z",
    "foo",  # no extension
    "foo.tar.xz",
])
def test_rejected_extensions(name):
    issues = validate_upload_extension(name)
    assert issues, f"expected rejection for {name!r}"


# --------------------------------------------------------------------------
# inject_version
# --------------------------------------------------------------------------

def test_inject_version_replaces_existing():
    text = (
        "Short:        x\n"
        "Version:      0.1\n"
        "Type:         util/misc\n"
        "\nBody.\n"
    )
    result = inject_version(text, "1.2.3")
    assert "Version:      1.2.3" in result
    assert "0.1" not in result


def test_inject_version_inserts_when_missing():
    text = (
        "Short:        x\n"
        "Type:         util/misc\n"
        "\nBody.\n"
    )
    result = inject_version(text, "1.0")
    assert "Version: 1.0" in result
    # Inserted line must come before the blank-line separator.
    lines = result.split("\n")
    blank_idx = lines.index("")
    version_idx = next(
        i for i, l in enumerate(lines) if l.lstrip().startswith("Version:")
    )
    assert version_idx < blank_idx


def test_inject_version_preserves_crlf_endings():
    text = "Short: x\r\nVersion: 0.1\r\n\r\nBody.\r\n"
    result = inject_version(text, "1.0")
    assert "\r\n" in result
    assert "Version: 1.0" in result
    assert "0.1" not in result


def test_inject_version_then_validates_clean():
    """Smoke: injecting a version into the minimum fixture leaves it valid."""
    text = load("valid/minimum.readme")
    text = inject_version(text, "9.9.9")
    issues = validate(parse(text), "util/misc")
    assert errors(issues) == []
    assert "Version: 9.9.9" in text or "Version:      9.9.9" in text
