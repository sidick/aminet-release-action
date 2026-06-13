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

import ftp_uploader
import github_output
import github_release
import path_checker
import readme_validator

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
    check_replaces: bool
    ftp_host: str


@dataclass
class RunResult:
    """Accumulated state from one main() invocation.

    Drives both the GITHUB_STEP_SUMMARY markdown and (in a follow-up) the
    action outputs, so every code path that exits must populate the fields
    it owns before returning.
    """

    filename_name: str = ""
    readme_name: str = ""
    category: str = ""
    mode: str = "upload"  # "upload" | "validate-only"

    errors: int = 0
    warnings: int = 0

    uploaded: bool = False
    upload_target: str = ""
    release_attached: bool = False
    release_name: str = ""

    fatal_message: str = ""
    exit_code: int = EXIT_OK


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
        check_replaces=_truthy(_input("check-replaces", "false")),
        ftp_host=_input("ftp-host", ftp_uploader.DEFAULT_HOST).strip(),
    )


def _derive_version_from_tag() -> str | None:
    ref = os.environ.get("GITHUB_REF", "")
    prefix = "refs/tags/"
    if not ref.startswith(prefix):
        return None
    tag = ref[len(prefix) :]
    return tag[1:] if tag.startswith("v") else tag


def _normalise_line_endings(path: Path) -> None:
    raw = path.read_bytes()
    if b"\r\n" in raw:
        path.write_bytes(raw.replace(b"\r\n", b"\n"))


def _attach_to_release(filename: Path, readme: Path, result: RunResult) -> None:
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/tags/"):
        return  # not a tag push, nothing to attach to
    tag = ref[len("refs/tags/") :]

    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        github_output.warning(
            "GITHUB_REPOSITORY or GITHUB_TOKEN not set; skipping release asset attachment"
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
        release_name = release.get("name") or tag
        result.release_attached = True
        result.release_name = release_name
        github_output.notice(
            f"Attached {filename.name} and {readme.name} to release {release_name}"
        )
    except github_release.ReleaseError as e:
        # Don't fail the whole action if release attachment fails — the
        # Aminet upload already succeeded by this point.
        github_output.warning(f"Could not attach release assets: {e}")


def _build_summary(result: RunResult) -> str:
    title = result.filename_name or "(no filename)"
    category = result.category or "(no category)"
    lines: list[str] = [
        f"## Aminet Release — `{title}` → `{category}`",
        "",
        "| Check | Result |",
        "|---|---|",
    ]

    if result.errors:
        validation = f"FAIL — {result.errors} error(s), {result.warnings} warning(s)"
    else:
        validation = f"OK — 0 errors, {result.warnings} warning(s)"
    lines.append(f"| Validation | {validation} |")

    if result.uploaded:
        upload_cell = f"OK — {result.upload_target}"
    elif result.mode == "validate-only" and result.errors == 0:
        upload_cell = "skipped (validate-only)"
    elif result.exit_code == EXIT_UPLOAD_FAILURE:
        upload_cell = "FAIL"
    else:
        upload_cell = "—"
    lines.append(f"| Upload | {upload_cell} |")

    if result.release_attached:
        release_cell = f"OK — {result.release_name}"
    elif result.uploaded:
        release_cell = "n/a (no matching release or not a tag push)"
    else:
        release_cell = "—"
    lines.append(f"| Release attach | {release_cell} |")

    if result.fatal_message:
        lines.append("")
        lines.append(f"**Stopped:** {result.fatal_message}")

    return "\n".join(lines) + "\n"


def _emit_summary(result: RunResult) -> None:
    github_output.summary(_build_summary(result))


def _emit_outputs(result: RunResult) -> None:
    github_output.set_output("uploaded", result.uploaded)
    github_output.set_output("release-attached", result.release_attached)
    github_output.set_output("errors", result.errors)
    github_output.set_output("warnings", result.warnings)
    github_output.set_output("filename", result.filename_name)
    github_output.set_output("readme", result.readme_name)


def _run_pipeline(result: RunResult) -> int:
    inputs = _read_inputs()
    result.filename_name = inputs.filename.name
    result.readme_name = inputs.readme.name
    result.category = inputs.category
    result.mode = "validate-only" if inputs.validate_only else "upload"

    missing = [
        n
        for n, v in (
            ("filename", str(inputs.filename)),
            ("readme", str(inputs.readme)),
            ("category", inputs.category),
        )
        if not v
    ]
    if missing:
        msg = f"required inputs missing: {', '.join(missing)}"
        github_output.error(msg)
        result.fatal_message = msg
        return EXIT_VALIDATION_FAILURE

    if not inputs.filename.is_file():
        msg = f"filename not found: {inputs.filename}"
        github_output.error(msg)
        result.fatal_message = msg
        return EXIT_VALIDATION_FAILURE
    if not inputs.readme.is_file():
        msg = f"readme not found: {inputs.readme}"
        github_output.error(msg)
        result.fatal_message = msg
        return EXIT_VALIDATION_FAILURE

    if inputs.inject_version:
        version = _derive_version_from_tag()
        if version is None:
            msg = "inject-version requires a tag push (GITHUB_REF=refs/tags/<tag>)"
            github_output.error(msg)
            result.fatal_message = msg
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
        issues.extend(path_checker.check(value, field_line=line, field_name="Requires"))

    if inputs.check_replaces and "Replaces" in parsed.header:
        line, value = parsed.header["Replaces"]
        issues.extend(path_checker.check(value, field_line=line, field_name="Replaces"))

    readme_str = str(inputs.readme)
    for issue in issues:
        if issue.level == "error":
            github_output.error(issue.message, file=readme_str, line=issue.line)
            result.errors += 1
        else:
            github_output.warning(issue.message, file=readme_str, line=issue.line)
            result.warnings += 1

    if result.errors:
        msg = f"readme validation failed: {result.errors} error(s), {result.warnings} warning(s)"
        github_output.error(msg)
        result.fatal_message = msg
        return EXIT_VALIDATION_FAILURE

    if inputs.validate_only:
        github_output.notice(
            f"validate-only: readme is valid ({result.warnings} warning(s)); skipping upload"
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
        msg = (
            "no uploader email available: pass uploader-email as an input or "
            "set the readme's Uploader: field to an email address"
        )
        github_output.error(msg)
        result.fatal_message = msg
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
        msg = f"FTP upload failed: {e}"
        github_output.error(msg)
        result.fatal_message = msg
        return EXIT_UPLOAD_FAILURE

    result.uploaded = True
    result.upload_target = f"{inputs.ftp_host}{ftp_uploader.UPLOAD_DIR}"
    github_output.notice(
        f"Uploaded {inputs.filename.name} and {inputs.readme.name} to {result.upload_target}"
    )

    _attach_to_release(inputs.filename, inputs.readme, result)

    return EXIT_OK


def main() -> int:
    result = RunResult()
    result.exit_code = _run_pipeline(result)
    _emit_summary(result)
    _emit_outputs(result)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
