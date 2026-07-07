"""Loxo CRM client.

Everything the outreach automation needs to know about your Loxo account is
here — API paths, field names, and shape confirmed via preflight against
rommbic.app.loxo.co.

Public API surface (used by orchestrator):
  * search_company(name)           -> best-matched company dict or None
  * fetch_directors(company_id)    -> list of person dicts (director titles only)
  * fetch_person_detail(person_id) -> full person record including emails

Errors are caught and logged, never raised — one failed lookup can't break the
run for other signals.
"""
from __future__ import annotations

import logging
import os
import re
from difflib import SequenceMatcher
from typing import Optional

import requests

log = logging.getLogger("outreach.loxo")

BASE = "https://rommbic.app.loxo.co/api/rommbic"

# Words we DO NOT count when comparing company names, so 'Cemex' matches
# 'Cemex UK', 'Marshalls' matches 'Marshalls plc', etc.
_NAME_SUFFIXES = re.compile(
    r"\b(uk|u\.k\.|ltd|limited|plc|group|holdings|company|co|inc|"
    r"international|global|the)\b", re.I,
)


def _normalise_company_name(name: str) -> str:
    n = _NAME_SUFFIXES.sub(" ", (name or "").lower())
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _director_priority(title: str) -> int:
    """Lower = higher priority. Used to sort when there are more directors
    than the per-company cap allows."""
    t = (title or "").lower()
    if any(k in t for k in ("managing director", "ceo", "chief executive")):
        return 0
    if any(k in t for k in ("hr director", "people director", "talent director",
                            "director of people", "director of hr")):
        return 1
    if any(k in t for k in ("commercial director", "sales director",
                            "director of sales", "director of commercial")):
        return 2
    return 3


class LoxoClient:
    def __init__(self, api_key: Optional[str] = None):
        self.key = api_key or os.getenv("LOXO_API_KEY", "")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
        })

    # ---- low-level -------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        try:
            r = self.session.get(f"{BASE}{path}", params=params, timeout=30)
            if r.status_code >= 400:
                log.warning("Loxo GET %s -> HTTP %s: %s", path, r.status_code, r.text[:200])
                return None
            return r.json() if r.text.strip() else None
        except Exception as exc:
            log.warning("Loxo GET %s failed: %s", path, exc)
            return None

    # ---- companies -------------------------------------------------------

    def search_company(self, name: str) -> Optional[dict]:
        """Search Loxo for a company matching the given name. Returns the
        highest-confidence match, or None if no confident match found.

        Confidence heuristic (deliberately conservative to avoid emailing the
        wrong company's contacts):
          - Exact normalised-name match anywhere in results -> confident.
          - Otherwise, use fuzzy string similarity; require >=0.85.
        """
        data = self._get("/companies", params={"query": name})
        if not data:
            return None
        companies = data.get("companies") or []
        if not companies:
            log.info("Loxo: no match for %r", name)
            return None

        target = _normalise_company_name(name)
        # Exact normalised match beats anything else
        for c in companies:
            if _normalise_company_name(c.get("name", "")) == target:
                return c

        # Fuzzy fallback with a high threshold
        scored = []
        for c in companies:
            cand = _normalise_company_name(c.get("name", ""))
            ratio = SequenceMatcher(None, target, cand).ratio() if cand else 0
            scored.append((ratio, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_ratio, top = scored[0]
        if top_ratio >= 0.85:
            log.info("Loxo: fuzzy match for %r -> %r (%.2f)",
                     name, top.get("name"), top_ratio)
            return top
        log.info("Loxo: no confident match for %r (best %.2f)", name, top_ratio)
        return None

    # ---- people at a company --------------------------------------------

    def fetch_people(self, company_id: int) -> list[dict]:
        """All people linked to this company (Loxo returns them via
        /companies/{id}/people; these are CRM contacts, not candidates,
        because /companies/{id}/people returns only records already
        associated with this specific company)."""
        # Loxo may paginate with scroll_id; walk pages up to a safety cap.
        people: list[dict] = []
        params: dict = {}
        for _ in range(10):
            data = self._get(f"/companies/{company_id}/people", params=params)
            if not data:
                break
            page = data.get("people") or []
            people.extend(page)
            scroll = data.get("scroll_id")
            if not scroll or not page:
                break
            params = {"scroll_id": scroll}
        return people

    def fetch_directors(self, company_id: int, cap: int = 5) -> list[dict]:
        """People at the company whose current_title contains 'director',
        sorted by internal priority (MD > HR > Commercial > other), capped."""
        all_people = self.fetch_people(company_id)
        directors = [
            p for p in all_people
            if "director" in (p.get("current_title") or "").lower()
        ]
        directors.sort(key=lambda p: _director_priority(p.get("current_title", "")))
        capped = directors[:cap]
        log.info("Loxo: company %s -> %d people, %d directors, %d after cap",
                 company_id, len(all_people), len(directors), len(capped))
        return capped

    # ---- person detail (for email addresses) ----------------------------

    def fetch_person_detail(self, person_id: int) -> Optional[dict]:
        """The full record — this is where the emails array lives."""
        return self._get(f"/people/{person_id}")

    @staticmethod
    def extract_primary_email(person: dict) -> Optional[str]:
        """Loxo stores emails as a list of {value, email_type_id} objects on
        the person record. Returns the first non-empty address, or None."""
        emails = person.get("emails") or []
        for entry in emails:
            if isinstance(entry, dict):
                addr = entry.get("value") or entry.get("email") or ""
            else:
                addr = str(entry or "")
            addr = addr.strip()
            if addr and "@" in addr:
                return addr
        return None
