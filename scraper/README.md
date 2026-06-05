# DuPont Registry → MII Scraper

Pulls **sold** auction listings from DuPont Registry Live and folds them into
the Market Interest Index (the CSV the dashboard reads), tagged as
`data_source = "DuPont Registry"`.

DuPont Registry Live is a Next.js site that server-side renders every listing
into a `<script id="__NEXT_DATA__">` JSON blob, and the **sold-listings pages
are public** — so this is a plain HTTP fetch + JSON parse. No browser, no
login, no credentials.

```
scraper/
├── config.py            # settings + MII formula weights
├── dupont_scraper.py    # fetch pages, parse __NEXT_DATA__  -> data/raw/*.json
├── mii_transform.py     # raw listings -> MII schema + mii_score
├── merge_to_index.py    # fetch live index, score, write combined CSV
└── run.py               # scrape + merge in one shot
```

## Setup (one command)

```bash
bash scraper/setup.sh        # installs the two Python deps
```

## Run

```bash
python3 scraper/run.py              # scrape all sold listings + merge into the index
python3 scraper/run.py --merge-only # re-merge the most recent scrape (no re-scrape)
```

Output: `data/output/mii_results_latest.csv` (~338 DuPont rows merged in).

## See the results in the dashboard

```bash
python3 -m http.server 8000
# then open:
#   http://localhost:8000/index.html?data=data/output/mii_results_latest.csv
```

When it looks right, upload the file to S3 as
`reports/mii_results_latest.csv` (the dashboard's live data source). The merge
step **never** writes to S3 — uploading is a deliberate manual step so a bad
scrape can't clobber the live dashboard.

## How scoring works (and an important caveat)

DuPont rows are scored with the published MII methodology
(`config.MII_WEIGHTS`: price 30%, bids 30%, views 20%, comments 12%,
social 5%, age 3%), normalised against the existing index so they share the
same 0–100 scale.

**Caveat:** the DuPont feed only exposes **final sale price** (and year). It has
no view, comment, or bid-count signals. Those (67% of the weight) fall back to
the index median, so DuPont `mii_score`s mostly track price and cluster fairly
tightly. They're directionally right and comparable, but if you want DuPont rows
to spread out more, consider a price-weighted sub-score — see `mii_transform.py`.

## Running in the cloud environment

If you run this inside Claude Code on the web rather than locally, allowlist
`live.dupontregistry.com` in the environment's network policy
(https://code.claude.com/docs/en/claude-code-on-the-web). No browser-download
host is needed since this is a pure HTTP fetch.
