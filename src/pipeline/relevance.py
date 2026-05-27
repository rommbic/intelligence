"""Relevance filtering — the heart of noise reduction.

Gate logic per item:
  1. Recency: published within `recency_hours`.
  2. Exclude: drop if it contains any exclude keyword.
  3. Categorise: tag with every signal category whose keywords appear.
  4. Keep if:
       - signal / sector feed -> matched a category AND a sector keyword
       - company-watch feed    -> matched a category OR a sector keyword OR a company
       - companies_house / careers -> always kept (already pre-qualified)
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from ..util import Item, normalise, now_utc

log = logging.getLogger("pipeline.relevance")

# Names shorter than this (after normalising) are too generic to match safely,
# so they're excluded from auto-detection (they're still in their own feed).
_MIN_NAME_LEN = 6


def build_company_matcher(companies: list[str]):
    """One compiled word-boundary regex over all watch-list names. Each name is
    tagged 'strong' (multi-word, safe to match alone) or 'weak' (single common
    word like 'Marley' — only counts when the story also has sector context)."""
    cleaned, seen = [], set()
    for c in companies:
        n = normalise(c)
        if len(n) < _MIN_NAME_LEN or n in seen:
            continue
        seen.add(n)
        cleaned.append((c, n))
    if not cleaned:
        return None
    cleaned.sort(key=lambda x: len(x[1]), reverse=True)  # longest match wins
    rx = re.compile(r"\b(" + "|".join(re.escape(n) for _, n in cleaned) + r")\b")
    mapping = {n: c for c, n in cleaned}
    strong = {n: (" " in n) for _, n in cleaned}  # multi-word == strong
    return rx, mapping, strong


def _detect_company(text_norm: str, matcher) -> tuple[str, bool]:
    if not matcher:
        return "", False
    rx, mapping, strong = matcher
    m = rx.search(text_norm)
    if not m:
        return "", False
    n = m.group(1)
    return mapping.get(n, ""), strong.get(n, False)


def _matched_categories(text: str, categories: list[dict]) -> list[str]:
    return [c["name"] for c in categories
            if any(normalise(kw) in text for kw in c["keywords"])]


def _compile_geo(keywords: list[str]):
    """Word-boundary matcher for geography terms. Word boundaries stop short
    tokens like 'uk' matching inside 'Duke'/'Luke', and empty/symbol-only
    keywords (e.g. a stripped '£') are dropped so they can't match everything."""
    norm = [normalise(k) for k in keywords]
    norm = [k for k in norm if k]  # drop empties
    if not norm:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(k) for k in norm) + r")\b")


def filter_items(items: list[Item], settings: dict, companies: list[str]) -> list[Item]:
    categories = settings["categories"]
    sector_kws = [normalise(k) for k in settings["sector_keywords"]]
    exclude_kws = [normalise(k) for k in settings.get("exclude_keywords", [])]
    geo = settings.get("geography", {})
    require_uk = geo.get("require_uk", True)
    uk_rx = _compile_geo(geo.get("uk_keywords", []))
    foreign_rx = _compile_geo(geo.get("foreign_keywords", []))
    cutoff = now_utc() - timedelta(hours=settings["recency_hours"])
    matcher = build_company_matcher(companies)

    kept, dropped = [], 0
    for it in items:
        text = normalise(f"{it.title} {it.summary}")

        if it.feed_group in ("companies_house", "careers"):
            if not it.company:
                it.company = _detect_company(text, matcher)[0]
            kept.append(it)
            continue

        if it.published and it.published < cutoff:
            dropped += 1
            continue
        if any(k in text for k in exclude_kws):
            dropped += 1
            continue

        # --- Geography gate: drop items that name a non-UK location and have
        #     no positive UK signal. Keeps UK or location-neutral stories;
        #     removes Hong Kong / US-college / other overseas items. ---
        if require_uk:
            foreign_hit = bool(foreign_rx and foreign_rx.search(text))
            uk_hit = bool(uk_rx and uk_rx.search(text))
            if foreign_hit and not uk_hit:
                dropped += 1
                continue

        cats = _matched_categories(text, categories)
        sector_hit = any(k in text for k in sector_kws)
        company, strong = _detect_company(text, matcher)
        # A weak (single-word) name only counts when there's sector context.
        company_counts = company and (strong or sector_hit or bool(cats))

        # Every item must be ANCHORED to our world: it must name one of our
        # companies OR hit a sector keyword. A trigger category alone (e.g.
        # "expansion", "hiring", "appoints") is NOT enough on its own — that
        # was letting college-football "expansions" and generic overseas
        # "hiring" stories through the company feeds.
        anchored = sector_hit or bool(company_counts)

        if it.feed_group == "company":
            keep = anchored
        else:  # signal / sector feeds: need a trigger category AND an anchor
            keep = bool(cats) and anchored

        if not keep:
            dropped += 1
            continue
        it.categories = cats
        it.company = company if company_counts else ""
        kept.append(it)

    log.info("Relevance: kept %d, dropped %d", len(kept), dropped)
    return kept
