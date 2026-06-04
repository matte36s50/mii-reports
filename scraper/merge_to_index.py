"""Merge scraped DuPont rows into the MII index CSV.

Steps:
  1. Download the current MII index from S3 (read-only reference).
  2. Score the DuPont rows on the same scale (see mii_transform).
  3. Drop any prior DuPont rows for the same quarters, then concat.
  4. Write data/output/mii_results_latest.csv for you to upload to S3.

This script never writes to S3 itself — uploading the result is a deliberate,
manual step so a bad scrape can't clobber the live dashboard.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd
import requests

import config
import mii_transform


def load_reference() -> pd.DataFrame:
    print(f"[merge] Fetching current index: {config.MII_CSV_URL}")
    resp = requests.get(config.MII_CSV_URL, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def latest_raw() -> Path:
    files = sorted(config.DATA_RAW.glob("dupont_listings_*.json"))
    if not files:
        raise SystemExit("No scraped data found. Run dupont_scraper.py first.")
    return files[-1]


def merge(raw_path: Path | None = None) -> Path:
    reference = load_reference()
    raw_path = raw_path or latest_raw()
    raw_rows = json.loads(raw_path.read_text())
    print(f"[merge] Loaded {len(raw_rows)} DuPont listing(s) from {raw_path.name}")

    records = mii_transform.raw_to_records(raw_rows)
    scored = mii_transform.score(records, reference)

    # Replace any existing DuPont rows for the quarters we just scraped so
    # re-runs are idempotent rather than duplicating.
    existing = reference.copy()
    if "data_source" in existing and "quarter" in existing:
        scraped_quarters = set(scored["quarter"].unique())
        mask = (existing["data_source"] == config.DATA_SOURCE_LABEL) & (
            existing["quarter"].isin(scraped_quarters))
        existing = existing[~mask]

    combined = pd.concat([existing, scored], ignore_index=True)
    out = config.DATA_OUTPUT / "mii_results_latest.csv"
    combined.to_csv(out, index=False)
    print(f"[merge] Wrote {len(combined)} rows ({len(scored)} new DuPont) -> {out}")
    print("[merge] Review it, then upload to S3 as reports/mii_results_latest.csv")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, help="Specific raw JSON file to merge")
    merge(ap.parse_args().raw)
