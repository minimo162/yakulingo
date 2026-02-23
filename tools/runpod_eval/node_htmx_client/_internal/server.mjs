import http from "node:http";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publicDir = path.join(__dirname, "public");

const appPort = Number.parseInt(process.env.APP_PORT || "3030", 10);
const appBind = process.env.APP_BIND || "127.0.0.1";
const timeoutMs = Number.parseInt(process.env.RUNPOD_REQUEST_TIMEOUT_MS || "90000", 10);
const runPodBaseUrl = (process.env.RUNPOD_BASE_URL || "").trim().replace(/\/+$/, "");
const runPodApiKey = (process.env.RUNPOD_API_KEY || "").trim();
const defaultModel = (process.env.DEFAULT_MODEL || "gpt-oss-swallow-120b-iq4xs").trim();
const maxHistoryPairs = Number.parseInt(process.env.MAX_HISTORY_PAIRS || "8", 10);

if (!runPodBaseUrl) {
  console.error("[node-htmx] RUNPOD_BASE_URL is not set.");
  process.exit(1);
}
if (!runPodApiKey) {
  console.error("[node-htmx] RUNPOD_API_KEY is not set.");
  process.exit(1);
}

const sessions = new Map();

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function parseCookies(cookieHeader = "") {
  const output = {};
  const parts = cookieHeader.split(";");
  for (const part of parts) {
    const [keyRaw, ...rest] = part.trim().split("=");
    if (!keyRaw || rest.length === 0) continue;
    const key = keyRaw.trim();
    const value = rest.join("=").trim();
    output[key] = decodeURIComponent(value);
  }
  return output;
}

function getOrCreateSession(req, res) {
  const cookies = parseCookies(req.headers.cookie || "");
  let sid = cookies.sid;
  if (!sid || !sessions.has(sid)) {
    sid = randomBytes(16).toString("hex");
    sessions.set(sid, { messages: [] });
    res.setHeader("Set-Cookie", `sid=${encodeURIComponent(sid)}; HttpOnly; SameSite=Lax; Path=/`);
  }
  if (!sessions.has(sid)) {
    sessions.set(sid, { messages: [] });
  }
  return sessions.get(sid);
}

function send(res, statusCode, body, contentType = "text/plain; charset=utf-8") {
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  res.statusCode = statusCode;
  res.setHeader("Content-Type", contentType);
  res.setHeader("Cache-Control", "no-store");
  res.end(payload);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function extractAssistantText(payload) {
  const choice = payload?.choices?.[0];
  const content = choice?.message?.content;
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item.text === "string") return item.text;
        return "";
      })
      .join("")
      .trim();
  }
  return "";
}

async function callRunPodJson(endpointPath, body) {
  const url = `${runPodBaseUrl}${endpointPath}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${runPodApiKey}`,
        "x-api-key": runPodApiKey,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const raw = await response.text();
    let parsed;
    try {
      parsed = raw ? JSON.parse(raw) : {};
    } catch {
      parsed = { raw };
    }
    if (!response.ok) {
      const err = new Error(`RunPod HTTP ${response.status}`);
      err.statusCode = response.status;
      err.payload = parsed;
      throw err;
    }
    return parsed;
  } finally {
    clearTimeout(timeout);
  }
}

async function callRunPodModels() {
  const url = `${runPodBaseUrl}/models`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        authorization: `Bearer ${runPodApiKey}`,
        "x-api-key": runPodApiKey,
      },
      signal: controller.signal,
    });
    const raw = await response.text();
    let parsed;
    try {
      parsed = raw ? JSON.parse(raw) : {};
    } catch {
      parsed = { data: [] };
    }
    if (!response.ok) {
      const err = new Error(`RunPod HTTP ${response.status}`);
      err.statusCode = response.status;
      err.payload = parsed;
      throw err;
    }
    return parsed;
  } finally {
    clearTimeout(timeout);
  }
}

async function serveStatic(req, res, pathname) {
  let fileName = "index.html";
  if (pathname && pathname !== "/") {
    fileName = pathname.replace(/^\//, "");
  }

  const safePath = path.normalize(fileName).replace(/^(\.\.(\/|\\|$))+/, "");
  const fullPath = path.join(publicDir, safePath);

  if (!fullPath.startsWith(publicDir)) {
    send(res, 403, "Forbidden");
    return;
  }

  let content;
  try {
    content = await readFile(fullPath);
  } catch {
    send(res, 404, "Not Found");
    return;
  }

  const ext = path.extname(fullPath).toLowerCase();
  const typeMap = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
  };
  send(res, 200, content, typeMap[ext] || "application/octet-stream");
}

function trimHistory(messages) {
  const maxMessages = Math.max(1, maxHistoryPairs) * 2;
  if (messages.length <= maxMessages) return messages;
  return messages.slice(messages.length - maxMessages);
}

function renderTurn({ userPrompt, assistantText, model, elapsedMs }) {
  return [
    '<article class="turn turn-user">',
    '<header class="turn-header">You</header>',
    `<pre class="turn-body">${escapeHtml(userPrompt)}</pre>`,
    "</article>",
    '<article class="turn turn-assistant">',
    `<header class="turn-header">RunPod (${escapeHtml(model)})</header>`,
    `<pre class="turn-body">${escapeHtml(assistantText)}</pre>`,
    `<footer class="turn-footer">${elapsedMs} ms</footer>`,
    "</article>",
  ].join("");
}

function renderError(message) {
  return [
    '<article class="turn turn-error">',
    '<header class="turn-header">Error</header>',
    `<pre class="turn-body">${escapeHtml(message)}</pre>`,
    "</article>",
  ].join("");
}

const server = http.createServer(async (req, res) => {
  const reqUrl = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  const pathname = reqUrl.pathname;

  if (req.method === "GET" && pathname === "/health") {
    send(res, 200, { ok: true, service: "node-htmx-client" }, "application/json; charset=utf-8");
    return;
  }

  if (req.method === "GET" && pathname === "/api/models/options") {
    try {
      const models = await callRunPodModels();
      const rows = Array.isArray(models.data) ? models.data : [];
      const options = rows
        .map((row) => (typeof row?.id === "string" ? row.id : null))
        .filter(Boolean);
      if (!options.includes(defaultModel)) {
        options.unshift(defaultModel);
      }
      const html = options
        .map((modelId) => {
          const selected = modelId === defaultModel ? ' selected="selected"' : "";
          return `<option value="${escapeHtml(modelId)}"${selected}>${escapeHtml(modelId)}</option>`;
        })
        .join("");
      send(res, 200, html, "text/html; charset=utf-8");
    } catch (err) {
      const html = `<option value="${escapeHtml(defaultModel)}" selected="selected">${escapeHtml(defaultModel)}</option>`;
      send(res, 200, html, "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/session/reset") {
    const session = getOrCreateSession(req, res);
    session.messages = [];
    send(res, 200, "", "text/html; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/chat/form") {
    const session = getOrCreateSession(req, res);
    let bodyText = "";
    try {
      bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const prompt = (data.get("prompt") || "").trim();
      const systemPrompt = (data.get("systemPrompt") || "").trim();
      const model = (data.get("model") || defaultModel).trim() || defaultModel;
      const temperatureRaw = (data.get("temperature") || "0.7").trim();
      const temperature = Number.parseFloat(temperatureRaw);

      if (!prompt) {
        send(res, 400, renderError("Prompt is empty."), "text/html; charset=utf-8");
        return;
      }

      const messages = [];
      if (systemPrompt) {
        messages.push({ role: "system", content: systemPrompt });
      }
      for (const msg of session.messages) {
        messages.push(msg);
      }
      messages.push({ role: "user", content: prompt });

      const started = Date.now();
      const response = await callRunPodJson("/chat/completions", {
        model,
        messages,
        temperature: Number.isFinite(temperature) ? temperature : 0.7,
        stream: false,
      });
      const assistantText = extractAssistantText(response) || "(empty response)";
      const elapsedMs = Date.now() - started;

      session.messages.push({ role: "user", content: prompt });
      session.messages.push({ role: "assistant", content: assistantText });
      session.messages = trimHistory(session.messages);

      send(
        res,
        200,
        renderTurn({ userPrompt: prompt, assistantText, model, elapsedMs }),
        "text/html; charset=utf-8",
      );
    } catch (err) {
      const statusCode = Number.isInteger(err?.statusCode) ? err.statusCode : 502;
      let msg = "Failed to call RunPod endpoint.";
      if (err?.name === "AbortError") {
        msg = `RunPod request timed out (${timeoutMs} ms).`;
      } else if (typeof err?.message === "string" && err.message) {
        msg = err.message;
      }
      send(res, statusCode, renderError(msg), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "GET") {
    await serveStatic(req, res, pathname);
    return;
  }

  send(res, 405, "Method Not Allowed");
});

server.listen(appPort, appBind, () => {
  console.log(`[node-htmx] listening on http://${appBind}:${appPort}/`);
  console.log(`[node-htmx] model default: ${defaultModel}`);
});
