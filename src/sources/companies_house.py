"""Optional: Companies House filing signals (director appointments, charges,
incorporations). Requires a free CH API key in CH_API_KEY and a watch-list of
company numbers in config/companies.json. If either is missing this module
returns nothing and the run continues normally.

Get a key: https://developer.company-information.service.gov.uk/
companies.json format:  [{"number": "00824821", "name": "Travis Perkins plc"}, ...]
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from pathlib import Path

import requests

from ..config import CONFIG_DIR
from ..util import Item, now_utc

log = logging.getLogger("sources.companies_house")
BASE = "https://api.company-information.service.gov.uk"

# Filing categories that imply growth / change worth a recruiter's attention.
INTERESTING = {
    "officers": ("Leadership appointment", 8),
    "appointment": ("Leadership appointment", 8),
    "mortgage": ("Investment / funding", 6),       # MR01 charge = secured lending
    "persons-with-significant-control": ("Acquisition / M&A", 8),
    "incorporation": ("New facility / expansion", 6),
}


def _classify(filing: dict):
    text = " ".join(str(filing.get(k, "")) for k in ("category", "type", "description")).lower()
    for needle, (cat, tier) in INTERESTING.items():
        if needle in text:
            return cat, tier
    return None, None


def fetch(recency_hours: int) -> list[Item]:
    key = os.getenv("CH_API_KEY")
    path = CONFIG_DIR / "companies.json"
    if not key or not path.exists():
        log.info("Companies House skipped (no CH_API_KEY or companies.json).")
        return []

    companies = json.loads(Path(path).read_text(encoding="utf-8"))
    cutoff = (now_utc() - timedelta(hours=recency_hours)).date()
    items: list[Item] = []

    for c in companies:
        num, name = c.get("number"), c.get("name", c.get("number"))
        try:
            r = requests.get(
                f"{BASE}/company/{num}/filing-history",
                auth=(key, ""), params={"items_per_page": 20}, timeout=20,
            )
            r.raise_for_status()
            for f in r.json().get("items", []):
                fdate = f.get("date", "")
                if fdate and fdate[:10] < cutoff.isoformat():
                    continue
                cat, tier = _classify(f)
                if not cat:
                    continue
                desc = f.get("description", f.get("type", "filing")).replace("_", " ").title()
                items.append(
                    Item(
                        title=f"{name}: {desc}",
                        link=f"https://find-and-update.company-information.service.gov.uk/company/{num}/filing-history",
                        source="Companies House",
                        published=now_utc(),
                        summary=f"Companies House filing ({fdate}) for {name}.",
                        feed_group="companies_house",
                        feed_title="Companies House",
                        categories=[cat],
                        company=name,
                        score=tier,
                    )
                )
        except Exception as exc:
            log.warning("CH fetch failed for %s: %s", num, exc)
    log.info("Companies House: %d signal filings", len(items))
    return items
