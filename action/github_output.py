"""GitHub Actions output helpers: workflow-command annotations and step summary."""

from __future__ import annotations

import os


def _emit(level: str, message: str, file: str | None, line: int | None) -> None:
    parts: list[str] = []
    if file:
        parts.append(f"file={file}")
    if line is not None:
        parts.append(f"line={line}")
    location = (" " + ",".join(parts)) if parts else ""
    # The Actions parser splits on the first "::" after the level keyword,
    # so the message itself must not contain "::" — replace defensively.
    safe = message.replace("::", ": ")
    print(f"::{level}{location}::{safe}", flush=True)


def error(message: str, file: str | None = None, line: int | None = None) -> None:
    _emit("error", message, file, line)


def warning(message: str, file: str | None = None, line: int | None = None) -> None:
    _emit("warning", message, file, line)


def notice(message: str, file: str | None = None, line: int | None = None) -> None:
    _emit("notice", message, file, line)


def set_output(name: str, value: str | bool | int) -> None:
    """Write `name=value` to $GITHUB_OUTPUT so downstream steps can read it
    as `steps.<id>.outputs.<name>`. No-op if GITHUB_OUTPUT isn't set.

    Bools become the strings `true`/`false` (GitHub convention). Ints are
    stringified. Multiline values use the heredoc form.
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    else:
        rendered = str(value)
    if "\n" in rendered:
        delim = "__AMINET_EOF__"
        line = f"{name}<<{delim}\n{rendered}\n{delim}\n"
    else:
        line = f"{name}={rendered}\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def summary(markdown: str) -> None:
    """Append to the job's step summary, if the runner has set GITHUB_STEP_SUMMARY."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(markdown)
        if not markdown.endswith("\n"):
            fh.write("\n")
