# Rommbic Intelligence Portal

An unattended daily agent that scans UK construction-products news (Google News
feeds + optional Companies House + optional careers pages), **filters out the
noise**, scores what's left by hiring-intent, publishes a **dashboard**, and
emails a **daily digest** to all consultants. Runs itself every morning on
GitHub Actions — no server, no manual steps, free.

```
┌────────── COLLECT ──────────┐   ┌──── FILTER ────┐   ┌──── DELIVER ────┐
 Google News RSS (38 feeds)        recency gate          dashboard (Pages)
 Companies House  (optional)  ───▶ exclude words   ───▶  email digest
 Careers pages    (optional)       category+sector        (Resend or SMTP)
                                    dedup + score
```

The whole thing is driven by `config/settings.yaml` and `config/feeds.opml`,
so you tune relevance without touching Python.

---

## 1. Build & test locally with Claude Code

```bash
cd rommbic-intel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # fill in recipients + an email transport
python -m tests.test_pipeline # sanity-check the filtering logic
python -m src.main            # do a real run; writes data/ and emails the digest
```

Open `data/last_email.html` to preview the digest, and open `dashboard/index.html`
(served from the repo root so it can read `./data/`) to preview the dashboard:
`python -m http.server` then visit `/dashboard/index.html` after copying data, or
just push and let Pages serve it.

## 2. Deploy (one-time, ~10 minutes)

1. Create a GitHub repo and push this folder.
2. **Settings → Pages →** Source: *GitHub Actions*.
3. **Settings → Secrets and variables → Actions →** add secrets:

   | Secret | Required? | Notes |
   |---|---|---|
   | `DIGEST_RECIPIENTS` | yes | comma-separated consultant emails |
   | `DASHBOARD_URL` | yes | `https://intel.rommbic.co.uk` or your `*.pages.dev` URL |
   | `RESEND_API_KEY` | email option A | from resend.com |
   | `SMTP_HOST/PORT/USER/PASS` | email option B | your M365 / Workspace mailbox |
   | `CH_API_KEY` | optional | Companies House signals |
   | `USE_CLAUDE` + `ANTHROPIC_API_KEY` | optional | "why it matters" enrichment |

4. **Actions tab → Daily Intel → Run workflow** to fire the first run.
   After that it runs automatically at **06:30 UTC daily**.

That's it — fully unattended from here. The job commits each day's data back to
the repo (giving you history *and* keeping the GitHub schedule from going
dormant) and redeploys the dashboard.

## 3. Tuning what gets through (the important part)

Everything lives in **`config/settings.yaml`**:

- `sector_keywords` — proves a story is about our industry.
- `categories` — the signal types and their base scores; add keywords to widen
  or tighten each. **This is where you reduce noise or catch more.**
- `exclude_keywords` — instant-drop terms.
- `recency_hours`, `max_items`, `email.min_score_to_email`.

**Feeds** live in `config/feeds.opml` (164 feeds, also importable into any RSS
reader) in three groups: **signal** feeds (industry-wide trigger events),
**sector** feeds (one per sub-sector — these catch *similar* firms you didn't
list), and **company** feeds (your targets batched ~10 names per Google News
query, grouped by sub-sector). The full target list lives in
`config/watchlist.csv` (name, website, sector); the pipeline uses it to **tag**
and **score-boost** any story that names one of your firms, across every feed —
so you can filter the dashboard to "only my companies." Regenerate both files
from an updated CSV with:

```bash
python tools/build_feeds_from_csv.py your_companies.csv config/feeds.opml config/watchlist.csv
```

Single-word company names (e.g. "Marley") are matched only when a story also has
sector context, so a "Bob Marley" article never sneaks in.

## 4. Optional sources

- **Companies House** — `config/companies.json` is **pre-loaded** with verified
  registration numbers for 12 major targets (Travis Perkins, Saint-Gobain UK,
  Huws Gray, Marshalls, Ibstock, Forterra, Breedon, Genuit, Eurocell, plus key
  trading subsidiaries). Just add a free `CH_API_KEY` secret and the source
  activates — pulling director appointments, charges (expansion/acquisition
  financing), and ownership changes. Add more targets by searching a name at
  find-and-update.company-information.service.gov.uk and pasting its number.

  *Nuance worth knowing:* a listed **holding PLC** files board-level officer
  changes but often **no charges**; its **trading subsidiary** carries the
  charges and operational filings. That's why the biggest groups appear twice
  in the list (e.g. *Travis Perkins plc* for board changes **and** *Travis
  Perkins Trading Company Limited* for charges) — between them you catch both.

- **Careers pages** — copy `config/careers.json.example` to `config/careers.json`
  and edit. New vacancies are the strongest signal (Tier-1, score 10). Many
  merchant careers pages are JavaScript-rendered, so point each `url` at the
  company's underlying ATS board (Greenhouse/Workable/Teamtailor), which serves
  static HTML the agent can read. Verify a URL shows job titles in its page
  source before trusting it.

## 5. How it stays unbreakable

Every source and every item is wrapped in error handling — one dead feed or one
malformed entry can never stop the daily brief. If email isn't configured the
run still succeeds and writes `data/last_email.html`. If `USE_CLAUDE` is off it
uses fast rule-based scoring. Nothing about the daily run requires you to be
present.

## Layout

```
config/      settings.yaml · feeds.opml · companies.json* · careers.json*
src/         main.py · config.py · util.py
  sources/   rss.py · companies_house.py · careers.py
  pipeline/  relevance.py · dedup.py · score.py
  deliver/   dashboard.py · email_digest.py
dashboard/   index.html         (static, reads ../data)
data/        latest.json · YYYY-MM-DD.json · index.json   (generated)
.github/workflows/daily.yml     (the scheduler)
```
\* optional
