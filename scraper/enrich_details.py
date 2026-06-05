"""Enrich scraped listings with per-car signals from each detail page.

The sold-listings index only exposes final price. Each individual car page
(https://live.dupontregistry.com/listings/<slug>) additionally shows a public
**bid count** and **watching** count (confirmed in the live UI: "73 Bids",
"62 Watching"). The detail page is the same Next.js app, so those numbers are
rendered from its own __NEXT_DATA__ blob and/or the api.live.dupontregistry.com
backend.

Because we haven't pinned the exact JSON key names yet, this module auto-detects
them: it parses the detail page's __NEXT_DATA__, locates the auction object, and
deep-searches for integer fields whose key looks like a bid / watch count. If
the page yields nothing (counts loaded purely via XHR), it falls back to the
API host. The matched values are logged so the heuristics can be tightened once
we see one real payload.

Note on scoring: bid counts (~tens) are on the same scale as the existing index
(BAT bids: 1-114), so they slot straight into the MII `bids` signal. "Watching"
is a different magnitude than BAT view counts, so it's stored separately and not
mapped onto the BAT-scaled views column (that would zero it out).
"""
from __future__ import annotations

import re
import time

import requests

import config
from dupont_scraper import extract_next_data, HEADERS

API_BASE = "https://api.live.dupontregistry.com"

# Key-name heuristics (case-insensitive).
_BID_KEY = re.compile(r"(bid.?count|count.?bid|total.?bids|num.?bids|^bids$|bidstotal)", re.I)
_WATCH_KEY = re.compile(r"(watch|watcher|watching)", re.I)
_VIEW_KEY = re.compile(r"(view.?count|^views$|total.?views|page.?views)", re.I)


def _find_auction_obj(next_data: dict) -> dict:
    pp = next_data.get("props", {}).get("pageProps", {}) or {}
    for key in ("auction", "auctionDetails", "auctionDetail", "listing",
                "vehicle", "data"):
        if isinstance(pp.get(key), dict):
            return pp[key]
    aucs = pp.get("auctions")
    if isinstance(aucs, list) and aucs:
        return aucs[0]
    return pp


def _deep_max_int(obj, key_re) -> int | None:
    """Return the largest integer whose key matches key_re, anywhere in obj."""
    best = None
    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)) and key_re.search(str(k)):
                    iv = int(v)
                    if best is None or iv > best:
                        best = iv
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(obj)
    return best


def enrich_row(session: requests.Session, row: dict, verbose: bool = True) -> dict:
    slug = row.get("slug")
    if not slug:
        return row
    url = f"{config.BASE_URL}/listings/{slug}"
    try:
        resp = session.get(url, headers=HEADERS, timeout=config.NAV_TIMEOUT_MS / 1000)
        resp.raise_for_status()
        obj = _find_auction_obj(extract_next_data(resp.text))
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"[enrich] {slug}: fetch/parse failed ({e})")
        return row

    bids = _deep_max_int(obj, _BID_KEY)
    watching = _deep_max_int(obj, _WATCH_KEY)
    views = _deep_max_int(obj, _VIEW_KEY)

    if bids is not None:
        row["bids"] = bids
    if watching is not None:
        row["watching"] = watching
    if views is not None:
        row["views"] = views

    if verbose:
        print(f"[enrich] {slug}: bids={bids} watching={watching} views={views}")
    return row


def enrich(rows: list[dict], limit: int | None = None) -> list[dict]:
    session = requests.Session()
    n = len(rows) if limit is None else min(limit, len(rows))
    print(f"[enrich] Enriching {n} listing(s) from detail pages...")
    for i, row in enumerate(rows[:n]):
        enrich_row(session, row)
        time.sleep(0.4)  # be polite
    hits = sum(1 for r in rows[:n] if r.get("bids"))
    print(f"[enrich] Done. {hits}/{n} rows now have a bid count.")
    if hits == 0:
        print("[enrich] No counts found in __NEXT_DATA__ — they're likely loaded "
              f"via XHR from {API_BASE}. Paste one detail page's api.live response "
              "and I'll point the enricher straight at that endpoint.")
    return rows


if __name__ == "__main__":
    import json
    import sys
    from dupont_scraper import latest_raw  # type: ignore

    path = config.DATA_RAW / sys.argv[1] if len(sys.argv) > 1 else None
    raw_path = path or sorted(config.DATA_RAW.glob("dupont_listings_*.json"))[-1]
    data = json.loads(raw_path.read_text())
    enrich(data)
    raw_path.write_text(json.dumps(data, indent=2))
    print(f"[enrich] Updated {raw_path}")
