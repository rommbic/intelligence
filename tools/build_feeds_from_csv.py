"""Build feeds.opml + watchlist.csv from the uploaded company CSV.

Design:
  * SIGNAL feeds      — industry-wide trigger events (unchanged, 8)
  * SUB-SECTOR feeds  — one per coarse niche; catches *similar* companies too
  * COMPANY feeds     — your 1,374 firms, batched ~N names per Google News query
                        (full per-feed coverage without 1,374 separate requests)
  * watchlist.csv     — every company (name, website, sector) used by the
                        pipeline to TAG and score-boost any story that names one
"""
import csv, html, re, sys, urllib.parse
from collections import defaultdict

CSV_PATH = sys.argv[1]
OUT_OPML = sys.argv[2]
OUT_WATCH = sys.argv[3]
CHAR_BUDGET = 230   # max chars of OR'd names per company feed
MAX_NAMES = 14      # hard cap per company feed

def gnews(q):
    return ("https://news.google.com/rss/search?q="
            + urllib.parse.quote(q) + "&hl=en-GB&gl=GB&ceid=GB:en")

# ---- coarse sub-sector buckets (ordered: specific wins over broad) ----------
BUCKETS = [
    ("Merchants & Distribution", ["merchant", "distributor", "distribution"]),
    ("Insulation & Fire Protection", ["insulation", "fire protection", "passive fire"]),
    ("Roofing & Rooflights", ["roofing", "roof", "rooflight"]),
    ("Cladding & Facades", ["cladding", "facade", "brickslip", "rainscreen"]),
    ("Windows, Doors & Curtain Walling", ["window", "curtain walling", "entrance door", "glazing", "fenestration"]),
    ("Lighting", ["lighting", "lamps", "bulbs"]),
    ("HVAC & Building Services", ["m&e", "heating", "ventilation", "air conditioning", "hvac"]),
    ("Drainage & Pipework", ["drainage", "pipework", "plumbing"]),
    ("Flooring & Tiles", ["flooring", "floor", "tiles"]),
    ("Kitchens & Bathrooms", ["kitchen", "bathroom"]),
    ("Ceilings, Partitions & Interiors", ["ceiling", "partition", "acoustic", "interiors", "furniture"]),
    ("Masonry, Concrete & Heavyside", ["masonry", "aggregate", "concrete", "brick", "cement", "civils"]),
    ("Offsite & Modular", ["offsite", "modular"]),
    ("Sealants, Adhesives & Waterproofing", ["sealant", "adhesive", "waterproof", "membrane"]),
    ("Fixings & Framing", ["fixings", "framing", "fastener"]),
    ("Timber & Joinery", ["timber", "joinery"]),
    ("Landscaping & External", ["landscaping", "paving", "external works"]),
    ("Building Envelope (other)", ["building envelope"]),
]

# niche query terms for the SUB-SECTOR breadth feeds
SECTOR_QUERIES = {
    "Merchants & Distribution": '("builders merchant" OR "building materials" OR distributor) UK (branch OR depot OR acquires OR appoints OR expansion OR contract)',
    "Insulation & Fire Protection": '(insulation OR "passive fire protection" OR cavity OR PIR) UK (manufacturer OR contract OR launches OR appoints OR invests)',
    "Roofing & Rooflights": '(roofing OR rooflight OR "flat roof" OR "metal roof") UK (manufacturer OR supplier OR contract OR launches OR appoints)',
    "Cladding & Facades": '(cladding OR rainscreen OR facade OR brickslip) UK (manufacturer OR contract OR launches OR appoints OR acquires)',
    "Windows, Doors & Curtain Walling": '(windows OR "curtain walling" OR glazing OR fenestration OR "entrance doors") UK (manufacturer OR contract OR appoints OR launches)',
    "Lighting": '("architectural lighting" OR "exterior lighting" OR luminaire) UK (manufacturer OR contract OR launches OR appoints)',
    "HVAC & Building Services": '(HVAC OR "heating and ventilation" OR "air conditioning") UK (manufacturer OR contract OR launches OR appoints OR acquires)',
    "Drainage & Pipework": '(drainage OR pipework OR plumbing) UK (manufacturer OR supplier OR contract OR launches OR appoints)',
    "Flooring & Tiles": '(flooring OR tiles OR "floor coverings") UK (manufacturer OR contract OR launches OR appoints)',
    "Kitchens & Bathrooms": '(kitchens OR bathrooms OR sanitaryware) UK (manufacturer OR contract OR launches OR appoints OR acquires)',
    "Ceilings, Partitions & Interiors": '(ceilings OR partitions OR "interior systems" OR acoustics) UK (manufacturer OR contract OR appoints OR launches)',
    "Masonry, Concrete & Heavyside": '(masonry OR concrete OR aggregates OR bricks OR cement) UK (manufacturer OR contract OR invests OR appoints OR acquires)',
    "Offsite & Modular": '(offsite OR modular OR "modern methods of construction" OR MMC) UK (factory OR contract OR invests OR appoints OR launches)',
    "Sealants, Adhesives & Waterproofing": '(sealants OR adhesives OR waterproofing OR membranes) UK (manufacturer OR contract OR launches OR appoints)',
    "Fixings & Framing": '(fixings OR fasteners OR "framing systems") UK (manufacturer OR contract OR launches OR appoints)',
    "Timber & Joinery": '(timber OR joinery OR "engineered timber") UK (manufacturer OR contract OR invests OR appoints OR acquires)',
    "Landscaping & External": '(landscaping OR paving OR "hard landscaping") UK (manufacturer OR contract OR launches OR appoints)',
    "Building Envelope (other)": '"building envelope" UK (manufacturer OR contract OR launches OR appoints OR acquires)',
}

SIGNAL_FEEDS = {
    "M&A / acquisitions": '("building materials" OR "construction products" OR "builders merchant") (acquires OR acquisition OR merger OR buys OR "takes over") UK',
    "New facilities / expansion": '("building materials" OR "construction products" OR manufacturer) (warehouse OR "distribution centre" OR factory OR depot OR "new site" OR "sq ft") (opens OR lease OR invests OR new) UK',
    "Contract / supply wins": '("building materials" OR "construction products" OR supplier OR manufacturer) ("supply contract" OR "awarded contract" OR framework OR "preferred supplier") construction UK',
    "New product launches": '("construction products" OR "building materials" OR insulation OR roofing OR cladding) ("new product" OR launches OR "new range") UK',
    "Hiring / job creation": '("building materials" OR "construction products" OR "builders merchant") ("creating jobs" OR "new jobs" OR hiring OR recruits OR expansion) UK',
    "Leadership appointments": '("building materials" OR "construction products" OR manufacturer) (appoints OR "new managing director" OR "new sales director" OR "new CEO" OR "new commercial director") UK',
    "Investment / PE / funding": '("building materials" OR "construction products") ("private equity" OR investment OR funding OR backs OR "management buyout" OR MBO) UK',
    "Manufacturing capacity": '("construction products" OR "building materials" OR manufacturer) ("new factory" OR "new line" OR "production capacity" OR "manufacturing facility") UK',
}

def bucket_for(tags: str) -> str:
    t = tags.lower()
    for name, kws in BUCKETS:
        if any(k in t for k in kws):
            return name
    return "Other / General"

# ---- read CSV --------------------------------------------------------------
rows = []
seen = set()
with open(CSV_PATH, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        name = (r.get("Company Name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append({
            "name": name,
            "website": (r.get("Website") or "").strip(),
            "tags": (r.get("Industry Tags") or "").strip(),
            "bucket": bucket_for(r.get("Industry Tags") or ""),
        })

# group companies by bucket
by_bucket = defaultdict(list)
for r in rows:
    by_bucket[r["bucket"]].append(r)

# ---- build company batch feeds ---------------------------------------------
def batches(names):
    cur, cur_len = [], 0
    for n in names:
        token = f'"{n}"'
        add = len(token) + 4  # ' OR '
        if cur and (cur_len + add > CHAR_BUDGET or len(cur) >= MAX_NAMES):
            yield cur
            cur, cur_len = [], 0
        cur.append(n)
        cur_len += add
    if cur:
        yield cur

def esc(s):
    return html.escape(s, quote=True)

def feed_outline(title, query):
    return f'      <outline type="rss" text="{esc(title)}" title="{esc(title)}" xmlUrl="{esc(gnews(query))}"/>'

lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<opml version="2.0">',
         '  <head><title>Rommbic Intelligence Agent — Feeds</title></head>', '  <body>']

# 1. signal
lines.append('    <outline text="1. SIGNAL FEEDS (trigger events)" title="1. SIGNAL FEEDS (trigger events)">')
for t, q in SIGNAL_FEEDS.items():
    lines.append(feed_outline(t, q))
lines.append('    </outline>')

# 2. sub-sector (group = sector)
lines.append('    <outline text="2. SECTOR FEEDS (your niches + similar firms)" title="2. SECTOR FEEDS (your niches + similar firms)">')
for bucket in sorted(by_bucket):
    q = SECTOR_QUERIES.get(bucket)
    if q:
        lines.append(feed_outline(f"{bucket} — sector news", q))
lines.append('    </outline>')

# 3. company watch-list (group = company), nested by bucket
company_feed_count = 0
lines.append('    <outline text="3. COMPANY WATCH-LIST (your 1,374 firms)" title="3. COMPANY WATCH-LIST (your 1,374 firms)">')
for bucket in sorted(by_bucket):
    comps = sorted(by_bucket[bucket], key=lambda x: x["name"].lower())
    lines.append(f'      <outline text="{esc(bucket)} ({len(comps)})" title="{esc(bucket)} ({len(comps)})">')
    for grp in batches([c["name"] for c in comps]):
        q = " OR ".join(f'"{n}"' for n in grp)
        first, last = grp[0], grp[-1]
        label = f"{bucket}: {first[:18]} … {last[:18]} ({len(grp)})"
        lines.append('  ' + feed_outline(label, q))
        company_feed_count += 1
    lines.append('      </outline>')
lines.append('    </outline>')
lines.append('  </body>')
lines.append('</opml>')

with open(OUT_OPML, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

# ---- watchlist.csv ---------------------------------------------------------
with open(OUT_WATCH, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["name", "website", "sector"])
    for r in rows:
        w.writerow([r["name"], r["website"], r["bucket"]])

import xml.dom.minidom as m
m.parse(OUT_OPML)  # validate
print(f"Companies: {len(rows)} | buckets: {len(by_bucket)}")
print(f"Feeds -> signal: {len(SIGNAL_FEEDS)}  sector: {len(SECTOR_QUERIES)}  company-batches: {company_feed_count}")
print(f"TOTAL FEEDS: {len(SIGNAL_FEEDS) + len(SECTOR_QUERIES) + company_feed_count}")
