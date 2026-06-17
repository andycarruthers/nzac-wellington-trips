#!/usr/bin/env python3
"""Add authors: [...] taxonomy field to any trip report that has author: but lacks authors:"""
import re
from pathlib import Path

TRIPS_DIR = Path(__file__).parent.parent / "content" / "trips"

def process(path):
    text = path.read_text(encoding="utf-8")
    if "authors:" in text:
        return False
    m = re.search(r'^author:\s*"(.+?)"', text, re.MULTILINE)
    if not m:
        return False
    name = m.group(1)
    new_text = text.replace(
        m.group(0),
        m.group(0) + f'\nauthors: ["{name}"]',
        1,
    )
    path.write_text(new_text, encoding="utf-8")
    return True

updated = sum(process(f) for f in sorted(TRIPS_DIR.glob("*.md")))
print(f"Updated {updated} files.")
