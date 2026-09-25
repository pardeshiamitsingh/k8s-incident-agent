"use strict";

// Spec 010. All API-derived text goes through textContent (see the el
// helper below), never HTML parsing: runbook and postmortem chunk text is
// user-authored and untrusted.

const POLL_INTERVAL_MS = 3000;
const POLL_CEILING_MS = 5 * 60 * 1000;
const TOKEN_KEY = "incident-agent-token";

const $ = (id) => document.getElementById(id);

function getToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
function setToken(value) {
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable: token just won't persist */ }
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

class AuthError extends Error {}
class ApiError extends Error {}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
  });
  if (response.status === 401) throw new AuthError("invalid token");
  if (response.status === 429) {
    throw new ApiError("System busy, try again shortly.");
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch { /* keep */ }
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

function showTokenPrompt(message) {
  $("token-section").hidden = false;
  const msg = $("token-msg");
  msg.hidden = !message;
  msg.textContent = message || "";
}

function objectLabel(o) {
  return `${o.kind} ${o.namespace}/${o.name}`;
}

function list(tag, items) {
  const node = el(tag);
  for (const item of items) node.appendChild(el("li", item));
  return node;
}

function section(card, title, content) {
  card.appendChild(el("h2", title));
  card.appendChild(content);
}

function renderJob(card, job) {
  card.textContent = "";
  const header = el("header");
  header.appendChild(el("strong", objectLabel(job.resolved_object)));
  header.appendChild(el("span", job.status, `badge ${job.status}`));
  card.appendChild(header);

  if (job.status === "running") {
    card.appendChild(el("p", "Diagnosing...", "muted"));
    return;
  }
  if (job.status === "failed") {
    card.appendChild(el("p", job.error || "Diagnosis failed.", "error"));
    return;
  }

  if (job.classified_failure_classes?.length) {
    section(card, "Failure classes", el("p", job.classified_failure_classes.join(", ")));
  }
  section(card, "Root cause", el("p", job.diagnosis.root_cause));
  section(card, "Cited evidence", list("ul", job.diagnosis.cited_evidence));

  const chunks = job.retrieved_chunks || [];
  const cited = new Set(job.diagnosis.cited_runbook_chunks);
  const runbooks = el("div");
  for (const chunk of chunks.filter((c) => cited.has(c.id))) {
    const details = el("details");
    details.appendChild(el("summary", chunk.id));
    details.appendChild(el("pre", chunk.text));
    runbooks.appendChild(details);
  }
  const uncitedIds = [...cited].filter((id) => !chunks.some((c) => c.id === id));
  for (const id of uncitedIds) runbooks.appendChild(el("p", id, "muted"));
  section(card, "Cited runbook chunks", runbooks);

  const plan = job.remediation_plan;
  section(card, "Remediation (proposed, not executed)", el("p", plan.summary));
  card.appendChild(list("ol", plan.steps));
}

async function pollJob(card, jobId) {
  const deadline = Date.now() + POLL_CEILING_MS;
  while (Date.now() < deadline) {
    const job = await api(`/diagnose/${encodeURIComponent(jobId)}`);
    renderJob(card, job);
    if (job.status !== "running") return;
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  card.appendChild(el("p", "Still running; stopped polling. Check the job again later.", "muted"));
}

function renderMention(mention) {
  const card = el("div", null, "card");
  if (mention.status === "resolved") {
    card.appendChild(el("p", `Diagnosing "${mention.mentioned_service}"...`, "muted"));
    pollJob(card, mention.job_id).catch((err) => handleError(err, card));
  } else if (mention.status === "ambiguous") {
    card.appendChild(el("strong", `"${mention.mentioned_service}" matched several objects`));
    card.appendChild(list("ul", (mention.candidates || []).map(objectLabel)));
    card.appendChild(el("p", "Rephrase the query to name one of them.", "muted"));
  } else {
    card.appendChild(el("strong", `"${mention.mentioned_service}"`));
    card.appendChild(el("p", "No matching object found in the cluster.", "muted"));
  }
  return card;
}

function handleError(err, card) {
  if (err instanceof AuthError) {
    setToken("");
    showTokenPrompt("Invalid token. Enter it again.");
    $("status").textContent = "";
    return;
  }
  const message = err instanceof ApiError ? err.message : "Request failed.";
  if (card) card.appendChild(el("p", message, "error"));
  else $("status").textContent = message;
}

async function submitQuery(event) {
  event.preventDefault();
  const query = $("query").value.trim();
  if (!query) return;
  const typed = $("token").value.trim();
  if (typed) { setToken(typed); $("token").value = ""; $("token-section").hidden = true; }
  if (!getToken()) {
    showTokenPrompt();
    $("status").textContent = "Enter your API token above first.";
    return;
  }

  const results = $("results");
  results.textContent = "";
  $("status").textContent = "Resolving your query...";
  $("submit").disabled = true;
  try {
    const { mentions } = await api("/diagnose/query", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    $("status").textContent = mentions.length
      ? "" : "No services detected in that query.";
    for (const mention of mentions) results.appendChild(renderMention(mention));
  } catch (err) {
    handleError(err);
  } finally {
    $("submit").disabled = false;
  }
}

$("token-save").addEventListener("click", () => {
  setToken($("token").value.trim());
  $("token").value = "";
  if (getToken()) $("token-section").hidden = true;
});
$("query-form").addEventListener("submit", submitQuery);
if (!getToken()) showTokenPrompt();
