# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Docker-based GitHub Action that takes a pre-built Aminet upload (any
Aminet-accepted file type, not just `.lha`) plus its `.readme`, validates the
readme against Aminet conventions, uploads both via **anonymous FTP to
`main.aminet.net:/new`**, and (when run on a tag) attaches them to the
corresponding GitHub Release. Packaging the upload is explicitly out of
scope — the user's own build step produces it.

The code under `action/` and the user-facing `README.md` are the source of
truth. The Aminet wiki is the upstream spec for the readme format and the
upload procedure — when behaviour and wiki disagree, the wiki wins and the
code/README get updated to match:

- <https://wiki.aminet.net/The_Readme_file>
- <https://wiki.aminet.net/Uploading_instructions>

## Architecture notes that aren't obvious from the file tree

- **Single-language by design.** Everything orchestration-side is Python
  stdlib only; `lftp` is the only non-Python dependency and is used purely as
  a subprocess for its retry / passive-mode handling. The GitHub API client
  uses `urllib`, not `requests`, to keep the image lean.
- **Inputs arrive as `INPUT_*` env vars.** GitHub Actions maps `with:` keys
  to env vars, uppercasing and preserving hyphens (`uploader-email` →
  `INPUT_UPLOADER-EMAIL`). `entrypoint.py` reads these directly rather than
  taking CLI args.
- **Exit codes are part of the contract**, not just diagnostics: `0`
  success, `1` validation failure, `2` upload failure. Don't collapse these
  or invent new ones without updating the README's "Exit codes" table.
- **FTP is anonymous, destination is fixed.** Anonymous FTP, password =
  `uploader-email` input, destination is always `/new` (regardless of
  category). The category input is used only to cross-check the readme's
  `Type:` field. The `ftp-host` input exists for debugging — defaults to
  `main.aminet.net`.
- **Readme validation is structural.** Aminet `.readme` files are a
  `Key: Value` header block followed by a blank line and free-text body. The
  validator splits on the first blank line. Required fields per the wiki:
  `Short` (≤40 chars, must be line 1), `Uploader`, `Type` (must equal the
  `category` input), `Architecture`. `Architecture` parses the full
  `ARCH [MOD VER] [; ARCH ...]` syntax.
- **Body line length and CR+LF are warnings, not errors.** The uploader
  silently normalises CR+LF → LF before sending so the wire format is always
  correct, regardless of what was authored.
- **Errors surface via GitHub annotation syntax** (`::error file=…,line=…::`)
  so they render inline in the PR UI. `github_output.py` owns this format —
  don't scatter `print("::error::")` calls through the codebase.
- **`inject-version: true`** rewrites the readme's `Version:` field *before*
  validation, deriving the version from `GITHUB_REF` (strip `refs/tags/` and
  a leading `v`). Without a tag ref, this is a hard error.
- **`validate-only: true`** is the PR-check path: validate and exit;
  `uploader-email` is not required in this mode.
- **`check-requires: true`** is opt-in. It HTTP-HEADs each file-path entry
  in the readme's `Requires:` field against `aminet.net` to catch dangling
  references. Free-text entries like `1MB RAM` are skipped silently. Lives
  in its own `requires_checker.py` so the validator stays pure and
  network-free.
- **Distribution is via GHCR**, not rebuild-from-source. `action.yml`
  currently points at the local Dockerfile for development; the release
  workflow will switch it to `docker://ghcr.io/...:vN`.

## Layout

```
action.yml              # action metadata
action/
  Dockerfile            # python:3.12-alpine + lftp
  entrypoint.py         # INPUT_* parsing, orchestration, exit codes
  readme_validator.py   # parse + validate + inject_version (pure logic)
  requires_checker.py   # HTTP-HEAD check for Requires: entries (opt-in)
  ftp_uploader.py       # lftp subprocess wrapper
  github_output.py      # ::error::/::warning::/::notice::, step summary
  github_release.py     # release lookup + asset upload (urllib)
tests/
  test_*.py             # 93 tests covering all of the above
  fixtures/
    readmes/{valid,invalid}/  # one fixture per validator failure mode
    smoke/                    # used by the CI FTP smoke job
.github/workflows/ci.yml      # unit tests + docker build + FTP smoke
```

## Commands

Everything goes through the Makefile — same targets locally and in CI:

- `make` — list targets
- `make test` — pytest (auto-creates `.venv` on first run, ~0.1s)
- `make compile` — `py_compile` syntax sweep
- `make docker-build` — build the action image as `aminet-release-action:dev`
- `make smoke` — end-to-end FTP smoke test (spawns pyftpdlib on `:2121`,
  runs the entrypoint against it, asserts both files land in `/new` with
  LF-only readme); requires `lftp` (`brew install lftp` / `apt install lftp`)
- `make ci` — everything (compile + test + docker-build + smoke)
- `make clean` — wipe `.venv`, caches, and `__pycache__`

Override `PYTHON=python3` (or any path) to bypass the `.venv` for a single
invocation. The smoke recipe lives in `scripts/smoke.sh` so the Makefile
stays portable (no need for `.ONESHELL`); CI calls `make smoke` directly,
so local and CI run the exact same script.

CI (`.github/workflows/ci.yml`) is just three `make` calls across three
parallel jobs: `unit-tests` (compile + test), `docker-build`, and
`ftp-smoke` (lftp via apt + smoke).
