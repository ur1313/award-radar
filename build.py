#!/usr/bin/env python3
"""Award Radar: static SEO site of recent U.S. federal contract awards.
Source: USASpending.gov public API (no API key). Competitive intel for small businesses."""
import datetime
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from urllib.parse import quote

API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
CAT_NAICS = "https://api.usaspending.gov/api/v2/search/spending_by_category/naics/"
PRO_URL = os.environ.get("PRO_URL", "#pro")
BASE = "https://ur1313.github.io/award-radar/"
MAX_AWARDS = int(os.environ.get("MAX_AWARDS", "7000"))
PAGE_SIZE = 100
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "75"))
# Amount bands for SB-relevant mix (under ~$10M)
AMOUNT_BANDS = [
    (1_000, 250_000),
    (250_000, 1_000_000),
    (1_000_000, 10_000_000),
]
# Pages per (naics, band) — keep runtime reasonable
PAGES_PER_BAND = 1
TOP_NAICS_N = 45

FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Start Date",
    "End Date",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Contract Award Type",
    "Description",
    "Place of Performance State Code",
    "NAICS Code",
    "NAICS Description",
]

NAICS_LABEL = {
    "541511": "Custom Computer Programming",
    "541512": "Computer Systems Design",
    "541519": "Other Computer Related Services",
    "541611": "Administrative Management Consulting",
    "541330": "Engineering Services",
    "541690": "Other Scientific/Technical Consulting",
    "236220": "Commercial Building Construction",
    "238210": "Electrical Contractors",
    "238220": "Plumbing/HVAC Contractors",
    "561210": "Facilities Support Services",
    "561720": "Janitorial Services",
    "484110": "General Freight Trucking Local",
    "493110": "General Warehousing",
    "541620": "Environmental Consulting",
    "562910": "Remediation Services",
    "237310": "Highway/Street/Bridge Construction",
    "237990": "Other Heavy Construction",
    "238910": "Site Preparation Contractors",
    "811310": "Commercial Machinery Repair",
    "541380": "Testing Laboratories",
    "518210": "Data Processing/Hosting",
    "541715": "R&D Physical Engineering Life Sciences",
    "541990": "All Other Professional Services",
    "561320": "Temporary Help Services",
    "541513": "Computer Facilities Management",
    "336411": "Aircraft Manufacturing",
    "541618": "Other Management Consulting",
    "236210": "Industrial Building Construction",
    "541370": "Surveying and Mapping",
    "325412": "Pharmaceutical Preparation Mfg",
    "336611": "Ship Building and Repairing",
    "524114": "Direct Health/Medical Insurance",
    "541710": "R&D Physical/Engineering/Life Sciences",
    "928110": "National Security",
    "621111": "Offices of Physicians",
    "423450": "Medical Equipment Wholesalers",
    "339112": "Surgical/Medical Instrument Mfg",
    "517311": "Wired Telecommunications Carriers",
    "488190": "Other Air Transportation Support",
    "541720": "R&D Social Sciences/Humanities",
    "561612": "Security Guards and Patrol Services",
    "238160": "Roofing Contractors",
    "238220": "Plumbing/HVAC Contractors",
}

SEED_NAICS = [
    "541511", "541512", "541519", "541513", "541611", "541330", "541690",
    "541620", "541715", "541990", "561210", "561720", "236220", "238210",
    "238220", "237310", "562910", "518210", "541380", "336411", "325412",
    "336611", "524114", "561320", "541618", "236210", "237990", "238910",
    "811310", "493110", "484110", "423450", "339112", "621111", "541370",
    "561612", "238160", "541720", "928110", "517110", "541710", "334111",
    "488190", "541310", "541820",
]

today = datetime.date.today()
start_date = (today - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
end_date = today.isoformat()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "x"


def money(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.1f}K"
    return f"${n:,.0f}"


def usaspending_link(award_id, generated=None):
    if generated:
        return f"https://www.usaspending.gov/award/{generated}"
    aid = (award_id or "").strip()
    if not aid:
        return "https://www.usaspending.gov/"
    return f"https://www.usaspending.gov/search/?hash=false&field=keyword&value={quote(aid)}"


def post_json(url, payload, timeout=90):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "AwardRadar/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def top_naics_codes():
    """Popular NAICS by obligation in window; fall back to seed list."""
    codes = []
    try:
        data = post_json(
            CAT_NAICS,
            {
                "filters": {
                    "time_period": [{"start_date": start_date, "end_date": end_date}],
                    "award_type_codes": ["A", "B", "C", "D"],
                },
                "limit": TOP_NAICS_N,
                "page": 1,
            },
        )
        for row in data.get("results") or []:
            c = str(row.get("code") or "").strip()
            if c and c not in codes:
                codes.append(c)
                NAICS_LABEL.setdefault(c, (row.get("name") or f"NAICS {c}"))
        print(f"Category API returned {len(codes)} NAICS")
    except Exception as e:
        print(f"Category NAICS failed ({e}); using seed list")
    for c in SEED_NAICS:
        if c not in codes:
            codes.append(c)
    return codes[:TOP_NAICS_N]


def fetch_page(page, fields, naics=None, amount_band=None):
    filters = {
        "time_period": [{"start_date": start_date, "end_date": end_date}],
        "award_type_codes": ["A", "B", "C", "D"],
    }
    if naics:
        filters["naics_codes"] = [naics] if isinstance(naics, str) else list(naics)
    if amount_band:
        lo, hi = amount_band
        filters["award_amounts"] = [{"lower_bound": lo, "upper_bound": hi}]
    payload = {
        "filters": filters,
        "fields": fields,
        "limit": PAGE_SIZE,
        "page": page,
        "sort": "Award Amount",
        "order": "desc",
    }
    return post_json(API, payload)


def fetch_all():
    fields = list(FIELDS)
    awards = []
    seen = set()
    naics_list = top_naics_codes()
    print(f"Fetching across {len(naics_list)} NAICS × {len(AMOUNT_BANDS)} amount bands…")

    def ingest(results, forced_naics=None, forced_naics_desc=None):
        added = 0
        for row in results:
            aid = row.get("Award ID") or row.get("generated_internal_id") or ""
            key = (aid, row.get("Recipient Name"), row.get("Award Amount"), row.get("Start Date"))
            if key in seen:
                continue
            seen.add(key)
            # Search API often returns null NAICS even when filter matched — stamp from filter
            if forced_naics and not row.get("NAICS Code"):
                row = dict(row)
                row["NAICS Code"] = forced_naics
                if forced_naics_desc:
                    row["NAICS Description"] = forced_naics_desc
            awards.append(row)
            added += 1
            if len(awards) >= MAX_AWARDS:
                break
        return added

    for ni, naics in enumerate(naics_list):
        if len(awards) >= MAX_AWARDS:
            break
        label = NAICS_LABEL.get(naics, "")
        for band in AMOUNT_BANDS:
            if len(awards) >= MAX_AWARDS:
                break
            for page in range(1, PAGES_PER_BAND + 1):
                if len(awards) >= MAX_AWARDS:
                    break
                try:
                    data = None
                    for attempt in range(3):
                        try:
                            data = fetch_page(page, fields, naics=naics, amount_band=band)
                            break
                        except TimeoutError:
                            print(f"Timeout naics={naics} band={band} p{page} attempt {attempt+1}")
                            time.sleep(1.5 * (attempt + 1))
                    if data is None:
                        print(f"Skipping naics={naics} band={band} p{page} after timeouts")
                        break
                except urllib.error.HTTPError as e:
                    body = e.read().decode(errors="replace")[:400]
                    print(f"HTTP {e.code} naics={naics} band={band} page={page}: {body[:120]}")
                    if e.code == 400 and "NAICS Description" in fields:
                        fields = [f for f in fields if f != "NAICS Description"]
                        try:
                            data = fetch_page(page, fields, naics=naics, amount_band=band)
                        except Exception as e2:
                            print(f"  retry failed: {e2}")
                            break
                    else:
                        break
                except Exception as e:
                    print(f"Error naics={naics} band={band} p{page}: {e}")
                    break
                results = data.get("results") or []
                added = ingest(results, forced_naics=naics, forced_naics_desc=label)
                has_next = (data.get("page_metadata") or {}).get("hasNext")
                if page == 1 and ni < 5:
                    print(
                        f"  NAICS {naics} band {band[0]}-{band[1]} p{page}: "
                        f"+{added}/{len(results)} (total {len(awards)})"
                    )
                if not results or not has_next:
                    break
                time.sleep(0.08)
        if (ni + 1) % 10 == 0:
            print(f"… {ni+1}/{len(naics_list)} NAICS done, {len(awards)} awards")
        time.sleep(0.05)

    # Extra general pages (no NAICS filter) for state/agency breadth if still room
    if len(awards) < MAX_AWARDS * 0.7:
        print("Filling with unfiltered SB-band pages…")
        for band in AMOUNT_BANDS:
            for page in range(1, 6):
                if len(awards) >= MAX_AWARDS:
                    break
                try:
                    data = fetch_page(page, fields, amount_band=band)
                except Exception as e:
                    print("unfiltered err", e)
                    break
                results = data.get("results") or []
                ingest(results)
                if not results or not (data.get("page_metadata") or {}).get("hasNext"):
                    break
                time.sleep(0.1)

    return awards


print(f"Fetching contract awards {start_date} → {end_date} (≤$10M bands)…")
raw = fetch_all()
print(f"Fetched {len(raw)} raw awards")

awards = []
naics_count = Counter()
state_count = Counter()
agency_count = Counter()
naics_desc = {}

for row in raw:
    naics = str(row.get("NAICS Code") or "").strip()
    if naics.endswith(".0"):
        naics = naics[:-2]
    state = (row.get("Place of Performance State Code") or "").strip().upper()
    agency = (row.get("Awarding Agency") or "").strip() or "Unknown Agency"
    desc_n = (row.get("NAICS Description") or "").strip()
    if naics and desc_n:
        naics_desc[naics] = desc_n.title() if desc_n == desc_n.upper() else desc_n
    amt = row.get("Award Amount")
    try:
        amt_f = float(amt) if amt is not None else 0.0
    except (TypeError, ValueError):
        amt_f = 0.0
    gen = row.get("generated_internal_id")
    a = {
        "id": (row.get("Award ID") or "").strip(),
        "recipient": (row.get("Recipient Name") or "").strip(),
        "amount": amt_f,
        "start": (row.get("Start Date") or "").strip(),
        "end": (row.get("End Date") or "").strip(),
        "agency": agency,
        "subagency": (row.get("Awarding Sub Agency") or "").strip(),
        "atype": (row.get("Contract Award Type") or "").strip(),
        "description": (row.get("Description") or "").strip(),
        "state": state if len(state) == 2 else "",
        "naics": naics,
        "naics_desc": desc_n,
        "generated": gen,
        "link": usaspending_link(row.get("Award ID"), gen),
        "agency_slug": slug(agency),
    }
    awards.append(a)
    if naics:
        naics_count[naics] += 1
    if a["state"]:
        state_count[a["state"]] += 1
    agency_count[agency] += 1

awards.sort(key=lambda a: (-a["amount"], a["start"] or "", a["id"]))
top_naics = [c for c, _ in naics_count.most_common(50)]
top_states = [s for s, _ in state_count.most_common(50)]
top_agencies = [ag for ag, _ in agency_count.most_common(30)]

CSS = """body{font-family:system-ui,sans-serif;max-width:1040px;margin:auto;padding:16px;color:#1a2332;line-height:1.45}
h1{color:#0a3d62;font-size:1.6rem}h2{font-size:1.15rem;color:#0a3d62}a{color:#0a3d62}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #e2e8f0;padding:7px 6px;text-align:left;vertical-align:top}
th{background:#f1f5f9}.cta{background:#0a3d62;color:#fff;padding:16px;border-radius:8px;margin:16px 0}
.cta a{color:#fff;font-weight:700}
.badge{display:inline-block;background:#e0f2fe;color:#0a3d62;padding:1px 6px;border-radius:4px;font-size:11px;margin-right:4px}
nav{margin:12px 0;line-height:1.9}nav a{margin-right:10px;font-size:13px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}.stat{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;min-width:120px}
.stat b{display:block;font-size:1.4rem;color:#0a3d62}
.amt{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600}
.muted{color:#64748b;font-size:12px}"""


def rel(from_path, to_path):
    from_dir = os.path.dirname(from_path)
    return os.path.relpath(to_path, from_dir or ".").replace(os.sep, "/")


def row_html(a, from_path="index.html"):
    title = a["description"] or a["id"] or "(no description)"
    title = html.escape(title[:140] + ("…" if len(title) > 140 else ""))
    link = html.escape(a["link"])
    recip = html.escape((a["recipient"] or "—")[:70])
    agency = html.escape((a["agency"] or "—")[:50])
    naics = html.escape(a["naics"] or "—")
    state = html.escape(a["state"] or "—")
    start = html.escape(a["start"] or "—")
    amt = money(a["amount"])
    atype = html.escape((a["atype"] or "")[:40])
    return (
        f'<tr><td><a href="{link}" rel="nofollow" target="_blank">{title}</a><br>'
        f'<small class="muted">{html.escape(a["id"])} · {atype}</small></td>'
        f"<td>{recip}</td><td class=\"amt\">{amt}</td><td>{agency}</td>"
        f"<td>{naics}</td><td>{state}</td><td>{start}</td></tr>"
    )


def page(title, desc, items, fname, extra=""):
    items_sorted = sorted(items, key=lambda a: (-a["amount"], a["start"] or ""))
    shown = items_sorted[:600]
    note = ""
    if len(items_sorted) > 600:
        note = f"<p><em>Showing 600 of {len(items_sorted):,} (largest first). Full dump in awards.json.</em></p>"

    home = rel(fname, "index.html")
    recent = rel(fname, "recent.html")
    naics_nav = " ".join(
        f'<a href="{rel(fname, f"by-naics/{c}.html")}">{c}</a>' for c in top_naics[:20]
    )
    state_nav = " ".join(
        f'<a href="{rel(fname, f"by-state/{s}.html")}">{s}</a>' for s in top_states[:20]
    )
    agency_nav = " ".join(
        f'<a href="{rel(fname, f"by-agency/{slug(ag)}.html")}">{html.escape(ag[:28])}</a>'
        for ag in top_agencies[:12]
    )
    cta = (
        f'<div class="cta" id="pro"><b>Award Radar Pro — $49/month:</b> weekly email of new federal '
        f"contract awards matching your NAICS codes and states — see who won what, find teaming partners, "
        f'and spot competitors. <a href="{html.escape(PRO_URL)}">Start Pro</a></div>'
    )
    total_amt = sum(a["amount"] for a in items_sorted)
    out = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{BASE}{fname}">
<style>{CSS}</style></head><body>
<h1>{html.escape(title)}</h1>
<p>{html.escape(desc)} Updated {today:%B %d, %Y} from USASpending.gov public data
({LOOKBACK_DAYS}-day window, awards under ~$10M). {len(items_sorted):,} matching awards
(~{money(total_amt)} combined).</p>
{extra}{cta}{note}
<nav><a href="{home}">Home</a> <a href="{recent}">Recent / largest</a></nav>
<nav><b>Top NAICS:</b> {naics_nav}</nav>
<nav><b>States:</b> {state_nav}</nav>
<nav><b>Agencies:</b> {agency_nav}</nav>
<table><thead><tr><th>Award</th><th>Recipient</th><th>Amount</th><th>Agency</th><th>NAICS</th><th>State</th><th>Start</th></tr></thead>
<tbody>{"".join(row_html(a, fname) for a in shown)}</tbody></table>
{cta}
<p><small>Data: <a href="https://www.usaspending.gov/">USASpending.gov</a> public API (award types A/B/C/D).
Not affiliated with the U.S. government. Amounts and dates can lag or revise — confirm on the official award page.
Competitive intel only; do not scrape recipient contacts for bulk marketing.</small></p>
</body></html>"""
    path = os.path.join("site", fname)
    os.makedirs(os.path.dirname(path) or "site", exist_ok=True)
    open(path, "w", encoding="utf-8").write(out)


under_1m = [a for a in awards if a["amount"] < 1_000_000]
under_250k = [a for a in awards if a["amount"] < 250_000]
with_naics = [a for a in awards if a["naics"]]

stats = f"""<div class="stats">
<div class="stat"><b>{len(awards):,}</b>recent awards</div>
<div class="stat"><b>{len(with_naics):,}</b>with NAICS</div>
<div class="stat"><b>{len(under_1m):,}</b>under $1M</div>
<div class="stat"><b>{len(top_states)}</b>states covered</div>
</div>"""

# Home: mix of larger + mid awards for browsing
home_items = awards[:150] + under_1m[:100]
# dedupe preserving order
_seen = set()
home_dedup = []
for a in home_items:
    k = (a["id"], a["amount"], a["recipient"])
    if k in _seen:
        continue
    _seen.add(k)
    home_dedup.append(a)

page(
    f"Federal Contract Awards — Who Won What ({today:%B %Y})",
    "Free list of recent U.S. federal contract awards so small businesses can see winners by NAICS and state — competitive intel and teaming partners.",
    home_dedup,
    "index.html",
    extra=stats
    + f"<p>Home highlights a sample of recent awards. Browse by NAICS, state, or agency for the full SB-relevant set "
    + f"(awards under ~$10M in the last {LOOKBACK_DAYS} days). Distinct from Bid Radar (open solicitations) "
    + "and Grant Radar (nonprofit grants).</p>",
)

page(
    f"Largest Recent Federal Contract Awards ({today:%B %Y})",
    "Recent USASpending.gov contract awards sorted by amount — competitive intel for small-business contractors.",
    awards,
    "recent.html",
)

for c in top_naics:
    label = NAICS_LABEL.get(c) or naics_desc.get(c) or f"NAICS {c}"
    items = [a for a in awards if a["naics"] == c]
    page(
        f"{label} Contract Awards — NAICS {c} ({today:%B %Y})",
        f"Recent federal contract awards under NAICS {c} ({label}) from USASpending.gov.",
        items,
        f"by-naics/{c}.html",
    )

for s in top_states:
    items = [a for a in awards if a["state"] == s]
    page(
        f"Federal Contract Awards in {s} ({today:%B %Y})",
        f"Recent federal contract awards with place of performance in {s}.",
        items,
        f"by-state/{s}.html",
    )

for ag in top_agencies:
    items = [a for a in awards if a["agency"] == ag]
    page(
        f"{ag} Contract Awards ({today:%B %Y})",
        f"Recent federal contract awards from {ag}.",
        items,
        f"by-agency/{slug(ag)}.html",
    )

urls = (
    ["index.html", "recent.html"]
    + [f"by-naics/{c}.html" for c in top_naics]
    + [f"by-state/{s}.html" for s in top_states]
    + [f"by-agency/{slug(ag)}.html" for ag in top_agencies]
)
open("site/sitemap.xml", "w").write(
    '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    + "".join(f"<url><loc>{BASE}{u}</loc><lastmod>{today}</lastmod></url>" for u in urls)
    + "</urlset>"
)
open("site/robots.txt", "w").write(f"User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n")

slim = [
    {
        "id": a["id"],
        "recipient": a["recipient"],
        "amount": a["amount"],
        "start": a["start"],
        "end": a["end"],
        "agency": a["agency"],
        "subagency": a["subagency"],
        "atype": a["atype"],
        "description": a["description"][:300],
        "state": a["state"],
        "naics": a["naics"],
        "link": a["link"],
    }
    for a in awards
]
json.dump(slim, open("site/awards.json", "w"), separators=(",", ":"))

meta = {
    "built": today.isoformat(),
    "lookback_days": LOOKBACK_DAYS,
    "start_date": start_date,
    "end_date": end_date,
    "awards": len(awards),
    "naics_pages": len(top_naics),
    "state_pages": len(top_states),
    "agency_pages": len(top_agencies),
    "urls": len(urls),
    "under_1m": len(under_1m),
    "under_250k": len(under_250k),
    "pro_url": PRO_URL,
}
json.dump(meta, open("site/meta.json", "w"), indent=2)
print(
    f"{len(awards)} awards; {len(top_naics)} NAICS pages; {len(top_states)} state pages; "
    f"{len(top_agencies)} agency pages; {len(urls)} URLs; under_$1M={len(under_1m)} under_$250k={len(under_250k)}"
)
