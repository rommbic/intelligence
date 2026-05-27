"""Writes the JSON the static dashboard consumes:
  data/latest.json          -> today's brief (what the dashboard loads by default)
  data/YYYY-MM-DD.json       -> daily archive
  data/index.json            -> list of available dates (for the history dropdown)
"""
from __future__ import annotations

import json
import logging
from datetime import timezone

from ..config import DATA_DIR
from ..util import Item, now_utc

log = logging.getLogger("deliver.dashboard")


def write(items: list[Item], settings: dict) -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    today = now_utc().astimezone(timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "generated_at": now_utc().isoformat(),
        "date": today,
        "count": len(items),
        "categories": [c["name"] for c in settings["categories"]],
        "items": [it.to_dict() for it in items],
    }

    (DATA_DIR / f"{today}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (DATA_DIR / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Maintain the date index for the history dropdown.
    dates = sorted(
        {p.stem for p in DATA_DIR.glob("*.json")
         if p.stem not in ("latest", "index") and len(p.stem) == 10},
        reverse=True,
    )
    (DATA_DIR / "index.json").write_text(
        json.dumps({"dates": dates}, indent=2), encoding="utf-8")

    log.info("Dashboard data written for %s (%d items)", today, len(items))
    return payload
