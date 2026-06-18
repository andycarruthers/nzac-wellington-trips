// Triggered automatically by Netlify when a form submission comes in.
// Creates a draft markdown file in content/trips/ via the GitHub API.

exports.handler = async function (event) {
  console.log("submission-created fired, body:", event.body);

  let body;
  try {
    body = JSON.parse(event.body);
  } catch (e) {
    console.error("Failed to parse body:", e);
    return { statusCode: 400, body: "Bad request" };
  }

  // Netlify sends payload at body.payload
  const payload = body.payload || body;
  console.log("form_name:", payload.form_name);

  if (payload.form_name !== "trip-report") {
    return { statusCode: 200, body: "Not a trip report submission" };
  }

  const data = payload.data || {};
  console.log("form data:", JSON.stringify(data));

  const title = data.title || "Untitled Trip";
  const date = data.date || new Date().toISOString().split("T")[0];
  const author = data.name || "";
  const location = data.location || "";
  const participants = data.participants || "";
  const tags = Array.isArray(data.tags)
    ? data.tags
    : data.tags
    ? [data.tags]
    : [];
  const report = data.report || "";

  // Build slug from date + title
  const slug = `${date}-${title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}`;

  const filename = `content/trips/${slug}.md`;

  const tagsList =
    tags.length
      ? `\ntags: [${tags.map((t) => `"${t}"`).join(", ")}]`
      : "";
  const locationsList = location ? `\nlocations: ["${location}"]` : "";
  const participantsParsed = participants
    ? participants.split(",").map((p) => p.trim())
    : [];
  const participantsList =
    participantsParsed.length
      ? `\nparticipants: [${participantsParsed.map((p) => `"${p}"`).join(", ")}]`
      : "";

  const fileContent = `---
title: "${title.replace(/"/g, '\\"')}"
date: ${date}
author: "${author}"
authors: ["${author}"]
location: "${location}"${locationsList}${tagsList}${participantsList}
draft: true
---

${report}
`;

  const contentEncoded = Buffer.from(fileContent).toString("base64");

  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  const REPO = "andycarruthers/nzac-wellington-trips";

  if (!GITHUB_TOKEN) {
    console.error("GITHUB_TOKEN env var not set");
    return { statusCode: 500, body: "Server configuration error: missing GITHUB_TOKEN" };
  }

  const apiUrl = `https://api.github.com/repos/${REPO}/contents/${filename}`;
  console.log("Creating file:", apiUrl);

  const response = await fetch(apiUrl, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({
      message: `Draft trip report: ${title}`,
      content: contentEncoded,
      branch: "main",
    }),
  });

  const responseText = await response.text();
  console.log("GitHub API response:", response.status, responseText);

  if (!response.ok) {
    console.error("GitHub API error:", response.status, responseText);
    return { statusCode: 500, body: `Failed to create draft: ${response.status}` };
  }

  console.log(`Created draft: ${filename}`);
  return { statusCode: 200, body: "Draft created" };
};
