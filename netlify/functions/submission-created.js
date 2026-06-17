// Triggered automatically by Netlify when a form submission comes in.
// Creates a draft markdown file in content/trips/ via the GitHub API.

exports.handler = async function (event) {
  const body = JSON.parse(event.body);

  // Only handle the trip-report form
  if (body.payload?.form_name !== "trip-report") {
    return { statusCode: 200, body: "Not a trip report submission" };
  }

  const data = body.payload.data;

  const title = data.title || "Untitled Trip";
  const date = data.date || new Date().toISOString().split("T")[0];
  const author = data.name || "";
  const location = data.location || "";
  const participants = data.participants || "";
  const tags = Array.isArray(data.tags) ? data.tags : data.tags ? [data.tags] : [];
  const report = data.report || "";

  // Build slug from date + title
  const slug = `${date}-${title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}`;

  const filename = `content/trips/${slug}.md`;

  // Build frontmatter
  const tagsList = tags.length ? `\ntags: [${tags.map((t) => `"${t}"`).join(", ")}]` : "";
  const locationsList = location ? `\nlocations: ["${location}"]` : "";
  const participantsList = participants ? `\nparticipants: ["${participants.split(",").map((p) => p.trim()).join('", "')}"]` : "";

  const content = `---
title: "${title.replace(/"/g, '\\"')}"
date: ${date}
author: "${author}"
authors: ["${author}"]
location: "${location}"${locationsList}${tagsList}${participantsList}
draft: true
---

${report}
`;

  // Base64 encode the file content
  const contentEncoded = Buffer.from(content).toString("base64");

  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  const REPO = "andycarruthers/nzac-wellington-trips";

  if (!GITHUB_TOKEN) {
    console.error("GITHUB_TOKEN env var not set");
    return { statusCode: 500, body: "Server configuration error" };
  }

  const apiUrl = `https://api.github.com/repos/${REPO}/contents/${filename}`;

  const response = await fetch(apiUrl, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      Accept: "application/vnd.github+json",
    },
    body: JSON.stringify({
      message: `Draft trip report: ${title}`,
      content: contentEncoded,
      branch: "main",
    }),
  });

  if (!response.ok) {
    const err = await response.text();
    console.error("GitHub API error:", err);
    return { statusCode: 500, body: "Failed to create draft" };
  }

  console.log(`Created draft: ${filename}`);
  return { statusCode: 200, body: "Draft created" };
};
