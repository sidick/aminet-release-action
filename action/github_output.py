"""GitHub Actions output helpers: workflow-command annotations and step summary."""

from __future__ import annotations

import os
from typing import Optional


def _emit(level: str, message: str, file: Optional[str], line: Optional[int]) -> None:
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


def error(message: str, file: Optional[str] = None, line: Optional[int] = None) -> None:
    _emit("error", message, file, line)


def warning(message: str, file: Optional[str] = None, line: Optional[int] = None) -> None:
    _emit("warning", message, file, line)


def notice(message: str, file: Optional[str] = None, line: Optional[int] = None) -> None:
    _emit("notice", message, file, line)


def summary(markdown: str) -> None:
    """Append to the job's step summary, if the runner has set GITHUB_STEP_SUMMARY."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(markdown)
        if not markdown.endswith("\n"):
            fh.write("\n")
