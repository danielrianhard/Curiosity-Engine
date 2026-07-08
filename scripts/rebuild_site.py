"""Rebuild docs/ from data/history without re-ingesting anything.

Usage: python -m scripts.rebuild_site   (from the repo root)
"""
import datetime as dt
import os

from engine import history, publish

base = {
    "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    "dashboard_url": os.environ.get("DASHBOARD_URL", "#"),
    "provider": "history",
}
print(publish.render_site(history.recent_days(30), base))
