#!/usr/bin/env python3
"""
Wayback Machine scraper for NZAC Wellington trip reports.

Usage:
    pip install -r requirements.txt
    python scrape_wayback.py

Outputs:
    ../content/trips/*.md          Hugo markdown files
    ../static/images/trips/*.jpg   Downloaded images
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from slugify import slugify
import html2text

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ORIGIN = "http://www.nzalpine.wellington.net.nz"
CATEGORY_PATH = "/category/trip-reports/"
CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK = "https://web.archive.org/web"

OUT_CONTENT = Path(__file__).parent.parent / "content" / "trips"
OUT_IMAGES  = Path(__file__).parent.parent / "static" / "images" / "trips"

REQUEST_DELAY = 2.0   # seconds between Wayback requests (be polite)
MAX_RETRIES   = 3

SESSION = requests.Session()
SESSION.headers["User-Agent"] = (
    "NZAC-Wellington-Archive-Bot/1.0 "
    "(non-commercial club archive; andy@hardbasket.com)"
)

# ---------------------------------------------------------------------------
# CDX: discover all trip-report post URLs
# ---------------------------------------------------------------------------

def cdx_get_post_urls():
    """Return list of (timestamp, original_url) for all trip-report posts."""
    params = {
        "url":      f"{ORIGIN}/trip-reports/*",   # catches /trip-reports/slug/
        "output":   "json",
        "fl":       "timestamp,original",
        "filter":   "statuscode:200",
        "collapse": "urlkey",                     # one result per unique URL
        "matchType": "prefix",
    }
    print("Querying CDX API for trip report URLs...")
    r = SESSION.get(CDX_API, params=params, timeout=30)
    r.raise_for_status()
    rows = r.json()
    # First row is the header ["timestamp","original"]
    if not rows or rows[0] != ["timestamp", "original"]:
        print("Unexpected CDX response:", rows[:3])
        return []
    posts = []
    for ts, url in rows[1:]:
        # Skip category/tag/page index URLs — keep only single post slugs
        path = urlparse(url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        # WordPress single post: /year/month/slug or just /trip-reports/slug
        if len(parts) >= 2 and "trip-reports" not in parts[-1]:
            posts.append((ts, url))
    print(f"Found {len(posts)} unique trip-report posts via CDX.")
    return posts


# Also try the category listing pages as a fallback / supplement
def scrape_category_pages():
    """Walk paginated category pages and collect post URLs."""
    found = {}
    page = 1
    while True:
        if page == 1:
            url = f"{ORIGIN}{CATEGORY_PATH}"
        else:
            url = f"{ORIGIN}{CATEGORY_PATH}page/{page}/"

        wb_url = best_snapshot(url)
        if not wb_url:
            break
        print(f"  Category page {page}: {wb_url}")
        soup = fetch_soup(wb_url)
        if soup is None:
            break

        links = soup.select("h1.entry-title a, h2.entry-title a, .post-title a")
        if not links:
            # Try generic: any link whose href contains the origin + a year
            links = [
                a for a in soup.find_all("a", href=True)
                if re.search(r"/20\d\d/", a["href"]) or
                   (ORIGIN in a["href"] and "/trip" in a["href"])
            ]
        if not links:
            break

        for a in links:
            href = a["href"]
            if href not in found:
                found[href] = True

        # Check for next page
        next_link = soup.find("a", string=re.compile(r"older|next", re.I))
        if not next_link:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    return list(found.keys())


# ---------------------------------------------------------------------------
# Wayback helpers
# ---------------------------------------------------------------------------

def best_snapshot(original_url, prefer_timestamp=None):
    """Return the best Wayback URL for an original URL."""
    params = {
        "url":    original_url,
        "output": "json",
        "fl":     "timestamp,statuscode",
        "filter": "statuscode:200",
        "limit":  "1",
        "sort":   "desc",
    }
    if prefer_timestamp:
        params["closest"] = prefer_timestamp
        params["sort"] = "closest"
    try:
        r = SESSION.get(CDX_API, params=params, timeout=15)
        rows = r.json()
        if len(rows) < 2:
            return None
        ts = rows[1][0]
        return f"{WAYBACK}/{ts}/{original_url}"
    except Exception:
        return None


def fetch_soup(url, retries=MAX_RETRIES):
    """Fetch a Wayback URL and return BeautifulSoup, or None on failure."""
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            if r.status_code == 404:
                return None
        except requests.RequestException as e:
            print(f"    Fetch error (attempt {attempt+1}): {e}")
        time.sleep(REQUEST_DELAY * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# HTML → Hugo markdown conversion
# ---------------------------------------------------------------------------

h2md = html2text.HTML2Text()
h2md.ignore_links    = False
h2md.ignore_images   = False   # we handle images ourselves
h2md.body_width      = 0       # no line wrapping
h2md.protect_links   = True
h2md.wrap_links      = False


def clean_wayback_html(soup):
    """Remove Wayback toolbar and navigation cruft."""
    for sel in [
        "#wm-ipp", "#wm-ipp-base",   # Wayback toolbar
        ".site-header", ".site-footer",
        "header", "footer",
        "nav", ".navigation", ".nav-links",
        ".sidebar", "#sidebar", "aside",
        ".comments", "#comments",
        ".sharedaddy", ".jp-relatedposts",
    ]:
        for el in soup.select(sel):
            el.decompose()
    return soup


def extract_post(soup, post_url):
    """
    Extract structured data from a WordPress single-post page.
    Returns dict with keys: title, date, author, body_html, images
    """
    soup = clean_wayback_html(soup)

    # --- Title ---
    title = ""
    for sel in ["h1.entry-title", "h2.entry-title", ".post-title h1", "h1.post-title", "h1"]:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break

    # --- Date ---
    date_str = ""
    for sel in ["time.entry-date", ".entry-date", ".post-date", "time[datetime]", ".date"]:
        el = soup.select_one(sel)
        if el:
            date_str = el.get("datetime", el.get_text(strip=True))
            break
    date_iso = parse_date(date_str)

    # --- Author ---
    author = ""
    for sel in [".author.vcard a", ".entry-author a", ".byline a", ".author"]:
        el = soup.select_one(sel)
        if el:
            author = el.get_text(strip=True)
            break

    # --- Tags ---
    tags = []
    for el in soup.select(".entry-tags a, .tags-links a, .cat-links a, [rel=tag]"):
        t = el.get_text(strip=True).lower()
        if t and t not in tags:
            tags.append(t)

    # --- Body ---
    body_el = soup.select_one(
        ".entry-content, .post-content, article .content, .post-body"
    )
    if not body_el:
        body_el = soup.find("article")
    if not body_el:
        body_el = soup.find("body")

    # Collect images before converting to markdown
    images = []
    if body_el:
        for img in body_el.find_all("img"):
            src = img.get("src", "")
            # Unwrap Wayback image URLs
            src = unwrap_wayback_url(src)
            alt = img.get("alt", "")
            if src and not src.endswith(".gif"):  # skip UI gifs
                images.append({"src": src, "alt": alt})
                # Rewrite src in soup so html2text picks up local path later
                local_path = image_local_path(src)
                img["src"] = f"/images/trips/{local_path.name}"

    body_html = str(body_el) if body_el else ""
    body_md   = html2text_clean(body_html)

    return {
        "title":    title or "Untitled Trip Report",
        "date":     date_iso,
        "author":   author,
        "tags":     tags,
        "body_md":  body_md,
        "images":   images,
        "source_url": post_url,
    }


def html2text_clean(html):
    """Convert HTML to clean markdown."""
    md = h2md.handle(html)
    # Remove excessive blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def parse_date(raw):
    """Best-effort parse of a date string to YYYY-MM-DD."""
    if not raw:
        return ""
    # ISO datetime
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    # "15 March 2012"
    months = "january february march april may june july august september october november december"
    ml = months.split()
    m = re.search(
        r"(\d{1,2})\s+(" + "|".join(ml) + r")\s+(\d{4})",
        raw, re.I
    )
    if m:
        d, mon, y = m.groups()
        mo = ml.index(mon.lower()) + 1
        return f"{y}-{mo:02d}-{int(d):02d}"
    # "March 2012"
    m = re.search(r"(" + "|".join(ml) + r")\s+(\d{4})", raw, re.I)
    if m:
        mon, y = m.groups()
        mo = ml.index(mon.lower()) + 1
        return f"{y}-{mo:02d}-01"
    return ""


# ---------------------------------------------------------------------------
# Image downloading
# ---------------------------------------------------------------------------

def unwrap_wayback_url(url):
    """Extract the original URL from a Wayback-wrapped image URL."""
    # https://web.archive.org/web/20130505172652im_/http://...
    m = re.match(r"https?://web\.archive\.org/web/\d+[^/]*/(.+)", url)
    if m:
        return m.group(1)
    return url


def image_local_path(src):
    """Derive a local filename from an image URL."""
    name = Path(urlparse(src).path).name
    if not name or "." not in name:
        name = slugify(src[-40:]) + ".jpg"
    return OUT_IMAGES / name


def download_image(src, dest_path):
    """Download an image from the best Wayback snapshot."""
    if dest_path.exists():
        return True
    # Try direct URL first, then via Wayback
    wayback_src = f"{WAYBACK}/20130101000000im_/{src}"
    for url in [wayback_src, src]:
        try:
            r = SESSION.get(url, timeout=20, stream=True)
            if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(r.content)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    print(f"    Could not download image: {src}")
    return False


# ---------------------------------------------------------------------------
# Hugo markdown output
# ---------------------------------------------------------------------------

def to_hugo_markdown(post, slug):
    """Render a post dict as a Hugo markdown file string."""
    def q(s):
        return s.replace('"', '\\"')

    lines = ["---"]
    lines.append(f'title: "{q(post["title"])}"')
    if post["date"]:
        lines.append(f'date: {post["date"]}')
    if post["author"]:
        lines.append(f'author: "{q(post["author"])}"')
    if post.get("images"):
        cover = f"/images/trips/{image_local_path(post['images'][0]['src']).name}"
        lines.append(f'cover: "{cover}"')
    if post["tags"]:
        lines.append("tags:")
        for t in post["tags"]:
            lines.append(f'  - "{t}"')
    lines.append(f'source_url: "{post["source_url"]}"')
    lines.append('source: "NZAC Wellington website (via Wayback Machine)"')
    lines.append("draft: false")
    lines.append("---")
    lines.append("")
    lines.append(post["body_md"])
    return "\n".join(lines)


def slug_from_url(url):
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]
    return slugify(slug) if slug else "untitled"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUT_CONTENT.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    # Step 1: discover post URLs via CDX
    post_records = cdx_get_post_urls()

    # Step 2: if CDX found nothing useful, fall back to category page scraping
    if not post_records:
        print("CDX found no results, falling back to category page scraping...")
        urls = scrape_category_pages()
        post_records = [(None, u) for u in urls]

    if not post_records:
        print("No posts found. Exiting.")
        sys.exit(1)

    print(f"\nProcessing {len(post_records)} posts...\n")

    skipped = []
    processed = 0

    for i, (ts, original_url) in enumerate(post_records, 1):
        slug = slug_from_url(original_url)
        out_file = OUT_CONTENT / f"{slug}.md"

        if out_file.exists():
            print(f"[{i}/{len(post_records)}] Skip (exists): {slug}")
            continue

        print(f"[{i}/{len(post_records)}] Fetching: {original_url}")

        # Get best snapshot URL
        wb_url = f"{WAYBACK}/{ts}/{original_url}" if ts else best_snapshot(original_url)
        if not wb_url:
            print(f"  No snapshot found for {original_url}")
            skipped.append(original_url)
            continue

        soup = fetch_soup(wb_url)
        if soup is None:
            print(f"  Failed to fetch {wb_url}")
            skipped.append(original_url)
            continue

        post = extract_post(soup, original_url)
        print(f"  Title: {post['title']}")
        print(f"  Date:  {post['date']}")
        print(f"  Author:{post['author']}")
        print(f"  Images:{len(post['images'])}")

        # Download images
        for img in post["images"]:
            dest = image_local_path(img["src"])
            print(f"  Downloading image: {dest.name}")
            download_image(img["src"], dest)
            time.sleep(0.3)

        # Write markdown
        md = to_hugo_markdown(post, slug)
        out_file.write_text(md, encoding="utf-8")
        print(f"  Wrote: {out_file.name}")
        processed += 1

        time.sleep(REQUEST_DELAY)

    print(f"\nDone. {processed} posts written, {len(skipped)} skipped.")
    if skipped:
        print("\nSkipped URLs:")
        for u in skipped:
            print(f"  {u}")


if __name__ == "__main__":
    main()
