"""Decide whether THIS run should send the daily email digest.

Resilient to GitHub's unreliable cron: instead of trusting one exact scheduled
slot, the agent sends on the FIRST run at/after `send_after_hour_utc` on a given
date, then records that date in data/email_state.json so it won't send again
that day. A skipped 06:30 slot self-heals on the next run.

Overrides:
  FORCE_EMAIL=1  -> always send this run (used by manual "Run workflow" tests)
  FORCE_EMAIL=0  -> never send this run
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timezone

from ..config import DATA_DIR
from ..util import now_utc

log = logging.getLogger("deliver.schedule")
STATE = DATA_DIR / "email_state.json"


def _last_sent_date() -> str:
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get("last_sent_date", "")
    except Exception:
        return ""


def mark_sent(date_str: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        STATE.write_text(json.dumps({"last_sent_date": date_str}, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("Could not write email_state.json: %s", exc)


def should_send(settings: dict) -> tuple[bool, str]:
    """Returns (send?, today_str). today_str is passed to mark_sent() after a
    successful send so we record the date only once the email actually went."""
    force = os.getenv("FORCE_EMAIL")
    now = now_utc().astimezone(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    if force in ("1", "true", "True"):
        log.info("FORCE_EMAIL set: sending regardless of schedule.")
        return True, today
    if force in ("0", "false", "False"):
        log.info("FORCE_EMAIL=0: not sending this run.")
        return False, today

    target_hour = settings.get("email", {}).get("send_after_hour_utc", 6)
    if now.hour < target_hour:
        log.info("Before target hour (%02d:00 UTC); not the morning send window yet.", target_hour)
        return False, today
    if _last_sent_date() == today:
        log.info("Digest already sent today (%s); skipping.", today)
        return False, today
    log.info("First run at/after %02d:00 UTC today and not yet sent -> sending digest.", target_hour)
    return True, today
