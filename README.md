# aminet-release-action

A GitHub Action that validates a pre-built Aminet upload (`.lha`/`.zip`/etc. plus a `.readme`), uploads it to Aminet via anonymous FTP, and optionally attaches both files to a matching GitHub Release.

Packaging the archive is out of scope — bring your own build step.

## Features

- **Readme validation** against the [Aminet wiki spec](https://wiki.aminet.net/The_Readme_file): required fields, `Short:` length, multi-architecture syntax (e.g. `m68k-amigaos; ppc-morphos >= 1.4.0`), distribution values, filename rules, body line length.
- **Anonymous FTP upload** to `main.aminet.net:/new` per the [Aminet upload procedure](https://wiki.aminet.net/Uploading_instructions). CR+LF readmes are silently normalised to LF on the wire.
- **Inline PR annotations** — validation failures surface as `::error::` / `::warning::` annotations in the GitHub UI with file/line locations.
- **Optional `inject-version`** rewrites the readme's `Version:` field from the git tag before validation.
- **Optional `check-requires`** HTTP-HEADs file-path entries in the readme's `Requires:` field against aminet.net to catch typos and dangling references.
- **Release asset attachment** — on tag pushes, attaches the upload file and `.readme` to the matching GitHub Release.

## Usage

### Release workflow (tag-driven upload)

```yaml
name: Release
on:
  push:
    tags: ['v*']

permissions:
  contents: write   # needed to attach the upload to the GitHub Release

jobs:
  aminet:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - name: Build the archive
        run: make dist   # whatever produces dist/MyTool.lha + dist/MyTool.readme

      - uses: sidick/aminet-release-action@v1
        with:
          filename: dist/MyTool.lha
          readme: dist/MyTool.readme
          category: util/misc
          uploader-email: ${{ secrets.AMINET_UPLOADER_EMAIL }}
          inject-version: true
```

### Pull-request check (validate without uploading)

```yaml
name: Validate
on: [pull_request]
jobs:
  readme:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - run: make dist
      - uses: sidick/aminet-release-action@v1
        with:
          filename: dist/MyTool.lha
          readme: dist/MyTool.readme
          category: util/misc
          validate-only: true
          check-requires: true
```

`uploader-email` is not required when `validate-only: true`.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `filename` | yes | — | Path to the file to upload. Aminet accepts archives (`.lha`, `.run`, `.zip`), tarballs (`.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`), disk images (`.adf`, `.adz`), pictures (`.jpg`, `.png`, `.gif`), documents (`.pdf`, `.txt`), audio (`.ogg`, `.mp3`), and video (`.mpg`). |
| `readme` | yes | — | Path to the Aminet-format `.readme` file. |
| `category` | yes | — | Aminet category, e.g. `util/misc`, `dev/c`. Must match the `Type:` field in the readme. |
| `uploader-email` | no | `''` | Your email address. Used as the FTP password for anonymous upload. If omitted, the action extracts an email from the readme's `Uploader:` field. Fails before upload only if neither source yields one. |
| `inject-version` | no | `false` | If `true`, rewrites the readme's `Version:` field from the git tag (strips a leading `v`) before validation. Hard error if not run on a tag push. |
| `validate-only` | no | `false` | If `true`, validate the readme and exit; skip upload and release-asset attachment. |
| `check-requires` | no | `false` | If `true`, HTTP-HEAD each file-path entry in `Requires:` against `aminet.net`. 404 → error; other failures → warning. Off by default because it adds a network dependency at validation time. |
| `check-replaces` | no | `false` | If `true`, same HEAD-based check applied to the `Replaces:` field. Wildcard entries (`*`, `?`) are skipped — they can't be HEAD-checked meaningfully. |
| `ftp-host` | no | `main.aminet.net` | Accepts `host` or `host:port`. Override only for debugging — the default targets the real Aminet. |

## Filename rules

Per the wiki, upload filenames must be ≤ 30 characters and contain only `[A-Za-z0-9._-]`. Version numbers belong in the readme's `Version:` field, not the filename. The validator enforces both.

## GitHub Releases

When the workflow that calls the action is triggered by a **tag push** (`GITHUB_REF` starts with `refs/tags/`), the action looks for a matching GitHub Release and attaches the upload file and readme to it as release assets.

**Lookup order:**
1. Tag name verbatim (e.g. `v1.0.0`).
2. Tag name with a leading `v` stripped (e.g. `1.0.0`).
   This lets you tag with either convention; the action finds the release either way.

**Required permission:** the workflow needs `contents: write` so the action's `GITHUB_TOKEN` can upload release assets. The release workflow example above sets this.

**Graceful behaviour:**
- **No matching release** → a `notice` is logged ("No GitHub Release found for tag …; skipping asset attachment"). The action still exits with the Aminet upload result; the missing release is not a failure.
- **Asset upload fails** (transient API error, etc.) → a `warning` is logged. The action still exits successfully if the Aminet FTP upload succeeded — the release attachment is best-effort and never overrides the upload result.
- **Not a tag push** → the release attachment step is skipped entirely. No API calls are made.
- **`GITHUB_TOKEN` or `GITHUB_REPOSITORY` not in the environment** → a `warning` is logged and attachment is skipped.

The `release-attached` output (see below) is `true` only when both files were successfully attached.

## Outputs

| Output | Type | Description |
|---|---|---|
| `uploaded` | bool | `true` if the action actually uploaded the files to FTP. |
| `release-attached` | bool | `true` if both files were attached to a matching GitHub Release. |
| `errors` | int | Count of validation errors. |
| `warnings` | int | Count of validation warnings. |
| `filename` | string | Basename of the upload file (as it would land on Aminet). |
| `readme` | string | Basename of the readme file. |

Reference them in downstream steps as `steps.<id>.outputs.<name>`:

```yaml
      - id: aminet
        uses: sidick/aminet-release-action@v1
        with:
          filename: dist/MyTool.lha
          readme: dist/MyTool.readme
          category: util/misc
          uploader-email: ${{ secrets.AMINET_UPLOADER_EMAIL }}

      - if: steps.aminet.outputs.uploaded == 'true'
        run: echo "Shipped ${{ steps.aminet.outputs.filename }}"
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (or validation passed in `validate-only` mode) |
| 1 | Validation failure |
| 2 | Upload failure |

## How it works

See [`PLAN.md`](./PLAN.md) for the full design — module layout, validation rules, FTP procedure, CI strategy, and how to add tests.

For local development, [`CLAUDE.md`](./CLAUDE.md) documents the Makefile targets (`make test`, `make smoke`, `make ci`).

## License

[MIT](./LICENSE).
