# Scraping Scripts

Three scrapers to populate the Hugo site with historical trip reports.

## Setup

```bash
cd scripts
pip install -r requirements.txt
pip install pymupdf   # for PDF scraper only
```

---

## 1. Wayback Machine scraper

Scrapes trip reports from the archived NZAC Wellington website.

```bash
python scrape_wayback.py
```

This will:
- Query the Wayback CDX API to find all trip-report post URLs
- Fetch each post, extract title / date / author / body text / images
- Save markdown files to `content/trips/wayback-*.md`
- Download images to `static/images/trips/`

Expect ~2-3 minutes runtime due to polite rate limiting.

---

## 2. Mailchimp newsletter scraper

Extracts trip-report sections from Mailchimp campaign archives.

**Step 1** — Export the URL column from your Google Sheet as `scripts/newsletter_urls.txt`  
(one URL per line, e.g. `http://eepurl.com/hq9F2n`)

```bash
python scrape_mailchimp.py newsletter_urls.txt
```

This will:
- Follow each eepurl.com redirect to the hosted Mailchimp page
- Identify trip-report sections by heading keywords
- Extract text and images for each section
- Save markdown files to `content/trips/mailchimp-*.md`

---

## 3. PDF newsletter scraper

Processes PDF files from your Google Drive download.

**Step 1** — Download the PDFs from Google Drive to a local folder, e.g. `~/Downloads/vertigo/`

```bash
python scrape_pdfs.py ~/Downloads/vertigo/
```

Or a single file:
```bash
python scrape_pdfs.py ~/Downloads/Vertigo_201302_Feb.pdf
```

This will:
- Extract embedded images from each PDF
- Split the text into trip-report sections by heading pattern
- Save markdown files to `content/trips/pdf-*.md`
- Save images to `static/images/trips/`

PDF text extraction is ~90% clean — expect some manual tidying for garbled characters or broken paragraph flow.

---

## 4. Push to GitHub

After running the scrapers, push generated content to GitHub:

```bash
export GITHUB_TOKEN=ghp_your_token_here
python push_to_github.py
```

Netlify will auto-deploy within ~30 seconds of each push.

---

## Expected file counts

| Source | Estimate |
|--------|----------|
| Wayback Machine posts | 30–80 posts |
| Mailchimp newsletters (5 years) | 20–50 trip sections |
| PDF newsletters (20 years, ~240 issues) | 300–600 trip sections |
| **Total** | **~400–700 trip reports** |
