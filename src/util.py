"""Shared data model and helpers."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]")


def normalise(text: str) -> str:
    """Lower-case, strip punctuation and collapse whitespace — used for
    matching and for building dedup fingerprints."""
    text = (text or "").lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def strip_source_suffix(title: str) -> str:
    """Google News titles look like 'Headline - Publisher'. Drop the suffix
    so the same story from two outlets dedupes together."""
    # Only strip the last ' - X' segment, and only if it looks like a source.
    parts = title.rsplit(" - ", 1)
    if len(parts) == 2 and 0 < len(parts[1]) <= 40:
        return parts[0].strip()
    return title.strip()


@dataclass
class Item:
    title: str
    link: str
    source: str = ""
    published: Optional[datetime] = None
    summary: str = ""
    feed_group: str = "signal"        # signal | company | sector | companies_house | careers
    feed_title: str = ""
    categories: list = field(default_factory=list)
    company: str = ""                 # named watch-list company, if matched
    score: int = 0
    rationale: str = ""               # filled by the optional Claude pass
    likely_roles: str = ""

    @property
    def fingerprint(self) -> str:
        base = normalise(strip_source_suffix(self.title))
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    @property
    def published_iso(self) -> str:
        return self.published.astimezone(timezone.utc).isoformat() if self.published else ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("published", None)
        d["published"] = self.published_iso
        d["fingerprint"] = self.fingerprint
        return d
