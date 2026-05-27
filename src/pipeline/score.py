"""Scoring. Filtering is the priority, so scoring is deliberately simple:
the score just orders the items that already survived filtering.

Rule-based (default, no API key, never fails):
  base = highest tier among matched categories (or company_watch_tier)
  + bonus if multiple categories matched
  + bonus if a watch-list company is named
  capped at 10.

Optional Claude pass (USE_CLAUDE=1): adds a one-line rationale + likely roles
and may nudge the score. Degrades silently to rule-based on any error.
"""
from __future__ import annotations

import json
import logging
import os

from ..util import Item

log = logging.getLogger("pipeline.score")


def rule_score(items: list[Item], settings: dict) -> list[Item]:
    tier = {c["name"]: c["tier"] for c in settings["categories"]}
    base_default = settings.get("company_watch_tier", 4)
    multi = settings.get("score_bonus_multi_category", 1)
    named = settings.get("score_bonus_named_company", 1)

    for it in items:
        if it.score and it.feed_group in ("companies_house", "careers"):
            continue  # already scored by the source
        base = max((tier.get(c, 0) for c in it.categories), default=base_default)
        if len(it.categories) > 1:
            base += multi
        if it.company:
            base += named
        it.score = max(1, min(10, base))
    return items


def claude_enrich(items: list[Item], settings: dict) -> list[Item]:
    if os.getenv("USE_CLAUDE") not in ("1", "true", "True"):
        return items
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic not installed; skipping Claude enrichment.")
        return items

    cfg = settings.get("claude", {})
    cap = cfg.get("max_items_to_enrich", 40)
    targets = sorted(items, key=lambda x: x.score, reverse=True)[:cap]
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    for it in targets:
        prompt = (
            "You advise recruitment consultants at Rommbic, who place senior staff "
            "in the UK construction products / building materials industry. "
            "Given this news item, reply with STRICT JSON: "
            '{"why": "<=20 words on why this signals a likely hiring need", '
            '"roles": "likely roles to pitch, comma-separated", '
            '"score": <1-10 hiring-intent>}.\n\n'
            f"HEADLINE: {it.title}\nSUMMARY: {it.summary}\nCATEGORIES: {it.categories}"
        )
        try:
            resp = client.messages.create(
                model=cfg.get("model", "claude-opus-4-7"),
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = "".join(b.text for b in resp.content if b.type == "text")
            txt = txt[txt.find("{"): txt.rfind("}") + 1]
            data = json.loads(txt)
            it.rationale = str(data.get("why", ""))[:200]
            it.likely_roles = str(data.get("roles", ""))[:200]
            if isinstance(data.get("score"), (int, float)):
                it.score = max(1, min(10, int(data["score"])))
        except Exception as exc:
            log.warning("Claude enrich failed for one item: %s", exc)
    return items


def score(items: list[Item], settings: dict) -> list[Item]:
    items = rule_score(items, settings)
    items = claude_enrich(items, settings)
    items.sort(key=lambda x: (x.score, x.published_iso), reverse=True)
    return items[: settings.get("max_items", 60)]
