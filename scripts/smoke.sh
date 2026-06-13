#!/usr/bin/env bash
# End-to-end FTP smoke test.
#
# Brings up an anonymous-write pyftpdlib on localhost, runs the action's
# entrypoint against it, and asserts that both files arrived in /new with
# LF-only line endings on the readme.
#
# Used by `make smoke` and by the ftp-smoke CI job — identical recipe in
# both places.
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"
FTPROOT="${FTPROOT:-/tmp/aminet-smoke}"
FTPPORT="${FTPPORT:-2121}"

cleanup() {
  if [[ -n "${FTP_PID:-}" ]]; then
    kill "$FTP_PID" 2>/dev/null || true
    wait "$FTP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

rm -rf "$FTPROOT"
mkdir -p "$FTPROOT/new"

"$PYTHON" -m pyftpdlib \
  --port "$FTPPORT" \
  --directory "$FTPROOT" \
  --write &
FTP_PID=$!

# Give pyftpdlib a beat to bind. Verified locally as enough.
sleep 1

env \
  "INPUT_FILENAME=tests/fixtures/smoke/test.lha" \
  "INPUT_README=tests/fixtures/smoke/test.readme" \
  "INPUT_CATEGORY=util/misc" \
  "INPUT_UPLOADER-EMAIL=ci@example.com" \
  "INPUT_FTP-HOST=localhost:${FTPPORT}" \
  "$PYTHON" action/entrypoint.py

test -s "$FTPROOT/new/test.lha"
test -s "$FTPROOT/new/test.readme"

# Readme on the wire must be LF-only — uploader should normalise CRLF input.
if LC_ALL=C grep -lU $'\r' "$FTPROOT/new/test.readme" > /dev/null; then
  echo "uploaded readme contains CR — normalisation failed" >&2
  exit 1
fi

echo "smoke test OK"
