"""Rommbic Intelligence Agent — daily entry point.

    python -m src.main

Pipeline: collect (RSS + optional CH + optional careers) -> filter -> dedup
-> score -> write dashboard data -> email digest. Every stage is defensive so
the scheduled run is effectively unbreakable.
"""
from __future__ import annotations

import logging
import sys

from .config import load_feeds, load_settings, watch_companies
from .deliver import dashboard, email_digest
from .pipeline import dedup, relevance, score
from .sources import careers, companies_house, rss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def run() -> int:
    settings = load_settings()
    feeds = load_feeds()
    companies = watch_companies(settings, feeds)
    log.info("Loaded %d feeds, %d watch-list companies", len(feeds), len(companies))

    # 1) COLLECT
    items = rss.fetch_all(feeds)
    items += companies_house.fetch(settings["recency_hours"])
    items += careers.fetch()
    log.info("Collected %d raw items", len(items))

    # 2) FILTER  3) DEDUP  4) SCORE
    items = relevance.filter_items(items, settings, companies)
    items = dedup.dedup(items)
    items = score.score(items, settings)
    log.info("Final: %d scored items", len(items))

    # 5) DELIVER
    dashboard.write(items, settings)
    # The dashboard refreshes every run. The email is sent at most ONCE per day,
    # on the first run at/after the configured morning hour — resilient to
    # GitHub skipping a scheduled slot. See deliver/schedule.py.
    from .deliver import schedule
    send, today = schedule.should_send(settings)
    if send:
        email_digest.send(items, settings)
        schedule.mark_sent(today)   # record only after the send attempt
        # 6) OUTREACH — runs on the same once-per-day cadence as the email.
        # Defensively isolated: failures logged, never raised.
        try:
            from .outreach import orchestrator as outreach
            outreach.run()
        except Exception:
            log.exception("Outreach step failed (portal + email are unaffected).")
    log.info("Done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        log.exception("Fatal error in daily run")
        sys.exit(1)
