"""Tests for the outreach automation. Uses mock Loxo responses shaped after
the real preflight output against Rommbic's Loxo account.
"""
from unittest.mock import patch, MagicMock

from src.outreach.loxo_client import (
    LoxoClient, _director_priority, _normalise_company_name,
)


def test_name_normalisation():
    """Confirm 'Cemex' matches 'CEMEX UK', 'Marshalls' matches 'Marshalls plc'."""
    cases = [
        ("Cemex", "cemex"),
        ("CEMEX UK", "cemex"),
        ("Marshalls plc", "marshalls"),
        ("Travis Perkins Group Limited", "travis perkins"),
        ("Huws Gray Ltd", "huws gray"),
    ]
    for raw, expected in cases:
        got = _normalise_company_name(raw)
        assert got == expected, f"{raw!r} -> {got!r} (expected {expected!r})"
    print("[normalisation] all 5 name pairs correct")


def test_director_priority():
    """Priority order: MD > HR > Commercial > other."""
    assert _director_priority("Managing Director") == 0
    assert _director_priority("CEO") == 0
    assert _director_priority("HR Director") == 1
    assert _director_priority("People Director") == 1
    assert _director_priority("Commercial Director") == 2
    assert _director_priority("Sales Director") == 2
    assert _director_priority("Finance Director") == 3
    assert _director_priority("Regional Ops Manager") == 3
    print("[priority] all 8 title priorities correct")


def test_email_extraction():
    """Confirmed shape from preflight: emails is a list of dicts with 'value'."""
    # Loxo's actual shape (from preflight)
    person = {"emails": [{"value": "will@example.co.uk", "email_type_id": 1}]}
    assert LoxoClient.extract_primary_email(person) == "will@example.co.uk"

    # Empty list
    assert LoxoClient.extract_primary_email({"emails": []}) is None

    # Missing field
    assert LoxoClient.extract_primary_email({}) is None

    # Skip invalid entries, find valid one
    person = {"emails": [{"value": ""}, {"value": "real@x.com"}]}
    assert LoxoClient.extract_primary_email(person) == "real@x.com"

    # String entry (alternative shape)
    assert LoxoClient.extract_primary_email({"emails": ["a@b.com"]}) == "a@b.com"
    print("[email] extraction handles 5 shapes correctly")


def test_search_company_exact_and_fuzzy():
    """search_company returns exact-normalised match when available, else
    highest fuzzy match above threshold, else None."""
    client = LoxoClient(api_key="test")

    # Case 1: exact normalised match wins even when a longer name comes first.
    with patch.object(client, "_get") as mock_get:
        mock_get.return_value = {
            "companies": [
                {"id": 1, "name": "Marshalls plc"},
                {"id": 2, "name": "Marshalls Building Supplies Ltd"},
            ],
        }
        got = client.search_company("Marshalls")
        assert got and got["id"] == 1, f"expected id=1, got {got}"

    # Case 2: no exact — fuzzy match returns closest above threshold.
    with patch.object(client, "_get") as mock_get:
        mock_get.return_value = {
            "companies": [{"id": 5, "name": "Cemex UK Limited"}],
        }
        got = client.search_company("Cemex")
        assert got and got["id"] == 5

    # Case 3: nothing similar enough -> None (no wrong-company email).
    with patch.object(client, "_get") as mock_get:
        mock_get.return_value = {
            "companies": [{"id": 9, "name": "Completely Unrelated Inc"}],
        }
        assert client.search_company("Marshalls") is None

    # Case 4: empty search -> None.
    with patch.object(client, "_get") as mock_get:
        mock_get.return_value = {"companies": []}
        assert client.search_company("XYZ") is None
    print("[search] exact + fuzzy + no-match + empty all handled correctly")


def test_fetch_directors_filters_and_sorts():
    """fetch_directors returns only director titles, priority-sorted, capped."""
    client = LoxoClient(api_key="test")
    with patch.object(client, "fetch_people") as mock_fetch:
        mock_fetch.return_value = [
            {"id": 1, "name": "Alice", "current_title": "Sales Director"},
            {"id": 2, "name": "Bob", "current_title": "Managing Director"},
            {"id": 3, "name": "Carol", "current_title": "Regional Manager"},
            {"id": 4, "name": "Dave", "current_title": "HR Director"},
            {"id": 5, "name": "Eve", "current_title": "Marketing Assistant"},
            {"id": 6, "name": "Frank", "current_title": "Finance Director"},
        ]
        got = client.fetch_directors(company_id=999, cap=3)
        assert len(got) == 3
        names = [p["name"] for p in got]
        # MD (Bob) first, then HR (Dave), then Commercial/Sales (Alice)
        assert names == ["Bob", "Dave", "Alice"], f"got {names}"
        # Non-directors (Carol, Eve) never included even with room to spare
        for exclude in ("Carol", "Eve"):
            assert exclude not in names
    print("[directors] filters non-directors, priority-sorts, respects cap")


def test_orchestrator_prospects_unknown_companies():
    """If Loxo has no match for a signal's company, it's logged for prospecting."""
    from src.outreach import orchestrator as orch
    import tempfile, json
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "latest.json").write_text(json.dumps({
            "items": [{
                "title": "Some Startup opens new UK factory",
                "link": "http://example.com/x",
                "score": 9,
                "company": "Some Startup Ltd",
                "fingerprint": "test-fp-1",
                "categories": ["New facility / expansion"],
                "summary": "News summary",
            }],
        }))

        # Patch: DATA_DIR points at tmp, outreach enabled, Loxo returns nothing
        with patch.object(orch, "DATA_DIR", tmp), \
             patch.object(orch, "STATE_FILE", tmp / "outreach_state.json"), \
             patch.object(orch, "PROSPECT_FILE", tmp / "prospecting_queue.json"), \
             patch.object(orch, "SUMMARY_FILE", tmp / "outreach_summary.json"), \
             patch.object(orch, "load_settings", return_value={
                 "outreach": {"enabled": True, "min_score": 8,
                              "max_drafts_per_company": 5,
                              "inbox": "will@rommbic.co.uk"}}), \
             patch("src.outreach.orchestrator.LoxoClient") as MockClient:
            instance = MockClient.return_value
            instance.search_company.return_value = None  # not in CRM
            summary = orch.run()

        assert summary["signals_processed"] == 1
        assert summary["drafts_created"] == 0
        assert summary["prospects_logged"] == 1
        prospects = json.loads((tmp / "prospecting_queue.json").read_text())
        assert len(prospects) == 1
        assert prospects[0]["company"] == "Some Startup Ltd"
        print("[orchestrator] unknown company correctly logged for prospecting")


if __name__ == "__main__":
    test_name_normalisation()
    test_director_priority()
    test_email_extraction()
    test_search_company_exact_and_fuzzy()
    test_fetch_directors_filters_and_sorts()
    test_orchestrator_prospects_unknown_companies()
    print("\nALL OUTREACH TESTS PASSED")
