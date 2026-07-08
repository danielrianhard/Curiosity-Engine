"""Daily orchestrator: ingest -> extract -> validate -> score -> publish.

Usage:  python -m engine.run [--no-email] [--max-signals N]
Design: every stage degrades gracefully; the run only exits non-zero when
        ALL ingestion sources fail (so GitHub Actions surfaces a red run).
"""
import argparse
import datetime as dt
import json
import os
import sys

import yaml

from . import extract, history, ingest, publish, score, validate


def load_yaml(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or (default if default is not None else {})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--max-signals", type=int, default=6)
    ap.add_argument("--min-score", type=int, default=55)
    ap.add_argument("--podcast-days", type=int, default=3)
    ap.add_argument("--news-days", type=int, default=2)
    args = ap.parse_args(argv)

    cfg = load_yaml("config/sources.yml")
    brand_map = load_yaml("config/brand_map.yml")
    today = dt.date.today().isoformat()
    status = {}

    # ---- 1. ingest ------------------------------------------------------
    items = []
    pods = ingest.ingest_podcasts(cfg, days=args.podcast_days)
    status["podcasts"] = bool(pods)
    items += pods

    prev_snap = history.load_snapshot("appstore")
    apps, snap = ingest.ingest_appstore(prev_snap)
    status["appstore"] = bool(snap)
    if snap:
        history.save_snapshot("appstore", snap)
    items += apps

    news = ingest.ingest_news(cfg, days=args.news_days)
    status["news"] = bool(news)
    items += news

    edgar_items = ingest.ingest_edgar_new_registrations()
    status["edgar"] = bool(edgar_items)
    items += edgar_items

    print(f"[ingest] {len(items)} items "
          f"(podcasts {len(pods)}, appstore {len(apps)}, news {len(news)}, "
          f"edgar {len(edgar_items)})")
    if not items:
        print("FATAL: every source failed", file=sys.stderr)
        return 1

    # ---- 2. extract candidates -----------------------------------------
    by_ticker, by_name = validate.load_sec_map()
    status["sec_tickers"] = bool(by_ticker)
    candidates, provider = extract.extract(items, brand_map, (by_ticker, by_name))
    print(f"[extract] {len(candidates)} candidates via {provider}")

    # ---- 3. validate tickers (anti-hallucination gate) ------------------
    items_by_id = {it["id"]: it for it in items}
    signals = []
    for cand in candidates:
        v = validate.validate_candidate(cand, by_ticker, by_name, brand_map)
        if v is None:
            print(f"[validate] DISCARDED (unverifiable): {cand.get('trend_name')!r} "
                  f"hint={cand.get('ticker_hint')!r}")
            continue
        srcs = [{"type": items_by_id[i]["source_type"],
                 "name": items_by_id[i]["source_name"],
                 "title": items_by_id[i]["title"],
                 "url": items_by_id[i]["url"]}
                for i in cand["item_ids"] if i in items_by_id]
        if not srcs:
            continue  # no traceable source -> not publishable
        signals.append({
            "trend": cand["trend_name"].strip(),
            "why": cand.get("why_matters", ""),
            "evidence": cand.get("evidence", ""),
            "confidence": cand.get("confidence", 0.5),
            "item_ids": cand["item_ids"],
            "sources": srcs,
            "ticker": v.get("ticker"),
            "company": v.get("company"),
            "exchange": v.get("exchange", ""),
            "method": v.get("method", ""),
            "watchlist": bool(v.get("watchlist")),
        })

    # ---- 4. corroborate + score + select --------------------------------
    trend_names = [s["trend"] for s in signals if not s["watchlist"]]
    trends = {k.lower(): v for k, v in ingest.trends_interest(trend_names).items()}
    status["google_trends"] = bool(trends)
    edgar_hits = {}
    for s in signals[:10]:
        hit = ingest.edgar_mentions(s["trend"])
        if hit:
            edgar_hits[s["trend"].lower()] = hit
            if hit.get("filings_30d"):
                s["sources"].append({
                    "type": "edgar", "name": "SEC full-text search",
                    "title": f"{hit['filings_30d']} filing(s) mention this in 30d",
                    "url": ("https://efts.sec.gov/LATEST/search-index?q=%22"
                            + s["trend"].replace(" ", "+") + "%22")})

    hist = history.load(days=30)
    for s in signals:
        score.score_signal(s, items_by_id, trends, edgar_hits, hist)
    published, watchlist = score.select(
        signals, min_score=args.min_score, max_signals=args.max_signals)
    print(f"[select] {len(published)} published, {len(watchlist)} watchlist, "
          f"{len(signals) - len(published) - len(watchlist)} below bar")

    # ---- 5. persist + publish -------------------------------------------
    daily = {"date": today, "signals": published, "watchlist": watchlist,
             "provider": provider, "source_status": status,
             "items_ingested": len(items)}
    history.save(today, daily)

    base_ctx = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "dashboard_url": os.environ.get("DASHBOARD_URL", "#"),
        "provider": provider,
    }
    dash = publish.render_site(history.recent_days(30), base_ctx)
    print(f"[publish] site -> {dash}")

    email_html = publish.render_email({
        "date": today, "pretty_date": publish._pretty(today),
        "signals": published, "watchlist": watchlist,
        "dashboard_url": base_ctx["dashboard_url"],
    })
    if args.no_email:
        msg = "skipped (--no-email)"
        os.makedirs("data/out", exist_ok=True)  # still save a copy for review
        with open(f"data/out/email-{today}.html", "w", encoding="utf-8") as f:
            f.write(email_html)
    else:
        _, msg = publish.send_email(
            email_html, f"Curiosity Engine — {len(published)} signal(s) for {today}")
    print(f"[email] {msg}")

    with open("data/out/last_run.json", "w", encoding="utf-8") as f:
        json.dump({"date": today, "status": status, "provider": provider,
                   "published": len(published)}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
