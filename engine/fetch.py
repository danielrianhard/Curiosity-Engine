"""HTTP layer for the Curiosity Engine.

All network access goes through get()/get_json() so that:
  * every request carries a proper User-Agent (SEC requires one),
  * failures degrade gracefully (return None, never raise),
  * the whole pipeline can run offline against saved fixtures
    (set CE_FIXTURES=/path/to/dir) for testing/sample runs.

Fixture files are named sha1(url)[:16] + ".txt".
"""
import hashlib
import json
import os
import time

import requests

USER_AGENT = os.environ.get(
    "CE_USER_AGENT",
    "CuriosityEngine/1.0 (personal research tool; set CE_USER_AGENT secret to your contact email)",
)
FIXTURE_DIR = os.environ.get("CE_FIXTURES")  # offline mode when set


def fixture_key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def get(url: str, timeout: int = 25, retries: int = 2, headers: dict | None = None,
        min_interval: float = 0.0) -> str | None:
    """GET a URL, returning body text or None. Never raises."""
    if FIXTURE_DIR:
        path = os.path.join(FIXTURE_DIR, fixture_key(url) + ".txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        return None

    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=h, timeout=timeout)
            if resp.status_code == 200:
                if min_interval:
                    time.sleep(min_interval)
                return resp.text
            if resp.status_code in (403, 429):  # rate limited: back off harder
                time.sleep(5 * (attempt + 1))
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    return None


def get_json(url: str, **kw):
    text = get(url, **kw)
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def post_json(url: str, payload: dict, headers: dict | None = None,
              timeout: int = 60, retries: int = 1):
    """POST JSON (used for LLM APIs). Returns parsed JSON or None. Never raises.

    Not fixture-able: in fixture mode LLM calls are skipped upstream.
    """
    h = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=h, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                time.sleep(15 * (attempt + 1))
        except requests.RequestException:
            pass
        time.sleep(3)
    return None
