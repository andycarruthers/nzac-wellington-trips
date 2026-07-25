# Trip Reports Site — Committee Guide

This is the reference doc for how [trip-reports.wellingtonalpineclub.org.nz](https://trip-reports.wellingtonalpineclub.org.nz) was built, and how committee members can access, edit, and maintain it going forward. A more polished, readable version of this guide is also available as a shared web page (ask Andy for the link).

## 1. What this is

An archive blog of Wellington Section trip reports, spanning ~20 years of newsletters (scanned PDFs), five years of Mailchimp email newsletters, and new reports submitted directly through the site. It's a static site — there's no database or server to maintain, which keeps it cheap (free tier) and low-maintenance.

## 2. How it's built — the pieces

| Piece | What it does | Where it lives |
|---|---|---|
| **Hugo** | Generates the actual HTML pages from Markdown files + templates | Code in the GitHub repo |
| **GitHub** | Stores all the source content and code; every change is a commit | `github.com/andycarruthers/nzac-wellington-trips` |
| **Netlify** | Hosts the site; rebuilds and redeploys automatically every time something changes on GitHub | Netlify dashboard |
| **Decap CMS** | A simple editing interface at `/admin` so non-developers can add/edit trip reports without touching code | `/admin` on the live site |
| **Netlify Identity** | Controls who can log into `/admin` | Netlify dashboard → Identity |
| **Google Analytics (GA4)** | Tracks site visitors | `analytics.google.com`, property ID `G-WYTLFR0ZXC` |

Every trip report is a single Markdown file in `content/trips/`. It has two parts:
- **Front matter** — the metadata block at the top (title, date, author, location, tags, cover photo, draft status)
- **Body** — the actual trip report text and photos, written in Markdown

## 3. Two ways to add or edit a trip report

### Option A — The public submission form (for members)

Members can go to **/submit** on the site and fill in a form (name, email, trip title, date, location, participants, trip type, report text, up to 5 photos). When they hit submit, it:

1. Compresses their photos in the browser
2. Commits the photos and a new Markdown file straight to the GitHub repo, marked `draft: true`
3. Also fires a submission to Netlify's built-in Forms system, which triggers an email notification (configured in Netlify dashboard → **Forms → Form notifications**)

The report does **not** go live automatically — it sits as a draft until a committee member reviews and publishes it (see §4).

### Option B — The admin editor (for committee members)

Go to **trip-reports.wellingtonalpineclub.org.nz/admin**. This is a proper visual editor (Decap CMS) — no Markdown or code needed. You can:

- See every trip report in one list, with filters/sorting for **draft vs published** (drafts sort to the top by default)
- Create a new report from scratch with a form (same fields as above)
- Edit an existing report's text, photos, tags, or metadata
- Toggle the **Draft** checkbox to publish/unpublish

**Getting access:** log-in for `/admin` is controlled by Netlify Identity, not a separate password system. To give a committee member access:
1. Go to the Netlify dashboard → the site → **Identity**
2. Click **Invite users**, enter their email
3. They'll get an email invite to set a password, then can log into `/admin` from then on

## 4. Publishing a draft

Whether a report came in through the submission form or was started in `/admin`, it stays hidden from the public site as long as `draft: true` is set in its front matter. To publish:

1. Open `/admin`, find the report (drafts are sorted to the top)
2. Read it over, fix anything that needs fixing (typos, formatting, missing photo captions)
3. Untick the **Draft** checkbox
4. Save/publish — Netlify will rebuild the site automatically (takes 1–2 minutes)

## 5. Photos

- Photos live in `static/images/trips/`
- The **first photo** listed in a report typically becomes its **cover image** (shown on the homepage/trip listing cards) — set via the `cover:` field in the front matter
- The admin editor has an image picker/uploader built in — no need to touch files directly
- Recommended: keep photos under ~2MB each; the submission form auto-compresses to a reasonable size, but photos added via `/admin` are not compressed automatically

## 6. Analytics

Site traffic is tracked with Google Analytics (GA4), property ID `G-WYTLFR0ZXC`. To check traffic:
1. Go to `analytics.google.com`
2. Select the NZAC Wellington property
3. **Reports → Realtime** shows current visitors; **Reports → Engagement → Pages and screens** shows what's being read most

## 7. Domain & email

- The site is served at **trip-reports.wellingtonalpineclub.org.nz**, a subdomain pointed at Netlify via a DNS CNAME record
- SSL (the padlock/HTTPS) is provisioned automatically by Netlify via Let's Encrypt — no action needed unless the domain changes
- Form submission notification emails are configured in Netlify dashboard → **Forms → Form notifications** — add/change the recipient email there

## 8. SEO basics (already set up)

- `robots.txt` and `sitemap.xml` are auto-generated by Hugo on every build
- Every page has proper title tags, meta descriptions, canonical URLs, and Open Graph tags (for nice previews when shared on social media/Slack)
- A favicon (browser tab icon) is set, using the NZAC logo mark on a navy background so it's visible in search results and browser tabs

## 9. Making bigger changes (design, layout, new features)

Anything beyond adding/editing a trip report — changing the site's look, adding new page types, fixing bugs — requires editing the Hugo templates and CSS in the GitHub repo directly. This isn't something the `/admin` editor can do. If the committee doesn't have someone comfortable with this, the easiest path is asking whoever set this up (or a developer/Claude Code session) to make the change, test it, and push it — Netlify redeploys automatically once it's pushed to the `main` branch on GitHub.

## 10. Troubleshooting

| Problem | Likely cause / fix |
|---|---|
| Site not updating after an edit | Check Netlify dashboard → **Deploys** tab for a build in progress or a failed build (red X) |
| Can't log into `/admin` | Confirm you've been invited via Netlify Identity (§3); check spam folder for the invite email |
| Form submissions but no email | Check Netlify dashboard → **Forms → Form notifications** has a recipient configured |
| New trip report not showing on homepage | It's probably still `draft: true` — publish it via `/admin` (§4) |
| Broken image on a report | The image file may be missing from `static/images/trips/` — re-upload via `/admin`'s image picker |

## Glossary

- **Front matter** — the `---`-delimited metadata block at the top of a Markdown file (title, date, tags, etc.)
- **Markdown** — a simple plain-text formatting syntax (e.g. `**bold**`, `# Heading`) that converts to HTML
- **Static site** — a site built as plain HTML files ahead of time, rather than generated per-request by a server/database. Faster, cheaper, and simpler to maintain.
- **Repo (repository)** — the GitHub project containing all the site's code and content
- **Deploy** — the process of Netlify rebuilding and publishing the site after a change
- **CNAME** — a type of DNS record that points a subdomain at another host (here, Netlify)
