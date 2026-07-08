"""Signal extraction: raw items -> candidate signals.

Provider chain (first available wins, later ones are fallbacks):
  1. Gemini free tier   (GEMINI_API_KEY)  — ~2-6 requests/day vs 1,500/day cap
  2. Groq free tier     (GROQ_API_KEY)
  3. Rule-based         (no key needed)   — brand map + explicit ticker regex

Candidates are NOT trusted: every ticker/company goes through validate.py.
"""
import json
import os
import re

from . import fetch

GEMINI_MODEL = os.environ.get("CE_GEMINI_MODEL", "gemini-flash-latest")
GROQ_MODEL = os.environ.get("CE_GROQ_MODEL", "llama-3.3-70b-versatile")

PROMPT = """You are a buy-side research analyst screening raw daily inputs \
(podcast episode notes, app-store chart movers, news headlines, SEC registrations) \
for EMERGING, investable consumer/culture/tech trends — the kind of obscure early \
signal that Labubu was for Pop Mart, or 'Grow a Garden' was for Roblox.

From the numbered items below, extract at most {max_out} candidate signals. Rules:
- STRONGLY prefer niche, under-covered names: small/mid caps (<$10B), foreign \
listings, chokepoint suppliers (e.g. a tungsten near-monopoly like Almonty), fresh \
S-1s, apps quietly climbing charts, brands going viral. Megacap coverage \
(AAPL/MSFT/GOOGL/AMZN/META/NVDA/TSLA/NFLX and the like) is NOISE — exclude it \
unless something structurally unusual is happening across multiple sources.
- Only include a candidate when there is a plausible PUBLIC-EQUITY angle: a public \
company, or a public parent company. If the company is private, still include it \
but set "public_company" to null (it becomes a watchlist item).
- ticker_hint is only a hint; it will be independently verified. Never invent one — \
use null if unsure.
- why_matters: one crisp sentence an analyst would want, citing what's actually in the items.
- item_ids: the ids of EVERY input item that supports the signal (verbatim quote in \
"evidence" from one of them).

Respond with ONLY a JSON array, each element:
{{"trend_name": str, "public_company": str|null, "ticker_hint": str|null,
 "why_matters": str, "evidence": str, "item_ids": [str], "confidence": 0.0-1.0}}

ITEMS:
{items_block}"""


def _items_block(items):
    lines = []
    for it in items:
        lines.append(f"[{it['id']}] ({it['source_type']}/{it['source_name']}) "
                     f"{it['text'][:600]}")
    return "\n".join(lines)


def _parse_llm_json(text):
    if not text:
        return []
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
    if isinstance(data, dict):
        data = data.get("signals", [])
    out = []
    for c in data if isinstance(data, list) else []:
        if isinstance(c, dict) and c.get("trend_name") and c.get("item_ids"):
            out.append(c)
    return out


def _call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={key}")
    resp = fetch.post_json(url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0.2},
    })
    try:
        return resp["candidates"][0]["content"]["parts"][0]["text"]
    except (TypeError, KeyError, IndexError):
        return None


def _call_groq(prompt):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    resp = fetch.post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"model": GROQ_MODEL, "temperature": 0.2,
         "messages": [{"role": "user", "content": prompt}]},
        headers={"Authorization": f"Bearer {key}"})
    try:
        return resp["choices"][0]["message"]["content"]
    except (TypeError, KeyError, IndexError):
        return None


# ------------------------------------------------------------ rule-based
TICKER_RE = re.compile(r"\((?:NYSE|NASDAQ|Nasdaq|NYSEARCA|AMEX)\s*:\s*([A-Z][A-Z.\-]{0,5})\)")
BARE_TICKER_RE = re.compile(r"\(([A-Z]{2,5})\)")  # e.g. "Roblox (RBLX)" — SEC-verified below
_GENERIC_TOKENS = {
    "holdings", "group", "international", "company", "brands", "global",
    "financial", "capital", "energy", "technologies", "technology", "resources",
    "industries", "systems", "partners", "pharmaceuticals", "therapeutics",
    "acquisition", "sciences", "digital", "network", "networks", "american",
    "united", "national", "general", "first", "health", "medical", "growth",
}


def _token_index(sec_by_name):
    """Distinctive company-name FIRST tokens that uniquely identify one SEC
    filer (companies are referred to by their first word: 'Palantir', 'Roblox')."""
    counts, first = {}, {}
    for name, ticker in (sec_by_name or {}).items():
        toks = name.split()
        if not toks:
            continue
        tok = toks[0]
        if len(tok) >= 6 and tok not in _GENERIC_TOKENS:
            counts[tok] = counts.get(tok, 0) + 1
            first.setdefault(tok, (ticker, name))
    return {t: v for t, v in first.items() if counts[t] == 1}


def _rule_based(items, brand_map, sec, max_out):
    """No-LLM fallback: curated brand map, '(NASDAQ: XYZ)'-style mentions,
    SEC-verified bare '(XYZ)' mentions, and unique company-name tokens."""
    by_ticker, by_name = sec or ({}, {})
    tok_idx = _token_index(by_name)
    found = {}
    for it in items:
        text = it["text"]
        low = text.lower()
        for brand, info in brand_map.items():
            if re.search(r"\b" + re.escape(brand.lower()) + r"\b", low):
                key = brand.lower()
                c = found.setdefault(key, {
                    "trend_name": brand,
                    "public_company": info.get("company"),
                    "ticker_hint": info.get("ticker"),
                    "why_matters": f"'{brand}' surfacing in daily inputs"
                                   f" (mapped to {info.get('company') or 'private company'}).",
                    "evidence": text[:220],
                    "item_ids": [], "confidence": 0.55,
                })
                if it["id"] not in c["item_ids"]:
                    c["item_ids"].append(it["id"])
        tickers_here = {m.group(1) for m in TICKER_RE.finditer(text)}
        tickers_here |= {m.group(1) for m in BARE_TICKER_RE.finditer(text)
                         if m.group(1) in by_ticker}
        for t in tickers_here:
            key = "tkr:" + t
            c = found.setdefault(key, {
                "trend_name": (by_ticker.get(t) or text[:60].rsplit(" ", 1)[0]),
                "public_company": by_ticker.get(t), "ticker_hint": t,
                "why_matters": f"Ticker cited in source: “{it['title'][:90]}”.",
                "evidence": text[:220], "item_ids": [], "confidence": 0.5,
            })
            if it["id"] not in c["item_ids"]:
                c["item_ids"].append(it["id"])
        for tok, (t, name) in tok_idx.items():
            # proper-noun occurrence of a distinctive company-name token
            if tok in low and re.search(r"\b" + re.escape(tok.capitalize()) + r"\b", text):
                key = "tkr:" + t
                c = found.setdefault(key, {
                    "trend_name": by_ticker.get(t, tok.capitalize()),
                    "public_company": by_ticker.get(t), "ticker_hint": t,
                    "why_matters": f"{tok.capitalize()} named in: “{it['title'][:90]}”.",
                    "evidence": text[:220], "item_ids": [], "confidence": 0.4,
                })
                if it["id"] not in c["item_ids"]:
                    c["item_ids"].append(it["id"])
    ranked = sorted(found.values(),
                    key=lambda c: len(c["item_ids"]), reverse=True)
    return ranked[:max_out]


# ------------------------------------------------------------ entry point
def extract(items, brand_map, sec=None, max_out=15, chunk=45):
    """Returns (candidates, provider_used). `sec` = (by_ticker, by_name)."""
    if not items:
        return [], "none"
    llm_available = not fetch.FIXTURE_DIR and (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))
    if llm_available:
        merged = {}
        for i in range(0, len(items), chunk):
            block = _items_block(items[i:i + chunk])
            prompt = PROMPT.format(max_out=max_out, items_block=block)
            raw = _call_gemini(prompt)
            provider = "gemini"
            if raw is None:
                raw = _call_groq(prompt)
                provider = "groq"
            for c in _parse_llm_json(raw):
                key = c["trend_name"].strip().lower()
                if key in merged:
                    merged[key]["item_ids"] = sorted(
                        set(merged[key]["item_ids"]) | set(c["item_ids"]))
                    merged[key]["confidence"] = max(
                        merged[key].get("confidence", 0), c.get("confidence", 0))
                else:
                    merged[key] = c
        if merged:
            # union with rule-based so the curated brand map is never missed
            for c in _rule_based(items, brand_map, sec, max_out):
                key = c["trend_name"].strip().lower()
                merged.setdefault(key, c)
            return list(merged.values())[: max_out * 2], provider
        # fall through to rules if every LLM call failed
    return _rule_based(items, brand_map, sec, max_out), "rules"
