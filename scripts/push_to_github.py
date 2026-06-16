#!/usr/bin/env python3
"""
Push generated Hugo content and images to GitHub after scraping.

Uses the GitHub API (no git binary needed).

Usage:
    export GITHUB_TOKEN=ghp_...
    python push_to_github.py
"""

import base64
import os
import sys
import time
from pathlib import Path

import requests

REPO_OWNER = "andycarruthers"
REPO_NAME  = "nzac-wellington-trips"
BRANCH     = "main"
BASE_DIR   = Path(__file__).parent.parent

TOKEN = os.environ.get("GITHUB_TOKEN", "")
if not TOKEN:
    print("Set GITHUB_TOKEN environment variable first.")
    sys.exit(1)

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
})
API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"


def get_sha(path):
    r = SESSION.get(f"{API}/contents/{path}", params={"ref": BRANCH})
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def push_file(local_path, repo_path, message):
    content = base64.b64encode(local_path.read_bytes()).decode()
    sha = get_sha(repo_path)
    payload = {"message": message, "content": content, "branch": BRANCH}
    if sha:
        payload["sha"] = sha
    r = SESSION.put(f"{API}/contents/{repo_path}", json=payload)
    if r.status_code in (200, 201):
        print(f"  Pushed: {repo_path}")
    else:
        print(f"  FAILED {repo_path}: {r.status_code} {r.text[:100]}")
    time.sleep(0.3)  # stay under rate limit


def main():
    dirs_to_push = [
        (BASE_DIR / "content" / "trips", "content/trips"),
        (BASE_DIR / "static" / "images" / "trips", "static/images/trips"),
    ]

    for local_dir, repo_prefix in dirs_to_push:
        files = list(local_dir.glob("*")) if local_dir.exists() else []
        # Skip the two sample posts already in the repo
        skip = {"wharepapa-south-dec-2012.md", "mount-hopeless-jan-2013.md"}
        files = [f for f in files if f.name not in skip and f.is_file()]
        print(f"Pushing {len(files)} files from {local_dir.name}/...")
        for f in sorted(files):
            push_file(f, f"{repo_prefix}/{f.name}", f"Add scraped content: {f.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
