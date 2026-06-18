// Triggered via Netlify webhook when a trip-report form submission comes in.
// Creates a draft markdown file (and downloads any photos) via the GitHub API.

exports.handler = async function (event) {
  let body;
  try {
    body = JSON.parse(event.body);
  } catch (e) {
    console.error("Failed to parse body:", e);
    return { statusCode: 400, body: "Bad request" };
  }

  const payload = body.payload || body;
  console.log("form_name:", payload.form_name);

  if (payload.form_name !== "trip-report") {
    return { statusCode: 200, body: "Not a trip report submission" };
  }

  const data = payload.data || {};
  const submissionId = payload.id || "";
  console.log("submission id:", submissionId);

  const title = data.title || "Untitled Trip";
  const date = data.date || new Date().toISOString().split("T")[0];
  const author = data.name || "";
  const location = data.location || "";
  const participants = data.participants || "";
  const tags = Array.isArray(data.tags)
    ? data.tags
    : data.tags ? [data.tags] : [];
  const report = data.report || "";

  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  const NETLIFY_API_TOKEN = process.env.NETLIFY_API_TOKEN;
  const REPO = "andycarruthers/nzac-wellington-trips";

  if (!GITHUB_TOKEN) {
    console.error("GITHUB_TOKEN not set");
    return { statusCode: 500, body: "Missing GITHUB_TOKEN" };
  }

  // Build slug
  const slug = `${date}-${title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}`;

  // Download and commit photos if any
  const photoLines = [];
  let coverPath = "";

  if (submissionId && NETLIFY_API_TOKEN) {
    try {
      // Fetch the full submission to get file URLs
      const subRes = await fetch(
        `https://api.netlify.com/api/v1/submissions/${submissionId}`,
        { headers: { Authorization: `Bearer ${NETLIFY_API_TOKEN}` } }
      );
      if (subRes.ok) {
        const sub = await subRes.json();
        const files = sub.data?.photos || sub.ordered_human_fields?.find(f => f.name === "photos")?.value;
        const fileList = Array.isArray(files) ? files : files ? [files] : [];

        for (let i = 0; i < fileList.length; i++) {
          const file = fileList[i];
          const fileUrl = typeof file === "string" ? file : file.url;
          const origName = typeof file === "string"
            ? `photo-${i + 1}.jpg`
            : file.filename || `photo-${i + 1}.jpg`;

          const ext = origName.split(".").pop().toLowerCase() || "jpg";
          const imgName = `${slug}-photo-${i + 1}.${ext}`;
          const imgPath = `static/images/trips/${imgName}`;

          // Download the file
          const imgRes = await fetch(fileUrl, {
            headers: NETLIFY_API_TOKEN
              ? { Authorization: `Bearer ${NETLIFY_API_TOKEN}` }
              : {},
          });

          if (imgRes.ok) {
            const imgBuffer = await imgRes.arrayBuffer();
            const imgBase64 = Buffer.from(imgBuffer).toString("base64");

            // Commit image to GitHub
            await fetch(
              `https://api.github.com/repos/${REPO}/contents/${imgPath}`,
              {
                method: "PUT",
                headers: {
                  Authorization: `Bearer ${GITHUB_TOKEN}`,
                  "Content-Type": "application/json",
                  Accept: "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28",
                },
                body: JSON.stringify({
                  message: `Photo for draft: ${title}`,
                  content: imgBase64,
                  branch: "main",
                }),
              }
            );

            const publicPath = `/images/trips/${imgName}`;
            if (i === 0) coverPath = publicPath;
            photoLines.push(`![Photo](/images/trips/${imgName})`);
            console.log(`Committed photo: ${imgPath}`);
          } else {
            console.error(`Failed to download photo ${i + 1}:`, imgRes.status);
          }
        }
      }
    } catch (e) {
      console.error("Error handling photos:", e);
    }
  }

  // Build frontmatter
  const tagsList = tags.length
    ? `\ntags: [${tags.map((t) => `"${t}"`).join(", ")}]` : "";
  const locationsList = location ? `\nlocations: ["${location}"]` : "";
  const participantsParsed = participants
    ? participants.split(",").map((p) => p.trim()) : [];
  const participantsList = participantsParsed.length
    ? `\nparticipants: [${participantsParsed.map((p) => `"${p}"`).join(", ")}]` : "";
  const coverLine = coverPath ? `\ncover: "${coverPath}"` : "";

  const fileContent = `---
title: "${title.replace(/"/g, '\\"')}"
date: ${date}
author: "${author}"
authors: ["${author}"]
location: "${location}"${locationsList}${tagsList}${participantsList}${coverLine}
draft: true
---

${report}
${photoLines.length ? "\n" + photoLines.join("\n\n") : ""}
`;

  const contentEncoded = Buffer.from(fileContent).toString("base64");
  const filename = `content/trips/${slug}.md`;

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
    return { statusCode: 500, body: `Failed to create draft: ${res.status}` };
  }

  console.log(`Created draft: ${filename} with ${photoLines.length} photos`);
  return { statusCode: 200, body: "Draft created" };
};
