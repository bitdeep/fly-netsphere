#!/usr/bin/env bash
# Download the pinned flybody source tree into ./flybody and apply the local patch.
# flybody (Apache-2.0, Google DeepMind + HHMI Janelia) is not vendored in this repository.
#
#   scripts/fetch_flybody.sh            # populate ./flybody (no-op if already present)
#   scripts/fetch_flybody.sh --force    # re-download and re-apply the patch
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMIT=d015e9bfe441bd90ae431bac24c55cb74bdbce26
TARBALL_URL="https://codeload.github.com/TuragaLab/flybody/tar.gz/${COMMIT}"
TARBALL_SHA256=766c5c68ce700b35dc6fb19d324c97c76a4c0dcc804c77d898483d2416efae96
DEST="$ROOT/flybody"
STAMP="$DEST/.fetched-${COMMIT}"
PATCH="$ROOT/patches/flybody-lazy-plot-imports.patch"

if [ -f "$STAMP" ] && [ "${1:-}" != "--force" ]; then
  echo "flybody: already at ${COMMIT:0:12} ($DEST); use --force to refresh"; exit 0
fi
if [ -e "$DEST" ] && [ "${1:-}" != "--force" ]; then
  echo "flybody: $DEST exists but has no stamp; refusing to overwrite (use --force)" >&2; exit 1
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/flybody.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
echo "flybody: downloading TuragaLab/flybody@${COMMIT:0:12}"
curl -fsSL --retry 3 -o "$tmp/flybody.tar.gz" "$TARBALL_URL"
echo "${TARBALL_SHA256}  $tmp/flybody.tar.gz" | sha256sum -c - >/dev/null
mkdir -p "$tmp/src"
tar -xzf "$tmp/flybody.tar.gz" -C "$tmp/src" --strip-components=1
patch -p1 -d "$tmp/src" --no-backup-if-mismatch < "$PATCH"

[ -e "$DEST" ] && rm -rf "$DEST"
mv "$tmp/src" "$DEST"
touch "$STAMP"
echo "flybody: ready at $DEST (commit ${COMMIT:0:12}, patch applied)"
