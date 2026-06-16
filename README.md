# NZAC Wellington — Trip Reports

Archive blog for the Wellington Section of the New Zealand Alpine Club, built with [Hugo](https://gohugo.io) and deployed via Netlify.

## Adding a trip report

Create a new file in `content/trips/` using this front matter:

```yaml
---
title: "Trip title"
date: YYYY-MM-DD
author: "Author Name"
participants:
  - "Person One"
  - "Person Two"
location: "Specific location"
region: "Region name"  # used for grouping
tags:
  - "rock climbing"
cover: "/images/trips/filename.jpg"  # optional
source: "Vertigo Newsletter No. XXX"  # provenance
draft: false
---

Trip report text in Markdown...
```

Images go in `static/images/trips/`.

## Data sources

- **Wayback Machine**: `https://web.archive.org/web/20130505172652/http://www.nzalpine.wellington.net.nz/category/trip-reports/`
- **PDF newsletters**: Google Drive archive of Vertigo newsletter (~20 years)
- **Mailchimp archives**: Last 5 years of email newsletters (see Google Sheet for URLs)

## Local development

```bash
brew install hugo
hugo server
```
