"""Flat-file state: one JSON per day in data/history/, committed to the repo."""
import datetime as dt
import glob
import json
import os

HIST_DIR = "data/history"


def load(days=30):
    """-> {trend_key: {first_seen, best_score, last_seen}} over recent days."""
    out = {}
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    for path in sorted(glob.glob(os.path.join(HIST_DIR, "*.json"))):
        day = os.path.basename(path)[:-5]
        if day < cutoff:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                daily = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for sig in daily.get("signals", []) + daily.get("watchlist", []):
            key = sig["trend"].lower()
            rec = out.setdefault(key, {"first_seen": day, "best_score": 0})
            rec["best_score"] = max(rec["best_score"], sig.get("score", 0))
            rec["last_seen"] = day
    return out


def recent_days(limit=14):
    """[(date, daily_dict)] newest first, for the dashboard history section."""
    days = []
    for path in sorted(glob.glob(os.path.join(HIST_DIR, "*.json")), reverse=True)[:limit]:
        try:
            with open(path, encoding="utf-8") as f:
                days.append((os.path.basename(path)[:-5], json.load(f)))
        except (json.JSONDecodeError, OSError):
            continue
    return days


def save(date_str, payload):
    os.makedirs(HIST_DIR, exist_ok=True)
    with open(os.path.join(HIST_DIR, f"{date_str}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, default=str)


def load_snapshot(name):
    path = os.path.join("data", "raw", f"{name}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_snapshot(name, data):
    os.makedirs(os.path.join("data", "raw"), exist_ok=True)
    with open(os.path.join("data", "raw", f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, default=str)
