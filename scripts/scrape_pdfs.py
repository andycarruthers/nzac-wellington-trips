#!/usr/bin/env python3
"""
PDF newsletter scraper for NZAC Wellington Vertigo newsletters.

Downloads all PDFs from a Google Drive folder and extracts trip reports
using PyMuPDF, then outputs Hugo-compatible markdown files.

Usage:
    # Step 1: download PDFs from Google Drive (run once)
    python scrape_pdfs.py --download

    # Step 2: process already-downloaded PDFs
    python scrape_pdfs.py

    # Or point at a specific folder of PDFs:
    python scrape_pdfs.py --pdf-dir C:/path/to/pdfs
"""

import argparse
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

GDRIVE_FOLDER_ID = "1J3tH7jR7QS1SPe2MWJWOMau9jI22dhzx"

SCRIPT_DIR   = Path(__file__).parent
PDF_DIR      = SCRIPT_DIR / "vertigo_pdfs"
OUT_CONTENT  = SCRIPT_DIR.parent / "content" / "trips"
OUT_IMAGES   = SCRIPT_DIR.parent / "static" / "images" / "trips"

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------
#
# Vertigo newsletters have trip reports that start with headings like:
#   "Trip Report – Mt Hopeless, Nelson Lakes, 19-21 January 2013"
#   "Mt Aspiring – January 2013"
#   "Section Trip: Wharepapa South, March 2012"
#   "Rock Trip to Castle Hill"
# They are usually ALL CAPS or Title Case, often on their own line,
# 20–120 chars, and followed by an author or participant list.

TRIP_HEADING_RE = re.compile(
    r"""^
    (?:
        # Explicit "Trip Report" prefix
        [Tt]rip\s+[Rr]eport\b.*
        |
        # "Section Trip" prefix
        [Ss]ection\s+[Tt]rip\b.*
        |
        # Named peak/location followed by a date or dash
        (?:Mt\.?\s+|Mount\s+|Lake\s+)?
        [A-Z][A-Za-z'\-]{2,}
        (?:\s+[A-Z][A-Za-z'\-]{2,}){0,4}
        \s*[–\-—]\s*
        .{5,60}
        |
        # ALL CAPS heading that looks like a place name (≥3 words)
        [A-Z]{2,}(?:\s+[A-Z]{2,}){2,}\b.*
    )
    $""",
    re.VERBOSE,
)

# Sections that should NOT be treated as trip reports
SKIP_RE = re.compile(
    r"^(?:"
    r"Contents?|Index|Editorial|Notices?|Club\s+Night|Section\s+Night"
    r"|Events?|Upcoming|Contacts?|Advertisem|Gear\s+Review|Book\s+Review"
    r"|Instruction|Course|Letter|Competition|Photo\s+Comp|Sponsors?"
    r"|[Pp]resident|[Ss]ecretary|[Tt]reasurer"
    r")",
    re.I,
)

# Minimum body length (chars) for a section to be worth keeping
MIN_BODY_CHARS = 200


# ---------------------------------------------------------------------------
# Google Drive download
# ---------------------------------------------------------------------------

def download_from_gdrive():
    """Download all PDFs from the NZAC Wellington Vertigo folder."""
    try:
        import gdown
    except ImportError:
        print("Install gdown: pip install gdown")
        sys.exit(1)

    PDF_DIR.mkdir(exist_ok=True)
    folder_url = f"https://drive.google.com/drive/folders/{GDRIVE_FOLDER_ID}"
    print(f"Downloading PDFs from Google Drive folder...")
    print(f"  URL: {folder_url}")
    print(f"  Destination: {PDF_DIR}")
    print()
    print("NOTE: If prompted in a browser, sign in with your Google account")
    print("      that has access to the Wellington Alpine Club Drive folder.")
    print()

    try:
        gdown.download_folder(
            url=folder_url,
            output=str(PDF_DIR),
            quiet=False,
            use_cookies=True,
            remaining_ok=True,
        )
    except Exception as e:
        print(f"\nFolder download failed ({e}). Trying individual file download...")
        _download_individual_files()

    pdfs = list(PDF_DIR.glob("*.pdf"))
    print(f"\nDownloaded {len(pdfs)} PDF files to {PDF_DIR}")
    return pdfs


def _download_individual_files():
    """Fallback: download each PDF individually by hardcoded file ID."""
    import gdown
    # File ID list collected from the Google Drive API
    files = [
        ("Vertigo_201304_April.pdf", "1LMzgAeV1nh40mKqUngR7Ah9NTpCGcNwJ"),
        ("Vertigo_201604_April.pdf", "1s5SjBedM7a6-B2_v_ML--UYsw_PA6ShM"),
        ("Vertigo_201405_May.pdf",   "1T4D55NKDk8DcScW31ybIBDd6A8vhXdyd"),
        ("Vertigo_201605_May.pdf",   "11RexTFfOI5e4fjhTxzHB8DKRawHz7obp"),
        ("Vertigo_201611_Nov.pdf",   "1f2xIHksgwVD_EJeN6LW6ScHF2yQLuj6L"),
        ("Vertigo_201703_March.pdf", "141t0bgMKPD-nxo4yirxUW-3Io4zIP96z"),
        ("Vertigo_201511_Nov.pdf",   "1nOLyPqkBo79Hydm9zfIZ5k2nw0TfJU15"),
        ("Vertigo_201702_Feb.pdf",   "1GnPf_IrKvz7CjW3LAlh3NY5KvQjivYZj"),
        ("Vertigo_201401_Jan.pdf",   "1QFG9D54qPOikWsQ0U8pm-KCcEJ81A_gE"),
        ("Vertigo_201302_Feb.pdf",   "1mtPR4qq8kaBJTNTbYirtokTItSK85d5l"),
        ("Vertigo_201608_Aug.pdf",   "1zrhB9lBLdNcg7YKhlchUqy66PJFRlUhn"),
        ("Vertigo_201704_April.pdf", "1yD2wnmUO5kXtZR4S_pjfjfJ3j9acy_D8"),
        ("Vertigo_201410_Oct.pdf",   "1iUJ5Zz4VI60YVc4lPyApceA1r1z20zXq"),
        ("Vertigo_201609_Sept.pdf",  "11y3r7onb6eu2VofnNy95RjRXkM383A7h"),
        ("Vertigo_201610_Oct.pdf",   "1Q-50xbawntd12VTeG-LS2DVJfNr54r2_"),
        ("Vertigo_201602_Feb.pdf",   "1yUyYTG46hEyrgaETRrcglz3-nK925IPf"),
        ("Vertigo_201408_Aug.pdf",   "1pvYlKP9Jna9D06mfl4wy1Rw-JG63XsUy"),
        ("Vertigo_201402_Feb.pdf",   "1zUnCcGqPN5w1alpNSEVyPTj7RVbyBchW"),
        ("Vertigo_201701_Jan.pdf",   "1t4kxHfTdS1xUcTbXPuVOwVrvk1oQguW3"),
        ("Vertigo_201409_Sept.pdf",  "1gndUTByNO6nPv6CkU55YI-NcB3ZIYtjf"),
        ("Vertigo_201404_April.pdf", "1TzV_U7itemuguQV8sRzRBwH3mnT0VGO0"),
        ("Vertigo_201412_Dec.pdf",   "1Jm5J4p8tyRUNjyNhq5pFniJxR0nqgq5M"),
        ("Vertigo_201606_June.pdf",  "1cEWnHTtm8HzaHNlna0S5h5DrRPjNWob8"),
        ("Vertigo_201510_Oct.pdf",   "1HJFw3H6HSx4lQ3rv2IDw4TaQ54rOhXRx"),
        ("Vertigo_201509_Sept.pdf",  "19BgDQEXrRBCSLbm4n80qOBUcKBNfLjhH"),
        ("Vertigo_201407_Jul.pdf",   "1G5MgwKbrwWBfXOMymsGSohr24r5seTwl"),
        ("Vertigo_201403_March.pdf", "1H47dBaaxdouuyfhTz1tfXS9SZw_uUFob"),
        ("Vertigo_201406_June.pdf",  "1t65z41DObsiyAH_5O5olgXTOoG1ONNJK"),
        ("Vertigo_201601_Jan.pdf",   "1FExGbZ7Hb6rpoaJSwdp_NFJa_SBGbkHj"),
        ("Vertigo_201603_March.pdf", "1AHjr-HoVJMxXt9wsoV8Imqz1Cvj-0hzT"),
        ("Vertigo_201607_Jul.pdf",   "19_oxY0o-o3gZlUrQUCRK7n4Tc0qYtgPM"),
        ("Vertigo_201204_April.pdf", "1LMSwOaVmtQZZB3Uc_L4xL6_IfKwJuMRp"),
        ("Vertigo_201205_May.pdf",   "1DJ4XMUaAw_KAhza9VFZZOZzT7zxNtsds"),
        ("Vertigo_201206_June.pdf",  "1uer8z4OwDRVd5fGXNK78gXacTcxHNM2u"),
        ("Vertigo_201203_March.pdf", "1kaTUQO9KvxBlEUAa0y7L--0mcXGJhOUr"),
        ("Vertigo_201110_Oct.pdf",   "1qOyC-wHDGIZ9l5znumYt2mf6opy_HQDF"),
        ("Vertigo_201111_Nov.pdf",   "1-4JDm8EJS7xWQYg2pF4qrFmTDlYWtU4J"),
        ("Vertigo_201112_Dec.pdf",   "1Mk4uponOtps7zgJopLhssDhRInh8KAQI"),
        ("Vertigo_201011_Nov.pdf",   "1FkPL9VF009vaQ4fg_1gLhdWS1d-qSH9G"),
        ("Vertigo_201012_Dec.pdf",   "1pxiuK2knP0v2KVG9yWqAV7zeAb0I_Gls"),
        ("Vertigo_201008_Aug.pdf",   "1668sB7LpH21apPcr4QkB0Go9nrN95_cq"),
        ("Vertigo_201006_Jun.pdf",   "1pPnmK5Avb_cnA21R5XO-uXJ53o7tdYJz"),
        ("Vertigo_201005_May.pdf",   "1u9as3_KHbB1udL6KTYxb2KI1uYy01aQO"),
        ("Vertigo_201004_Apr.pdf",   "1aKsaU1Voiq4ITJSV5Dz8b5z7hjN5TNKq"),
        ("Vertigo_201002_Feb.pdf",   "1yHg4xEBSn0WeRrebWXW01L2HFdqUTs3M"),
        ("Vertigo_201001_Jan.pdf",   "1Jl0mTq4N6QFIrORAmS6RQmPcC5hhT6xe"),
        ("Vertigo_200911_Nov.pdf",   "1jELCqaLgchcp6ldYBQUSYgmcT57TKtkX"),
        ("Vertigo_200910_Oct.pdf",   "1uGpc7IwYWRtfZgGCIts4PoNp84omCY-4"),
        ("Vertigo_200909_Sep.pdf",   "1P4naJsCLUMN_u3n8JzCB_1QVPqTfwWgk"),
        ("Vertigo_200908_Aug.pdf",   "1b3juHSaVyv_IwN4R1n8c0PaAbKtJ4-au"),
        ("Vertigo_200907_Jul.pdf",   "1gqBC-JyER4zB5V2_krac0UJXDCPkogiN"),
        ("Vertigo_200906_Jun.pdf",   "1O8INyp3GtSBYKL2-RSp5pgzrJY6qc4SD"),
        ("Vertigo_200904_Apr.pdf",   "1-9t148tMYTZAvg2r7pFYVUgMR2ZGtU_f"),
        ("Vertigo_200903_Mar.pdf",   "1kTg5-1NblZnzvBbLO-1dUUFAVQr5jkHv"),
        ("Vertigo_200902_Feb.pdf",   "1uYD18Vn5OC9VYrb0cSY-budxWAcylyEi"),
        ("Vertigo_200812_Dec.pdf",   "1Ezf6vWRnVifS_e1X1NSXLyf0dNFm4g9I"),
        ("Vertigo_200811_Nov.pdf",   "19LshOOt0yFGJ0znlFnISS8R8CfyzGINV"),
        ("Vertigo_200810_Oct.pdf",   "10p8ehfLISi2yPcvp7nsY1zVA5JBVq_Bf"),
        ("Vertigo_200809_Sep.pdf",   "1wfDxk521nmOd70PuSsjxo4bBYKzWSKT1"),
        ("Vertigo_200808_Aug.pdf",   "19G3b7A8wxzHpV78uNQBVy05F3pxySykO"),
        ("Vertigo_200805_May.pdf",   "1TA4kE_fZhpfCU9in-bUGRJW2pyDRV7jb"),
        ("Vertigo_200803_Mar.pdf",   "1kRkmPhfFSG8ga7Uj-9MPs7OYJVy0QgSV"),
        ("Vertigo_200802_Feb.pdf",   "1A7O8h6oPgBGpjkYFAfyc0kNguw0GcFZ3"),
        ("Vertigo_200712_Dec.pdf",   "14d4M57dvly7xvSF5dStz6LGC6uqlIALq"),
        ("Vertigo_200711_Nov.pdf",   "1IQQZPSv0q3kuh5K4-1fRGNyzVA3RD70F"),
        ("Vertigo_200710_Oct.pdf",   "1hFKusdyKfHjFP6IVoQaVfiP4kE1PW30A"),
        ("Vertigo_200709_Sep.pdf",   "13Rvj9LMvLCgauRl2Jtuu4FHRzAb6Wizv"),
        ("Vertigo_200708_Aug.pdf",   "1M02GpyltdmmDgint7A10dl1HLkMezdSx"),
        ("Vertigo_200707_Jul.pdf",   "1Hszzaeyd6s4UL7ZPjxWLV54wlF6n43Kg"),
        ("Vertigo_200706_Jun.pdf",   "1_noh_inHX5RL0xb8JEFh_OmziDMN7lY1"),
        ("Vertigo_200705_May.pdf",   "1GmweI06SJ6l60395RerIBAOklTjNuapM"),
        ("Vertigo_200704_Apr.pdf",   "1ce8bQNlf2kDnyW5er1YFn_UsG76DnlSA"),
        ("Vertigo_200702_Feb.pdf",   "1zntaVlKKnCAOhwdoQhIncnQdWYws0iXx"),
        ("Vertigo_200612_Dec.pdf",   "1p-hs7rWeLURyMWUhoJX67H51yHEQX7qV"),
        ("Vertigo_200611_Nov.pdf",   "1UP9Pu4isUxI70xgzsRFsZfD76TLg8iHI"),
        ("Vertigo_200609_Sep.pdf",   "1v3jHsy57eYME8M-NWbX1WPFBydAt09zD"),
        ("Vertigo_200608_Aug.pdf",   "1fe13_D29omgf-9pBpERr7jQPCBwiLE1R"),
        ("Vertigo_200607_Jul.pdf",   "16KyzsJzRboF4dbCn1sg0IHcMSj-fhL_c"),
        ("Vertigo_200606_Jun.pdf",   "1R2LA5gwdD87XLguSjUM0p3nZBRKV8eum"),
        ("Vertigo_200605_May.pdf",   "1gfKBuN7-kIEBjXDT3KnPAXchp16yti-u"),
        ("Vertigo_200604_Apr.pdf",   "1BaIxqea2QKcuzqpcLQwOHOp-w0JVQGh8"),
        ("Vertigo_200510_Oct.pdf",   "19Tqsh87Riu7pqXMwKXKGx3VaIOF9-Avm"),
        ("Vertigo_200509_Sep.pdf",   "1sthBlYHtQ8-DoX28I7wNka9D4D6Mr2-a"),
        ("Vertigo_200508_Aug.pdf",   "10wWYvMlLRnC1EJrRhX3r1-iQEw_Ikj-3"),
        ("Vertigo_200507_Jul.pdf",   "1qDsFvhsOajGSYNcZb1eI7cRNZYMcYojf"),
        ("Vertigo_200505_May.pdf",   "1ptNj5S7_-gc9R5O58s7-fREwhc5qbk6h"),
        ("Vertigo_200504_Apr.pdf",   "16ZTvwwLJgT1wA8XSRGsE89VHYbbeCSun"),
        ("Vertigo_200503_Mar.pdf",   "1XyCLH1bzI0P8dpiLuij40k8sCtFH9tTa"),
        ("Vertigo_200502_Feb.pdf",   "1--UH1ku28wTZDM0RBSTcZ9m9914qacsm"),
        ("Vertigo_200412_Dec.pdf",   "1EgfSC29DFVm0KbACItZnDFR8HohYGL04"),
        ("Vertigo_200411_Nov.pdf",   "1Pfs8evxEtqSxImPqhkMAqQYjreD49Kzc"),
        ("Vertigo_200410_Oct.pdf",   "1Va2HgNyhLU8H4nQdlU3PoxUSnnpO1Ks_"),
        ("Vertigo_200409_Sep.pdf",   "1PjwU6w5HpFCfKH3mBH7miULT6UBTamMP"),
        ("Vertigo_200408_Aug.pdf",   "1LsKdfqFEvR756Podk_Wmr9VSAP_e-amn"),
        ("Vertigo_200407_Jul.pdf",   "1T0HEIA1YxNt8qBwzs6c2t32iMIFautek"),
        ("Vertigo_200406_Jun.pdf",   "1j1HyOMYyfzkUC0aCVhleY77vS8L825Vf"),
        ("Vertigo_200405_May.pdf",   "1la9SZTjcbHyFM1I2v-kPPDW58B_ESyl_"),
        ("Vertigo_200404_Apr.pdf",   "155ifT_WBIn6QRwVeChECxDnFiZDue3Aw"),
        ("Vertigo_200403_Mar.pdf",   "1HI-tWw6CKl_Kqpwq-XG2NfZt01TCdPe4"),
        ("Vertigo_200402_Feb.pdf",   "1ltRt3ByBvKr2YumV5lx14wepk7tyiAqY"),
        ("Vertigo_200312_Dec.pdf",   "1AtHhXY-Qj3wunhBKfFs9Px2KlihEUk33"),
        ("Vertigo_200311_Nov.pdf",   "1Lk69BLrFAxBHn10-NO9Vao3EYLd-PrYR"),
        ("Vertigo_200310_Oct.pdf",   "151wRwxIO6nnB2NDe2kGoouZ4OqCE-QRF"),
        ("Vertigo_200309_Sep.pdf",   "1-aJ7-vQD6jeEClBUePIADk2gMwcbcRM4"),
        ("Vertigo_200308_Aug.pdf",   "1PPm6cgQ6Edx3o3cauk4vMw93zhs1Op0M"),
        ("Vertigo_200307_Jul.pdf",   "12F-U5zzW3jpDDSZoztV4fzek7GNbTMiw"),
        ("Vertigo_200306_Jun.pdf",   "1MJ_cbswL60r4BjwZgqD_N1j90_SZmNXi"),
        ("Vertigo_200305_May.pdf",   "1hcETplGvQcJf1JuVLn6kdZMVG6LpjudB"),
        ("Vertigo_200304_Apr.pdf",   "1H2RH7jP-gmseJRbmkd_RnUqV2taocT4J"),
        ("Vertigo_200303_Mar.pdf",   "1nURO_VUJgRzt5mPZso_azy7_Jr3Pensv"),
        ("Vertigo_200302_Feb.pdf",   "1hNRyy2anOgaLAB5tGqPO3k0zL5nk5V-g"),
        ("Vertigo_200212_Dec.pdf",   "1a0IN3bTqThlA1TkAF80HCvGtnWrAlrbJ"),
        ("Vertigo_200211_Nov.pdf",   "1Wa3Ju4MhCbSydu0-iMNF2FARVIhsiPmF"),
        ("Vertigo_200209_Sep.pdf",   "1jw4IolJGp8mBgTzVuwZkrOrg1KtAk8XU"),
        ("Vertigo_200110_Oct.pdf",   "1RUZuu3e8GNEAVfkQCYtdKMkGHL1f4CGb"),
        ("Vertigo_200108_Aug.pdf",   "1lmS9sQBtsAYCylYKZ_8hIUdVCqke6F_F"),
        ("Vertigo_200105_May.pdf",   "1m1YmMXdJEPvan8bF6A2jqpNRAFL_sMqF"),
        ("Vertigo_200102_Feb.pdf",   "1zzv1h0Zf9sTXuNRr0_LEx8y8LeYWUhIF"),
    ]

    for fname, fid in files:
        dest = PDF_DIR / fname
        if dest.exists():
            print(f"  Skipping (already downloaded): {fname}")
            continue
        url = f"https://drive.google.com/uc?id={fid}"
        print(f"  Downloading {fname}...")
        try:
            gdown.download(url, str(dest), quiet=True)
        except Exception as e:
            print(f"    FAILED: {e}")


# ---------------------------------------------------------------------------
# PDF text + image extraction
# ---------------------------------------------------------------------------

def extract_pages(pdf_path):
    """Return list of (page_num, text) tuples."""
    doc = fitz.open(str(pdf_path))
    return [(i, page.get_text("text")) for i, page in enumerate(doc)]


def extract_images_by_page(pdf_path):
    """Return dict mapping page_num -> list of saved image Paths."""
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    page_images = {}
    seen = set()
    for page_num, page in enumerate(doc):
        imgs = []
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                base = doc.extract_image(xref)
                data = base["image"]
                if len(data) < 8000:   # skip tiny icons/decorations
                    continue
                ext   = base["ext"]
                fname = OUT_IMAGES / f"{pdf_path.stem}-p{page_num+1}-x{xref}.{ext}"
                fname.write_bytes(data)
                imgs.append(fname)
            except Exception:
                pass
        if imgs:
            page_images[page_num] = imgs
    return page_images


# ---------------------------------------------------------------------------
# Section splitting — two-pass approach
# ---------------------------------------------------------------------------

def split_into_sections(pages):
    """
    Split newsletter text into candidate trip-report sections.

    Pass 1: Identify heading lines.
    Pass 2: Group body lines under each heading.

    Returns list of dicts: {heading, body, page_start, page_end}
    """
    # Flatten lines with page metadata
    tagged_lines = []
    for page_num, text in pages:
        for line in text.splitlines():
            s = line.strip()
            if s:
                tagged_lines.append((page_num, s))

    sections = []
    current = None

    for page_num, line in tagged_lines:
        # Is this line a trip-report heading?
        if _is_heading(line):
            if current and len(" ".join(current["body"])) >= MIN_BODY_CHARS:
                sections.append(current)
            current = {
                "heading":    line,
                "body":       [],
                "page_start": page_num,
                "page_end":   page_num,
            }
        elif current is not None:
            current["body"].append(line)
            current["page_end"] = page_num

    if current and len(" ".join(current["body"])) >= MIN_BODY_CHARS:
        sections.append(current)

    return sections


def _is_heading(line):
    """True if line looks like a trip-report heading."""
    if len(line) < 8 or len(line) > 150:
        return False
    if SKIP_RE.match(line):
        return False
    # Must not be all lowercase
    if line == line.lower():
        return False
    # Must not be mostly numbers (page numbers, dates)
    if re.match(r"^[\d\s\W]+$", line):
        return False
    return bool(TRIP_HEADING_RE.match(line))


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

def parse_section(section, pdf_path, page_images):
    heading = section["heading"]
    lines   = section["body"]

    # Extract author from first line
    author = ""
    body_start = 0
    if lines:
        first = lines[0].strip()
        if re.match(r"^[Bb]y\s+", first):
            author = re.sub(r"^[Bb]y\s+", "", first).strip()
            body_start = 1
        elif re.match(r"^[A-Z][a-z]+(\s+[A-Z][a-z]+){1,2}$", first):
            author = first
            body_start = 1

    # Body text — join into paragraphs (blank line = paragraph break)
    body_lines = lines[body_start:]
    paragraphs = []
    para = []
    for l in body_lines:
        if l.strip():
            para.append(l.strip())
        else:
            if para:
                paragraphs.append(" ".join(para))
                para = []
    if para:
        paragraphs.append(" ".join(para))
    body_md = "\n\n".join(paragraphs)

    # Inline images that belong to this section's page range
    section_imgs = []
    for pg in range(section["page_start"], section["page_end"] + 1):
        section_imgs.extend(page_images.get(pg, []))

    # Append image markdown
    for img in section_imgs:
        body_md += f"\n\n![Trip photo](/images/trips/{img.name})"

    # Date
    date_iso = _parse_date(heading)
    if not date_iso:
        date_iso = _date_from_filename(pdf_path)

    # Newsletter issue from filename
    issue = pdf_path.stem  # e.g. Vertigo_201302_Feb

    return {
        "title":    heading,
        "date":     date_iso,
        "author":   author,
        "body_md":  body_md,
        "source":   f"Vertigo Newsletter — {issue.replace('_', ' ')}",
        "pdf_stem": pdf_path.stem,
    }


def _parse_date(heading):
    m = re.search(
        r"(\d{1,2})[–\-]?(\d{0,2})\s*"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
        r"\s*(\d{4})",
        heading, re.I
    )
    if m:
        day = m.group(2) or m.group(1)
        mon = MONTH_MAP[m.group(3).lower()[:3]]
        yr  = m.group(4)
        try:
            return f"{yr}-{mon}-{int(day):02d}"
        except ValueError:
            return f"{yr}-{mon}-01"
    m = re.search(r"\b(20\d{2}|199\d)\b", heading)
    if m:
        return f"{m.group(1)}-01-01"
    return ""


def _date_from_filename(pdf_path):
    """Extract date from e.g. Vertigo_201302_Feb.pdf -> 2013-02-01"""
    m = re.search(r"(\d{4})(\d{2})", pdf_path.stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-01"
    return ""


# ---------------------------------------------------------------------------
# Hugo markdown output
# ---------------------------------------------------------------------------

def to_hugo_markdown(post):
    def q(s):
        return str(s).replace('"', '\\"')

    lines = ["---"]
    lines.append(f'title: "{q(post["title"])}"')
    if post["date"]:
        lines.append(f'date: {post["date"]}')
    if post["author"]:
        lines.append(f'author: "{q(post["author"])}"')
    lines.append(f'source: "{q(post["source"])}"')
    lines.append("draft: false")
    lines.append("---")
    lines.append("")
    lines.append(post["body_md"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Process one PDF
# ---------------------------------------------------------------------------

def process_pdf(pdf_path):
    print(f"\n[{pdf_path.name}]")
    OUT_CONTENT.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    pages       = extract_pages(pdf_path)
    page_images = extract_images_by_page(pdf_path)
    img_count   = sum(len(v) for v in page_images.values())
    print(f"  {len(pages)} pages, {img_count} images extracted")

    sections = split_into_sections(pages)
    print(f"  {len(sections)} trip-report section(s) found")

    written = 0
    for section in sections:
        post = parse_section(section, pdf_path, page_images)
        print(f"    → {post['title'][:70]}")

        # Build slug: YYYYMM-location
        date_part = (post["date"] or "000000").replace("-", "")[:6]
        loc_slug  = slugify(post["title"])[:45]
        slug      = f"pdf-{date_part}-{loc_slug}"
        out_file  = OUT_CONTENT / f"{slug}.md"

        # Avoid overwriting
        n = 0
        while out_file.exists():
            n += 1
            out_file = OUT_CONTENT / f"{slug}-{n}.md"

        out_file.write_text(to_hugo_markdown(post), encoding="utf-8")
        written += 1

    print(f"  Wrote {written} file(s)")
    return written


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape Vertigo PDF newsletters for trip reports"
    )
    parser.add_argument(
        "--download", action="store_true",
        help="Download PDFs from Google Drive first"
    )
    parser.add_argument(
        "--pdf-dir", default=str(PDF_DIR),
        help=f"Folder of PDFs to process (default: {PDF_DIR})"
    )
    args = parser.parse_args()

    if args.download:
        download_from_gdrive()

    pdf_folder = Path(args.pdf_dir)
    if not pdf_folder.exists():
        print(f"PDF folder not found: {pdf_folder}")
        print("Run with --download first, or pass --pdf-dir to an existing folder.")
        sys.exit(1)

    pdfs = sorted(pdf_folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {pdf_folder}")
        sys.exit(1)

    print(f"Processing {len(pdfs)} PDF(s) from {pdf_folder}")
    total = 0
    for pdf in pdfs:
        try:
            total += process_pdf(pdf)
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\nDone. {total} trip-report files written to {OUT_CONTENT}")


if __name__ == "__main__":
    main()
