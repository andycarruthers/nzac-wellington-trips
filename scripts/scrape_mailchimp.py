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
    r"trip\s+report|section\s+trip|climb|alpine|tramp|hike|traverse|summit|peak",
    re.I,
)

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

def extract_trip_sections(html, source_url):
    """
    Parse a Mailchimp campaign HTML and return a list of trip-report dicts.
    Each dict: {title, date, author, body_html, images, source_url}
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove Mailchimp header/footer boilerplate
    for sel in [
        ".mcnPreviewText", "#templateHeader", "#templateFooter",
        ".mcnDividerBlock", "#bodyCell",  # keep inner content
    ]:
        pass  # we'll work with the full soup and filter by content

    # Mailchimp campaigns use table-based layout.
    # Strategy: find all heading elements, check if they look like trip reports,
    # then collect following content until the next heading of the same level.

    reports = []
    headings = soup.find_all(re.compile(r"h[1-6]"))

    for heading in headings:
        heading_text = heading.get_text(strip=True)
        if not TRIP_HEADING_RE.search(heading_text):
            continue

        print(f"    Found trip section: {heading_text[:60]}")

        # Collect content nodes until the next heading of same/higher level
        h_level = int(heading.name[1])
        content_nodes = []
        for sibling in heading.find_next_siblings():
            if sibling.name and re.match(r"h[1-6]", sibling.name):
                sib_level = int(sibling.name[1])
                if sib_level <= h_level:
                    break  # next section at same or higher level
            content_nodes.append(sibling)

        if not content_nodes:
            continue

        # Extract author from first paragraph if it matches "by Name" or "- Name"
        author = ""
        if content_nodes:
            first_p = content_nodes[0].get_text(strip=True) if hasattr(content_nodes[0], 'get_text') else ""
            m = re.match(r"^[Bb]y\s+([\w\s]+?)(?:\.|,|$)", first_p)
            if m:
                author = m.group(1).strip()

        # Build body HTML
        body_html = str(heading) + "".join(str(n) for n in content_nodes)

        # Extract images
        images = []
        body_soup = BeautifulSoup(body_html, "html.parser")
        for img in body_soup.find_all("img"):
            src = img.get("src", "")
            if src and not src.endswith(".gif") and "mcsf" not in src:
                alt = img.get("alt", "")
                images.append({"src": src, "alt": alt})
                # Rewrite src to local path
                fname = slugify(src.split("/")[-1].split("?")[0]) or "image"
                img["src"] = f"/images/trips/{fname}"

        # Rebuild body_html after image rewriting
        body_html = str(body_soup)
        body_md = h2md.handle(body_html)
        body_md = re.sub(r"\n{3,}", "\n\n", body_md).strip()

        reports.append({
            "title":      heading_text,
            "date":       "",
            "author":     author,
            "body_md":    body_md,
            "images":     images,
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
    urls = [
        u.strip() for u in urls_file.read_text().splitlines()
        if u.strip() and not u.strip().startswith("#")
    ]
    print(f"Loaded {len(urls)} newsletter URLs")

    OUT_CONTENT.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    total_reports = 0

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] {url}")
        final_url, html = fetch_final_url(url)
        if not html:
            continue
        print(f"  Resolved to: {final_url}")

        reports = extract_trip_sections(html, final_url)
        print(f"  Found {len(reports)} trip report section(s)")

        for report in reports:
            slug = slugify(report["title"])[:60]
            out_file = OUT_CONTENT / f"mailchimp-{slug}.md"

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
