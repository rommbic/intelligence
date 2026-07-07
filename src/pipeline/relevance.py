"""Relevance filtering — the heart of noise reduction.

Every keyword-feed item must be ABOUT THE CONSTRUCTION-PRODUCTS INDUSTRY: it
has to contain at least one sector keyword. Naming one of your companies is
not enough on its own — that's how coincidental collisions (e.g. a "Northern
Lights" arts story matching a lighting company) used to slip through.

Gate order per item (cheapest checks first):
  1. Recency: within `recency_hours`.
  2. Exclude: drop if any exclude keyword appears.
  3. Geography: drop if a foreign place is named with no UK/Ireland signal.
  4. SECTOR ANCHOR (hard gate): drop unless a sector keyword appears — this is
     the "actually about construction products?" check.
  5. Categorise: tag with every trigger category whose keywords appear.
  6. Company detection: tag the story with the specific watch-list firm named.
  7. Keep if:
       company feed  -> sector-anchor already passed => keep
       other feeds   -> also requires a trigger category
  Structured sources (Companies House, careers) bypass all of this — they're
  pre-qualified at collection time.
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

# Common English words we auto-treat as ambiguous when they appear in a
# watchlist name. Any watchlist name made ONLY of these words is treated as
# ambiguous automatically — so future collisions like "Northern Lights" don't
# need to be manually added to the config. (Curated to construction-adjacent
# generics that keep cropping up in company names.)
_COMMON_WORDS = {
    "northern", "southern", "eastern", "western", "central", "national",
    "lights", "light", "systems", "solutions", "products", "services",
    "group", "holdings", "industries", "international", "global", "uk",
    "direct", "supplies", "partners", "trading", "distribution",
    "building", "construction", "materials", "premier", "prime", "advanced",
}


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


def _auto_ambiguous(companies: list[str]) -> set[str]:
    """Any watchlist name made entirely of common English words is ambiguous
    and needs sector context to count."""
    out = set()
    for c in companies:
        n = normalise(c)
        words = [w for w in n.split() if w]
        if words and all(w in _COMMON_WORDS for w in words):
            out.add(n)
    return out


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
    # Combine explicitly-flagged ambiguous names with auto-detected ones.
    ambiguous_norm = {normalise(n) for n in settings.get("ambiguous_companies", [])}
    ambiguous_norm |= _auto_ambiguous(companies)
    log.info("Ambiguous names requiring sector context: %d", len(ambiguous_norm))

    kept, dropped_geo, dropped_sector, dropped_other = [], 0, 0, 0
    for it in items:
        text = normalise(f"{it.title} {it.summary}")

        # Structured sources are pre-qualified at collection time.
        if it.feed_group in ("companies_house", "careers"):
            if not it.company:
                it.company = _detect_company(text, matcher)[0]
            kept.append(it)
            continue

        if it.published and it.published < cutoff:
            dropped_other += 1
            continue
        if any(k in text for k in exclude_kws):
            dropped_other += 1
            continue

        # 3. Geography gate.
        if require_uk:
            foreign_hit = bool(foreign_rx and foreign_rx.search(text))
            uk_hit = bool(uk_rx and uk_rx.search(text))
            if foreign_hit and not uk_hit:
                dropped_geo += 1
                continue

        # 4. HARD SECTOR-KEYWORD REQUIREMENT — the "is this actually about
        #    construction products?" check. Three ways to pass:
        #      (a) sector keyword directly present
        #      (b) strong watchlist company name AND a signal category match
        #          (e.g. "Travis Perkins opens new depot" — passes on company
        #          name + 'New facility / expansion' category, even though
        #          "building materials" isn't in the headline)
        #    A strong company name ALONE is NOT enough — that used to let
        #    unrelated articles through when they happened to contain a
        #    watchlist company name as a coincidence (e.g. an AWS blog post
        #    about "Multi-Turn RL" hit the "Multi-Turn" company by accident).
        sector_hit = any(k in text for k in sector_kws)
        company, strong = _detect_company(text, matcher)
        ambiguous = bool(company) and normalise(company) in ambiguous_norm
        cats = _matched_categories(text, categories)
        strong_name_with_signal = (
            bool(company) and strong and not ambiguous and bool(cats)
        )
        if not (sector_hit or strong_name_with_signal):
            dropped_sector += 1
            continue

        # 5. Suppress ambiguous-name matches when there's no independent
        #    industry context (belt and braces alongside step 4).
        if ambiguous and not sector_hit and not cats:
            company, strong = "", False

        # 7. Keep decision. Sector-anchor already passed; company feeds keep;
        #    other feeds also need a trigger category.
        if it.feed_group == "company":
            keep = True
        else:
            keep = bool(cats)

        if not keep:
            dropped_other += 1
            continue
        it.categories = cats
        it.company = company
        kept.append(it)

    log.info("Relevance: kept %d | dropped: sector=%d geo=%d other=%d",
             len(kept), dropped_sector, dropped_geo, dropped_other)
    return kept
