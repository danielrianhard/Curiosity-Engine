"""Daily ingestion: podcasts, app-store charts, news RSS, EDGAR, Google Trends.

Every source returns a list of normalized "items":
    {id, source_type, source_name, title, url, published, text, extra}
Each source is wrapped so a failure yields an empty list + a status flag,
never a crashed run.
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import xml.etree.ElementTree as ET

from . import fetch

ITUNES_LOOKUP = "https://itunes.apple.com/lookup?id={id}"
APPLE_CHARTS = [
    ("Apple Top Free Apps (US)", "https://rss.marketingtools.apple.com/api/v2/us/apps/top-free/100/apps.json"),
    ("Apple Top Paid Apps (US)", "https://rss.marketingtools.apple.com/api/v2/us/apps/top-paid/100/apps.json"),
]
EDGAR_FTS = ("https://efts.sec.gov/LATEST/search-index?q=%22{q}%22"
             "&dateRange=custom&startdt={start}&enddt={end}")

TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return html.unescape(TAG_RE.sub(" ", s or "")).strip()


def _parse_date(s):
    try:
        return email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_rss(xml_text: str):
    """Minimal, dependency-free RSS 2.0 / Atom parser -> list of dicts."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # feeds occasionally contain stray control chars
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml_text)
        try:
            root = ET.fromstring(cleaned)
        except ET.ParseError:
            return out
    nodes = root.iter()
    for node in nodes:
        if _local(node.tag) not in ("item", "entry"):
            continue
        e = {"title": "", "link": "", "summary": "", "published": None}
        for child in node:
            t = _local(child.tag)
            if t == "title":
                e["title"] = _strip_html(child.text or "")
            elif t == "link":
                e["link"] = (child.text or child.get("href") or "").strip()
            elif t in ("description", "summary", "content", "encoded"):
                txt = _strip_html(child.text or "")
                if len(txt) > len(e["summary"]):
                    e["summary"] = txt
            elif t in ("pubDate", "published", "updated"):
                e["published"] = e["published"] or _parse_date(child.text)
                if e["published"] is None and child.text:
                    try:  # Atom ISO dates
                        e["published"] = dt.datetime.fromisoformat(
                            child.text.strip().replace("Z", "+00:00"))
                    except ValueError:
                        pass
        if e["title"]:
            out.append(e)
    return out


def _recent(published, days):
    if published is None:
        return True  # keep undated items; extraction judges relevance
    now = dt.datetime.now(dt.timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=dt.timezone.utc)
    return (now - published).days < days


def resolve_itunes_feed(itunes_id):
    data = fetch.get_json(ITUNES_LOOKUP.format(id=itunes_id))
    if data and data.get("results"):
        return data["results"][0].get("feedUrl")
    return None


# ---------------------------------------------------------------- podcasts
def ingest_podcasts(cfg, days=3):
    items = []
    for show in cfg.get("podcasts", []):
        name = show.get("name", "podcast")
        rss = show.get("rss") or (
            resolve_itunes_feed(show["itunes_id"]) if show.get("itunes_id") else None)
        if not rss:
            continue
        xml_text = fetch.get(rss)
        if not xml_text:
            continue
        for e in parse_rss(xml_text)[:15]:
            if not _recent(e["published"], days):
                continue
            summary = e["summary"][:2500]
            items.append({
                "id": f"pod:{fetch.fixture_key(name + e['title'])}",
                "source_type": "podcast",
                "source_name": name,
                "title": e["title"],
                "url": e["link"] or rss,
                "published": e["published"].isoformat() if e["published"] else None,
                "text": f"{e['title']}. {summary}",
                "extra": {},
            })
    return items


# ---------------------------------------------------------------- app store
def ingest_appstore(prev_snapshot: dict | None):
    """Returns (items, snapshot). Items only for movers/new entrants."""
    items, snapshot = [], {}
    for chart_name, url in APPLE_CHARTS:
        data = fetch.get_json(url)
        if not data:
            continue
        results = data.get("feed", {}).get("results", [])
        ranks = {}
        for rank, app in enumerate(results, start=1):
            key = app.get("id") or app.get("name")
            ranks[key] = {"rank": rank, "name": app.get("name"),
                          "dev": app.get("artistName"), "url": app.get("url"),
                          "genres": [g.get("name") for g in app.get("genres", [])]}
        snapshot[chart_name] = ranks
        prev = (prev_snapshot or {}).get(chart_name, {})
        for key, cur in ranks.items():
            old = prev.get(str(key)) or prev.get(key)
            old_rank = old["rank"] if old else None
            delta = (old_rank - cur["rank"]) if old_rank else None
            is_new = old is None and bool(prev)
            notable = (is_new and cur["rank"] <= 50) or (delta is not None and delta >= 10)
            if not (notable or cur["rank"] <= 10):
                continue
            move = (f"NEW at #{cur['rank']}" if is_new
                    else f"#{old_rank} -> #{cur['rank']}" if delta else f"#{cur['rank']}")
            genres = ", ".join(g for g in cur["genres"] if g) or "n/a"
            items.append({
                "id": f"app:{fetch.fixture_key(chart_name + str(key))}",
                "source_type": "appstore",
                "source_name": chart_name,
                "title": f"{cur['name']} ({move})",
                "url": cur["url"],
                "published": None,
                "text": (f"App '{cur['name']}' by {cur['dev']} is {move} on {chart_name}. "
                         f"Genres: {genres}."),
                "extra": {"rank": cur["rank"], "prev_rank": old_rank,
                          "delta": delta, "new_entrant": is_new},
            })
    return items, snapshot


# ---------------------------------------------------------------- news
def ingest_news(cfg, days=2):
    items = []
    for feed in cfg.get("news_feeds", []):
        xml_text = fetch.get(feed["url"])
        if not xml_text:
            continue
        for e in parse_rss(xml_text)[:40]:
            if not _recent(e["published"], days):
                continue
            items.append({
                "id": f"news:{fetch.fixture_key(e['link'] or e['title'])}",
                "source_type": "news",
                "source_name": feed["name"],
                "title": e["title"],
                "url": e["link"],
                "published": e["published"].isoformat() if e["published"] else None,
                "text": f"{e['title']}. {e['summary'][:1200]}",
                "extra": {},
            })
    return items


# ---------------------------------------------------------------- EDGAR
def edgar_mentions(term: str, days=30) -> dict | None:
    """Count recent SEC filings mentioning `term` (corroboration signal)."""
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    url = EDGAR_FTS.format(q=term.replace(" ", "+"), start=start.isoformat(),
                           end=end.isoformat())
    data = fetch.get_json(url, min_interval=0.15)  # stay far under SEC's 10 req/s
    if not data:
        return None
    total = (data.get("hits", {}).get("total", {}) or {}).get("value", 0)
    first = (data.get("hits", {}).get("hits") or [{}])[0].get("_source", {})
    return {
        "term": term, "filings_30d": total,
        "example": first.get("display_names", [None])[0] if first else None,
        "search_url": ("https://efts.sec.gov/LATEST/search-index?q=%22"
                       + term.replace(" ", "+") + "%22"),
        "ui_url": f"https://www.sec.gov/cgi-srv/srqsb?text={term}"  # informational
    }


def ingest_edgar_new_registrations(days=7):
    """Recent S-1/F-1 registrations: fresh IPO pipeline = early signals."""
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    url = (f"https://efts.sec.gov/LATEST/search-index?q=%22initial+public+offering%22"
           f"&forms=S-1,F-1&dateRange=custom&startdt={start}&enddt={end}")
    data = fetch.get_json(url, min_interval=0.15)
    items = []
    if not data:
        return items
    for hit in (data.get("hits", {}).get("hits") or [])[:15]:
        src = hit.get("_source", {})
        names = src.get("display_names") or ["Unknown filer"]
        adsh = (src.get("adsh") or "").replace("-", "")
        cik = str(src.get("cik") or "").lstrip("0")
        link = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}"
                if cik and adsh else "https://efts.sec.gov/LATEST/search-index?q=IPO")
        items.append({
            "id": f"edgar:{fetch.fixture_key(str(names[0]) + str(adsh))}",
            "source_type": "edgar",
            "source_name": "SEC EDGAR (S-1/F-1)",
            "title": f"New registration: {names[0]}",
            "url": link,
            "published": src.get("file_date"),
            "text": f"New SEC registration statement filed by {names[0]} ({src.get('file_type', 'S-1')}).",
            "extra": {"form": src.get("file_type")},
        })
    return items


# ---------------------------------------------------------------- trends
def trends_interest(terms: list[str]) -> dict:
    """OPTIONAL Google Trends check via the unofficial `trendspy` package.

    pytrends was archived in 2025; every free Trends wrapper is unofficial and
    rate-limit-prone, so this is a best-effort enhancer: any failure returns {}
    and the pipeline continues without Trends data.
    """
    if fetch.FIXTURE_DIR:
        path = os.path.join(fetch.FIXTURE_DIR, "trends.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return {}
    out = {}
    try:
        from trendspy import Trends  # type: ignore
        tr = Trends()
        for term in terms[:10]:  # keep request volume tiny
            try:
                df = tr.interest_over_time(term, timeframe="now 7-d")
                series = df[term].tolist() if term in getattr(df, "columns", []) else []
                if len(series) >= 8:
                    head = sum(series[: len(series) // 2]) or 1
                    tail = sum(series[len(series) // 2:])
                    out[term] = {"rising": tail > head * 1.5,
                                 "ratio": round(tail / head, 2)}
            except Exception:
                continue
    except Exception:
        return {}
    return out
