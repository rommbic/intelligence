"""Loads settings.yaml and the OPML feed list."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.yaml", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    # Env overrides for the things you'll tweak per-deployment.
    recipients_env = os.getenv("DIGEST_RECIPIENTS")
    if recipients_env:
        settings.setdefault("email", {})["recipients"] = [
            r.strip() for r in recipients_env.split(",") if r.strip()
        ]
    dash_env = os.getenv("DASHBOARD_URL")
    if dash_env:
        settings["dashboard_url"] = dash_env
    return settings


def _group_for(folder_title: str) -> str:
    t = (folder_title or "").lower()
    if "company" in t or "watch" in t:
        return "company"
    if "sector" in t:
        return "sector"
    return "signal"


def load_feeds(opml_path: Path | None = None) -> list[dict]:
    """Returns a flat list of {title, url, group} from the OPML. The group is set
    by the TOP-LEVEL folder and inherited by everything beneath it, so nested
    sub-folders (e.g. company feeds grouped by sub-sector) keep the right group."""
    opml_path = opml_path or (CONFIG_DIR / "feeds.opml")
    body = ET.parse(opml_path).getroot().find("body")
    feeds: list[dict] = []

    def collect(node, group):
        for child in node.findall("outline"):
            if child.get("xmlUrl"):
                feeds.append({
                    "title": child.get("title") or child.get("text") or "",
                    "url": child.get("xmlUrl"),
                    "group": group,
                })
            else:
                collect(child, group)  # inherit parent group

    for top in body.findall("outline"):
        if top.get("xmlUrl"):
            feeds.append({"title": top.get("title", ""), "url": top.get("xmlUrl"), "group": "signal"})
        else:
            collect(top, _group_for(top.get("title") or top.get("text") or ""))
    return feeds


def watch_companies(settings: dict, feeds: list[dict]) -> list[str]:
    """All target company names, used to tag and score-boost stories that name
    one of them. Reads config/watchlist.csv if present, else falls back to the
    company-group feed titles."""
    path = CONFIG_DIR / "watchlist.csv"
    if path.exists():
        import csv
        with open(path, encoding="utf-8") as f:
            names = [(r.get("name") or "").strip() for r in csv.DictReader(f)]
        return [n for n in names if n]
    return [f["title"] for f in feeds if f["group"] == "company"]
