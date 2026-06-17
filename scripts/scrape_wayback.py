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

# Known good Wayback snapshots of the category listing to start from
SEED_URLS = [
    "https://web.archive.org/web/20130505172652/http://www.nzalpine.wellington.net.nz/category/trip-reports/",
    "https://web.archive.org/web/20120601000000*/http://www.nzalpine.wellington.net.nz/category/trip-reports/",
]

def cdx_get_post_urls():
    """Return list of (timestamp, original_url) for all trip-report posts via CDX."""
    # Try the whole domain — posts are at root level on this WordPress site
    for url_pattern in [
        f"{ORIGIN}/*",
        f"www.nzalpine.wellington.net.nz/*",
        f"nzalpine.wellington.net.nz/*",
    ]:
        params = {
            "url":       url_pattern,
            "output":    "json",
            "fl":        "timestamp,original",
            "filter":    ["statuscode:200", "mimetype:text/html"],
            "collapse":  "urlkey",
            "matchType": "prefix",
            "limit":     "500",
        }
        print(f"Querying CDX API: {url_pattern}")
        try:
            r = SESSION.get(CDX_API, params=params, timeout=30)
            r.raise_for_status()
            rows = r.json()
        except Exception as e:
            print(f"  CDX error: {e}")
            continue

        if not rows or rows[0] != ["timestamp", "original"]:
            print(f"  No results for {url_pattern}")
            continue

        posts = []
        skip_patterns = re.compile(
            r"/(category|tag|page|author|feed|wp-|xmlrpc|\?)"
        )
        for ts, url in rows[1:]:
            path = urlparse(url).path.rstrip("/")
            parts = [p for p in path.split("/") if p]
            # Keep only single-post URLs (1-3 path segments, no index pages)
            if parts and not skip_patterns.search(url) and len(parts) <= 4:
                posts.append((ts, url))

        print(f"  Found {len(posts)} candidate URLs")
        if posts:
            return posts

    return []


# Also try the category listing pages as a fallback / supplement
def scrape_category_pages():
    """Walk paginated category pages starting from known good Wayback snapshot."""
    found = {}

    # Try multiple timestamps to maximise post discovery.
    # Older seeds surface older posts; newer seeds surface newer ones.
    seed_wayback_urls = [
        "https://web.archive.org/web/20130505172652/http://www.nzalpine.wellington.net.nz/category/trip-reports/",
        "https://web.archive.org/web/20121201000000/http://www.nzalpine.wellington.net.nz/category/trip-reports/",
        "https://web.archive.org/web/20120101000000/http://www.nzalpine.wellington.net.nz/category/trip-reports/",
        "https://web.archive.org/web/20111001000000/http://www.nzalpine.wellington.net.nz/category/trip-reports/",
        "https://web.archive.org/web/20110101000000/http://www.nzalpine.wellington.net.nz/category/trip-reports/",
        # Also try the blog root — some themes show all posts there
        "https://web.archive.org/web/20130505172652/http://www.nzalpine.wellington.net.nz/",
        "https://web.archive.org/web/20121201000000/http://www.nzalpine.wellington.net.nz/",
    ]

    for seed_url in seed_wayback_urls:
        print(f"  Trying seed: {seed_url}")
        soup = fetch_soup(seed_url)
        if soup is None:
            print(f"    (no snapshot)")
            time.sleep(REQUEST_DELAY)
            continue

        links = collect_post_links(soup)
        print(f"    Got {len(links)} links")
        for href in links:
            found[href] = True

        # Follow ALL pagination from this seed
        page = 2
        current_soup = soup
        ts_match = re.search(r"/web/(\d+)/", seed_url)
        ts = ts_match.group(1) if ts_match else "20130505172652"

        while page <= 20:  # safety cap
            # Look for "Older posts" / "Next" pagination link
            next_link = None
            for text_pat in [r"older\s+posts?", r"next\s+page", r"next\s+»", r"»"]:
                next_link = current_soup.find("a", string=re.compile(text_pat, re.I))
                if next_link:
                    break
            # Also try href containing /page/N/
            if not next_link:
                next_link = current_soup.find(
                    "a", href=re.compile(
                        r"/category/trip-reports/page/\d+/|"
                        r"nzalpine\.wellington\.net\.nz/page/\d+/", re.I
                    )
                )
            if not next_link:
                break

            next_href = next_link.get("href", "")
            original_next = unwrap_wayback_url(next_href) if "archive.org" in next_href else next_href
            # Make sure it's a full URL
            if not original_next.startswith("http"):
                original_next = ORIGIN + "/" + original_next.lstrip("/")
            wb_next = f"{WAYBACK}/{ts}/{original_next}"
            print(f"    Page {page}: {original_next}")
            current_soup = fetch_soup(wb_next)
            if current_soup is None:
                break
            new_links = collect_post_links(current_soup)
            print(f"      Got {len(new_links)} links")
            if not new_links:
                break
            for href in new_links:
                found[href] = True
            page += 1
            time.sleep(REQUEST_DELAY)

        time.sleep(REQUEST_DELAY)

    print(f"  Total unique post URLs discovered: {len(found)}")
    return list(found.keys())


def collect_post_links(soup):
    """
    Extract trip-report post URLs from a Wayback-archived WordPress category page.
    Strategy: remove nav/header/footer first, then scan the main content area only.
    """
    # --- Step 1: remove nav chrome so we don't pick up menu links ---
    for sel in [
        "nav", "header", "footer", "#nav", "#header", "#footer",
        ".nav", ".menu", ".navigation", "#navigation",
        "#access", "#colophon", "#site-navigation",
        "[id*='menu']", "[class*='menu']",
        ".widget", "#sidebar", "aside",
        ".wm-ipp", "#wm-ipp",           # Wayback toolbar
    ]:
        for el in soup.select(sel):
            el.decompose()

    # --- Step 2: find the main content container ---
    content = None
    for sel in ["#content", "#main", "main", ".site-content",
                "#primary", ".content-area", "#wrapper", "body"]:
        content = soup.select_one(sel)
        if content:
            break
    if content is None:
        content = soup

    # --- Step 3: collect all links from the content area ---
    # Wayback rewrites internal links to full archive.org URLs
    domain_re = re.compile(r"nzalpine\.wellington\.net\.nz", re.I)
    skip_re   = re.compile(
        r"/(category|tag|page|author|feed|wp-|xmlrpc|"
        r"how-to-find-us|email-discussion|climbing-trips|instruction|"
        r"rock-climbing|club-meetings|club-activities|loaning|newsletter|"
        r"members-area|contacts|our-sponsors|webcams|photo-galleries|"
        r"about|resources|join)/",
        re.I,
    )
    # Must have a real slug path (not query strings)
    has_slug = re.compile(r"/[a-z0-9][a-z0-9\-]{3,}/?$", re.I)

    links = []

    # First try: WordPress post-title heading links (most reliable)
    for sel in [
        "h1.entry-title a", "h2.entry-title a",
        ".post-title a", ".entry-title a",
        "article h2 a", ".hentry h2 a", "h2.post-title a",
    ]:
        els = content.select(sel)
        if els:
            for a in els:
                href = a.get("href", "")
                if domain_re.search(href) and not skip_re.search(href):
                    links.append(href)
            if links:
                print(f"      found {len(links)} post links via '{sel}'")
                return list(dict.fromkeys(links))

    # Second try: any link in the content that looks like a dated post URL
    # WordPress date-based: /2013/04/slug/ or /2012/12/some-trip/
    dated_re = re.compile(
        r"nzalpine\.wellington\.net\.nz/20\d\d/\d\d/[a-z0-9\-]+/?$", re.I
    )
    for a in content.find_all("a", href=True):
        href = a["href"]
        if dated_re.search(href):
            links.append(href)

    if links:
        print(f"      found {len(links)} dated post links")
        return list(dict.fromkeys(links))

    # Third try: any content link matching slug pattern, excluding known static pages
    for a in content.find_all("a", href=True):
        href = a["href"]
        if domain_re.search(href) and not skip_re.search(href) and has_slug.search(href):
            if "?" not in href and "#" not in href:
                links.append(href)

    if links:
        print(f"      found {len(links)} candidate links (broad fallback)")
        return list(dict.fromkeys(links))

    # Debug dump if still nothing
    all_domain_links = [
        a["href"] for a in soup.find_all("a", href=True)
        if domain_re.search(a.get("href",""))
    ]
    print(f"      DEBUG: {len(all_domain_links)} domain links after nav strip:")
    for h in all_domain_links[:25]:
        print(f"        {h}")
    return []


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

    # --- Find main post/article element first ---
    post_el = None
    for sel in [".post", "article.post", ".hentry", "article", "#post", ".type-post"]:
        post_el = soup.select_one(sel)
        if post_el:
            break

    # --- Title: look inside post element first, then page-wide ---
    title = ""
    search_root = post_el or soup
    for sel in [
        "h1.entry-title", "h2.entry-title", ".post-title",
        "h1.post-title", "h2.post-title", ".entry-title",
        "h1", "h2",
    ]:
        el = search_root.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            # Skip the generic site title
            if t and "New Zealand Alpine Club" not in t and len(t) > 5:
                title = t
                break
    # Fallback: derive from URL slug
    if not title:
        slug = urlparse(post_url).path.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").replace("trip-report-", "").title()

    # --- Date: try meta, post element classes, then URL ---
    date_str = ""
    for sel in [
        "time.entry-date", "time.published", ".entry-date",
        ".post-date", "time[datetime]", ".date", ".published",
        "abbr.published", "span.date",
    ]:
        el = (post_el or soup).select_one(sel)
        if el:
            date_str = el.get("datetime", "") or el.get("title", "") or el.get_text(strip=True)
            if date_str:
                break
    # Fallback: extract date from URL path e.g. /2013/03/slug/
    if not date_str:
        m = re.search(r"/(\d{4})/(\d{2})/", post_url)
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-01"
    date_iso = parse_date(date_str) if date_str else ""

    # --- Author ---
    author = ""
    for sel in [".author.vcard a", ".entry-author a", ".byline a", ".author", ".by-author"]:
        el = (post_el or soup).select_one(sel)
        if el:
            a_text = el.get_text(strip=True)
            if a_text and a_text != "admin":
                author = a_text
                break
    # Fallback: look for "by <Name>" pattern in first few paragraphs
    if not author and post_el:
        for p in post_el.find_all("p")[:3]:
            m = re.match(r"^[Bb]y\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})", p.get_text(strip=True))
            if m:
                author = m.group(1)
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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url-file", default=None,
        help="Text file of Wayback URLs to scrape (one per line, # = comment)"
    )
    args = parser.parse_args()

    OUT_CONTENT.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    if args.url_file:
        # Read URLs directly from file — most reliable approach
        lines = Path(args.url_file).read_text(encoding="utf-8").splitlines()
        urls = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
        post_records = [(None, u) for u in urls]
        print(f"Loaded {len(post_records)} URLs from {args.url_file}")
    else:
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

        # scrape_category_pages returns full Wayback URLs; wrap as (None, url) tuples
        if post_records and isinstance(post_records[0], str):
            post_records = [(None, u) for u in post_records]

    print(f"\nProcessing {len(post_records)} posts...\n")

    skipped = []
    processed = 0

    for i, (ts, original_url) in enumerate(post_records, 1):
        # original_url may already be a full Wayback URL (from scrape_category_pages)
        if original_url.startswith("https://web.archive.org"):
            wb_url = original_url
            slug = slug_from_url(original_url)
        else:
            slug = slug_from_url(original_url)
            wb_url = f"{WAYBACK}/{ts}/{original_url}" if ts else None

        out_file = OUT_CONTENT / f"{slug}.md"

        if out_file.exists():
            print(f"[{i}/{len(post_records)}] Skip (exists): {slug}")
            continue

        print(f"[{i}/{len(post_records)}] Fetching: {wb_url or original_url}")

        if not wb_url:
            print(f"  No snapshot URL available, skipping")
            skipped.append(original_url)
            continue

        soup = fetch_soup(wb_url)

        # If the primary timestamp fails, try nearby timestamps
        if soup is None:
            original = unwrap_wayback_url(wb_url) if "archive.org" in wb_url else wb_url
            for alt_ts in ["20121201000000", "20120601000000", "20120101000000",
                           "20111201000000", "20111001000000", "20130101000000"]:
                alt_url = f"{WAYBACK}/{alt_ts}/{original}"
                print(f"  Retrying with timestamp {alt_ts}...")
                soup = fetch_soup(alt_url)
                if soup:
                    wb_url = alt_url
                    break
                time.sleep(1)

        if soup is None:
            print(f"  Failed all timestamps for {wb_url}")
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
