# The Curiosity Engine

A $0/month, zero-maintenance research pipeline that scans finance podcasts,
app-store charts, financial news, and SEC filings every morning, then surfaces
the few emerging trends — with a bias to niche, under-covered names — and
verified stock tickers worth an analyst's attention.

- **Dashboard:** TCM-branded site on GitHub Pages; one page per day with
  click-through navigation across the archive (`docs/index.html` = latest,
  `docs/d/<date>.html` per day). Ships pre-loaded with a real sample week
  (see [SAMPLE_RUN.md](SAMPLE_RUN.md)).
- **Email digest:** sent each morning via Gmail
- **Runs on:** GitHub Actions cron (free on public repos) — no server, no database

See [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions and the honest list
of what can't be done for free (and what the pipeline does instead).

## One-time setup (~15 minutes, then never again)

### 1. Create the repo
1. Create a **public** GitHub repository (public = unlimited free Actions minutes).
2. Push these files to it (`git init && git add -A && git commit -m init`, add remote, push).

### 2. Enable Pages + Actions
1. Repo **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main`, folder `/docs` → Save.
2. **Actions** tab → enable workflows if prompted.

### 3. Add secrets (Settings → Secrets and variables → Actions → New repository secret)

| Secret | Required | How to get it |
|---|---|---|
| `GEMINI_API_KEY` | recommended | Free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (no card needed). Powers signal extraction. |
| `GMAIL_ADDRESS` | for email | Your Gmail address. |
| `GMAIL_APP_PASSWORD` | for email | Google Account → Security → 2-Step Verification → App passwords → create one for "Mail". |
| `DIGEST_TO` | optional | Recipient(s), comma-separated. Defaults to `GMAIL_ADDRESS`. |
| `GROQ_API_KEY` | optional | Free key at [console.groq.com](https://console.groq.com) — backup LLM if Gemini is down. |
| `CE_USER_AGENT` | recommended | Any string with your contact email, e.g. `CuriosityEngine you@example.com` (SEC asks for this). |

No secrets at all? The pipeline still runs: extraction falls back to rule-based
mode and the email is skipped (dashboard still updates).

### 4. Test it
Actions tab → **daily-curiosity-run** → *Run workflow*. In ~2 minutes:
dashboard at `https://<your-username>.github.io/<repo-name>/`, email in your inbox.

Done. It now runs daily at ~6:30am ET on its own.

## Everyday things you might (but never have to) do

- **Add a podcast:** append `- name: X` + `itunes_id: NNNN` (the number in the
  show's Apple Podcasts URL) to `config/sources.yml`.
- **Teach it a brand:** add a line to `config/brand_map.yml`
  (e.g. `Sonny Angel: {company: Dreams Inc, ticker: null}`).
- **Change schedule:** edit the cron line in `.github/workflows/daily.yml`.
- **Tune strictness:** `--min-score` / `--max-signals` in the workflow run step.

## Local test run

```bash
pip install -r requirements.txt
python -m engine.run --no-email
open docs/index.html
```

## Guarantees & limits

- **No invented tickers.** A ticker appears only after matching SEC's official
  `company_tickers.json` or a live market-data listing check; otherwise the item
  is discarded or shown ticker-less in the Watchlist.
- **Every signal cites its sources** — click through from dashboard or email.
- **Graceful degradation.** Any single source failing (Trends, a feed, the LLM)
  never kills the run; the dashboard footer shows per-source ✓/✗ each day.
- Not investment advice; it's a screening aid.
