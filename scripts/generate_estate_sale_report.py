#!/usr/bin/env python3
"""Generate a DFW estate sale report from public listing sites.

Usage:
  python3 scripts/generate_estate_sale_report.py --start 2026-06-13 --end 2026-06-14
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


CENTRAL = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data" / "reports"

ESTATESALES_NET_URL = "https://www.estatesales.net/TX/Dallas-Fort-Worth-Arlington"
ESTATESALES_ORG_URLS = [
    "https://estatesales.org/estate-sales/tx/dallas",
    "https://estatesales.org/estate-sales/tx/fort-worth",
    "https://estatesales.org/estate-sales/tx/plano",
    "https://estatesales.org/estate-sales/tx/southlake",
]
MANUAL_CHECK_URLS = [
    ("EstateSale.com Dallas", "https://www.estatesale.com/cities/view/12/Estate-Sales-Dallas-.html"),
    ("EstateSale.com Fort Worth", "https://www.estatesale.com/cities/view/20/Estate-Sales-Fort-Worth-TX.html"),
    ("HiBid Dallas", "https://dallas.hibid.com/auctions"),
    ("AuctionNinja Dallas", "https://www.auctionninja.com/tx/dallas"),
    ("MaxSold Dallas", "https://maxsold.com/usa/texas/dallas"),
]

HOT_ZIPS = {
    "75205": {"priority": "A", "rank": 1, "area": "Highland Park / Park Cities"},
    "75225": {"priority": "A", "rank": 2, "area": "University Park / Preston Center"},
    "75230": {"priority": "A", "rank": 3, "area": "Preston Hollow"},
    "75209": {"priority": "A", "rank": 4, "area": "Bluffview / Devonshire / Greenway Parks"},
    "75229": {"priority": "A", "rank": 5, "area": "Preston Hollow west / North Dallas"},
    "76107": {"priority": "A", "rank": 6, "area": "Rivercrest / Westover Hills / Cultural District"},
    "76092": {"priority": "A", "rank": 7, "area": "Southlake"},
    "76262": {"priority": "A", "rank": 8, "area": "Westlake / Trophy Club / Roanoke"},
    "76034": {"priority": "B", "rank": 9, "area": "Colleyville"},
    "75214": {"priority": "B", "rank": 10, "area": "Lakewood"},
    "75220": {"priority": "B", "rank": 11, "area": "Northwest Dallas / Bluffview adjacent"},
    "76109": {"priority": "B", "rank": 12, "area": "Tanglewood / Colonial / TCU"},
    "75093": {"priority": "B", "rank": 13, "area": "West Plano / Willow Bend"},
    "75022": {"priority": "B", "rank": 14, "area": "Flower Mound"},
    "75034": {"priority": "B", "rank": 15, "area": "West Frisco / Starwood / Stonebriar"},
    "75078": {"priority": "B", "rank": 16, "area": "Prosper"},
    "76226": {"priority": "B", "rank": 17, "area": "Argyle / Bartonville / Lantana"},
    "75208": {"priority": "B", "rank": 18, "area": "Kessler Park / Winnetka Heights / Bishop Arts"},
    "75019": {"priority": "B", "rank": 19, "area": "Coppell"},
    "75039": {"priority": "B", "rank": 20, "area": "Las Colinas / Irving"},
    "76132": {"priority": "C", "rank": 21, "area": "Mira Vista / Southwest Fort Worth"},
    "75024": {"priority": "C", "rank": 22, "area": "West Plano / Legacy"},
    "75218": {"priority": "C", "rank": 23, "area": "Casa Linda / Forest Hills / White Rock"},
    "75238": {"priority": "C", "rank": 24, "area": "Lake Highlands"},
    "75033": {"priority": "C", "rank": 25, "area": "Northwest Frisco"},
    "75009": {"priority": "C", "rank": 26, "area": "Celina"},
    "75013": {"priority": "C", "rank": 27, "area": "Allen"},
}

KEYWORDS = [
    "art",
    "jewelry",
    "designer",
    "decor",
    "furnishings",
    "furniture",
    "mid century",
    "mcm",
    "vintage",
    "collectibles",
    "antiques",
    "silver",
    "rugs",
    "records",
    "vinyl",
    "tools",
    "asian",
    "high end",
    "coins",
    "gold",
    "sterling",
    "books",
    "fine",
    "luxury",
    "upscale",
]


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")


def fetch(url: str) -> tuple[str | None, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 DFWEstateSalePlanner/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return response.read().decode("utf-8", "ignore"), None
    except (urllib.error.URLError, TimeoutError) as exc:
        return None, str(exc)


def parse_datetime(value: object) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    text = re.sub(r"T(\d):(\d{2})", r"T0\1:\2", text)
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CENTRAL)
    return parsed.astimezone(CENTRAL)


def date_window(start: str, end: str) -> tuple[dt.datetime, dt.datetime]:
    start_date = dt.date.fromisoformat(start)
    end_date = dt.date.fromisoformat(end)
    return (
        dt.datetime.combine(start_date, dt.time.min, CENTRAL),
        dt.datetime.combine(end_date, dt.time.max, CENTRAL),
    )


def overlaps(start: dt.datetime | None, end: dt.datetime | None, window_start: dt.datetime, window_end: dt.datetime) -> bool:
    return (start is None or start <= window_end) and (end is None or end >= window_start)


def iso(value: dt.datetime | None) -> str:
    return value.isoformat(timespec="minutes") if value else ""


def fmt_range(sale: dict) -> str:
    start = parse_datetime(sale.get("start"))
    end = parse_datetime(sale.get("end"))
    if not start or not end:
        return "Dates not listed"
    if start.date() == end.date():
        return f"{start.strftime('%a %b %-d, %-I:%M%p')} to {end.strftime('%-I:%M%p')}"
    return f"{start.strftime('%a %b %-d, %-I:%M%p')} to {end.strftime('%a %b %-d, %-I:%M%p')}"


def open_on(sale: dict, day: dt.date) -> bool:
    start = parse_datetime(sale.get("start"))
    end = parse_datetime(sale.get("end"))
    if not start or not end:
        return True
    return start.date() <= day <= end.date()


def collect_estatesales_net(window_start: dt.datetime, window_end: dt.datetime) -> tuple[list[dict], dict]:
    page, error = fetch(ESTATESALES_NET_URL)
    status = {"name": "EstateSales.NET", "url": ESTATESALES_NET_URL, "ok": error is None, "error": error}
    if not page:
        return [], status

    sales = []
    pattern = r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>'
    for match in re.finditer(pattern, page, re.S):
        raw = html.unescape(match.group(1))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "SaleEvent":
            continue
        start = parse_datetime(data.get("startDate"))
        end = parse_datetime(data.get("endDate"))
        if not overlaps(start, end, window_start, window_end):
            continue
        location = data.get("location") or {}
        address = location.get("address") or {}
        organizer = data.get("organizer") or {}
        sales.append(
            {
                "source": "EstateSales.NET",
                "title": clean_text(data.get("name")),
                "url": data.get("url") or ESTATESALES_NET_URL,
                "company": clean_text(organizer.get("name")),
                "street": clean_text(address.get("streetAddress")),
                "city": clean_text(address.get("addressLocality")),
                "state": clean_text(address.get("addressRegion") or "TX"),
                "zip": clean_text(address.get("postalCode")),
                "start": iso(start),
                "end": iso(end),
                "type": "In-person estate sale",
                "description": clean_text(data.get("description")),
                "photo_count": len(data.get("image") or []),
            }
        )
    return sales, status


def collect_estatesales_org(window_start: dt.datetime, window_end: dt.datetime) -> tuple[list[dict], list[dict]]:
    sales: list[dict] = []
    statuses: list[dict] = []
    for url in ESTATESALES_ORG_URLS:
        page, error = fetch(url)
        statuses.append({"name": "EstateSales.org", "url": url, "ok": error is None, "error": error})
        if not page:
            continue
        matches = list(re.finditer(r"window\.pageData\.(?:listingsForMap|listings)\s*=\s*(\[.*?\]);", page, re.S))
        if not matches:
            statuses[-1]["ok"] = False
            statuses[-1]["error"] = "No embedded pageData listings found"
            continue
        match = matches[0]
        for candidate in matches:
            if "listingsForMap" in candidate.group(0)[:80]:
                match = candidate
                break
        try:
            listings = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            statuses[-1]["ok"] = False
            statuses[-1]["error"] = f"Could not parse listings JSON: {exc}"
            continue
        for item in listings:
            start = parse_datetime(item.get("date_from_with_utc_offset") or item.get("date_from"))
            end = parse_datetime(item.get("date_to_with_utc_offset") or item.get("date_to"))
            if not overlaps(start, end, window_start, window_end):
                continue
            zip_code = clean_text(item.get("zip"))
            if not zip_code:
                for field in ("city_zip_url", "url_abs", "url"):
                    found = re.search(r"/([0-9]{5})(?:/|$)", str(item.get(field) or ""))
                    if found:
                        zip_code = found.group(1)
                        break
            relative_url = item.get("url") or ""
            abs_url = item.get("url_abs") or ("https://estatesales.org" + relative_url)
            sales.append(
                {
                    "source": "EstateSales.org",
                    "title": clean_text(item.get("title") or item.get("title_sum")),
                    "url": abs_url,
                    "company": clean_text(item.get("company_name")),
                    "street": clean_text(item.get("address")),
                    "city": clean_text(item.get("city")),
                    "state": clean_text(item.get("state") or "TX"),
                    "zip": zip_code,
                    "start": iso(start),
                    "end": iso(end),
                    "type": clean_text(item.get("type_name")),
                    "description": clean_text(item.get("descr") or item.get("descr_sum")),
                    "photo_count": int(item.get("media_count") or 0),
                }
            )
    return sales, statuses


def dedupe_sales(sales: list[dict]) -> list[dict]:
    by_url: dict[str, dict] = {}
    for sale in sales:
        url = sale.get("url") or ""
        if url and url in by_url:
            by_url[url] = merge_sale(by_url[url], sale)
        elif url:
            by_url[url] = sale
        else:
            key = normalize_key(sale)
            by_url[key] = merge_sale(by_url[key], sale) if key in by_url else sale

    by_title_zip: dict[str, dict] = {}
    for sale in by_url.values():
        key = normalize_key(sale)
        by_title_zip[key] = merge_sale(by_title_zip[key], sale) if key in by_title_zip else sale
    return list(by_title_zip.values())


def normalize_key(sale: dict) -> str:
    title = re.sub(r"\W+", "", (sale.get("title") or "").lower())[:80]
    return f"{title}:{sale.get('zip', '')}:{sale.get('start', '')[:10]}"


def merge_sale(a: dict, b: dict) -> dict:
    merged = dict(a)
    sources = set((a.get("sources") or [a.get("source", "")]) + (b.get("sources") or [b.get("source", "")]))
    merged["sources"] = sorted(x for x in sources if x)
    for field in ("description", "street", "company", "city", "zip", "type"):
        if len(str(b.get(field) or "")) > len(str(merged.get(field) or "")):
            merged[field] = b.get(field)
    if int(b.get("photo_count") or 0) > int(merged.get("photo_count") or 0):
        merged["photo_count"] = b.get("photo_count")
    return merged


def score_sale(sale: dict) -> None:
    hot = HOT_ZIPS.get(sale.get("zip", ""))
    priority = hot["priority"] if hot else "Outside"
    base = {"A": 82, "B": 62, "C": 42}.get(priority, 22)
    text = f"{sale.get('title', '')} {sale.get('description', '')}".lower()
    keywords = [word for word in KEYWORDS if word in text]
    score = base + min(len(keywords) * 4, 32)
    photos = int(sale.get("photo_count") or 0)
    if photos >= 300:
        score += 10
    elif photos >= 100:
        score += 6
    elif photos >= 40:
        score += 3
    sale_type = (sale.get("type") or "").lower()
    if "in-person" in sale_type or "estate sale" in sale_type:
        score += 8
    if "online" in sale_type:
        score -= 10
    sale["score"] = score
    sale["keywords"] = keywords
    sale["zip_priority"] = priority
    sale["zip_rank"] = hot["rank"] if hot else 999
    sale["hot_area"] = hot["area"] if hot else ""


def reason_for(sale: dict) -> str:
    bits = []
    if sale.get("zip_priority") != "Outside":
        bits.append(f"{sale['zip_priority']} ZIP target")
    if sale.get("keywords"):
        bits.append(", ".join(sale["keywords"][:5]))
    photos = int(sale.get("photo_count") or 0)
    if photos >= 100:
        bits.append(photo_phrase(photos))
    elif photos:
        bits.append(photo_phrase(photos))
    return "; ".join(bits) or "General DFW candidate"


def photo_phrase(count: int) -> str:
    noun = "photo" if count == 1 else "photos"
    return f"{count} {noun}"


def sale_row_md(sale: dict, index: int) -> str:
    location = ", ".join(x for x in [sale.get("city"), sale.get("state"), sale.get("zip")] if x)
    title = sale.get("title") or "Untitled sale"
    link = sale.get("url") or "#"
    return (
        f"| {index} | {sale['score']} | {sale['zip_priority']} | "
        f"[{escape_md(title)}]({link}) | {escape_md(location)} | "
        f"{escape_md(fmt_range(sale))} | {escape_md(reason_for(sale))} |"
    )


def escape_md(text: object) -> str:
    return str(text or "").replace("|", "\\|")


def short_line(sale: dict) -> str:
    location = ", ".join(x for x in [sale.get("city"), sale.get("zip")] if x)
    title = sale.get("title") or "Untitled sale"
    return f"[{title}]({sale.get('url')}) - {location}, {fmt_range(sale)}, score {sale['score']} ({reason_for(sale)})"


def build_markdown(payload: dict) -> str:
    sales = payload["sales"]
    start = payload["date_range"]["start"]
    end = payload["date_range"]["end"]
    generated = payload["generated_at"]
    start_date = dt.date.fromisoformat(start)
    end_date = dt.date.fromisoformat(end)
    sat_sales = [sale for sale in sales if open_on(sale, start_date) and "online" not in (sale.get("type") or "").lower()]
    sun_sales = [sale for sale in sales if open_on(sale, end_date) and "online" not in (sale.get("type") or "").lower()]

    lines = [
        f"# DFW Estate Sale Plan: {start} to {end}",
        "",
        f"Generated: {generated}",
        "",
        "## Quick Take",
        "",
        f"- {len(sales)} candidate sales matched the date range across automated sources.",
        "- Prioritize exact hot ZIP matches first, then high-keyword sales near North Dallas, Plano, Argyle, Hurst, and Carrollton.",
        "- Verify addresses and hours before driving. Many estate sale sites hide exact addresses until the day before or morning of sale.",
        "",
        "## Saturday Plan",
        "",
    ]

    if sat_sales:
        lines.append("Best route if you want high-end upside and do not want to drive everywhere:")
        for sale in sat_sales[:6]:
            lines.append(f"- {short_line(sale)}")
    else:
        lines.append("- No in-person Saturday sales found in the automated pull.")

    lines += ["", "## Sunday Plan", ""]
    if sun_sales:
        lines.append("Sunday is mostly cleanup and second-day pricing. Pick one cluster:")
        for sale in sun_sales[:6]:
            lines.append(f"- {short_line(sale)}")
    else:
        lines.append("- No in-person Sunday sales found in the automated pull.")

    lines += [
        "",
        "## Top Targets",
        "",
        "| # | Score | ZIP Priority | Sale | Location | Dates | Why |",
        "|---|---:|---|---|---|---|---|",
    ]
    for index, sale in enumerate(sales[:15], 1):
        lines.append(sale_row_md(sale, index))

    lines += [
        "",
        "## All Matched Candidates",
        "",
        "| # | Score | ZIP Priority | Sale | Location | Dates | Why |",
        "|---|---:|---|---|---|---|---|",
    ]
    for index, sale in enumerate(sales, 1):
        lines.append(sale_row_md(sale, index))

    lines += ["", "## Automated Sources", ""]
    for source in payload["source_status"]:
        status = "OK" if source["ok"] else f"Check manually: {source.get('error') or 'unavailable'}"
        lines.append(f"- [{source['name']}]({source['url']}): {status}")

    lines += ["", "## Manual Cross-Checks", ""]
    for label, url in MANUAL_CHECK_URLS:
        lines.append(f"- [{label}]({url})")

    return "\n".join(lines) + "\n"


def markdown_to_html(markdown: str, payload: dict) -> str:
    # Small targeted renderer for this report structure.
    rows = []
    in_table = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            rows.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_table:
                rows.append("</tbody></table>")
                in_table = False
            rows.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("|---"):
            continue
        elif line.startswith("| # |"):
            if in_table:
                rows.append("</tbody></table>")
            in_table = True
            headers = [cell.strip() for cell in line.strip("|").split("|")]
            rows.append("<table><thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr></thead><tbody>")
        elif line.startswith("|") and in_table:
            cells = [cell.strip() for cell in split_markdown_row(line)]
            rows.append("<tr>" + "".join(f"<td>{linkify_markdown_cell(c)}</td>" for c in cells) + "</tr>")
        elif line.startswith("- "):
            rows.append(f"<p class=\"bullet\">{linkify_markdown_cell(line[2:])}</p>")
        elif line:
            rows.append(f"<p>{linkify_markdown_cell(line)}</p>")
        else:
            if in_table:
                rows.append("</tbody></table>")
                in_table = False
    if in_table:
        rows.append("</tbody></table>")

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html.escape(payload['title'])}</title>
  <style>
    :root {{ --ink: #172026; --muted: #60717c; --line: #d8e1e5; --bg: #f6f8f9; --panel: #fff; --a: #c7352d; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 18px 48px; }}
    nav {{ margin-bottom: 16px; }}
    a {{ color: #14637a; text-decoration-thickness: 1px; text-underline-offset: 2px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; line-height: 1.12; letter-spacing: 0; }}
    h2 {{ margin: 30px 0 10px; font-size: 20px; letter-spacing: 0; }}
    p {{ color: #2d3c43; line-height: 1.48; }}
    .bullet {{ margin: 8px 0; padding-left: 18px; position: relative; }}
    .bullet::before {{ content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--a); position: absolute; left: 0; top: 0.68em; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #edf3f5; font-size: 12px; color: #41545d; }}
    td:nth-child(1), td:nth-child(2), td:nth-child(3) {{ white-space: nowrap; }}
    .card {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin: 14px 0 20px; }}
    @media (max-width: 820px) {{ table {{ display: block; overflow-x: auto; }} h1 {{ font-size: 24px; }} }}
  </style>
</head>
<body>
  <main>
    <nav><a href=\"../index.html\">Back to ZIP map</a></nav>
    <div class=\"card\">
      {"".join(rows)}
    </div>
  </main>
</body>
</html>
"""


def split_markdown_row(line: str) -> list[str]:
    row = line.strip("|")
    cells = []
    current = []
    escaped = False
    for char in row:
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        escaped = False
    cells.append("".join(current).strip())
    return cells


def linkify_markdown_cell(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda match: f'<a href="{match.group(2)}" target="_blank" rel="noopener">{match.group(1)}</a>',
        escaped,
    )


def run(start: str, end: str) -> dict:
    window_start, window_end = date_window(start, end)
    net_sales, net_status = collect_estatesales_net(window_start, window_end)
    org_sales, org_statuses = collect_estatesales_org(window_start, window_end)
    sales = dedupe_sales(net_sales + org_sales)
    for sale in sales:
        score_sale(sale)
    sales.sort(key=lambda item: (-item["score"], item["zip_rank"], item.get("start", ""), item.get("title", "")))

    generated_at = dt.datetime.now(CENTRAL).isoformat(timespec="minutes")
    payload = {
        "title": f"DFW Estate Sale Plan: {start} to {end}",
        "generated_at": generated_at,
        "date_range": {"start": start, "end": end},
        "source_status": [net_status] + org_statuses,
        "manual_check_urls": [{"label": label, "url": url} for label, url in MANUAL_CHECK_URLS],
        "sales": sales,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument("--stdout", action="store_true", help="Print Markdown instead of writing files")
    args = parser.parse_args()

    payload = run(args.start, args.end)
    markdown = build_markdown(payload)
    if args.stdout:
        print(markdown)
        return 0

    slug = f"dfw-{args.start}-to-{args.end}"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / f"{slug}.json"
    md_path = REPORTS_DIR / f"{slug}.md"
    html_path = REPORTS_DIR / f"{slug}.html"
    latest_path = REPORTS_DIR / "latest.html"
    latest_json_path = DATA_DIR / "latest.json"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(markdown_to_html(markdown, payload), encoding="utf-8")
    latest_path.write_text(markdown_to_html(markdown, payload), encoding="utf-8")

    print(f"Wrote {md_path}")
    print(f"Wrote {html_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {latest_json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
