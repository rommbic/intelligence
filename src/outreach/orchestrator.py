"""Outreach orchestrator — runs after the main portal build.

For each signal above the score threshold:
  * look up the company in Loxo
  * if found: fetch directors -> for each, get email -> Claude draft -> Gmail draft
  * if not found: append to prospecting queue for visibility on the dashboard

Everything is defensive: any single failure is logged and skipped, not raised.
State (which items have already been drafted) is persisted so we never draft
the same signal twice, even across runs of the same day.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timezone
from typing import Optional

from ..config import DATA_DIR, load_settings
from ..util import now_utc
from .drafter import draft_email
from .gmail_drafts import GmailDrafter
from .loxo_client import LoxoClient

log = logging.getLogger("outreach.orchestrator")

STATE_FILE = DATA_DIR / "outreach_state.json"
PROSPECT_FILE = DATA_DIR / "prospecting_queue.json"
SUMMARY_FILE = DATA_DIR / "outreach_summary.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"drafted_signal_ids": []}


def _save_state(state: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_prospects() -> list[dict]:
    if PROSPECT_FILE.exists():
        try:
            data = json.loads(PROSPECT_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_prospects(prospects: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PROSPECT_FILE.write_text(json.dumps(prospects, indent=2), encoding="utf-8")


def _load_todays_signals(settings: dict) -> list[dict]:
    """Read data/latest.json — produced by the main portal run. Only items
    scoring at/above the outreach threshold, that name a specific company."""
    path = DATA_DIR / "latest.json"
    if not path.exists():
        log.warning("No latest.json — main pipeline hasn't run yet.")
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    threshold = settings.get("outreach", {}).get("min_score", 8)
    log.info("Outreach filter: reading latest.json from %s (%d items total)",
             path.resolve(), len(payload.get("items") or []))
    log.info("Outreach filter: threshold=%s (%s)", threshold, type(threshold).__name__)

    kept: list[dict] = []
    for it in payload.get("items") or []:
        score = it.get("score", 0)
        company = it.get("company", "")
        passes_score = score >= threshold
        has_company = bool(company)
        if passes_score and has_company:
            kept.append(it)
        else:
            # Log the first few rejections with their exact values and types —
            # this reveals if score is an unexpected type, if company is empty
            # for items the dashboard shows tagged, etc.
            if len(kept) < 3 or not passes_score or not has_company:
                log.info("  REJECTED: score=%r (%s, passes=%s), company=%r (has=%s), title=%r",
                         score, type(score).__name__, passes_score,
                         company, has_company, (it.get("title") or "")[:60])
    log.info("Outreach filter: %d passed", len(kept))
    return kept


def _signal_id(item: dict) -> str:
    return item.get("fingerprint") or item.get("link") or item.get("title", "")


def run() -> dict:
    """Main entry point. Returns a summary dict written to data/outreach_summary.json."""
    settings = load_settings()
    outreach_cfg = settings.get("outreach", {})

    if not outreach_cfg.get("enabled", False):
        log.info("Outreach disabled in settings; skipping.")
        return {"enabled": False}

    env_inbox = os.getenv("OUTREACH_INBOX")
    yaml_inbox = outreach_cfg.get("inbox", "")
    inbox = env_inbox or yaml_inbox
    if not inbox:
        log.warning("No OUTREACH_INBOX configured; skipping.")
        return {"enabled": True, "error": "no inbox configured"}
    source = "env OUTREACH_INBOX secret" if env_inbox else "settings.yaml"
    log.info("Outreach inbox resolved to %r (source: %s)", inbox, source)

    signals = _load_todays_signals(settings)
    log.info("Outreach: %d qualifying signals in today's brief", len(signals))
    if not signals:
        summary = {"enabled": True, "generated_at": now_utc().isoformat(),
                   "signals_processed": 0, "drafts_created": 0,
                   "prospects_logged": 0}
        SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    state = _load_state()
    already = set(state.get("drafted_signal_ids", []))
    prospects = _load_prospects()
    existing_prospects = {p.get("company") for p in prospects}

    loxo = LoxoClient()
    gmail = GmailDrafter(inbox)
    cap_per_company = outreach_cfg.get("max_drafts_per_company", 5)

    # Per-run caches — Loxo lookups are the slowest step, and multiple signals
    # about the same company (James Hardie appeared twice in a real run)
    # shouldn't each fire fresh API calls.
    company_cache: dict = {}      # normalised name -> matched company (or None)
    directors_cache: dict = {}    # company_id -> list of director dicts

    drafts_created = 0
    prospects_logged = 0
    processed = 0

    for item in signals:
        sid = _signal_id(item)
        if sid in already:
            continue  # already processed on an earlier run today
        processed += 1

        company_name = item.get("company", "")
        cache_key = company_name.lower().strip()
        if cache_key in company_cache:
            matched = company_cache[cache_key]
        else:
            matched = loxo.search_company(company_name)
            company_cache[cache_key] = matched

        if not matched:
            if company_name not in existing_prospects:
                prospects.append({
                    "company": company_name,
                    "first_seen": now_utc().isoformat(),
                    "article_title": item.get("title", ""),
                    "article_url": item.get("link", ""),
                    "score": item.get("score", 0),
                })
                existing_prospects.add(company_name)
                prospects_logged += 1
                log.info("Prospect logged (not in Loxo): %s", company_name)
            already.add(sid)
            continue

        company_id = matched.get("id")
        if company_id in directors_cache:
            directors = directors_cache[company_id]
        else:
            directors = loxo.fetch_directors(company_id, cap=cap_per_company)
            directors_cache[company_id] = directors
        if not directors:
            log.info("No directors found in Loxo for %s", company_name)
            already.add(sid)
            continue

        for person in directors:
            person_detail = loxo.fetch_person_detail(person.get("id"))
            if not person_detail:
                continue
            email = LoxoClient.extract_primary_email(person_detail)
            if not email:
                log.info("No email on file for %s at %s",
                         person.get("name"), company_name)
                continue

            # Prefer the detail record for name and title (listing responses
            # can return trimmed/empty fields on some Loxo accounts). Fall back
            # to the listing record if the detail is missing the field.
            resolved_name = (person_detail.get("name")
                             or person.get("name") or "").strip()
            resolved_title = (person_detail.get("current_title")
                              or person.get("current_title") or "").strip()

            # CRITICAL: Loxo's /companies/{id}/people endpoint returns anyone
            # linked to the company - including past roles and network links.
            # Only draft when the person's CURRENT employer actually matches
            # the target company. Otherwise we'd email news about British
            # Steel to someone who left there five years ago and now works
            # at a completely different firm.
            current_employer = (person_detail.get("current_company")
                                or person.get("current_company") or "").strip()
            target = (matched.get("name") or company_name or "").strip()
            if current_employer and target:
                # Case-insensitive substring check either way, so "British
                # Steel" matches "British Steel Ltd" and vice versa.
                a, b = current_employer.lower(), target.lower()
                if a not in b and b not in a:
                    log.info("SKIP: %s current employer is %r, not %r - historical link only",
                             resolved_name, current_employer, target)
                    continue

            log.info("Drafting for %r (title=%r) at %s",
                     resolved_name or "[UNKNOWN NAME]",
                     resolved_title or "[UNKNOWN TITLE]",
                     company_name)

            subject, body_html = draft_email(
                recipient_name=resolved_name,
                recipient_title=resolved_title,
                company=matched.get("name") or company_name,
                article_title=item.get("title", ""),
                article_summary=item.get("summary", ""),
                article_url=item.get("link", ""),
                categories=item.get("categories") or [],
            )
            draft_id = gmail.create_draft(to=email, subject=subject, body_html=body_html)
            if draft_id:
                drafts_created += 1

        already.add(sid)

    state["drafted_signal_ids"] = sorted(already)[-500:]  # cap history
    _save_state(state)
    _save_prospects(prospects)

    summary = {
        "enabled": True,
        "generated_at": now_utc().isoformat(),
        "signals_processed": processed,
        "drafts_created": drafts_created,
        "prospects_logged": prospects_logged,
        "inbox": inbox,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Outreach done: %d drafts, %d prospects, %d signals processed",
             drafts_created, prospects_logged, processed)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    run()
