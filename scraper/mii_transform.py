"""Transform raw DuPont listings into MII index rows and score them.

The MII CSV (read by the dashboard) has absolute signal columns plus a set of
``*_normalized`` columns and a final ``mii_score``. To keep DuPont rows on the
SAME scale as the existing Bring a Trailer rows, we normalise each DuPont
signal against the *existing* dataset's range and score with the published
methodology weights (see config.MII_WEIGHTS). Signals DuPont doesn't expose
(e.g. views / comments) fall back to the existing dataset's median so they
neither help nor hurt a listing unfairly. Those fallbacks are flagged via the
``*_source = "estimate"`` columns that already exist in the schema.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import config

NOW_YEAR = datetime.now(timezone.utc).year

# Canonical column order of the MII CSV.
MII_COLUMNS = [
    "manufacturer", "model", "quarter", "price", "views", "bids", "comments",
    "year", "age", "decade", "sold", "data_source", "auction_count",
    "google_trends_interest", "google_trends_pct", "google_trends_direction",
    "google_trends_source", "youtube_total_views", "youtube_source",
    "social_score", "views_normalized", "bids_normalized",
    "comments_normalized", "price_normalized",
    "google_trends_interest_normalized", "youtube_total_views_normalized",
    "social_score_normalized", "age_normalized", "mii_score",
]

# Absolute signal column -> normalized column.
_NORM_PAIRS = {
    "price": "price_normalized",
    "bids": "bids_normalized",
    "views": "views_normalized",
    "comments": "comments_normalized",
    "social_score": "social_score_normalized",
    "age": "age_normalized",
}


def _quarter(sold_date) -> str:
    """Match the existing 'YYYY-MM' convention used in the index file."""
    dt = None
    if sold_date:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(str(sold_date)[:19], fmt)
                break
            except ValueError:
                continue
    dt = dt or datetime.now(timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def raw_to_records(raw_rows: list[dict]) -> pd.DataFrame:
    """Map scraper output -> absolute MII rows (pre-scoring)."""
    recs = []
    for r in raw_rows:
        year = r.get("year")
        year = int(year) if year else None
        age = (NOW_YEAR - year) if year else None
        recs.append({
            "manufacturer": r.get("make"),
            "model": r.get("model"),
            "quarter": _quarter(r.get("sold_date")),
            "price": r.get("price"),
            "views": r.get("views"),
            "bids": r.get("bids"),
            "comments": r.get("comments"),
            "year": year,
            "age": age,
            "decade": (year // 10 * 10) if year else None,
            "sold": 1 if r.get("sold") else 0,
            "data_source": config.DATA_SOURCE_LABEL,
            "auction_count": 1,
            # Signals DuPont doesn't provide -> marked as estimates downstream.
            "google_trends_interest": None,
            "google_trends_pct": 0,
            "google_trends_direction": "stable",
            "google_trends_source": "estimate",
            "youtube_total_views": None,
            "youtube_source": "estimate",
            "social_score": None,
        })
    return pd.DataFrame(recs)


def _ref_stats(reference: pd.DataFrame) -> dict:
    """Per-signal min/max (for scaling) and median normalized (for fallback)."""
    stats = {}
    for sig, norm_col in _NORM_PAIRS.items():
        col = pd.to_numeric(reference.get(sig), errors="coerce") if sig in reference else pd.Series(dtype=float)
        ncol = pd.to_numeric(reference.get(norm_col), errors="coerce") if norm_col in reference else pd.Series(dtype=float)
        stats[sig] = {
            "min": float(col.min()) if col.notna().any() else 0.0,
            "max": float(col.max()) if col.notna().any() else 1.0,
            "median_norm": float(ncol.median()) if ncol.notna().any() else 0.5,
        }
    return stats


def _scale(value, lo, hi):
    if value is None or pd.isna(value):
        return None
    if hi <= lo:
        return 1.0
    return max(0.0, min(1.0, (float(value) - lo) / (hi - lo)))


def score(records: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Add *_normalized columns and mii_score, scaled to the reference set."""
    stats = _ref_stats(reference)
    df = records.copy()

    for sig, norm_col in _NORM_PAIRS.items():
        s = stats[sig]
        if sig == "age":
            # Older cars score higher; existing data already normalises this way.
            scaled = df[sig].apply(lambda v: _scale(v, s["min"], s["max"]))
        else:
            scaled = df[sig].apply(lambda v: _scale(v, s["min"], s["max"]))
        # Fall back to the reference median where DuPont gives us nothing.
        df[norm_col] = scaled.where(scaled.notna(), s["median_norm"])

    # Trends / youtube aren't scraped; neutralise them (they don't feed the
    # 6-weight score, but the columns must exist for schema compatibility).
    df["google_trends_interest_normalized"] = 0.5
    df["youtube_total_views_normalized"] = 0.5

    w = config.MII_WEIGHTS
    df["mii_score"] = (
        df["price_normalized"] * w["price"]
        + df["bids_normalized"] * w["bids"]
        + df["views_normalized"] * w["views"]
        + df["comments_normalized"] * w["comments"]
        + df["social_score_normalized"] * w["social_score"]
        + df["age_normalized"] * w["age"]
    ) * 100
    df["mii_score"] = df["mii_score"].round(2)

    # Ensure every canonical column exists, in order.
    for col in MII_COLUMNS:
        if col not in df:
            df[col] = None
    return df[MII_COLUMNS]
