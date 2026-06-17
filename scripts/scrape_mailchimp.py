#!/usr/bin/env python3
"""
Mailchimp archive scraper for NZAC Wellington newsletters.

Reads a list of eepurl.com / Mailchimp archive URLs and extracts
trip-report sections, outputting Hugo markdown files.

Usage:
    python scrape_mailchimp.py urls.txt

The urls.txt file should have one URL per line (eepurl.com or mailchi.mp).
You can export the URL column from your Google Sheet as a plain text file.
"""

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from slugify import slugify
import html2text

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUT_CONTENT = Path(__file__).parent.parent / "content" / "trips"
OUT_IMAGES  = Path(__file__).parent.parent / "static" / "images" / "trips"
REQUEST_DELAY = 1.5

SESSION = requests.Session()
SESSION.headers["User-Agent"] = (
    "NZAC-Wellington-Archive-Bot/1.0 "
    "(non-commercial club archive; andy@hardbasket.com)"
)

h2md = html2text.HTML2Text()
h2md.ignore_links = False
h2md.ignore_images = False
h2md.body_width = 0

# Heading patterns that indicate a trip report section
TRIP_HEADING_RE = re.compile(
    r"trip\s+report|section\s+trip|climb|alpine|tramp|hike|traverse|summit|peak"
    r"|ski\s+tour|backcountry|mountaineer|bivouac|route|ascent|descent|expedition"
    r"|nelson\s+lakes|fiordland|ruapehu|aoraki|tasman|cook|kahurangi|arthur.s\s+pass",
    re.I,
)

# ---------------------------------------------------------------------------
# Location / tag inference (mirrors scrape_pdfs.py)
# ---------------------------------------------------------------------------

_LOCATION_RULES = [
    (r"\bHimalaya|Nepal|Tibet\b", "Himalaya"),
    (r"\bPatagonia\b", "Patagonia"),
    (r"\bAlaска|Alaska\b", "Alaska"),
    (r"\bAlps\b.*\b(?:Swiss|France|Italy|Austria|European)\b|\bEuropean\s+Alps\b", "European Alps"),
    (r"\bFiordland|Darran|Milford\b", "Fiordland"),
    (r"\bMt\.?\s+Cook|Aoraki|Tasman\s+Glacier\b", "Mount Cook"),
    (r"\bNelson\s+Lakes|Travers|St\.\s+Arnaud\b", "Nelson Lakes"),
    (r"\bArthur.s\s+Pass|Otira|Waimakariri\b", "Arthur's Pass"),
    (r"\bRuapehu|Tahurangi\b", "Ruapehu"),
    (r"\bTongariro\b", "Tongariro"),
    (r"\bKahurangi|Heaphy\b", "Kahurangi"),
    (r"\bAoraki|Mt\.?\s+Cook\b", "Mount Cook"),
    (r"\bWestland|Fox\s+Glacier|Franz\s+Josef\b", "Westland"),
    (r"\bArapiles|Australia\b", "Australia"),
    (r"\bAntarctica\b", "Antarctica"),
    (r"\bBaring\s+Head|Wellington|Wharepapa\b", "Wellington"),
    (r"\bHawke.s\s+Bay|Kaweka\b", "Hawke's Bay"),
    (r"\bTararua\b", "Tararua"),
    (r"\bMarlborough|Kaikoura\b", "Marlborough"),
    (r"\bOtago|Mt\.?\s+Aspiring|Wanaka\b", "Otago"),
    (r"\bQueenstown|Remarkables\b", "Queenstown"),
]

_TAG_RULES = [
    (r"\bski\s+tour(?:ing)?|skinning|backcountry\s+ski\b", "Ski Touring"),
    (r"\bice\s+climb|crampon|neve|crevasse\b", "Alpine"),
    (r"\balpine|mountaineer(?:ing)?|bivouac\b", "Alpine"),
    (r"\brock\s+climb|crag|trad\s+climb|bouldering\b", "Rock Climbing"),
    (r"\brock\s+hop|Arapiles|Wharepapa\b", "Rock Climbing"),
    (r"\btramping|hut\s+bag|bush\s+bash\b", "Tramping"),
    (r"\bski\s+field|ski\s+hill|piste\b", "Ski"),
]

def _infer_location(text):
    for pattern, location in _LOCATION_RULES:
        if re.search(pattern, text, re.I):
            return location
    return ""

def _infer_tags(text):
    seen = set(); tags = []
    for pattern, tag in _TAG_RULES:
        if tag not in seen and re.search(pattern, text, re.I):
            tags.append(tag); seen.add(tag)
    return tags or ["Alpine"]

# ---------------------------------------------------------------------------
# Fetch with redirect following
# ---------------------------------------------------------------------------

def fetch_final_url(url):
    """Follow redirects (eepurl -> mailchi.mp) and return final URL + HTML."""
    try:
        r = SESSION.get(url, timeout=20, allow_redirects=True)
        r.raise_for_status()
        return r.url, r.text
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return url, None


# ---------------------------------------------------------------------------
# Extract trip reports from a newsletter
# ---------------------------------------------------------------------------

_MAJOR_SECTION_RE = re.compile(
    r"^(?:Section\s+(?:Contacts?|News|Notices?)|"
    r"Coming\s+Trips|From\s+the\s+(?:Editor|Chair)|"
    r"Chair.s?\s+(?:Report|Update)|AGM|Notices?|Sponsors?|Calendar|"
    r"Photo\s+(?:Comp|Competition)|Club\s+(?:Night|Meeting)|"
    r"Events?|Instruction|Courses?|Newsletter|Powered\s+by)$",
    re.I,
)


def _block_ancestor(element):
    """Walk up to find the top-level Mailchimp mcnTextBlock / mcnImageCardBlock ancestor."""
    cur = element
    for _ in range(12):
        cur = cur.parent
        if cur is None:
            return None
        cls = cur.get("class", [])
        if any("mcn" in c and "Block" in c for c in cls):
            return cur
    return None


def _find_with_siblings(element):
    """Walk up from element until we find an ancestor that has next siblings."""
    cur = element
    for _ in range(15):
        sibs = [s for s in cur.find_next_siblings() if hasattr(s, "name") and s.name]
        if sibs:
            return cur, sibs
        cur = cur.parent
        if cur is None:
            break
    return None, []


def _extract_block_content(block):
    """
    From a Mailchimp content block, extract title, author, images, body_html.
    Trip report blocks use bold <strong> for title, no <h> tags.
    """
    # Clean up any inline style attributes to avoid noisy markdown
    for tag in block.find_all(True):
        if tag.has_attr("style"):
            del tag["style"]

    text_content = block.find("td", class_="mcnTextContent")
    if not text_content:
        text_content = block

    full_text = text_content.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    if not lines or len(full_text) < 30:
        return None

    # Title: first <h> tag, or first <strong> if no heading
    title = ""
    for h in text_content.find_all(["h1", "h2", "h3", "h4", "h5"]):
        t = h.get_text(strip=True)
        if t and len(t) > 4 and not _MAJOR_SECTION_RE.match(t):
            title = t
            break
    if not title:
        strong_tags = text_content.find_all("strong")
        for s in strong_tags:
            t = s.get_text(strip=True)
            # Skip short labels and ones that look like "By Name" or dates
            if t and len(t) > 8 and not re.match(r"^(?:By |Words? by |\d)", t, re.I):
                title = t
                break
    if not title and lines:
        title = lines[0]

    # Author — check first 8 and last 4 lines for byline patterns
    author = ""
    _AUTHOR_RE = re.compile(
        r"^(?:[Ww]ords?(?:\s+and\s+photos?)?\s+by|[Bb]y|[Ww]ritten\s+by|[Rr]eport\s+by|[Pp]hotos?\s+by)"
        r"\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})"
    )
    for line in lines[:8] + lines[-4:]:
        m = _AUTHOR_RE.match(line.strip())
        if m:
            author = m.group(1).strip()
            break

    # Images
    images = []
    for img in block.find_all("img"):
        src = img.get("src", "")
        if src and not src.endswith(".gif") and "mcsf" not in src and "mailchimp" not in src.lower():
            alt = img.get("alt", "")
            images.append({"src": src, "alt": alt})
            fname = slugify(src.split("/")[-1].split("?")[0]) or "image"
            img["src"] = f"/images/trips/{fname}"

    body_html = str(text_content)
    body_md = h2md.handle(body_html)
    body_md = re.sub(r"\n{3,}", "\n\n", body_md).strip()

    return {
        "title":     title,
        "author":    author,
        "images":    images,
        "body_md":   body_md,
    }


def extract_trip_sections(html, source_url):
    """
    Parse a Mailchimp campaign HTML and return a list of trip-report dicts.

    Mailchimp newsletters use a table-based layout: each section (Chair's Report,
    Trip Reports, Notices …) is a top-level <table class="mcnTextBlock"> element.
    Trip report content blocks follow the "Trip Reports" heading block as siblings.
    """
    soup = BeautifulSoup(html, "html.parser")
    reports = []

    # ── Strategy 1: find the "Trip Reports" section marker and collect siblings ──
    trip_marker_block = None
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        t = h.get_text(strip=True)
        if re.match(r"^Trip\s+Reports?$", t, re.I):
            block = _block_ancestor(h)
            if block:
                trip_marker_block = block
            break

    if trip_marker_block:
        marker_el, sibling_blocks = _find_with_siblings(trip_marker_block)
        content_blocks = []
        for sib in sibling_blocks:
            # Stop at next major section heading
            stopped = False
            for h in sib.find_all(["h1", "h2", "h3", "h4"]):
                if _MAJOR_SECTION_RE.match(h.get_text(strip=True)):
                    stopped = True
                    break
            if stopped:
                break
            sib_cls = sib.get("class", [])
            if any("mcnTextBlock" in c or "mcnImageCardBlock" in c for c in sib_cls):
                content_blocks.append(sib)

        # Each mcnTextBlock sibling is a trip report (image blocks attach to the next text block)
        pending_images = []
        for block in content_blocks:
            sib_cls = block.get("class", [])
            if any("mcnImageCardBlock" in c for c in sib_cls):
                # Collect images to attach to the next text block
                for img in block.find_all("img"):
                    src = img.get("src", "")
                    if src and not src.endswith(".gif") and "mcsf" not in src:
                        pending_images.append({"src": src, "alt": img.get("alt", "")})
                continue

            data = _extract_block_content(block)
            if not data or len(data["body_md"]) < 40:
                continue

            data["images"] = pending_images + data["images"]
            pending_images = []

            full_text = data["title"] + " " + data["body_md"]
            print(f"    Trip report: {data['title'][:70]}")
            reports.append({
                "title":      data["title"],
                "date":       "",
                "author":     data["author"],
                "location":   _infer_location(full_text),
                "tags":       _infer_tags(full_text),
                "body_md":    data["body_md"],
                "images":     data["images"],
                "source_url": source_url,
            })

    # ── Strategy 2: headings that directly match trip activity patterns ──
    # (for newsletters without a "Trip Reports" section header)
    if not reports:
        for h in soup.find_all(["h1", "h2", "h3", "h4"]):
            t = h.get_text(strip=True)
            if len(t) < 5 or not TRIP_HEADING_RE.search(t):
                continue
            if _MAJOR_SECTION_RE.match(t):
                continue
            # Find the block ancestor and collect its content
            block = _block_ancestor(h)
            if not block:
                continue
            data = _extract_block_content(block)
            if not data or len(data["body_md"]) < 40:
                continue
            full_text = t + " " + data["body_md"]
            data["title"] = t  # use heading as title
            print(f"    Trip report: {t[:70]}")
            reports.append({
                "title":      t,
                "date":       "",
                "author":     data["author"],
                "location":   _infer_location(full_text),
                "tags":       _infer_tags(full_text),
                "body_md":    data["body_md"],
                "images":     data["images"],
                "source_url": source_url,
            })

    return reports


# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------

def download_image(src, fname):
    dest = OUT_IMAGES / fname
    if dest.exists():
        return
    try:
        r = SESSION.get(src, timeout=20, stream=True)
        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
    except Exception as e:
        print(f"    Image download failed ({src}): {e}")


# ---------------------------------------------------------------------------
# Hugo markdown output
# ---------------------------------------------------------------------------

def to_hugo_markdown(post):
    def q(s): return s.replace('"', '\\"')
    lines = ["---"]
    lines.append(f'title: "{q(post["title"])}"')
    if post["date"]:
        lines.append(f'date: {post["date"]}')
    if post["author"]:
        lines.append(f'author: "{q(post["author"])}"')
        lines.append(f'authors: ["{q(post["author"])}"]')
    if post.get("location"):
        lines.append(f'location: "{q(post["location"])}"')
        lines.append(f'locations: ["{q(post["location"])}"]')
    if post.get("tags"):
        tag_list = ", ".join(f'"{t}"' for t in post["tags"])
        lines.append(f'tags: [{tag_list}]')
    if post.get("images"):
        fname = slugify(post["images"][0]["src"].split("/")[-1].split("?")[0]) or "cover"
        lines.append(f'cover: "/images/trips/{fname}"')
    lines.append(f'source_url: "{post["source_url"]}"')
    lines.append('source: "Vertigo Newsletter (Mailchimp archive)"')
    lines.append("draft: false")
    lines.append("---")
    lines.append("")
    lines.append(post["body_md"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python scrape_mailchimp.py urls.txt")
        sys.exit(1)

    urls_file = Path(sys.argv[1])
    # Each data line: "YYYY-MM-DD http://..." or just "http://..."
    entries = []
    for line in urls_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and re.match(r"\d{4}-\d{2}-\d{2}$", parts[0]):
            date, url = parts
        else:
            date, url = "", parts[0]
        entries.append((date, url))
    print(f"Loaded {len(entries)} newsletter URLs")

    OUT_CONTENT.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    total_reports = 0

    for i, (date, url) in enumerate(entries, 1):
        print(f"\n[{i}/{len(entries)}] {url}")
        final_url, html = fetch_final_url(url)
        if not html:
            continue
        print(f"  Resolved to: {final_url}")

        reports = extract_trip_sections(html, final_url)
        print(f"  Found {len(reports)} trip report section(s)")

        for report in reports:
            report["date"] = date  # use date from URL list
            slug = slugify(report["title"])[:60]
            out_file = OUT_CONTENT / f"mailchimp-{slug}.md"

            # If file already exists, patch date if missing then skip
            if out_file.exists():
                existing = out_file.read_text(encoding="utf-8")
                if date and "\ndate:" not in existing and date != "0000-01-01":
                    patched = existing.replace(
                        f'title: "{report["title"]}"',
                        f'title: "{report["title"]}"\ndate: {date}',
                        1,
                    )
                    if patched != existing:
                        out_file.write_text(patched, encoding="utf-8")
                        print(f"  Patched date ({date}): {out_file.name}")
                else:
                    print(f"  Skip (exists): {out_file.name}")
                continue

            # Download images
            for img in report["images"]:
                fname = slugify(img["src"].split("/")[-1].split("?")[0]) or "img"
                download_image(img["src"], fname)
                time.sleep(0.3)

            md = to_hugo_markdown(report)
            out_file.write_text(md, encoding="utf-8")
            print(f"  Wrote: {out_file.name}")
            total_reports += 1

        time.sleep(REQUEST_DELAY)

    print(f"\nDone. {total_reports} trip reports extracted.")


if __name__ == "__main__":
    main()
