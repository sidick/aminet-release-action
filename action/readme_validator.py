"""Aminet .readme parsing and validation.

Spec: https://wiki.aminet.net/The_Readme_file
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

REQUIRED_FIELDS: tuple[str, ...] = ("Short", "Uploader", "Type", "Architecture")
RECOMMENDED_FIELDS: tuple[str, ...] = ("Author", "Version")

KNOWN_ARCHITECTURES: frozenset[str] = frozenset(
    {
        "m68k-amigaos",
        "ppc-amigaos",
        "ppc-morphos",
        "ppc-powerup",
        "ppc-warpup",
        "i386-aros",
        "i386-amithlon",
        "generic",
    }
)

VALID_DISTRIBUTION: frozenset[str] = frozenset({"NoCD", "Aminet"})

ACCEPTED_EXTENSIONS: tuple[str, ...] = (
    ".lha",
    ".run",
    ".zip",
    ".adf",
    ".adz",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".jpg",
    ".png",
    ".gif",
    ".pdf",
    ".txt",
    ".ogg",
    ".mp3",
    ".mpg",
)

FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
ARCH_ENTRY_PATTERN = re.compile(
    r"^\s*(?P<arch>\S+?)(?:\s+(?P<mod>>=|<=|>|<|=)\s+(?P<ver>\S+))?\s*$"
)
ARCH_MODIFIERS: frozenset[str] = frozenset({">=", "<=", ">", "<", "="})

MAX_SHORT_LENGTH = 40
MAX_FILENAME_LENGTH = 30
MAX_BODY_LINE_LENGTH = 78


@dataclass
class Issue:
    level: str  # "error" or "warning"
    message: str
    line: int | None = None


@dataclass
class ParsedReadme:
    """Result of parsing a readme.

    `header` maps field name → (line number, raw value). Line numbers are
    1-indexed and refer to the original file. `body` is everything after the
    first blank line, joined with the original newlines.
    """

    header: dict[str, tuple[int, str]] = field(default_factory=dict)
    body: str = ""
    body_start_line: int = 1
    short_on_first_line: bool = False
    has_crlf: bool = False


def parse(text: str) -> ParsedReadme:
    has_crlf = "\r\n" in text
    # Normalise newlines for parsing; we preserve the original text elsewhere.
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalised.split("\n")

    header: dict[str, tuple[int, str]] = {}
    body_start = len(lines)
    short_on_first_line = False

    for i, line in enumerate(lines):
        if line.strip() == "":
            body_start = i + 1  # body starts on the next line (1-indexed)
            break
        if ":" not in line:
            # Malformed header line — leave it to the validator to complain.
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key:
            # First occurrence wins; duplicates are flagged by the validator.
            header.setdefault(key, (i + 1, value))
            if i == 0 and key == "Short":
                short_on_first_line = True

    body = "\n".join(lines[body_start:]) if body_start < len(lines) else ""
    return ParsedReadme(
        header=header,
        body=body,
        body_start_line=body_start + 1,
        short_on_first_line=short_on_first_line,
        has_crlf=has_crlf,
    )


def _validate_architecture(line_no: int, value: str) -> list[Issue]:
    issues: list[Issue] = []
    entries = [e for e in value.split(";")]
    if not entries or all(not e.strip() for e in entries):
        return [Issue("error", "Architecture field is empty", line_no)]
    for entry in entries:
        if not entry.strip():
            issues.append(Issue("error", "Empty architecture entry (stray semicolon?)", line_no))
            continue
        m = ARCH_ENTRY_PATTERN.match(entry)
        if not m:
            issues.append(
                Issue(
                    "error",
                    f'Cannot parse architecture entry "{entry.strip()}"; '
                    f"expected ARCH [>=|<=|>|<|= VERSION]",
                    line_no,
                )
            )
            continue
        arch = m.group("arch")
        if arch not in KNOWN_ARCHITECTURES:
            issues.append(
                Issue(
                    "error",
                    f'Unknown architecture "{arch}". Known: '
                    f"{', '.join(sorted(KNOWN_ARCHITECTURES))}",
                    line_no,
                )
            )
    return issues


def _ext_of(name: str) -> str:
    lower = name.lower()
    for ext in (".tar.gz", ".tar.bz2"):
        if lower.endswith(ext):
            return ext
    dot = lower.rfind(".")
    return lower[dot:] if dot != -1 else ""


def extract_uploader_email(uploader_value: str) -> str | None:
    """Pull the first email-like token out of an `Uploader:` field value.

    Accepts plain `name@host.tld`, with a display-name parenthetical
    (`name@host.tld (Name)`), or RFC2822 angle brackets (`Name <name@host.tld>`).
    Returns None if no email-like substring is present.
    """
    m = EMAIL_PATTERN.search(uploader_value)
    return m.group(0) if m else None


def validate_filename(name: str) -> list[Issue]:
    issues: list[Issue] = []
    if len(name) > MAX_FILENAME_LENGTH:
        issues.append(
            Issue(
                "error",
                f'Filename "{name}" is {len(name)} characters; max is {MAX_FILENAME_LENGTH}',
            )
        )
    if not FILENAME_PATTERN.match(name):
        issues.append(
            Issue(
                "error",
                f'Filename "{name}" contains characters outside [A-Za-z0-9._-]',
            )
        )
    return issues


def validate_upload_extension(name: str) -> list[Issue]:
    ext = _ext_of(name)
    if ext not in ACCEPTED_EXTENSIONS:
        return [
            Issue(
                "error",
                f'Upload extension "{ext or "(none)"}" not accepted by Aminet. '
                f"Accepted: {', '.join(ACCEPTED_EXTENSIONS)}",
            )
        ]
    return []


def validate(parsed: ParsedReadme, category: str) -> list[Issue]:
    issues: list[Issue] = []

    for f in REQUIRED_FIELDS:
        if f not in parsed.header:
            issues.append(Issue("error", f"Missing required field: {f}"))

    if "Short" in parsed.header:
        line, value = parsed.header["Short"]
        if len(value) > MAX_SHORT_LENGTH:
            issues.append(
                Issue(
                    "error",
                    f"Short description is {len(value)} characters; max is {MAX_SHORT_LENGTH}",
                    line,
                )
            )
        if not parsed.short_on_first_line:
            issues.append(
                Issue(
                    "warning",
                    "Short: should be the first line of the readme",
                    line,
                )
            )

    if "Type" in parsed.header:
        line, value = parsed.header["Type"]
        if value != category:
            issues.append(
                Issue(
                    "error",
                    f'Type "{value}" does not match the category input "{category}"',
                    line,
                )
            )

    if "Architecture" in parsed.header:
        line, value = parsed.header["Architecture"]
        issues.extend(_validate_architecture(line, value))

    if "Distribution" in parsed.header:
        line, value = parsed.header["Distribution"]
        if value not in VALID_DISTRIBUTION:
            issues.append(
                Issue(
                    "error",
                    f'Distribution "{value}" is not valid; expected NoCD or Aminet',
                    line,
                )
            )

    for f in RECOMMENDED_FIELDS:
        if f not in parsed.header:
            issues.append(Issue("warning", f"Missing recommended field: {f}"))

    if parsed.has_crlf:
        issues.append(
            Issue(
                "warning",
                "Readme uses CR+LF line endings; Aminet expects LF only "
                "(the uploader will normalise before sending)",
            )
        )

    for offset, line in enumerate(parsed.body.split("\n")):
        if len(line) > MAX_BODY_LINE_LENGTH:
            issues.append(
                Issue(
                    "warning",
                    f"Body line is {len(line)} characters; Aminet recommends "
                    f"≤ {MAX_BODY_LINE_LENGTH}",
                    parsed.body_start_line + offset,
                )
            )

    return issues


def inject_version(text: str, version: str) -> str:
    """Rewrite the Version: line in `text` to `version`. If no Version: line
    exists, insert one at the end of the header (before the blank-line
    separator). Preserves whatever line endings the input used."""
    newline = "\r\n" if "\r\n" in text else "\n"
    # Work on logical lines without the trailing newline.
    lines = text.replace("\r\n", "\n").split("\n")

    last_header_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == "":
            break
        last_header_idx = i
        if ":" not in line:
            continue
        key, sep, value = line.partition(":")
        if key.strip() == "Version":
            # Preserve the whitespace padding after the colon, if any.
            padding = value[: len(value) - len(value.lstrip())] or " "
            lines[i] = f"{key}{sep}{padding}{version}"
            return newline.join(lines)

    insert_at = last_header_idx + 1 if last_header_idx >= 0 else 0
    lines.insert(insert_at, f"Version: {version}")
    return newline.join(lines)
