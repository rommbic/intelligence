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
    # The dashboard refreshes every run; the email is gated so the few-hourly
    # refresh doesn't email consultants 8x/day. SEND_EMAIL=0 disables it for a
    # given run (the workflow sets this on the intra-day refreshes).
    import os
    if os.getenv("SEND_EMAIL", "1") not in ("0", "false", "False", ""):
        email_digest.send(items, settings)
    else:
        log.info("Email skipped for this run (SEND_EMAIL disabled).")
    log.info("Done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        log.exception("Fatal error in daily run")
        sys.exit(1)
