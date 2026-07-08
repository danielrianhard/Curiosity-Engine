# Sample week — July 2–8, 2026 (real, verified signals)

The repo ships pre-loaded with seven daily reports so you can click through a
real week before going live. Open `docs/index.html` (latest day) and use the
date chips / ‹ › arrows to move between days. The July 8 email digest is at
`data/out/email-2026-07-08.html`.

## What the week surfaced (all tickers verified, all claims sourced)

- **Jul 2 — Almonty Industries (NASDAQ: ALM)**, the tungsten near-monopoly:
  Sangdong began producing saleable concentrate as China export curbs lifted APT
  prices ~23% — the only integrated non-China tungsten supplier ramping ahead of
  the DoD's Jan 2027 sourcing ban. Plus Bending Spoons' 40% IPO pop (BSP),
  Red Cat's Army down-select (RCAT), Lime's debut (LIME), and Jersey Mike's S-1
  (watchlist).
- **Jul 3 —** US Antimony's DLA deliveries (UAMY), Critical Metals' Tanbreez
  pure-play sharpening (CRML), IQM's quantum listing (IQMX), Kratos re-rating (KTOS).
- **Jul 4 —** World Cup micro-merch on TikTok Shop (MNSO), Wendy's meme-flow
  gauge (WEN), prediction markets' record volumes (Kalshi/Polymarket — watchlist).
- **Jul 5 —** medicube's #1 US TikTok Shop SKU → APR Co. (KOSPI: 278470),
  USA Rare Earth's lawsuit/index double-hit (USAR).
- **Jul 6 —** TeraWulf's $19B Anthropic lease (WULF), Abivax's safety-scare-to-M&A
  flip (ABVX), FreeReels as a global top-10 app → Kunlun Tech (SZSE: 300418).
- **Jul 7 —** Centrus' HALEU chokepoint goes commercial (LEU), SpaceX's
  fast-track Nasdaq-100 entry (SPCX), Palladyne's AFRL swarm award (PDYN).
- **Jul 8 —** the live-data day: the short-drama app cluster holding Apple's
  Top-25 (Kunlun, *accelerating*) and Kalshi entrenched at #6 (watchlist,
  *accelerating*) — both fed by the engine's actual Apple-chart ingestion.

## Honest caveats

1. **Jul 2–7 are retrospective reconstructions** (flagged in each page's footer):
   assembled on Jul 8 from that day's public sources with analyst-grade research —
   the quality bar the LLM extraction path is prompted to match. Jul 8 combines
   the engine's real chart/podcast/news ingestion with the same enrichment.
2. Every ticker was verified against company press releases, SEC filings and/or
   quote pages (verification method shown on each card). Private companies
   (Kalshi, Polymarket, Jersey Mike's) appear only in the ticker-less Watchlist.
3. Signal scores for backfilled days were assigned per the engine's rubric
   (source-type count, velocity, novelty), not computed live.
4. Going forward the daily GitHub Actions run produces these pages automatically;
   set `GEMINI_API_KEY` for extraction depth approaching this sample.

Rebuild the site from history at any time: `python -m scripts.rebuild_site`
