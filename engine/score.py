"""Scoring, ranking, and day-over-day dedup.

Philosophy: a handful of well-corroborated signals > a long noisy list.
Signals below `min_score` are dropped; at most `max_signals` are published.
"""
import datetime as dt

MEGACAPS = {"AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            "BRK.B", "AVGO", "JPM", "NFLX", "DIS", "WMT", "V", "MA", "LLY",
            "UNH", "XOM", "ORCL", "COST", "HD", "PG", "KO", "PEP", "CRM"}


def score_signal(sig, items_by_id, trends, edgar_hits, history):
    items = [items_by_id[i] for i in sig["item_ids"] if i in items_by_id]
    src_types = {it["source_type"] for it in items}
    s = 25 * len(src_types)                      # independent source classes
    s += min(5 * max(len(items) - 1, 0), 15)     # extra corroborating items

    for it in items:                              # app-chart velocity
        d = it.get("extra", {}).get("delta")
        if it.get("extra", {}).get("new_entrant"):
            s += 25
        elif d and d >= 25:
            s += 25
        elif d and d >= 10:
            s += 15

    t = trends.get(sig["trend"].lower()) or trends.get(sig["trend"])
    if t and t.get("rising"):                     # search interest rising
        s += 15

    e = edgar_hits.get(sig["trend"].lower())
    if e and e.get("filings_30d"):                # showing up in filings
        s += 10

    s += int(10 * float(sig.get("confidence") or 0.5))

    if sig.get("ticker") in MEGACAPS:
        s -= 30 if len(src_types) >= 3 else 60    # megacap noise filter: the
        # engine exists for niche names; megacaps must massively over-corroborate

    key = sig["trend"].lower()
    prior = history.get(key)
    today = dt.date.today().isoformat()
    if prior is None:
        sig["status"] = "new"
        s += 20                                   # novelty bonus
        sig["first_seen"] = today
    else:
        sig["first_seen"] = prior.get("first_seen", today)
        if s >= prior.get("best_score", 0) * 1.25:
            sig["status"] = "accelerating"
            s += 10
        else:
            sig["status"] = "repeat"              # seen before, not accelerating
    sig["score"] = max(s, 0)
    return sig


def select(signals, min_score=55, max_signals=6, max_watchlist=3):
    """Split into (published, watchlist). Repeats need a higher bar."""
    published, watchlist = [], []
    for sig in sorted(signals, key=lambda x: x.get("score", 0), reverse=True):
        if sig.get("watchlist"):
            if len(watchlist) < max_watchlist and sig["score"] >= min_score - 15:
                watchlist.append(sig)
            continue
        if sig["status"] == "repeat" and sig["score"] < min_score + 20:
            continue                              # don't re-show yesterday's news
        if sig["score"] >= min_score and len(published) < max_signals:
            published.append(sig)
    return published, watchlist
