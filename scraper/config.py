"""Central configuration for the DuPont Registry -> MII scraper.

Sold listings are public, so no credentials are required. Everything the rest
of the pipeline needs lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ModuleNotFoundError:  # python-dotenv is optional now
    pass

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_OUTPUT = ROOT / "data" / "output"

for _p in (DATA_RAW, DATA_OUTPUT):
    _p.mkdir(parents=True, exist_ok=True)

# --- Target site -----------------------------------------------------------
BASE_URL = "https://live.dupontregistry.com"
LISTINGS_URL = os.getenv(
    "DR_LISTINGS_URL",
    f"{BASE_URL}/listings/sold/filter:sort=bid_high",
)

# --- Runtime knobs ---------------------------------------------------------
MAX_PAGES = int(os.getenv("DR_MAX_PAGES", "30"))   # safety cap (17 pages today)
NAV_TIMEOUT_MS = int(os.getenv("DR_NAV_TIMEOUT_MS", "45000"))

# --- MII index (the file the dashboard reads) ------------------------------
# Read-only source of truth used to keep DuPont rows on the same scale.
MII_CSV_URL = (
    "https://my-mii-reports.s3.amazonaws.com/reports/mii_results_latest.csv"
)

# MII formula weights (must sum to 1.0). Mirrors the dashboard methodology.
MII_WEIGHTS = {
    "price": 0.30,
    "bids": 0.30,
    "views": 0.20,
    "comments": 0.12,
    "social_score": 0.05,
    "age": 0.03,
}

DATA_SOURCE_LABEL = "DuPont Registry"
