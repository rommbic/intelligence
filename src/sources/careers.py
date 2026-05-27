"""Optional: watch target companies' own careers pages — the strongest signal
(a brand-new vacancy). Best-effort: fetches the page HTML, extracts visible
link text, and diffs against the previous run's snapshot stored in
data/careers_state.json. New entries become Tier-1 items.

config/careers.json format:
  [{"name": "Marshalls", "url": "https://www.marshalls.co.uk/careers"}, ...]

NOTE: pages that render jobs purely via JavaScript won't expose listings to a
plain fetch. For those, point this at the company's Greenhouse/Workable/Teamtailor
board URL (which is static HTML), or add a rendering step later.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from ..config import CONFIG_DIR, DATA_DIR
from ..util import Item, now_utc

log = logging.getLogger("sources.careers")
_UA = "Mozilla/5.0 (compatible; RommbicIntel/1.0; +https://rommbic.co.uk)"
_ANCHOR = re.compile(r"<a[^>]*>(.*?)</a>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_JOBWORDS = re.compile(r"manager|director|engineer|sales|estimator|surveyor|"
                       r"executive|specialist|representative|technical|buyer|"
                       r"merchand|operative|driver|controller|coordinator|"
                       r"assistant|advisor|consultant|lead|head of", re.I)

STATE = DATA_DIR / "careers_state.json"


def _extract_jobs(html: str) -> set[str]:
    found = set()
    for m in _ANCHOR.findall(html):
        text = _TAG.sub("", m).strip()
        text = re.sub(r"\s+", " ", text)
        if 6 <= len(text) <= 90 and _JOBWORDS.search(text):
            found.add(text)
    return found


def fetch() -> list[Item]:
    path = CONFIG_DIR / "careers.json"
    if not path.exists():
        log.info("Careers monitor skipped (no careers.json).")
        return []

    targets = json.loads(Path(path).read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    items: list[Item] = []

    for t in targets:
        name, url = t.get("name"), t.get("url")
        try:
            html = requests.get(url, headers={"User-Agent": _UA}, timeout=20).text
            jobs = _extract_jobs(html)
            previous = set(state.get(url, []))
            new_jobs = jobs - previous if previous else set()  # first run = baseline only
            for job in sorted(new_jobs):
                items.append(
                    Item(
                        title=f"{name}: new vacancy — {job}",
                        link=url,
                        source=f"{name} careers",
                        published=now_utc(),
                        summary=f"New listing detected on {name}'s careers page.",
                        feed_group="careers",
                        feed_title=f"{name} careers",
                        categories=["Hiring / job creation"],
                        company=name,
                        score=10,
                    )
                )
            state[url] = sorted(jobs)
        except Exception as exc:
            log.warning("Careers fetch failed for %s: %s", name, exc)

    DATA_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    log.info("Careers monitor: %d new vacancies", len(items))
    return items
