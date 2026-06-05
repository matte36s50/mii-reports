#!/usr/bin/env bash
# One-command setup for the DuPont Registry -> MII scraper.
# Sold listings are public, so there are no credentials to configure.
# Run from the repo root:  bash scraper/setup.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Installing Python dependencies"
python3 -m pip install -r requirements.txt

cat <<'NEXT'

Setup complete. Next:
  1. Scrape + merge:   python3 scraper/run.py
  2. Preview results locally:
       python3 -m http.server 8000
       open  http://localhost:8000/index.html?data=data/output/mii_results_latest.csv
NEXT
