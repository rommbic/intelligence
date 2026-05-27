"""Validate the filter -> dedup -> score pipeline with mock items.
Run: python -m tests.test_pipeline
"""
from datetime import timedelta

from src.config import load_settings
from src.pipeline import dedup, relevance, score
from src.util import Item, now_utc

SETTINGS = load_settings()
COMPANIES = ["Travis Perkins", "Marshalls plc", "Forterra"]


def mock():
    t = now_utc()
    return [
        # KEEP: signal feed, acquisition + sector term
        Item(title="Saint-Gobain acquires insulation manufacturer in UK deal",
             link="http://a/1", feed_group="signal", feed_title="M&A", published=t),
        # KEEP: company feed, facility signal + named company
        Item(title="Travis Perkins opens new distribution centre in Leeds",
             link="http://a/2", feed_group="company", feed_title="Travis Perkins", published=t),
        # DROP: signal feed but no sector term (generic politics)
        Item(title="Council debates new parking rules in town centre",
             link="http://a/3", feed_group="signal", feed_title="M&A", published=t),
        # DROP: exclude keyword
        Item(title="Builders merchant sponsors local football team",
             link="http://a/4", feed_group="sector", feed_title="Sector", published=t),
        # DROP: too old
        Item(title="Forterra appoints new sales director for brick division",
             link="http://a/5", feed_group="signal", feed_title="Leadership",
             published=t - timedelta(hours=99)),
        # KEEP duplicate of #1 from another outlet (different suffix)
        Item(title="Saint-Gobain acquires insulation manufacturer in UK deal - BMN",
             link="http://a/6", feed_group="sector", feed_title="Sector", published=t),
        # KEEP: careers source (pre-qualified, score 10)
        Item(title="Marshalls plc: new vacancy — Regional Sales Manager",
             link="http://a/7", feed_group="careers", feed_title="Marshalls careers",
             categories=["Hiring / job creation"], company="Marshalls plc", score=10, published=t),
    ]


def run():
    items = relevance.filter_items(mock(), SETTINGS, COMPANIES)
    titles = [i.title for i in items]
    assert not any("parking" in x for x in titles), "generic news should be dropped"
    assert not any("football" in x for x in titles), "exclude keyword should drop item"
    assert not any("brick division" in x for x in titles), "stale item should be dropped"
    print(f"[filter] kept {len(items)} of 7 (expected 4 before dedup)")

    items = dedup.dedup(items)
    sg = [i for i in items if "Saint-Gobain" in i.title]
    assert len(sg) == 1, "the two Saint-Gobain stories must merge"
    print(f"[dedup]  -> {len(items)} unique")

    items = score.score(items, SETTINGS)
    tp = next(i for i in items if "Travis Perkins" in i.title)
    careers = next(i for i in items if "Regional Sales Manager" in i.title)
    assert tp.company == "Travis Perkins"
    assert tp.score >= 8, f"facility+company should score high, got {tp.score}"
    assert careers.score == 10, "careers vacancy must stay Tier-1"
    print("[score]  results:")
    for i in items:
        print(f"   {i.score:>2}  {i.title[:62]:<62} {i.categories}")

    print("\nALL ASSERTIONS PASSED")


if __name__ == "__main__":
    run()
