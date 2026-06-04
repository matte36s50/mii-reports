"""Central configuration for the DuPont Registry -> MII scraper.

All knobs live here so the rest of the pipeline reads from a single place.
Secrets come from the environment (loaded from a gitignored .env file).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env sitting next to this file (if present).
load_dotenv(Path(__file__).resolve().parent / ".env")

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_OUTPUT = ROOT / "data" / "output"
AUTH_STATE = Path(__file__).resolve().parent / ".auth" / "state.json"

for _p in (DATA_RAW, DATA_OUTPUT, AUTH_STATE.parent):
    _p.mkdir(parents=True, exist_ok=True)

# --- Credentials -----------------------------------------------------------
USERNAME = os.getenv("DR_USERNAME", "")
PASSWORD = os.getenv("DR_PASSWORD", "")

# --- Target site -----------------------------------------------------------
BASE_URL = "https://live.dupontregistry.com"
LOGIN_URL = os.getenv("DR_LOGIN_URL", f"{BASE_URL}/login")
LISTINGS_URL = os.getenv(
    "DR_LISTINGS_URL",
    f"{BASE_URL}/listings/sold/filter:sort=bid_high",
)

# --- Runtime knobs ---------------------------------------------------------
HEADLESS = os.getenv("DR_HEADLESS", "true").lower() != "false"
MAX_PAGES = int(os.getenv("DR_MAX_PAGES", "20"))
NAV_TIMEOUT_MS = int(os.getenv("DR_NAV_TIMEOUT_MS", "45000"))
SCROLL_PAUSE_MS = int(os.getenv("DR_SCROLL_PAUSE_MS", "1200"))

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
