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

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_YEAR = r"(?:19|20)\d{2}"
_DATE_AFTER_DASH = (
    # day-range + month:  "21-22 September"
    r"(?:\d{1,2}[-–]\d{1,2}\s+" + _MONTH + r")"
    r"|(?:\d{1,2}\s+" + _MONTH + r")"              # day + month
    r"|(?:" + _MONTH + r"(?:\s+" + _YEAR + r")?)"  # month (+ optional year)
    r"|(?:" + _YEAR + r"\b)"                        # bare year (1900-2099 only)
)

TRIP_HEADING_RE = re.compile(
    r"""^
    (?:
        # Explicit "Trip Report" or "Trip report" prefix
        [Tt]rip\s+[Rr]eport\b.*
        |
        # "Section trip, Location" or "Section Trip Report" (not bare "Section Trip News")
        [Ss]ection\s+[Tt]rip\s+[Rr]eport\b.*
        |
        [Ss]ection\s+[Tt]rip\s*[,:\–\-—]\s*\S.*
        |
        # Named location + dash + a date (month or year required after dash)
        (?:Mt\.?\s+|Mount\s+|Lake\s+)?
        [A-Z][A-Za-z'\-]{2,}
        (?:\s+[A-Z][A-Za-z'\-]{2,}){0,3}
        \s*[–\-—]\s*
        (?:""" + _DATE_AFTER_DASH + r""")
        .*
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
    # Photo caption prefixes
    r"|Above|Below|Left|Right|Top|Bottom|Inset|Caption|Clockwise"
    r"|Photo\s+by|Photographed"
    r"|Looking\s+(?:up|down|north|south|east|west)"
    r"|Ascending|Descending|Skinning|Approaching\s+(?:the|Mt|Mount|Camp)"
    # Ads, notices, non-trip content
    r"|Wanted|For\s+Sale|Selling|NEW\b|Advance\s+Notice"
    r"|Expedition\s+Fund|Powell\s+Hut|Beautiful\s+World"
    r"|Our\s+[Ww]ebsite|Cheap\s+(?:climbing|flights)"
    r"|And\s+the\s+winner|The\s+winner|Quiz\s+No|The\s+answer\s+to"
    r"|NZAC\s+National|National\s+(?:Instruction|Office)|NZAJ\b"
    r"|Head\s+Office|National\s+office"
    # Film festivals and awards
    r"|(?:The\s+)?Banff\b|Film\s+Festival|Best\s+film|Grand\s+Prize|Peoples\s+Choice"
    r"|Sur\s+le|Parralelo|Proszac"
    # Funding and admin notices
    r"|Distahgil|Distaghil|Expedition\s+Fund|Sar\s+Fund"
    r"|Employment\s+opport|AGM\b|Annual\s+General|Financial\s+Year"
    r"|(?:Wellington\s+)?Section\s+(?:new\s+)?[Gg]ear\s+[Pp]urchase"
    r"|Books?\s+for\s+sale|Old\s+Annual|Discounted\s+Publications"
    r"|Alpine\s+Instruction|(?:AIC\s+20\d\d)|Summer\s+Rock\s+20"
    r"|(?:Multi.?[Pp]itch\s+)?Alpine\s+Rock\s+Course"
    r"|High\s+Alpine\s+Skills\s+Course|Instructor\s+Development"
    r"|Outdoor\s+First\s+Aid|Avalanche\s+Stage"
    r"|Scarpa\s+20\d\d|Travel\s+[Ii]nsurance|Guidebook"
    r"|Photo\s+Competition|Photo\s+competition"
    r"|National\s+Instruction|NZAC\s+Technique"
    # Club notices
    r"|Please\s+send|Thanks?\s+for\s+all|Cheap\s+flights"
    r"|Watch\s+out\s+for|This\s+just\s+off"
    r"|Change\s+in\s+(?:Section|Club)|Section\s+(?:Night|Contacts)"
    r"|News\s+from\s+(?:Head|National|the\s+May)"
    r"|Editor.s\s+note|In\s+other\s+news"
    r"|Note\s+-\s+|NZAC\s+Bulletin|NZAC\s+bulletin"
    r"|Mountaineering\s+Exemptions?|Mountain\s+Safety"
    r"|Workshop\s+for|Don.t\s+miss\s+(?:this|out)"
    r"|Only\s+\d+\s+seats?|Tickets?:\s*\$"
    r"|(?:From\s+)?National\s+Office|Head\s+Office|FROM\s+NATIONAL"
    r"|Ph\s+\d{2}\s+\d{7}|Fax\s+\d{2}"   # phone numbers
    r"|(?:The\s+)?Avalanche\s+Transceiver\s+Trust"
    r"|Junior\s+World\s+Champs|Photo\s+Competition"
    r"|Taranaki\s+Alpine\s+Club\s+\d+th\s+Jubilee"
    r"|Carriage\s+of\s+Stoves|Bevan\s+Col\s+air\s+access"
    r"|Memorial\s+[Pp]laques?|Titahi\s+Bay\s+Rebolting"
    r"|And\s+[Hh]ere\s+[Aa]re\s+the\s+[Cc]lub|Club\s+[Tt]rips?"
    r"|Southern\s+Hemisphere\s+Alpine\s+Conference"
    r"|[Ss]ection\s+[Nn]ight|April\s+Section\s+Night"
    r"|Interested\s+in\s+[Ii]nstruct|Do\s+something\s+with"
    r"|Other\s+Section\s+Member|Pete.s\s+[Pp]ost"
    r"|The\s+legend\s+that|Lost\s+mountaineers"
    r"|Deny\s+the\s+effects|Vertigo\s+[Gg]oes\s+[Ii]nternational"
    r"|And\s+more\s+from\s+[Mm]ike|And\s+the\s+last\s+word"
    r"|Caro\s+and\s+Matt\s+are|He.s\s+turning\s+into"
    r")",
    re.I,
)

# Minimum body length (chars) for a section to be worth keeping
MIN_BODY_CHARS = 300

# Newsletter section headers that mark the END of trip-report content.
# When one of these lines is encountered, close the current section.
SECTION_BREAK_RE = re.compile(
    r"^(?:"
    r"UPCOMING|NOTICES?|CLASSIFIEDS?|COMING\s+TRIPS?"
    r"|CLUB\s+CONTACTS?|SECTION\s+CONTACTS?"
    r"|ADVERTISEM|FOR\s+SALE|GEAR\s+FOR\s+SALE"
    r"|SPONSORS?|MEMBER\s+DISCOUNTS?"
    r"|POSITION\s+NAME"   # start of contacts table
    r")\b",
    re.I,
)


# Full-title junk filter — applied after extraction to catch patterns that
# can't be caught by a prefix-only regex (e.g. "IT'S FINALLY COMING! JOE SIMPSON'S…")
_TITLE_JUNK_RE = re.compile(
    r"banff\b|film\s+festival|film\s+coming|climbing\s+film"
    r"|photo\s+comp|photo\s+competition"
    r"|touching\s+the\s+void|joe\s+simpson"
    r"|distahgil|distaghil"
    r"|financial\s+year|annual\s+general|\bagm\b"
    r"|travel\s+insurance|over\s+70.s"
    r"|books?\s+for\s+sale|discounted\s+pub|national\s+office"
    r"|mountaineer\s+of\s+the\s+year\s+award"
    r"|section\s+general\s+news"
    r"|big\s+thanks|thankyou\s+from|thank\s+you\s+from"
    r"|peoples\s+choice\s+award|grand\s+prize\s+winner"
    r"|mont\s+blanc\s+centre\s+for|wellington\s+waterfront"
    r"|show\s+your\s+members\s+card|members\s+card\s+and\s+climb"
    r"|paramount\s+theatre"
    r"|guidebook\s+price\s+review|non\s+nzac\s+guidebook"
    r"|rock.climbing\s+grading\s+for\s+dummies"
    r"|mountaineering\s+exemptions"
    r"|arthurs\s+pass\s+celebrations"
    r"|just\s+prior\s+to.*xmas|prior\s+to.*xmas",
    re.I,
)

# Mid-sentence artifact titles: start with article/preposition then sentence fragment
_TITLE_MIDSENT_RE = re.compile(
    r"""^(?:
        # starts with "Still," / "Kuiti and" / "Monday Wall" type fragments
        Still\s*,
        |Kuiti\s+and\b
        |Monday\s+Wall\b
        |Cozette\s+Burn\b
        |October.November\s+had\b
        |Nelson.Marlborough\s+section\s+also\b
        |Hokkaido:\s+Late
        # Just a name or phone-number line
        |^[\w\s\.]+,\s+[\w\s\.]+\.$   # "Woodhead, Mark Yeo and Trey Guinn."
        |^Ph\s+\d
        |^\d{2}\s+\d{4}
    )""",
    re.VERBOSE | re.I,
)


def _is_junk_title(title):
    """Return True if the title is clearly not a trip report."""
    t = title.strip()
    # Contains $ signs (prices) or phone numbers
    if re.search(r"\$\d|\bPh\s+\d{2}", t):
        return True
    # Full title junk patterns
    if _TITLE_JUNK_RE.search(t):
        return True
    # Mid-sentence fragments (truncated at end)
    if re.search(r"\s+(?:and|the|in the|was|were|of|to|at|on|from|with|for|don.t|doesn.t|also|about|us at)$", t, re.I):
        return True
    # Title is a sentence that starts with "Still," or similar continuation words
    if re.match(r"^(?:Still\s*,|Kuiti\s+and\b|Monday\s+Wall\b|Cozette\s+Burn\b)", t, re.I):
        return True
    # "Word. In ..." or "Word: In ..." — single-word header followed by sentence (PDF artefact)
    if re.match(r"^[A-Z][a-z]+[.:]\s+(?:In|At|On|The|Late|Early|During)\s+[A-Z]", t):
        return True
    # "Name - I learnt..." or "Name - My two days..." (attribution line, not heading)
    if re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+ -\s+(?:I |My |We )", t):
        return True
    # "havin a well earned brew" type captions (past participle phrase)
    if re.search(r"\bhavin\b|\bhaving\s+a\s+well\s+earned\b", t, re.I):
        return True
    # Course / competition / admin titles that slip through
    if re.search(r"\bTechnique\s+Course\b|\bJunior\s+World\s+Champs\b", t, re.I):
        return True
    # Just a person's name — firstname must be a recognisable first name
    _FIRST_NAMES = r"Andrew|Caroline|Peter|Mike|Scott|Mark|Sarah|Kate|James|John|David|Paul|Kevin|Chris|Tom|Sam|Nick|Rob|Tim|Alan|Don|Dave|Jenny|Nicky|Matt|Simon|Brad|Craig|Ian|Grant|Murray|Steve|Richard|Brian|Tony|Lisa|Rachel|Anna|Emma|Karen|Helen|Amy"
    if re.match(r"^(?:" + _FIRST_NAMES + r")\s+[A-Z][a-zA-Z']+\.?$", t):
        return True
    # "Name (attribution note)" — e.g. "Caroline Duggan (All quotes verbatim from the group)"
    if re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+ \(", t):
        return True
    # Multiple names on one line (e.g. "Woodhead, Mark Yeo and Trey Guinn.")
    if re.match(r"^[A-Z][a-z]+,\s+[A-Z][a-z]", t) and re.search(r"\band\s+[A-Z][a-z]+\b", t):
        return True
    # "Firstname Lastname/Firstname Lastname" — two names with slash
    if re.match(r"^[A-Z][a-zA-Z']+ [A-Z][a-zA-Z']+/[A-Z][a-zA-Z']+ [A-Z][a-zA-Z']+$", t):
        return True
    return False


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


# Matches the "Section trips news" header that starts the trip-report block
TRIPS_SECTION_RE = re.compile(
    r"Section\s+trips?\s+news|Trip\s+reports?\s*(?:section|news)|Trips\s+section"
    r"|Section\s+trip\s+reports?",
    re.I,
)

# Major section headers that end the trip-report block
MAJOR_SECTION_RE = re.compile(
    r"^(?:Coming\s+trips?|Upcoming\s+trips?|Notices?|Club\s+night|Section\s+night"
    r"|Instruction|Courses?|Equipment|Gear|Advertisem|Sponsors?|Contacts?"
    r"|For\s+Sale|CLASSIFIEDS?|Members?\s+area|Events?"
    # Older newsletter section headers
    r"|Wellington\s+Section\s+Trips?"   # upcoming trips table
    r"|Other\s+Trips?"                  # "Other Trips" catch-all in coming trips
    r"|Chairperson|Chair(?:persons?)?\s+(?:Quiz|Report)"
    r"|Contributions\s+please|MOVED\s+HOUSE|HANGDOG"
    r"|Comp\s+results?|Competition\s+results?"
    r")\b",
    re.I,
)


# ---------------------------------------------------------------------------
# PDF text + image extraction (font-aware)
# ---------------------------------------------------------------------------

def extract_blocks_with_fonts(pdf_path):
    """
    Return list of {text, is_bold, font_size, page} for every non-empty line.
    Uses get_text("dict") to preserve font metadata.
    """
    doc = fitz.open(str(pdf_path))
    blocks = []
    for page_num, page in enumerate(doc):
        page_dict = page.get_text("dict")
        for blk in page_dict.get("blocks", []):
            if blk.get("type") != 0:   # type 0 = text
                continue
            for line in blk.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                # Bold: flag bit 4 (16) set in any span
                is_bold = any(s.get("flags", 0) & 16 for s in spans)
                font_size = max((s.get("size", 0) for s in spans), default=0)
                blocks.append({
                    "text":      text,
                    "is_bold":   is_bold,
                    "font_size": round(font_size, 1),
                    "page":      page_num,
                })
    return blocks


def _body_font_size(blocks):
    """Modal (most common) font size across all blocks — the body text size."""
    from collections import Counter
    sizes = [b["font_size"] for b in blocks if b["font_size"] > 4]
    if not sizes:
        return 10.0
    return Counter(sizes).most_common(1)[0][0]


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
# Section splitting — font-aware approach
# ---------------------------------------------------------------------------

def split_into_sections(blocks):
    """
    Split newsletter text into trip-report sections using font metadata.

    Strategy:
    1. Find the "Section trips news" header (marks start of trip-report block).
    2. Within that block, treat bold/large-font lines as individual trip headings.
    3. Stop at the next major section header (Coming trips, Notices, etc.).

    Falls back to the regex-based "Trip Report – Location" approach for PDFs
    that don't contain a trips-section header at all.

    Returns list of dicts: {heading, body, page_start, page_end}
    """
    body_size = _body_font_size(blocks)
    heading_threshold = body_size * 1.05   # slightly larger or bold = heading

    # ---- Pass 1: font-aware approach ----------------------------------------
    sections = _split_font_aware(blocks, body_size, heading_threshold)
    if sections:
        return sections

    # ---- Pass 2: fallback — regex on plain text (older PDFs / bad fonts) ----
    return _split_regex_fallback(blocks)


def _split_font_aware(blocks, body_size, heading_threshold):
    """Extract trips from inside the 'Section trips news' block."""
    # Find start of trips section
    trips_start = None
    for i, blk in enumerate(blocks):
        if TRIPS_SECTION_RE.search(blk["text"]):
            trips_start = i + 1
            break
    if trips_start is None:
        return []

    sections = []
    current = None

    for blk in blocks[trips_start:]:
        text = blk["text"]

        # Skip page-number artifacts
        if re.match(r"^(?:Page\s+)?\d+\s*$", text):
            continue

        # End of trips block: next major section header
        if MAJOR_SECTION_RE.match(text) and (blk["is_bold"] or blk["font_size"] >= heading_threshold):
            break

        # Is this line a trip heading? (bold, or larger than body text)
        is_subheading = (
            (blk["is_bold"] or blk["font_size"] >= heading_threshold)
            and 15 <= len(text) <= 160            # filter short labels like "Details"
            and text[0].isupper()                 # must start with capital
            and not re.match(r"^[\d\s\W]+$", text)
            # Filter mid-sentence bold text (personal pronoun / mid-narrative start)
            and not re.match(r"^(?:I |We |My |He |She |It |They |Our |His |Her |Their )", text)
            and not SKIP_RE.match(text)
            and not SECTION_BREAK_RE.match(text)
            and not MAJOR_SECTION_RE.match(text)
        )

        if is_subheading:
            if current and len(" ".join(current["body"])) >= MIN_BODY_CHARS:
                sections.append(current)
            current = {
                "heading":    text,
                "body":       [],
                "page_start": blk["page"],
                "page_end":   blk["page"],
            }
        elif current is not None:
            current["body"].append(text)
            current["page_end"] = blk["page"]

    if current and len(" ".join(current["body"])) >= MIN_BODY_CHARS:
        sections.append(current)

    return sections


def _split_regex_fallback(blocks):
    """
    Fallback for PDFs without a 'Section trips news' header.
    Uses the explicit-prefix and 'Location – Date' regex patterns.
    """
    sections = []
    current = None

    for blk in blocks:
        text = blk["text"]

        if re.match(r"^(?:Page\s+)?\d+\s*$", text):
            continue

        if current is not None and SECTION_BREAK_RE.match(text):
            if len(" ".join(current["body"])) >= MIN_BODY_CHARS:
                sections.append(current)
            current = None
            continue

        if _is_heading_regex(text):
            if current and len(" ".join(current["body"])) >= MIN_BODY_CHARS:
                sections.append(current)
            current = {
                "heading":    text,
                "body":       [],
                "page_start": blk["page"],
                "page_end":   blk["page"],
            }
        elif current is not None:
            current["body"].append(text)
            current["page_end"] = blk["page"]

    if current and len(" ".join(current["body"])) >= MIN_BODY_CHARS:
        sections.append(current)

    return sections


def _is_heading_regex(line):
    """True if line matches the explicit trip-report heading patterns."""
    if len(line) < 8 or len(line) > 150:
        return False
    if SKIP_RE.match(line):
        return False
    if line == line.lower():
        return False
    if re.match(r"^[\d\s\W]+$", line):
        return False
    return bool(TRIP_HEADING_RE.match(line))


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Location and tag detection
# ---------------------------------------------------------------------------

# Maps keyword patterns to canonical location name (first match wins)
_LOCATION_RULES = [
    # Overseas
    (r"\bHimalaya|Karakoram|Nepal|Tibet|Pakistan|India|Bhutan\b", "Himalaya"),
    (r"\bKangchenjunga|Manaslu|Annapurna|Everest|Dhaulagiri\b", "Himalaya"),
    (r"\bChamonix|Mont\s+Blanc|Alps\b|Aiguille|France\b", "European Alps"),
    (r"\bBugaboo|Selkirk|Rockies|Canada\b|Alberta\b", "Canada"),
    (r"\bYosemite|Sierra|California\b|Tahoe\b", "USA"),
    (r"\bKrabi|Thailand|Asia\b", "Asia"),
    (r"\bCordillera\s+Blanca|Peru\b|Bolivia|Andes\b", "South America"),
    (r"\bArapiles|Grampians|Australia\b|Moonarie|Buffalo\b", "Australia"),
    (r"\bMachu\s+Picchu|Mexico|Hokkaido|Japan\b", "Overseas"),
    # South Island
    (r"\bFiordland|Darran|Milford|Marian|Christina|Talbot|Sabre\b", "Fiordland"),
    (r"\bMt\.?\s+Cook|Aoraki|Tasman\s+Glacier|Hochstetter|Haast|Lendenfeld\b", "Mount Cook"),
    (r"\bMount\s+Cook|Mueller|Hooker|Grand\s+Plateau|Ball\s+Pass\b", "Mount Cook"),
    (r"\bArrowsmith|Castle\s+Hill|Arthur.s\s+Pass|Franklin|Phills\b", "Canterbury"),
    (r"\bGirdlestone|Taranaki|Egmont\b", "Taranaki"),
    (r"\bNelson\s+Lakes|Hopeless|Murchison|D.Urville|St\.\s+Arnaud\b", "Nelson Lakes"),
    (r"\bAspiring|Matukituki|Rob\s+Roy|Waipara|Bonar\b", "Mount Aspiring"),
    (r"\bArrowsmiths\b", "Canterbury"),
    (r"\bWanaka|Queenstown|Remarkables\b", "Queenstown / Wanaka"),
    (r"\bColin\s+Todd|Murchison\s+Glacier|Tukino\b", "Mount Cook"),
    (r"\bGarden\s+of\s+Eden|Cross\s+Ball\s+Pass|Browning|Lewis\b", "Canterbury"),
    (r"\bKaikoura|Tapuae|Pollux|Betsy|Awful|Crucible\b", "Kaikoura / Inland Kaikōura"),
    (r"\bDouglas|Sefton|Copland\b", "Westland"),
    (r"\bPinnacles|Coromandel\b", "Coromandel"),
    # North Island
    (r"\bRuapehu|Tukino|Tahurangi|Girdlestone\b", "Ruapehu"),
    (r"\bTararua|Mitre\s+Peak\b", "Tararua"),
    (r"\bWharepapa|Waikato\b", "Waikato"),
    (r"\bWhanganui\s+Bay|Kawakawa\b", "Lake Taupo"),
    (r"\bTitahi\s+Bay|Wellington\b", "Wellington"),
    (r"\bPayne.s\s+Ford|Golden\s+Bay\b", "Golden Bay"),
    (r"\bParetetaitonga|Cathedral\s+Rocks|Dome\b", "Ruapehu"),
    (r"\bEden|Hamilton\s+the\s+mountain\b", "Auckland"),
    # Generic overseas check (Europe, Middle East etc.)
    (r"\bMiddle\s+East|Israel|Jordan|Turkey|Egypt\b", "Middle East"),
    (r"\bScotland|UK\b|England\b", "UK"),
    (r"\bAntarctica\b", "Antarctica"),
    # Wellington local
    (r"\bBaring\s+Head|Red\s+Rocks|Makara\b", "Wellington"),
    (r"\bGarden\s+of\s+Eden|Browning\s+Pass\b", "Canterbury"),
]

# Activity tags inferred from keywords in title+body
_TAG_RULES = [
    (r"\bski\s+tour(?:ing)?|ski\s+mountain|skinning|backcountry\s+ski|telemark\b", "Ski Touring"),
    (r"\bice\s+climb|crampon|neve|crevasse|glacier\s+travel|seracs?\b", "Alpine"),
    (r"\balpine|mountaineer(?:ing)?|bivouac|high\s+camp|base\s+camp\b", "Alpine"),
    (r"\brock\s+climb|crag|trad\s+climb|sport\s+climb|bouldering|top\s+rope|lead\s+climb\b", "Rock Climbing"),
    (r"\brock\s+hop|Arapiles|Wharepapa|Paynes?\s+Ford|Kawakawa\b", "Rock Climbing"),
    (r"\btramping|hut\s+bag|bush\s+bash\b", "Tramping"),
    (r"\bski\s+field|ski\s+hill|piste\b", "Ski"),
]


def _infer_location(text):
    """Return a canonical location string or empty string."""
    for pattern, location in _LOCATION_RULES:
        if re.search(pattern, text, re.I):
            return location
    return ""


def _infer_tags(text):
    """Return list of activity tag strings."""
    seen = set()
    tags = []
    for pattern, tag in _TAG_RULES:
        if tag not in seen and re.search(pattern, text, re.I):
            tags.append(tag)
            seen.add(tag)
    return tags


def _extract_author(heading, lines):
    """Try to find an author name from heading or body lines."""
    # "Words by Kathleen Logan" or "By Kevin Patterson" at start of body
    if lines:
        first = lines[0].strip()
        m = re.match(r"^(?:[Ww]ords?\s+by|[Bb]y)\s+([A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+){1,2})", first)
        if m:
            return m.group(1), 1
        # "From Kevin Patterson:" as the first line
        m = re.match(r"^[Ff]rom\s+([A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+){1,2})\s*[:,]", first)
        if m:
            return m.group(1), 0   # keep the line, just extract the name

    # Look for "Words by X" or "X and Y" near end of body (last 3 lines)
    for line in reversed(lines[-3:] if len(lines) >= 3 else lines):
        m = re.search(r"[Ww]ords?\s+by\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,2})", line)
        if m:
            return m.group(1), 0
        # Standalone "Firstname Lastname" at end
        m = re.match(r"^\s*([A-Z][a-z]+\s+[A-Z][a-z]+)\s*$", line)
        if m and len(m.group(1).split()) == 2:
            return m.group(1), 0

    # "Heading – date (Author)" or "by Author" in heading itself
    m = re.search(r"[Bb]y\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,2})", heading)
    if m:
        return m.group(1), 0

    return "", 0


def parse_section(section, pdf_path, page_images):
    heading = section["heading"]
    lines   = section["body"]

    # Extract author
    author, body_start = _extract_author(heading, lines)

    # Fallback: old first-line check
    if not author and lines:
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
    # Cap the body: newsletters run on forever after the trip content
    MAX_BODY_CHARS = 6000
    body_md = "\n\n".join(paragraphs)
    # Rejoin PDF print-layout soft hyphens: "how- ever" -> "however"
    body_md = re.sub(r"(\w)- (\w)", r"\1\2", body_md)
    if len(body_md) > MAX_BODY_CHARS:
        # Truncate at the last paragraph boundary before the cap
        body_md = body_md[:MAX_BODY_CHARS].rsplit("\n\n", 1)[0]

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

    # Location and tags — infer from heading + full body text
    full_text = heading + " " + body_md
    location = _infer_location(full_text)
    tags = _infer_tags(full_text)
    if not tags:
        tags = ["Alpine"]  # default for mountaineering newsletters

    # Newsletter issue from filename
    issue = pdf_path.stem  # e.g. Vertigo_201302_Feb

    return {
        "title":    heading,
        "date":     date_iso,
        "author":   author,
        "location": location,
        "tags":     tags,
        "body_md":  body_md,
        "source":   f"Vertigo Newsletter — {issue.replace('_', ' ')}",
        "pdf_stem": pdf_path.stem,
    }


def _parse_date(heading):
    # "12-15 November 2011" or "12 November 2011"
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
    # "November 2011" — month name + year, no leading day
    m = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
        r"\s+((?:19|20)\d{2})\b",
        heading, re.I
    )
    if m:
        mon = MONTH_MAP[m.group(1).lower()[:3]]
        return f"{m.group(2)}-{mon}-01"
    # bare year
    m = re.search(r"\b((?:19|20)\d{2})\b", heading)
    if m:
        return f"{m.group(1)}-01-01"
    return ""


def _date_from_filename(pdf_path):
    """Extract date from e.g. 'NZAC Vertigo 2019_06' or 'Vertigo_201302_Feb'"""
    # Format: 4-digit year followed by optional separator then 2-digit month
    m = re.search(r"(\d{4})[_\s](\d{2})\b", pdf_path.stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-01"
    # Fallback: year + month concatenated e.g. 201302
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
    if post.get("author"):
        lines.append(f'author: "{q(post["author"])}"')
    if post.get("location"):
        lines.append(f'location: "{q(post["location"])}"')
        lines.append(f'locations: ["{q(post["location"])}"]')
    if post.get("tags"):
        tag_list = ", ".join(f'"{t}"' for t in post["tags"])
        lines.append(f'tags: [{tag_list}]')
    lines.append(f'source: "{q(post["source"])}"')
    lines.append("draft: false")
    lines.append("---")
    lines.append("")
    lines.append(post["body_md"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Process one PDF
# ---------------------------------------------------------------------------

def process_pdf(pdf_path, seen_headings=None):
    if seen_headings is None:
        seen_headings = set()

    print(f"\n[{pdf_path.name}]")
    OUT_CONTENT.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    blocks      = extract_blocks_with_fonts(pdf_path)
    page_images = extract_images_by_page(pdf_path)
    img_count   = sum(len(v) for v in page_images.values())
    n_pages     = 1 + max((b["page"] for b in blocks), default=0)
    print(f"  {n_pages} pages, {img_count} images extracted, {len(blocks)} text blocks")

    sections = split_into_sections(blocks)
    print(f"  {len(sections)} trip-report section(s) found")

    written = 0
    for section in sections:
        post = parse_section(section, pdf_path, page_images)

        # Post-extraction junk filter
        if _is_junk_title(post["title"]):
            print(f"    -> [SKIP junk] {post['title'][:70]}")
            continue

        # Deduplicate: skip if we've seen the same heading from an earlier newsletter
        heading_key = re.sub(r"\s+", " ", post["title"].lower().strip())
        if heading_key in seen_headings:
            print(f"    -> [SKIP duplicate] {post['title'][:70]}")
            continue
        seen_headings.add(heading_key)

        print(f"    -> {post['title'][:70]}")

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
    seen_headings = set()
    for pdf in pdfs:
        try:
            total += process_pdf(pdf, seen_headings)
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\nDone. {total} trip-report files written to {OUT_CONTENT}")


if __name__ == "__main__":
    main()
