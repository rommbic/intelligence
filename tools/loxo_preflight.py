"""Loxo preflight — safe, read-only inspection of your Loxo account structure.

Run once via the `.github/workflows/loxo-preflight.yml` workflow. Prints the raw
shape of a company and its linked people so the outreach automation can be
built against the actual field names in your account (Type, Stakeholder Type,
job_title, etc.) rather than a guess.

Reads LOXO_API_KEY from env. Uses the endpoint discovered from your account URL.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests

BASE = "https://rommbic.app.loxo.co/api/rommbic"
SEARCH_NAME = os.getenv("PREFLIGHT_COMPANY", "Marshalls")


def redact(obj: Any) -> Any:
    """Best-effort redaction of PII in the printed output. We only need
    STRUCTURE (field names), not real names/emails."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = k.lower()
            if lk in {"email", "emails", "phone", "phones", "mobile", "personal_email"}:
                out[k] = "[REDACTED]" if v else v
            elif lk == "name":
                out[k] = "[REDACTED_NAME]" if v else v
            elif lk in {"first_name", "last_name"}:
                out[k] = "[REDACTED]" if v else v
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def show(label: str, data: Any, limit: int = 6000):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    s = json.dumps(redact(data), indent=2, default=str)
    if len(s) > limit:
        s = s[:limit] + f"\n... [truncated, total {len(s)} chars]"
    print(s)


def _find_email_keys(obj: Any, path: str = "") -> list[str]:
    """Walk the JSON structure and return the JSON-paths of every field whose
    name looks email-related. This is what confirms exactly where email
    addresses live in a person record — top-level, nested, or under a custom
    field ID — regardless of how Loxo happens to organise it."""
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else k
            if "email" in k.lower() and v not in (None, "", [], {}):
                hits.append(here)
            hits.extend(_find_email_keys(v, here))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):  # only sample first few
            hits.extend(_find_email_keys(v, f"{path}[{i}]"))
    return hits


def main() -> int:
    key = os.getenv("LOXO_API_KEY")
    if not key:
        print("ERROR: LOXO_API_KEY not set")
        return 2

    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})

    # ------------------------------------------------------------------
    # Step 1: search for a company by name
    # ------------------------------------------------------------------
    print(f"\n>>> Searching companies for: {SEARCH_NAME!r}")
    r = s.get(f"{BASE}/companies", params={"query": SEARCH_NAME}, timeout=30)
    print(f"    HTTP {r.status_code}")
    if r.status_code == 403:
        print("    -> 403 Forbidden. Check the API key permissions/plan tier.")
        print("    Response body:", r.text[:400])
        return 1
    if not r.ok:
        print("    Response:", r.text[:600])
        return 1

    listing = r.json()
    show("A. Companies list response — TOP-LEVEL SHAPE (first company only)",
         listing if not isinstance(listing, dict) else
         {**{k: v for k, v in listing.items() if k != "companies"},
          "companies": (listing.get("companies") or [])[:1]})

    companies = listing.get("companies") or listing.get("results") or (listing if isinstance(listing, list) else [])
    if not companies:
        print("    -> No companies found. Try setting PREFLIGHT_COMPANY to a known name.")
        return 1
    first = companies[0]
    company_id = first.get("id") or first.get("company_id")
    print(f"\n>>> Using company id={company_id}")

    # ------------------------------------------------------------------
    # Step 2: fetch that company in detail — this is where linked people
    # or "contacts"/"relationships" typically live
    # ------------------------------------------------------------------
    r = s.get(f"{BASE}/companies/{company_id}", timeout=30)
    print(f"\n    /companies/{{id}} HTTP {r.status_code}")
    if r.ok:
        detail = r.json()
        show("B. Company detail — full structure", detail)

        # Enumerate likely people fields so we know which key holds contacts
        candidate_keys = [k for k in (detail if isinstance(detail, dict) else {}).keys()
                          if any(w in k.lower() for w in ("person", "people", "contact", "relationship"))]
        print("\n    Fields on the company that look people-related:", candidate_keys or "(none obvious)")
    else:
        print("    Response:", r.text[:400])

    # ------------------------------------------------------------------
    # Step 3: try common patterns for "people at this company"
    # ------------------------------------------------------------------
    print("\n>>> Probing endpoints that may return contacts at this company:")
    found_person_id = None
    for path in (
        f"/companies/{company_id}/people",
        f"/companies/{company_id}/contacts",
        f"/companies/{company_id}/relationships",
        f"/people?company_id={company_id}",
        f"/contacts?company_id={company_id}",
    ):
        try:
            r = s.get(f"{BASE}{path}", timeout=20)
            print(f"    {path:55} -> HTTP {r.status_code}")
            if r.ok and r.text.strip():
                data = r.json()
                sample = data if not isinstance(data, dict) else \
                         (data.get("people") or data.get("contacts") or data.get("results") or data)
                if isinstance(sample, list) and sample:
                    show(f"C. First person from {path}", sample[0])
                    found_person_id = sample[0].get("id") or sample[0].get("person_id")
                    break
        except Exception as exc:
            print(f"    {path} -> exception: {exc}")

    # ------------------------------------------------------------------
    # Step 3b: fetch the person's FULL DETAIL — critical, because list
    # endpoints often return trimmed records without email/phone. This is
    # where we confirm the exact path to the email field.
    # ------------------------------------------------------------------
    if found_person_id:
        print(f"\n>>> Fetching full person detail for id={found_person_id} (to see email field):")
        for path in (
            f"/people/{found_person_id}",
            f"/contacts/{found_person_id}",
            f"/candidates/{found_person_id}",
        ):
            try:
                r = s.get(f"{BASE}{path}", timeout=20)
                print(f"    {path:35} -> HTTP {r.status_code}")
                if r.ok and r.text.strip():
                    detail = r.json()
                    show(f"C2. Full person detail from {path}", detail)
                    # Report presence/absence of email-like fields explicitly
                    email_keys = _find_email_keys(detail)
                    if email_keys:
                        print(f"    -> EMAIL FIELDS FOUND at: {email_keys}")
                    else:
                        print("    -> NO obvious email field on this record. "
                              "Email may live under custom_fields or another endpoint.")
                    break
            except Exception as exc:
                print(f"    {path} -> exception: {exc}")
    else:
        print("\n>>> No linked person id captured; skipping person-detail probe.")

    # ------------------------------------------------------------------
    # Step 4: reference — list custom-field definitions so we can identify
    # the Stakeholder Type field by ID vs label
    # ------------------------------------------------------------------
    print("\n>>> Fetching custom-field definitions (for Type / Stakeholder Type mapping):")
    for path in ("/person_custom_fields", "/custom_fields", "/person_types"):
        try:
            r = s.get(f"{BASE}{path}", timeout=20)
            print(f"    {path:35} -> HTTP {r.status_code}")
            if r.ok and r.text.strip():
                show(f"D. {path}", r.json(), limit=3000)
        except Exception as exc:
            print(f"    {path} -> exception: {exc}")

    print("\nDONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
