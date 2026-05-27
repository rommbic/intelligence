"""Deduplicate the same story arriving via multiple feeds / outlets.

Google News surfaces one story across many of our queries. We merge by:
  * exact fingerprint (normalised, source-suffix-stripped title), then
  * fuzzy title similarity within the remaining set.
When merging we union the categories and keep the richest instance.
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher

from ..util import Item, normalise, strip_source_suffix

log = logging.getLogger("pipeline.dedup")
SIMILARITY = 0.86


def _merge(keep: Item, other: Item) -> None:
    keep.categories = sorted(set(keep.categories) | set(other.categories))
    if not keep.company and other.company:
        keep.company = other.company
    if not keep.source and other.source:
        keep.source = other.source


def dedup(items: list[Item]) -> list[Item]:
    # 1) exact fingerprint
    by_fp: dict[str, Item] = {}
    for it in items:
        fp = it.fingerprint
        if fp in by_fp:
            _merge(by_fp[fp], it)
        else:
            by_fp[fp] = it
    survivors = list(by_fp.values())

    # 2) fuzzy pass
    final: list[Item] = []
    titles: list[str] = []
    for it in survivors:
        norm = normalise(strip_source_suffix(it.title))
        match_idx = None
        for i, existing in enumerate(titles):
            if SequenceMatcher(None, norm, existing).ratio() >= SIMILARITY:
                match_idx = i
                break
        if match_idx is None:
            final.append(it)
            titles.append(norm)
        else:
            _merge(final[match_idx], it)

    log.info("Dedup: %d -> %d unique", len(items), len(final))
    return final
