"""Scrape sold auction listings from DuPont Registry Live.

Design notes
------------
The site is a JavaScript app, so we drive a real browser with Playwright.
Two extraction strategies run together, most-reliable first:

  1. API capture  -- record every JSON/XHR response while the page loads.
     Auction apps almost always render from a JSON endpoint; capturing it is
     far more robust than scraping the DOM. Anything that looks like listing
     data is saved to data/raw/api/ and parsed.

  2. DOM fallback -- if no usable JSON is found, walk the rendered listing
     cards. Selectors are centralised in CARD_SELECTORS below and are the
     first thing to revisit if the markup changes.

The first run is also a "discovery" run: it saves the rendered HTML and a
screenshot to data/raw/ so the exact selectors / API shape can be confirmed
against the live page (Phase 2).

Output: data/raw/dupont_listings_<timestamp>.json  (list of raw row dicts)
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config

# --- Selector candidates (revisit against the live DOM in Phase 2) ---------
LOGIN_SELECTORS = {
    "username": [
        "input[name='email']", "input[type='email']",
        "input[name='username']", "#email", "#username",
    ],
    "password": ["input[name='password']", "input[type='password']", "#password"],
    "submit": [
        "button[type='submit']", "button:has-text('Log In')",
        "button:has-text('Sign In')", "input[type='submit']",
    ],
}

CARD_SELECTORS = {
    "card": "[data-testid='listing-card'], article, .listing-card, .auction-card",
    "title": "h2, h3, .title, [data-testid='listing-title']",
    "price": "[data-testid='price'], .price, .sold-price, .high-bid",
    "bids": "[data-testid='bids'], .bid-count, .bids",
    "url": "a",
}

# Heuristics for spotting the listings JSON among captured responses.
LISTING_JSON_HINTS = ("listing", "auction", "vehicle", "result", "lot")


def _log(msg: str) -> None:
    print(f"[scraper] {msg}", flush=True)


def _first_visible(page, selectors: list[str]):
    """Return the first selector that resolves to a visible element."""
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible():
                return loc
        except PWTimeout:
            continue
    return None


def login(page) -> None:
    if not config.USERNAME or not config.PASSWORD:
        raise SystemExit(
            "Missing credentials. Set DR_USERNAME and DR_PASSWORD in scraper/.env"
        )
    _log(f"Navigating to login: {config.LOGIN_URL}")
    page.goto(config.LOGIN_URL, timeout=config.NAV_TIMEOUT_MS, wait_until="domcontentloaded")

    user = _first_visible(page, LOGIN_SELECTORS["username"])
    pw = _first_visible(page, LOGIN_SELECTORS["password"])
    if not user or not pw:
        _dump(page, "login_page")
        raise SystemExit(
            "Could not locate the login fields. A screenshot + HTML were saved to "
            "data/raw/ — update LOGIN_SELECTORS in dupont_scraper.py to match."
        )
    user.fill(config.USERNAME)
    pw.fill(config.PASSWORD)

    submit = _first_visible(page, LOGIN_SELECTORS["submit"])
    (submit or pw).press("Enter") if submit is None else submit.click()
    page.wait_for_load_state("networkidle", timeout=config.NAV_TIMEOUT_MS)
    _log("Login submitted.")


def _dump(page, name: str) -> None:
    """Save HTML + screenshot for offline selector/API inspection."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    html_path = config.DATA_RAW / f"{name}_{stamp}.html"
    png_path = config.DATA_RAW / f"{name}_{stamp}.png"
    html_path.write_text(page.content(), encoding="utf-8")
    try:
        page.screenshot(path=str(png_path), full_page=True)
    except Exception:  # screenshots are best-effort
        pass
    _log(f"Saved diagnostics: {html_path.name}")


def _looks_like_listings(url: str, body: object) -> bool:
    u = url.lower()
    if not any(h in u for h in LISTING_JSON_HINTS):
        return False
    # Must contain a non-trivial array somewhere.
    blob = json.dumps(body) if not isinstance(body, str) else body
    return ("[" in blob and len(blob) > 200)


def _attach_capture(page, captured: list[dict]) -> None:
    def on_response(resp):
        ct = (resp.headers or {}).get("content-type", "")
        if "json" not in ct.lower():
            return
        try:
            body = resp.json()
        except Exception:
            return
        if _looks_like_listings(resp.url, body):
            captured.append({"url": resp.url, "body": body})
    page.on("response", on_response)


def _paginate(page) -> None:
    """Trigger lazy loading: scroll to bottom and/or click 'next' repeatedly."""
    last_height = 0
    for i in range(config.MAX_PAGES):
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(config.SCROLL_PAUSE_MS)
        # Click a "load more / next" control if one is present.
        for sel in ("button:has-text('Load More')", "button:has-text('Next')",
                    "[aria-label='Next']", ".pagination-next"):
            btn = page.locator(sel).first
            try:
                if btn.count() and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    page.wait_for_timeout(config.SCROLL_PAUSE_MS)
            except Exception:
                pass
        height = page.evaluate("document.body.scrollHeight")
        if height == last_height:
            _log(f"Reached end of list after {i + 1} scroll(s).")
            break
        last_height = height


# --- Parsers ---------------------------------------------------------------
_PRICE_RE = re.compile(r"[\d,]+")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _num(text: str | None) -> float | None:
    if not text:
        return None
    m = _PRICE_RE.search(str(text).replace(",", ""))
    return float(m.group()) if m else None


def _split_title(title: str) -> tuple[int | None, str, str]:
    """'1971 Porsche 911S' -> (1971, 'Porsche', '911S')."""
    year = None
    ym = _YEAR_RE.search(title or "")
    if ym:
        year = int(ym.group())
        title = title.replace(ym.group(), "", 1)
    parts = title.strip().split()
    make = parts[0] if parts else ""
    model = " ".join(parts[1:]) if len(parts) > 1 else ""
    return year, make, model


def parse_api(captured: list[dict]) -> list[dict]:
    """Flatten captured JSON into raw rows. Field names are intentionally
    generous because the exact API shape is confirmed in Phase 2."""
    rows: list[dict] = []
    for cap in captured:
        items = _find_item_array(cap["body"])
        for it in items:
            if not isinstance(it, dict):
                continue
            title = _pick(it, "title", "name", "headline", "vehicle")
            year, make, model = _split_title(str(title or ""))
            rows.append({
                "make": _pick(it, "make", "manufacturer", "brand") or make,
                "model": _pick(it, "model", "trim") or model,
                "year": _pick(it, "year", "modelYear") or year,
                "price": _num(_pick(it, "soldPrice", "salePrice", "highBid",
                                    "currentBid", "price", "amount")),
                "bids": _num(_pick(it, "bidCount", "bids", "totalBids")),
                "views": _num(_pick(it, "views", "viewCount")),
                "comments": _num(_pick(it, "comments", "commentCount")),
                "sold_date": _pick(it, "endDate", "soldDate", "endsAt", "date"),
                "url": _pick(it, "url", "permalink", "slug"),
                "sold": True,
            })
    return rows


def _pick(d: dict, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _find_item_array(body: object) -> list:
    """Return the most likely array of listing objects within a JSON blob."""
    best: list = []
    def walk(node):
        nonlocal best
        if isinstance(node, list):
            if node and isinstance(node[0], dict) and len(node) > len(best):
                best = node
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
    walk(body)
    return best


def parse_dom(page) -> list[dict]:
    rows: list[dict] = []
    cards = page.locator(CARD_SELECTORS["card"])
    n = cards.count()
    _log(f"DOM fallback: found {n} candidate card(s).")
    for i in range(n):
        c = cards.nth(i)
        def txt(sel):
            el = c.locator(sel).first
            return el.inner_text().strip() if el.count() else ""
        title = txt(CARD_SELECTORS["title"])
        year, make, model = _split_title(title)
        href = ""
        a = c.locator(CARD_SELECTORS["url"]).first
        if a.count():
            href = a.get_attribute("href") or ""
        rows.append({
            "make": make, "model": model, "year": year,
            "price": _num(txt(CARD_SELECTORS["price"])),
            "bids": _num(txt(CARD_SELECTORS["bids"])),
            "views": None, "comments": None, "sold_date": None,
            "url": href, "sold": True,
        })
    return rows


def run() -> Path:
    captured: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"),
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        page.set_default_timeout(config.NAV_TIMEOUT_MS)
        _attach_capture(page, captured)

        login(page)

        _log(f"Loading sold listings: {config.LISTINGS_URL}")
        page.goto(config.LISTINGS_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        _dump(page, "listings_page")
        _paginate(page)

        rows = parse_api(captured)
        if captured:
            (config.DATA_RAW / "last_api_capture.json").write_text(
                json.dumps(captured, indent=2)[:5_000_000], encoding="utf-8")
        if not rows:
            _log("No rows from API capture; using DOM fallback.")
            rows = parse_dom(page)

        browser.close()

    # De-dupe and drop empties.
    seen, clean = set(), []
    for r in rows:
        key = (r.get("url") or "") + str(r.get("make")) + str(r.get("model")) + str(r.get("year"))
        if r.get("make") and key not in seen:
            seen.add(key)
            clean.append(r)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = config.DATA_RAW / f"dupont_listings_{stamp}.json"
    out.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    _log(f"Wrote {len(clean)} listing(s) -> {out}")
    return out


if __name__ == "__main__":
    try:
        run()
    except SystemExit as e:
        _log(str(e))
        sys.exit(1)
