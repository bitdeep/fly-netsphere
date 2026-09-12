#!/usr/bin/env bash
set -euo pipefail
seconds="${1:-60}"
take="${2:-out/city_$(date -u +%Y%m%dT%H%M%SZ)}"
view="${3:-first-person}"
python scripts/run_city.py --seconds "$seconds" --output "$take"
python scripts/render_city.py "$take" --view "$view"
python scripts/verify_take.py "$take" --seconds "$seconds"
