"""End-to-end: scrape DuPont sold listings, then merge into the MII index.

    python scraper/run.py            # scrape + merge
    python scraper/run.py --merge-only   # re-merge the latest scrape

Outputs data/output/mii_results_latest.csv for upload to S3.
"""
from __future__ import annotations

import argparse

import dupont_scraper
import merge_to_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge-only", action="store_true",
                    help="Skip scraping; merge the most recent raw file.")
    args = ap.parse_args()

    raw_path = None if args.merge_only else dupont_scraper.run()
    merge_to_index.merge(raw_path)


if __name__ == "__main__":
    main()
