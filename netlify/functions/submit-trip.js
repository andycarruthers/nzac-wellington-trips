// Receives trip report form data as JSON and creates a draft markdown file via GitHub API.

exports.handler = async function (event) {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method not allowed" };
  }

  let data;
  try {
    data = JSON.parse(event.body);
  } catch (e) {
    return { statusCode: 400, body: "Invalid JSON" };
  }

  const title = data.title || "Untitled Trip";
  const date = data.date || new Date().toISOString().split("T")[0];
  const author = data.name || "";
  const location = data.location || "";
  const participants = data.participants || "";
  const tags = Array.isArray(data.tags) ? data.tags : data.tags ? [data.tags] : [];
  const report = data.report || "";
  const photosLink = data.photos_link || "";

  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  const REPO = "andycarruthers/nzac-wellington-trips";

  if (!GITHUB_TOKEN) {
    return { statusCode: 500, body: JSON.stringify({ error: "Server config error" }) };
  }

  const slug = `${date}-${title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}`;

  const tagsList = tags.length
    ? `\ntags: [${tags.map((t) => `"${t}"`).join(", ")}]` : "";
  const locationsList = location ? `\nlocations: ["${location}"]` : "";
  const participantsParsed = participants
    ? participants.split(",").map((p) => p.trim()) : [];
  const participantsList = participantsParsed.length
    ? `\nparticipants: [${participantsParsed.map((p) => `"${p}"`).join(", ")}]` : "";
  const photosNote = photosLink
    ? `\n\n---\n*Photos: [View submitted photos](${photosLink})*` : "";

  const fileContent = `---
title: "${title.replace(/"/g, '\\"')}"
date: ${date}
author: "${author}"
authors: ["${author}"]
location: "${location}"${locationsList}${tagsList}${participantsList}
draft: true
---

${report}${photosNote}
`;

  const filename = `content/trips/${slug}.md`;
  const contentEncoded = Buffer.from(fileContent).toString("base64");

  const res = await fetch(
    `https://api.github.com/repos/${REPO}/contents/${filename}`,
    {
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
    }
  );

  if (!res.ok) {
    const err = await res.text();
    console.error("GitHub API error:", res.status, err);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "Failed to create draft" }),
    };
  }

  console.log(`Created draft: ${filename}`);
  return {
    statusCode: 200,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ok: true }),
  };
};
