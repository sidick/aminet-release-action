"""Orchestration tests for entrypoint.main().

The pure-logic modules have their own coverage; here we verify the wiring:
exit codes, input handling, the validate-only short-circuit, and that the
FTP/release modules are called with the inputs as configured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import entrypoint
import ftp_uploader

FIXTURES = Path(__file__).parent / "fixtures" / "readmes"


@pytest.fixture
def workspace(tmp_path):
    """Stage a valid upload pair (filename + readme) in a tmp dir."""
    upload = tmp_path / "test.lha"
    upload.write_bytes(b"not-really-an-lha-but-good-enough")
    readme = tmp_path / "test.readme"
    readme.write_text((FIXTURES / "valid" / "minimum.readme").read_text())
    return tmp_path, upload, readme


def _set_inputs(monkeypatch, **overrides):
    """Default a clean env, then apply overrides as INPUT_* env vars."""
    # Clear any pre-existing INPUT_* keys so the test environment is hermetic.
    for key in list(__import__("os").environ.keys()):
        if key.startswith("INPUT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    for name, value in overrides.items():
        env_name = "INPUT_" + name.replace("_", "-").upper()
        monkeypatch.setenv(env_name, value)


def test_validate_only_success_returns_zero(workspace, monkeypatch):
    _, upload, readme = workspace
    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        validate_only="true",
    )
    assert entrypoint.main() == 0


def test_validate_only_with_invalid_readme_returns_one(workspace, monkeypatch):
    _, upload, readme = workspace
    # Replace the staged readme with one that mismatches the category.
    readme.write_text((FIXTURES / "invalid" / "type_mismatch.readme").read_text())
    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        validate_only="true",
    )
    assert entrypoint.main() == 1


def test_missing_required_input_returns_one(workspace, monkeypatch):
    _, upload, readme = workspace
    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        # category deliberately omitted
        validate_only="true",
    )
    assert entrypoint.main() == 1


def test_missing_filename_file_returns_one(workspace, monkeypatch):
    _, upload, readme = workspace
    _set_inputs(
        monkeypatch,
        filename=str(upload.parent / "does_not_exist.lha"),
        readme=str(readme),
        category="util/misc",
        validate_only="true",
    )
    assert entrypoint.main() == 1


def test_upload_path_without_email_returns_two(workspace, monkeypatch):
    _, upload, readme = workspace
    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        # uploader-email deliberately omitted; not validate-only
    )
    assert entrypoint.main() == 2


def test_happy_upload_calls_ftp_with_inputs(workspace, monkeypatch):
    _, upload, readme = workspace
    captured: dict = {}

    def fake_upload(filename, readme_path, *, email, host):
        captured["filename"] = filename
        captured["readme"] = readme_path
        captured["email"] = email
        captured["host"] = host

    monkeypatch.setattr(ftp_uploader, "upload", fake_upload)

    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        uploader_email="me@example.com",
        ftp_host="localhost",
    )
    assert entrypoint.main() == 0
    assert captured["filename"] == upload
    assert captured["readme"] == readme
    assert captured["email"] == "me@example.com"
    assert captured["host"] == "localhost"


def test_ftp_failure_returns_two(workspace, monkeypatch):
    _, upload, readme = workspace

    def boom(*args, **kwargs):
        raise ftp_uploader.UploadError("connection refused")

    monkeypatch.setattr(ftp_uploader, "upload", boom)

    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        uploader_email="me@example.com",
    )
    assert entrypoint.main() == 2


def test_inject_version_without_tag_returns_one(workspace, monkeypatch):
    _, upload, readme = workspace
    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        inject_version="true",
        validate_only="true",
    )
    # No GITHUB_REF — should bail.
    assert entrypoint.main() == 1


def test_inject_version_rewrites_readme_before_validating(workspace, monkeypatch):
    _, upload, readme = workspace
    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        inject_version="true",
        validate_only="true",
    )
    # _set_inputs clears GITHUB_REF; set it after, not before.
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v3.2.1")
    assert entrypoint.main() == 0
    text = readme.read_text()
    assert "3.2.1" in text
    assert "Version:" in text


def test_upload_normalises_crlf_readme(workspace, monkeypatch):
    """A CRLF-authored readme should land on disk as LF before upload."""
    _, upload, readme = workspace
    # Re-write the readme with CR+LF endings.
    crlf = readme.read_text().replace("\n", "\r\n")
    readme.write_bytes(crlf.encode("utf-8"))

    monkeypatch.setattr(ftp_uploader, "upload", lambda *a, **k: None)

    _set_inputs(
        monkeypatch,
        filename=str(upload),
        readme=str(readme),
        category="util/misc",
        uploader_email="me@example.com",
    )
    assert entrypoint.main() == 0
    # The on-disk readme should now be LF-only.
    assert b"\r\n" not in readme.read_bytes()
