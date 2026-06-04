# DuPont Registry → MII Scraper

Scrapes **sold** auction listings from DuPont Registry Live and folds them into
the Market Interest Index (the CSV the dashboard reads), tagged as
`data_source = "DuPont Registry"`.

```
scraper/
├── config.py            # all settings + MII formula weights (reads .env)
├── dupont_scraper.py    # Playwright login + listing capture  -> data/raw/*.json
├── mii_transform.py     # raw listings -> MII schema + mii_score
├── merge_to_index.py    # fetch live index, score, write combined CSV
└── run.py               # scrape + merge in one shot
```

## Setup

```bash
cd scraper
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium

cp .env.example .env        # then edit .env with your DuPont login
```

`.env` is gitignored — credentials are **never** committed.

## Run

```bash
python3 run.py              # scrape sold listings + merge into the index
python3 run.py --merge-only # re-merge the most recent scrape (no re-scrape)
```

Output: `data/output/mii_results_latest.csv`. Review it, then upload it to S3 as
`reports/mii_results_latest.csv` (the dashboard's data source). The merge step
**does not** touch S3 — uploading is a deliberate manual step.

## How scoring works

DuPont rows are scored with the published MII methodology
(`config.MII_WEIGHTS`: price 30%, bids 30%, views 20%, comments 12%,
social 5%, age 3%). Each signal is normalised against the **existing** index so
DuPont rows land on the same 0–100 scale as the Bring a Trailer rows. Signals
DuPont doesn't expose (e.g. views/comments) fall back to the dataset median and
are flagged via the `*_source = "estimate"` columns.

## ⚠️ Two things before the first real run

1. **Network allowlist.** This repo's cloud environment blocks
   `live.dupontregistry.com` (`x-deny-reason: host_not_allowed`). Add the host
   to the environment's network policy
   (https://code.claude.com/docs/en/claude-code-on-the-web) before running here,
   or run the scraper locally where there's no egress restriction.

2. **Selectors are first-pass.** `LOGIN_SELECTORS` / `CARD_SELECTORS` and the
   API field guesses in `dupont_scraper.py` are written against the *expected*
   markup. The first run saves the rendered HTML + a screenshot to `data/raw/`
   so the exact login fields and listing API/DOM can be confirmed and the
   selectors finalised.
