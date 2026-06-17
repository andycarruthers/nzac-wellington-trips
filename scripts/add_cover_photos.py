#!/usr/bin/env python3
"""
For every trip report that lacks a 'cover' frontmatter field,
find the first image in the body and set it as cover.
"""
import re
import sys
from pathlib import Path

TRIPS_DIR = Path(__file__).parent.parent / "content" / "trips"

IMAGE_RE = re.compile(r'!\[.*?\]\((/images/trips/[^\)]+)\)')

def process_file(path):
    text = path.read_text(encoding="utf-8")

    # Skip if already has cover
    if re.search(r'^cover:', text, re.MULTILINE):
        return False

    # Find first image in body (after the closing ---)
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    frontmatter, body = parts[1], parts[2]

    m = IMAGE_RE.search(body)
    if not m:
        return False

    cover_path = m.group(1)

    # Insert cover field after the title line in frontmatter
    new_fm = re.sub(
        r'(^title:.*$)',
        r'\1\ncover: "' + cover_path + '"',
        frontmatter,
        count=1,
        flags=re.MULTILINE,
    )

    path.write_text("---" + new_fm + "---" + body, encoding="utf-8")
    return True

def main():
    files = sorted(TRIPS_DIR.glob("*.md"))
    updated = 0
    skipped_no_image = 0
    for f in files:
        result = process_file(f)
        if result:
            updated += 1
            print(f"  cover set: {f.name}")
        else:
            skipped_no_image += 1
    print(f"\nDone. {updated} files updated, {skipped_no_image} skipped (already have cover or no image).")

if __name__ == "__main__":
    main()
