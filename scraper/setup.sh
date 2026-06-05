#!/usr/bin/env bash
# One-command local setup for the DuPont Registry -> MII scraper.
# Run from the repo root:  bash scraper/setup.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Installing Python dependencies"
python3 -m pip install -r requirements.txt

echo "==> Installing the Chromium browser for Playwright"
python3 -m playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created scraper/.env  --  EDIT IT and add your DuPont login:"
  echo "      DR_USERNAME=...   DR_PASSWORD=..."
else
  echo "==> scraper/.env already exists (leaving it as-is)"
fi

cat <<'NEXT'

Setup complete. Next:
  1. Edit scraper/.env with your DuPont Registry credentials.
  2. Run:   python3 scraper/run.py
  3. Preview results locally:
       python3 -m http.server 8000
       open  http://localhost:8000/index.html?data=data/output/mii_results_latest.csv
NEXT
