"""Action entrypoint: parse INPUT_* env vars, orchestrate the pipeline.

Exit codes:
  0  success
  1  validation failure
  2  upload failure
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import ftp_uploader
import github_output
import github_release
import readme_validator
import requires_checker

EXIT_OK = 0
EXIT_VALIDATION_FAILURE = 1
EXIT_UPLOAD_FAILURE = 2


@dataclass
class Inputs:
    filename: Path
    readme: Path
    category: str
    uploader_email: str
    inject_version: bool
    validate_only: bool
    check_requires: bool
    ftp_host: str


def _input(name: str, default: str = "") -> str:
    # GitHub Actions maps `with:` keys to INPUT_<NAME> env vars, uppercasing
    # the name and preserving hyphens.
    return os.environ.get(f"INPUT_{name.upper()}", default)


def _truthy(s: str) -> bool:
    return s.strip().lower() in ("true", "1", "yes", "on")


def _read_inputs() -> Inputs:
    return Inputs(
        filename=Path(_input("filename")),
        readme=Path(_input("readme")),
        category=_input("category").strip(),
        uploader_email=_input("uploader-email").strip(),
        inject_version=_truthy(_input("inject-version", "false")),
        validate_only=_truthy(_input("validate-only", "false")),
        check_requires=_truthy(_input("check-requires", "false")),
        ftp_host=_input("ftp-host", ftp_uploader.DEFAULT_HOST).strip(),
    )


def _derive_version_from_tag() -> Optional[str]:
    ref = os.environ.get("GITHUB_REF", "")
    prefix = "refs/tags/"
    if not ref.startswith(prefix):
        return None
    tag = ref[len(prefix):]
    return tag[1:] if tag.startswith("v") else tag


def _normalise_line_endings(path: Path) -> None:
    raw = path.read_bytes()
    if b"\r\n" in raw:
        path.write_bytes(raw.replace(b"\r\n", b"\n"))


def _attach_to_release(filename: Path, readme: Path) -> None:
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/tags/"):
        return  # not a tag push, nothing to attach to
    tag = ref[len("refs/tags/"):]

    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        github_output.warning(
            "GITHUB_REPOSITORY or GITHUB_TOKEN not set; skipping release "
            "asset attachment"
        )
        return

    try:
        release = github_release.find_release_by_tag(repo, tag, token)
        if release is None and tag.startswith("v"):
            release = github_release.find_release_by_tag(repo, tag[1:], token)
        if release is None:
            github_output.notice(
                f"No GitHub Release found for tag {tag}; skipping asset attachment"
            )
            return
        upload_url = release["upload_url"]
        for asset in (filename, readme):
            github_release.upload_asset(upload_url, asset, token)
        github_output.notice(
            f"Attached {filename.name} and {readme.name} to release "
            f"{release.get('name') or tag}"
        )
    except github_release.ReleaseError as e:
        # Don't fail the whole action if release attachment fails — the
        # Aminet upload already succeeded by this point.
        github_output.warning(f"Could not attach release assets: {e}")


def main() -> int:
    inputs = _read_inputs()

    missing = [n for n, v in (
        ("filename", str(inputs.filename)),
        ("readme", str(inputs.readme)),
        ("category", inputs.category),
    ) if not v]
    if missing:
        github_output.error(
            f"required inputs missing: {', '.join(missing)}"
        )
        return EXIT_VALIDATION_FAILURE

    if not inputs.filename.is_file():
        github_output.error(f"filename not found: {inputs.filename}")
        return EXIT_VALIDATION_FAILURE
    if not inputs.readme.is_file():
        github_output.error(f"readme not found: {inputs.readme}")
        return EXIT_VALIDATION_FAILURE

    if inputs.inject_version:
        version = _derive_version_from_tag()
        if version is None:
            github_output.error(
                "inject-version requires a tag push "
                "(GITHUB_REF=refs/tags/<tag>)"
            )
            return EXIT_VALIDATION_FAILURE
        text = inputs.readme.read_text(encoding="utf-8")
        text = readme_validator.inject_version(text, version)
        inputs.readme.write_text(text, encoding="utf-8")
        github_output.notice(f"Injected Version: {version} from tag")

    readme_text = inputs.readme.read_text(encoding="utf-8")
    parsed = readme_validator.parse(readme_text)
    issues = readme_validator.validate(parsed, inputs.category)
    issues.extend(readme_validator.validate_filename(inputs.filename.name))
    issues.extend(readme_validator.validate_filename(inputs.readme.name))
    issues.extend(readme_validator.validate_upload_extension(inputs.filename.name))

    if inputs.check_requires and "Requires" in parsed.header:
        line, value = parsed.header["Requires"]
        issues.extend(requires_checker.check(value, requires_line=line))

    readme_str = str(inputs.readme)
    errors, warnings = 0, 0
    for issue in issues:
        if issue.level == "error":
            github_output.error(issue.message, file=readme_str, line=issue.line)
            errors += 1
        else:
            github_output.warning(issue.message, file=readme_str, line=issue.line)
            warnings += 1

    if errors:
        github_output.error(
            f"readme validation failed: {errors} error(s), {warnings} warning(s)"
        )
        return EXIT_VALIDATION_FAILURE

    if inputs.validate_only:
        github_output.notice(
            f"validate-only: readme is valid ({warnings} warning(s)); "
            "skipping upload"
        )
        return EXIT_OK

    effective_email = inputs.uploader_email
    if not effective_email and "Uploader" in parsed.header:
        _, uploader_value = parsed.header["Uploader"]
        derived = readme_validator.extract_uploader_email(uploader_value)
        if derived:
            effective_email = derived
            github_output.notice(
                f"uploader-email not provided; using {derived} from the "
                f"readme's Uploader: field as the FTP password"
            )

    if not effective_email:
        github_output.error(
            "no uploader email available: pass uploader-email as an input or "
            "set the readme's Uploader: field to an email address"
        )
        return EXIT_UPLOAD_FAILURE

    # Aminet expects LF-only readmes. Quietly normalise before uploading so
    # we never put a CRLF file on the wire, regardless of how the input was
    # authored.
    _normalise_line_endings(inputs.readme)

    try:
        ftp_uploader.upload(
            inputs.filename,
            inputs.readme,
            email=effective_email,
            host=inputs.ftp_host,
        )
    except ftp_uploader.UploadError as e:
        github_output.error(f"FTP upload failed: {e}")
        return EXIT_UPLOAD_FAILURE

    github_output.notice(
        f"Uploaded {inputs.filename.name} and {inputs.readme.name} to "
        f"{inputs.ftp_host}{ftp_uploader.UPLOAD_DIR}"
    )

    _attach_to_release(inputs.filename, inputs.readme)

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
