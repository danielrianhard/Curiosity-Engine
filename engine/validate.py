"""Ticker validation — the anti-hallucination gate.

A candidate only gets a ticker in the output if it passes one of:
  1. Curated brand map entry (config/brand_map.yml) whose ticker also passes 2/3.
  2. SEC's official company_tickers.json (name<->ticker for every US listing).
  3. yfinance listing check (used for non-US tickers like 9992.HK).

Anything that fails is either published WITHOUT a ticker (private-company
watchlist) or discarded. Tickers are never guessed.
"""
import json
import os
import re

from . import fetch

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUFFIXES = r"\b(incorporated|inc|corporation|corp|company|co|ltd|llc|plc|holdings?|group|the|sa|nv|ag)\b"


def normalize(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = re.sub(_SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_sec_map(cache_dir="data/cache"):
    """Official SEC ticker map -> (by_ticker, by_name). Cached daily."""
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "company_tickers.json")
    raw = fetch.get_json(SEC_TICKERS_URL)
    if raw is None and os.path.exists(cache):  # network hiccup: reuse cache
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
    if raw is None:
        return {}, {}
    if not fetch.FIXTURE_DIR:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(raw, f)
    by_ticker, by_name = {}, {}
    rows = raw.values() if isinstance(raw, dict) else raw
    for row in rows:
        t = (row.get("ticker") or "").upper()
        title = row.get("title") or ""
        if not t or not title:
            continue
        by_ticker[t] = title
        by_name.setdefault(normalize(title), t)
    return by_ticker, by_name


def _yf_verify(ticker: str):
    """Listing check for tickers outside SEC coverage (e.g. HK). Best-effort."""
    if fetch.FIXTURE_DIR:
        path = os.path.join(fetch.FIXTURE_DIR, "tickers.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                fx = json.load(f)
            hit = fx.get(ticker.upper())
            return (hit["name"], hit.get("exchange", "")) if hit else None
        return None
    try:
        import yfinance as yf  # type: ignore
        info = yf.Ticker(ticker).info or {}
        name = info.get("longName") or info.get("shortName")
        if name and info.get("regularMarketPrice") is not None:
            return name, info.get("fullExchangeName") or info.get("exchange", "")
    except Exception:
        pass
    return None


def _names_agree(claimed: str, official: str) -> bool:
    a, b = normalize(claimed), normalize(official)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return bool(set(a.split()) & set(b.split()) - {"and", "of", "new"})


def validate_candidate(cand, by_ticker, by_name, brand_map):
    """Returns dict {ticker, company, method} | {"watchlist": True} | None."""
    company = (cand.get("public_company") or "").strip()
    hint = (cand.get("ticker_hint") or "").strip().upper()
    trend = (cand.get("trend_name") or "").strip()

    # 1) curated brand map (still verified against SEC/yfinance below)
    for brand, info in brand_map.items():
        if brand.lower() in (trend.lower(), company.lower()):
            bt = (info.get("ticker") or "").upper()
            if not bt:
                return {"watchlist": True, "company": info.get("company")}
            if bt in by_ticker:
                return {"ticker": bt, "company": by_ticker[bt], "method": "brand_map+SEC"}
            yf_hit = _yf_verify(bt)
            if yf_hit:
                return {"ticker": bt, "company": yf_hit[0],
                        "exchange": yf_hit[1], "method": "brand_map+yfinance"}
            return None  # curated entry no longer verifies -> drop, don't guess

    # 2) ticker hint, cross-checked against the claimed company name
    if hint and hint in by_ticker:
        if not company or _names_agree(company, by_ticker[hint]):
            return {"ticker": hint, "company": by_ticker[hint], "method": "SEC"}
    if hint and company:
        yf_hit = _yf_verify(hint)
        if yf_hit and _names_agree(company, yf_hit[0]):
            return {"ticker": hint, "company": yf_hit[0],
                    "exchange": yf_hit[1], "method": "yfinance"}

    # 3) company name -> SEC exact normalized match
    if company:
        norm = normalize(company)
        if norm in by_name:
            t = by_name[norm]
            return {"ticker": t, "company": by_ticker[t], "method": "SEC name"}
        # unique prefix match, only for distinctive names
        if len(norm) >= 6:
            hits = [t for n, t in by_name.items() if n.startswith(norm)]
            if len(hits) == 1:
                return {"ticker": hits[0], "company": by_ticker[hits[0]],
                        "method": "SEC prefix"}

    # 4) explicitly-private candidate -> watchlist; otherwise unverifiable
    if cand.get("public_company") is None and trend:
        return {"watchlist": True, "company": None}
    return None
