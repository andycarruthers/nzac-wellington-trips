#!/usr/bin/env python3
"""
PDF newsletter scraper for NZAC Wellington Vertigo newsletters.

Extracts trip reports from PDF files using PyMuPDF.
Images embedded in the PDFs are also extracted.

Usage:
    pip install pymupdf python-slugify
    python scrape_pdfs.py /path/to/pdf/folder

Or for a single file:
    python scrape_pdfs.py Vertigo_201302_Feb.pdf
"""

import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Install PyMuPDF: pip install pymupdf")
    sys.exit(1)

from slugify import slugify

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUT_CONTENT = Path(__file__).parent.parent / "content" / "trips"
OUT_IMAGES  = Path(__file__).parent.parent / "static" / "images" / "trips"

# Headings that mark the start of a trip report
TRIP_START_RE = re.compile(
    r"""^
    (?:
        [Ss]ection\s+[Tt]rip\s+[Rr]eport     # "Section Trip Report"
        | [Tt]rip\s+[Rr]eport               # "Trip Report"
        | [A-Z][\w\s,']+?                   # Mountain/place name
          [,–\-]\s*                     # separator
          (?:[\w\s]+[,\s]+)?                # optional location
          \d{1,2}[–\-]?\d*\s+          # date range
          (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)
    )""",
    re.VERBOSE,
)

# Names that clearly aren't trip reports (Notices, Events, etc.)
SKIP_SECTION_RE = re.compile(
    r"^(?:Notices?|Events?|Upcoming|Club\s+Nights?|Contacts?|Advertisements?|Editorial)",
    re.I,
)

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def extract_pages(pdf_path):
    """Return list of page text strings."""
    doc = fitz.open(str(pdf_path))
    pages = []
    for page in doc:
        text = page.get_text("text")  # preserves layout order
        pages.append(text)
    return pages


def extract_images(pdf_path, dest_dir):
    """
    Extract all images from a PDF into dest_dir.
    Returns list of saved file paths.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    saved = []
    seen_xrefs = set()
    for page_num, page in enumerate(doc):
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                base_image = doc.extract_image(xref)
                ext  = base_image["ext"]
                data = base_image["image"]
                if len(data) < 5000:  # skip tiny UI elements
                    continue
                stem = f"{pdf_path.stem}-p{page_num+1}-img{xref}"
                fname = dest_dir / f"{stem}.{ext}"
                fname.write_bytes(data)
                saved.append(fname)
            except Exception as e:
                print(f"    Image extract error (xref {xref}): {e}")
    return saved


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

def split_into_sections(pages):
    """
    Concatenate all page text and split into sections by trip-report headings.
    Returns list of dicts: {heading, body_lines, page_start}
    """
    # Join all text with page markers
    full_text = []
    for i, page in enumerate(pages):
        full_text.append(f"\x0c PAGE {i+1} \x0c")  # form-feed page marker
        full_text.append(page)
    lines = "\n".join(full_text).splitlines()

    sections = []
    current = None

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("Page "):
            continue

        # Check if this line is a trip-report heading
        if TRIP_START_RE.match(line_stripped) and not SKIP_SECTION_RE.match(line_stripped):
            if current and current["body_lines"]:
                sections.append(current)
            current = {"heading": line_stripped, "body_lines": []}
        elif current is not None:
            current["body_lines"].append(line_stripped)

    if current and current["body_lines"]:
        sections.append(current)

    return sections


# ---------------------------------------------------------------------------
# Metadata extraction from section text
# ---------------------------------------------------------------------------

def parse_section(section, pdf_path, section_images):
    """Return a post dict from a section."""
    heading = section["heading"]
    lines   = section["body_lines"]

    # Author: often the second line, or "by Name"
    author = ""
    body_start = 0
    if lines:
        first = lines[0].strip()
        # "Firstname Lastname" (2-3 words, no other content)
        if re.match(r"^[A-Z][a-z]+(\s[A-Z][a-zñüáéíóúãâêôç]+){1,2}$", first):
            author = first
            body_start = 1
        elif re.match(r"^[Bb]y\s+", first):
            author = re.sub(r"^[Bb]y\s+", "", first).strip()
            body_start = 1

    # Participants: look for "Trip participants:" line
    participants = []
    for i, line in enumerate(lines[body_start:body_start+5], body_start):
        if "participants" in line.lower() or "party" in line.lower():
            names_str = re.sub(r"[Tt]rip\s+[Pp]articipants?:\s*", "", line)
            participants = [n.strip() for n in re.split(r"[,;]", names_str) if n.strip()]
            body_start = i + 1
            break

    # Date from heading
    date_iso = parse_heading_date(heading)

    # Location from heading
    location = extract_location(heading)

    # Body text
    body_lines = lines[body_start:]
    body_md = "\n\n".join(
        " ".join(para).strip()
        for para in split_paragraphs(body_lines)
        if para
    )

    # Assign images: distribute section images evenly in body
    img_md = ""
    for img_path in section_images:
        rel = f"/images/trips/{img_path.name}"
        img_md += f"\n\n![Trip photo]({rel})\n"

    # Derive newsletter issue from filename e.g. Vertigo_201302_Feb.pdf
    issue = pdf_path.stem.replace("_", " ")

    return {
        "title":        heading,
        "date":         date_iso,
        "author":       author,
        "participants": participants,
        "location":     location,
        "body_md":      body_md + img_md,
        "source":       f"Vertigo Newsletter — {issue}",
    }


def split_paragraphs(lines):
    """Group lines into paragraphs (split on blank lines)."""
    para = []
    for line in lines:
        if line.strip():
            para.append(line.strip())
        else:
            if para:
                yield para
                para = []
    if para:
        yield para


def parse_heading_date(heading):
    """Extract ISO date from a heading like 'Mt Hopeless, Nelson Lakes, 19-21 January 2013'."""
    m = re.search(
        r"(\d{1,2})[–\-]?(\d{0,2})\s+"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
        heading, re.I
    )
    if m:
        d_end = m.group(2) or m.group(1)
        mon = MONTH_MAP[m.group(3).lower()[:3]]
        year = m.group(4)
        try:
            return f"{year}-{mon}-{int(d_end):02d}"
        except ValueError:
            return f"{year}-{mon}-01"
    # Just year
    m = re.search(r"(20\d{2})", heading)
    if m:
        return f"{m.group(1)}-01-01"
    return ""


def extract_location(heading):
    """Best-effort extract a location name from a heading."""
    # Remove date portion
    loc = re.sub(
        r",?\s*\d{1,2}[–\-]?\d*\s+"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}.*",
        "", heading, flags=re.I
    ).strip().rstrip(",")
    # Remove "Section Trip Report –"
    loc = re.sub(r"^[Ss]ection\s+[Tt]rip\s+[Rr]eport\s*[–\-]\s*", "", loc)
    return loc


# ---------------------------------------------------------------------------
# Hugo markdown output
# ---------------------------------------------------------------------------

def to_hugo_markdown(post):
    def q(s): return str(s).replace('"', '\\"')
    lines = ["---"]
    lines.append(f'title: "{q(post["title"])}"')
    if post["date"]:
        lines.append(f'date: {post["date"]}')
    if post["author"]:
        lines.append(f'author: "{q(post["author"])}"')
    if post.get("participants"):
        lines.append("participants:")
        for p in post["participants"]:
            lines.append(f'  - "{q(p)}"')
    if post["location"]:
        lines.append(f'location: "{q(post["location"])}"')
    lines.append(f'source: "{q(post["source"])}"')
    lines.append("draft: false")
    lines.append("---")
    lines.append("")
    lines.append(post["body_md"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_pdf(pdf_path):
    print(f"\nProcessing: {pdf_path.name}")
    OUT_CONTENT.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    # Extract all images from PDF first
    all_images = extract_images(pdf_path, OUT_IMAGES)
    print(f"  Extracted {len(all_images)} images")

    # Extract and split text into sections
    pages = extract_pages(pdf_path)
    sections = split_into_sections(pages)
    print(f"  Found {len(sections)} trip report section(s)")

    # Distribute images evenly across sections
    imgs_per_section = []
    if sections:
        chunk = max(1, len(all_images) // len(sections))
        for i in range(len(sections)):
            imgs_per_section.append(all_images[i*chunk:(i+1)*chunk])
    else:
        imgs_per_section = [[] for _ in sections]

    for i, section in enumerate(sections):
        imgs = imgs_per_section[i] if i < len(imgs_per_section) else []
        post = parse_section(section, pdf_path, imgs)
        print(f"  Section: {post['title'][:60]}")

        # Build a unique slug: date + location slug
        date_part = post["date"].replace("-", "")[:6] if post["date"] else "000000"
        loc_part  = slugify(post["location"])[:40] if post["location"] else f"section{i}"
        slug      = f"{date_part}-{loc_part}"
        out_file  = OUT_CONTENT / f"pdf-{slug}.md"

        # Avoid overwriting
        counter = 0
        while out_file.exists():
            counter += 1
            out_file = OUT_CONTENT / f"pdf-{slug}-{counter}.md"

        md = to_hugo_markdown(post)
        out_file.write_text(md, encoding="utf-8")
        print(f"  Wrote: {out_file.name}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scrape_pdfs.py <pdf_file_or_folder>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if target.is_dir():
        pdfs = sorted(target.glob("*.pdf")) + sorted(target.glob("**/*.pdf"))
        pdfs = list(dict.fromkeys(pdfs))  # deduplicate
    else:
        pdfs = [target]

    print(f"Found {len(pdfs)} PDF(s) to process")
    for pdf in pdfs:
        try:
            process_pdf(pdf)
        except Exception as e:
            print(f"  ERROR processing {pdf.name}: {e}")

    print("\nAll done.")


if __name__ == "__main__":
    main()
