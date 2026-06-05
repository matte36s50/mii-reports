"""Scrape sold auction listings from DuPont Registry Live.

DuPont Registry Live is a Next.js site that server-side renders every listing
into a <script id="__NEXT_DATA__"> JSON blob. The sold-listings pages are
PUBLIC (no login required), so we just fetch each page over HTTP and read the
embedded JSON — far more robust than driving a browser or scraping the DOM.

Per-auction fields we use (under props.pageProps.auctions[]):
    bidDetails.value          -> sold price (winning bid)
    vehicleData.make/model/year
    vehicleData.vehicleStatus -> keep only "sold"
    soldDate
    lotNumber, slug           -> identity / URL

Note: the feed exposes no view/comment/bid-count signals, only final price.

Output: data/raw/dupont_listings_<timestamp>.json  (list of raw row dicts)
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import config

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _log(msg: str) -> None:
    print(f"[scraper] {msg}", flush=True)


def page_url(page: int) -> str:
    """Build the sold-listings URL for a given page.

    The site uses a `filter:key=value;key=value` path segment. Page 1 is the
    bare URL from config; later pages add a `page=N` filter key.
    """
    if page <= 1:
        return config.LISTINGS_URL
    base, _, filt = config.LISTINGS_URL.partition("filter:")
    keys = [kv for kv in filt.split(";") if kv and not kv.startswith("page=")]
    keys.insert(0, f"page={page}")
    return f"{base}filter:{';'.join(keys)}"


def extract_next_data(html: str) -> dict:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ script not found in page HTML")
    return json.loads(m.group(1))


def _clean_model(model: str) -> str:
    """'911 GT3RS | Carrera White & Guards Red' -> '911 GT3RS'."""
    return (model or "").split("|")[0].strip()


def parse_auctions(next_data: dict) -> tuple[list[dict], dict]:
    """Return (raw rows, pagination dict) from a parsed __NEXT_DATA__ blob."""
    page_props = next_data.get("props", {}).get("pageProps", {})
    auctions = page_props.get("auctions", []) or []
    pagination = page_props.get("pagination", {}) or {}

    rows = []
    for a in auctions:
        v = a.get("vehicleData", {}) or {}
        if (v.get("vehicleStatus") or "").lower() != "sold":
            continue
        rows.append({
            "make": v.get("make"),
            "model": _clean_model(v.get("model")),
            "model_full": v.get("model"),
            "year": v.get("year"),
            "price": (a.get("bidDetails") or {}).get("value"),
            "bids": None,        # not exposed by the feed
            "views": None,       # not exposed by the feed
            "comments": None,    # not exposed by the feed
            "sold_date": a.get("soldDate") or a.get("endTime"),
            "lot": a.get("lotNumber"),
            "slug": v.get("slug"),
            "url": f"{config.BASE_URL}/listings/{v.get('slug')}" if v.get("slug") else None,
            "sold": True,
        })
    return rows, pagination


def fetch_page(session: requests.Session, page: int) -> tuple[list[dict], dict]:
    url = page_url(page)
    _log(f"Fetching page {page}: {url}")
    resp = session.get(url, headers=HEADERS, timeout=config.NAV_TIMEOUT_MS / 1000)
    resp.raise_for_status()
    rows, pagination = parse_auctions(extract_next_data(resp.text))
    _log(f"  page {page}: {len(rows)} sold listing(s) "
         f"(currentPage={pagination.get('currentPage')}, "
         f"pageCount={pagination.get('pageCount')})")
    return rows, pagination


def run() -> Path:
    session = requests.Session()
    all_rows, page = [], 1
    rows, pagination = fetch_page(session, page)
    all_rows.extend(rows)

    page_count = int(pagination.get("pageCount") or 1)
    page_count = min(page_count, config.MAX_PAGES)
    while page < page_count:
        page += 1
        time.sleep(0.5)  # be polite
        rows, _ = fetch_page(session, page)
        all_rows.extend(rows)

    # De-dupe by lot/slug.
    seen, clean = set(), []
    for r in all_rows:
        key = r.get("slug") or f"{r.get('make')}-{r.get('model')}-{r.get('lot')}"
        if r.get("make") and key not in seen:
            seen.add(key)
            clean.append(r)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = config.DATA_RAW / f"dupont_listings_{stamp}.json"
    out.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    _log(f"Wrote {len(clean)} unique sold listing(s) -> {out}")
    return out


if __name__ == "__main__":
    try:
        run()
    except Exception as e:  # noqa: BLE001 - surface a clean message
        _log(f"ERROR: {e}")
        sys.exit(1)
