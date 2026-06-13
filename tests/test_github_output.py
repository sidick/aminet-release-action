"""Tests for the GitHub Actions annotation/output helpers."""

from __future__ import annotations

import github_output


def test_error_with_file_and_line(capsys):
    github_output.error("Short description too long", file="MyTool.readme", line=3)
    out = capsys.readouterr().out
    assert out.rstrip("\n") == "::error file=MyTool.readme,line=3::Short description too long"


def test_warning_without_location(capsys):
    github_output.warning("recommended field missing")
    out = capsys.readouterr().out
    assert out.rstrip("\n") == "::warning::recommended field missing"


def test_notice_with_only_file(capsys):
    github_output.notice("looks fine", file="x.readme")
    out = capsys.readouterr().out
    assert out.rstrip("\n") == "::notice file=x.readme::looks fine"


def test_line_zero_is_included(capsys):
    """line=0 is a real line number and should not be skipped as falsy."""
    github_output.error("oops", file="x", line=0)
    out = capsys.readouterr().out
    assert "line=0" in out


def test_double_colon_in_message_is_escaped(capsys):
    """:: would break the parser by introducing a second delimiter."""
    github_output.error("there are :: marks here")
    out = capsys.readouterr().out
    # Everything after the closing ::-delimiter is the safe message.
    _, _, body = out.partition("::error::")
    assert "::" not in body


def test_summary_appends_to_step_summary(tmp_path, monkeypatch):
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    github_output.summary("## first\n")
    github_output.summary("## second")
    content = target.read_text()
    assert content == "## first\n## second\n"


def test_summary_silent_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    # Should not raise.
    github_output.summary("anything")
