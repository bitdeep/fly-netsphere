#!/usr/bin/env bash
# Download the pretrained flybody policies and the flight-imitation dataset into ./data.
# Source: flybody Figshare deposit, https://doi.org/10.25378/janelia.25309105
#
#   scripts/fetch_data.sh            # populate data/policies and data/flight (skips what exists)
#   scripts/fetch_data.sh --force    # re-download everything
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
FORCE="${1:-}"
mkdir -p "$DATA"

fetch() { # name url sha256 dest-dir marker
  local name="$1" url="$2" sha="$3" dest="$4" marker="$5" zip="$DATA/$1"
  if [ -e "$dest/$marker" ] && [ "$FORCE" != "--force" ]; then echo "data: $dest present, skipping"; return; fi
  if [ ! -f "$zip" ] || [ "$FORCE" = "--force" ]; then
    echo "data: downloading $name"; curl -fL --retry 3 -o "$zip" "$url"
  fi
  echo "$sha  $zip" | sha256sum -c - >/dev/null
  mkdir -p "$dest"; unzip -q -o "$zip" -d "$dest"
  echo "data: $name -> $dest"
}

fetch trained-fly-policies.zip \
  https://ndownloader.figshare.com/files/44815195 \
  2d9937c9af2baafad1690c1b318791bde417b4d26dd96d4385ab6723d5d58582 \
  "$DATA/policies" flight/saved_model.pb
fetch datasets_flight-imitation.zip \
  https://ndownloader.figshare.com/files/51196859 \
  0d152331e38f2ca6bb1f3286c2500eab49b5ccef93c51a9cc9cff9bb6cd368d0 \
  "$DATA/flight" wing_pattern_fmech.npy
echo "data: done"
