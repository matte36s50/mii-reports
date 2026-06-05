"""End-to-end: scrape DuPont sold listings, optionally enrich, then merge.

    python scraper/run.py                 # scrape + merge (price-based)
    python scraper/run.py --enrich        # also fetch bid/watch counts per car
    python scraper/run.py --merge-only    # re-merge the latest scrape

Outputs data/output/mii_results_latest.csv for upload to S3.
"""
from __future__ import annotations

import argparse
import json

import dupont_scraper
import enrich_details
import merge_to_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge-only", action="store_true",
                    help="Skip scraping; merge the most recent raw file.")
    ap.add_argument("--enrich", action="store_true",
                    help="Visit each car's detail page for bid/watch counts.")
    args = ap.parse_args()

    if args.merge_only:
        merge_to_index.merge(None)
        return

    raw_path = dupont_scraper.run()

    if args.enrich:
        rows = json.loads(raw_path.read_text())
        enrich_details.enrich(rows)
        raw_path.write_text(json.dumps(rows, indent=2))

    merge_to_index.merge(raw_path)


if __name__ == "__main__":
    main()
