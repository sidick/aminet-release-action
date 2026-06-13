# aminet-release-action — project plan

## Purpose

A GitHub Action that takes a pre-built Aminet upload and handles validation,
upload, and release asset attachment. It does not build archives — that is
left to the user's own build step, as packaging preferences vary too much to
support generically.

The input is named `filename` (not `archive`) because Aminet accepts
pictures, audio, video, and documents too — not just archives. The validator
checks the extension against the accepted list (see "Accepted file types"
below) rather than requiring `.lha` specifically.

Authoritative references:

- Readme format: <https://wiki.aminet.net/The_Readme_file>
- Upload procedure: <https://wiki.aminet.net/Uploading_instructions>

If those pages and this document disagree, the wiki wins — update this plan
to match.

## Inputs

| Input | Description |
|---|---|
| `filename` | Path to the file to upload (`.lha` typical; see "Accepted file types") |
| `readme` | Path to the Aminet-format `.readme` file |
| `category` | Aminet category, e.g. `util/misc`, `dev/c` |
| `uploader-email` | Your email address. Used as the FTP password for anonymous upload. Required unless `validate-only` |
| `inject-version` | If `true`, overwrite `Version:` field from the git tag |
| `validate-only` | If `true`, validate the readme but skip upload |
| `check-requires` | If `true`, HTTP-HEAD each file-path entry in `Requires:` against `aminet.net` |
| `ftp-host` | FTP hostname (default `main.aminet.net`). Override only for testing |

## Implementation

### Runtime

Docker-based action using an Alpine base image (small, fast pulls). Python
throughout — single language for orchestration, validation, and upload. `lftp`
installed in the container for FTP upload (provides retry logic and passive
mode handling out of the box).

### Module structure

```
action/
├── Dockerfile
├── entrypoint.py        # arg parsing, orchestration, exit codes
├── readme_validator.py  # field parsing and validation rules
├── ftp_uploader.py      # lftp subprocess wrapper
├── github_output.py     # job summary, ::error:: / ::notice:: annotations
└── github_release.py    # release lookup + asset upload via the GitHub API
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Validation failure |
| 2 | Upload failure |

### README validation rules

Aminet readmes are a header block of `Key: Value` lines followed by a blank
line and a free-text body. Per the wiki:

- **`Short:` must be the first line.** Max 40 characters. Describes what the
  program does (not filename, version, or platform).
- **Required fields:** `Short`, `Uploader`, `Type`, `Architecture`.
- **Optional fields the validator recognises:** `Author`, `Version`,
  `Distribution` (`NoCD` or `Aminet`), `Kurz`, `Requires`, `Replaces`.
- **`Type:` must equal the `category` input.** Mismatch is an error — the
  category determines nothing about the upload path (everything goes to
  `/new`), but the readme must declare its destination directory honestly.
- **`Architecture:`** follows
  `ARCH1 [MODIFIER VERSION] [; ARCH2 [MODIFIER VERSION] ...]`, with
  modifiers `>=`, `>`, `=`, `<`, `<=` and semicolons separating multiple
  architectures. Recognised arch names:
  `m68k-amigaos`, `ppc-amigaos`, `ppc-morphos`, `ppc-powerup`, `ppc-warpup`,
  `i386-aros`, `i386-amithlon`, `generic`.
- **Body lines should be ≤ 78 characters.** Longer lines surface as warnings,
  not errors.
- **Line endings must be LF only.** CR+LF surfaces as a warning; the
  uploader normalises to LF before uploading so the wire-format is always
  correct.
- **Recommended but not required:** `Author`, `Version`. Missing → warning.

### Filename rules

Per the wiki, filenames must be ≤ 30 characters and contain only
`[a-zA-Z0-9._-]`. The validator checks the basenames of both the upload
file and the readme.

### Accepted file types

The upload file extension must be one of (per the wiki):

- Archives: `.lha`, `.run`, `.zip`
- Disk images: `.adf`, `.adz`
- Tarballs: `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`
- Pictures: `.jpg`, `.png`, `.gif`
- Documents: `.pdf`, `.txt`
- Audio: `.ogg`, `.mp3`
- Video: `.mpg`

The readme must always be a sibling `.readme` file.

### GitHub annotations

Validation errors are written to stdout using the Actions annotation syntax so
they surface inline in the PR UI:

```
::error file=MyTool.readme,line=3::Short description exceeds 40 characters
```

`github_output.py` owns this format. Don't scatter `print("::error::")`
calls through the codebase.

### FTP upload

Both the upload file and the `.readme` are uploaded to `main.aminet.net` via `lftp`,
using anonymous FTP into `/new`:

- Username: `anonymous`
- Password: `uploader-email` input (your email address)
- Destination: `/new/` (single staging directory; the readme's `Type:`
  field tells Aminet which category to file it under)

The password is passed to lftp via stdin to keep it out of process listings.

### GitHub Release attachment

If the workflow is running on a tag push and a matching GitHub Release
exists, the action attaches the upload file and `.readme` as release assets. Looks
up the release by exact tag name first, then with a `v` prefix removed if
that fails.

### Validate-only mode

Setting `validate-only: true` runs readme validation and exits without
uploading. Intended for use in PR checks so malformed readmes are caught
before release time. `uploader-email` is not required in this mode.

### Requires: existence check (opt-in)

When `check-requires: true`, the action HTTP-HEADs each file-path entry in
the `Requires:` field against `https://aminet.net/<path>`.

- Entries are split by `;` (same as `Replaces:`).
- An entry is treated as a file path if it contains `/` and ends in one of
  the accepted file extensions. Non-file entries (e.g. memory or chipset
  requirements like `1MB RAM`) are skipped silently.
- HTTP 404 surfaces as an error issue.
- Other HTTP/connection failures surface as warnings — we couldn't verify,
  but that's not the same as "definitely broken."
- Lives in a separate module (`requires_checker.py`) so the validator
  stays pure and network-free.

Off by default because it adds a network dependency at validation time and
because a `Requires:` entry may legitimately point at another package being
uploaded in the same release.

### inject-version

When `inject-version: true`, the action derives a version string from
`GITHUB_REF` (`refs/tags/<tag>`, stripping a leading `v`) and rewrites the
`Version:` line in the readme on disk **before** validation. If no
`Version:` field exists, one is inserted at the end of the header. Without a
tag ref, this is a hard error.

## Testing

The validator is the largest piece of pure logic in the action, so it gets
the most test coverage. Fixtures live under `tests/fixtures/readmes/`:

- `valid/` — minimum and fully-populated readmes that must pass clean. Used
  as a regression net: any change that turns a valid readme into an
  error/warning shows up here.
- `invalid/` — one readme per failure mode the validator is supposed to
  catch, each named for the rule it violates. The test asserts both that
  validation fails and that the specific expected `Issue` (level + substring
  of message) is present, so a regression that downgrades an error to a
  warning — or misses it entirely — is caught.

Failure modes to cover (one fixture each, at minimum):

- `missing_short.readme`, `missing_uploader.readme`, `missing_type.readme`,
  `missing_architecture.readme` — each required field absent
- `short_too_long.readme` — Short: > 40 chars
- `short_not_first.readme` — Short: present but not on line 1
- `type_mismatch.readme` — Type: disagrees with the `category` test arg
- `unknown_architecture.readme` — arch name not in the known set
- `malformed_architecture.readme` — syntax the parser can't handle
- `bad_distribution.readme` — Distribution: value other than `NoCD`/`Aminet`
- `long_body_line.readme` — body line > 78 chars (warning)

CRLF gets its own test but no fixture file: managing CR+LF bytes on disk
across editors is sketchy, so the test takes the LF-only minimum fixture and
mutates it to CR+LF in memory before parsing.

Filename validation has its own table-driven test (no fixtures needed): too
long, illegal characters, accepted/rejected extensions.

Test runner: `pytest`. Dev dependencies in `requirements-dev.txt`. The
container itself doesn't include pytest — tests run on the host.

## CI

`.github/workflows/ci.yml` runs on push and PR:

1. **Unit tests** — `pip install -r requirements-dev.txt`, `pytest`. Plus
   `python -m py_compile action/*.py` as a syntax-only sanity check that
   doesn't depend on pytest discovery.
2. **Docker build** — `docker build action/` to catch Dockerfile
   regressions. No image push from CI; that happens from a separate
   release workflow.
3. **FTP smoke test** — bring up `pyftpdlib` on localhost as anonymous
   write-enabled, then run `entrypoint.py` against it with `ftp-host:
   localhost` and a real fixture pair. The test asserts that both files
   land in the dummy server's `/new/` directory with correct contents.
   `lftp` gets installed via apt on the runner; we don't need Docker for
   this since we're running `entrypoint.py` directly and just need `lftp`
   in PATH.

Smoke-test fixtures live under `tests/fixtures/smoke/` — separate from
the validator fixtures because they need to satisfy filename and extension
rules as well as readme rules.

## Example workflow

```yaml
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build (user's own step)
        run: make dist

      - uses: your-handle/aminet-release-action@v1
        with:
          filename: dist/MyTool.lha
          readme: dist/MyTool.readme
          category: util/misc
          uploader-email: ${{ secrets.AMINET_UPLOADER_EMAIL }}
          inject-version: true
```

## Tagging and release

Actions are consumed by tag (`@v1`, `@v1.2.3`). Publish the Docker image to
GHCR and reference it directly in `action.yml` to avoid rebuilding on every
run:

```yaml
runs:
  using: docker
  image: docker://ghcr.io/your-handle/aminet-release-action:v1
```

During development, `action.yml` points at the local Dockerfile so changes
take effect without a push.
