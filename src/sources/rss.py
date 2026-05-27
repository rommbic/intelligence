"""Fetch and parse RSS / Google News feeds. Each feed failure is isolated so
one dead feed can never break the daily run."""
from __future__ import annotations

import logging
from datetime import timezone

import feedparser

from ..util import Item, now_utc

log = logging.getLogger("sources.rss")

# A real browser-ish UA avoids the occasional 403 from news endpoints.
_UA = "Mozilla/5.0 (compatible; RommbicIntel/1.0; +https://rommbic.co.uk)"


def _published(entry) -> object:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            import calendar
            return now_utc().fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def fetch_feed(feed: dict) -> list[Item]:
    items: list[Item] = []
    try:
        parsed = feedparser.parse(feed["url"], agent=_UA)
        if parsed.bozo and not parsed.entries:
            log.warning("Feed parse issue for %s: %s", feed["title"], parsed.bozo_exception)
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            source = ""
            if entry.get("source") and entry.source.get("title"):
                source = entry.source.title
            items.append(
                Item(
                    title=title,
                    link=link,
                    source=source,
                    published=_published(entry),
                    summary=(entry.get("summary") or "")[:600],
                    feed_group=feed["group"],
                    feed_title=feed["title"],
                )
            )
    except Exception as exc:  # never let one feed kill the run
        log.warning("Failed to fetch %s: %s", feed.get("title"), exc)
    return items


def fetch_all(feeds: list[dict]) -> list[Item]:
    import random
    import time
    out: list[Item] = []
    for i, feed in enumerate(feeds):
        got = fetch_feed(feed)
        if got:
            log.info("%-46s %3d items", feed["title"][:46], len(got))
        out.extend(got)
        # Polite pacing: ~150+ feeds means we space requests so Google News
        # doesn't rate-limit the daily run. ~0.6s + jitter.
        if i < len(feeds) - 1:
            time.sleep(0.6 + random.random() * 0.4)
    return out
