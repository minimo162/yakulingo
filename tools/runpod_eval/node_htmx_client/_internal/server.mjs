import http from "node:http";
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
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
const maxToolLogs = Number.parseInt(process.env.MAX_TOOL_LOGS || "10", 10);
const toolContextEntries = Number.parseInt(process.env.TOOL_CONTEXT_ENTRIES || "6", 10);
const maxToolOutputChars = Number.parseInt(process.env.MAX_TOOL_OUTPUT_CHARS || "12000", 10);
const maxReadBytes = Number.parseInt(process.env.MAX_READ_BYTES || "262144", 10);
const localShellTimeoutMs = Number.parseInt(process.env.LOCAL_SHELL_TIMEOUT_MS || "20000", 10);
const workspaceRoot = path.resolve((process.env.WORKSPACE_ROOT || process.cwd()).trim() || process.cwd());
const configuredAllowPrefixes = (process.env.LOCAL_SHELL_ALLOWLIST || "")
  .split(",")
  .map((item) => item.trim().toLowerCase())
  .filter(Boolean);
const shellAllowlist = configuredAllowPrefixes.length > 0
  ? configuredAllowPrefixes
  : [
      "git status",
      "git diff",
      "git log",
      "git show",
      "git branch",
      "git rev-parse",
      "rg",
      "pwd",
      "ls",
      "dir",
      "get-childitem",
      "type",
      "cat",
    ];
const codingModeSystemPrompt = [
  "You are a practical coding assistant working on a local repository.",
  "Prefer concrete edits, executable commands, and risk notes.",
  "If local tool context is provided, treat it as source of truth.",
].join(" ");

if (!runPodBaseUrl) {
  console.error("[node-htmx] RUNPOD_BASE_URL is not set.");
  process.exit(1);
}
if (!runPodApiKey) {
  console.error("[node-htmx] RUNPOD_API_KEY is not set.");
  process.exit(1);
}

const sessions = new Map();

function normalizeForCompare(value) {
  return process.platform === "win32" ? value.toLowerCase() : value;
}

function isInsideWorkspace(absPath) {
  const normalizedPath = normalizeForCompare(path.resolve(absPath));
  const normalizedRoot = normalizeForCompare(workspaceRoot);
  return normalizedPath === normalizedRoot || normalizedPath.startsWith(`${normalizedRoot}${path.sep}`);
}

function resolveWorkspacePath(rawPath) {
  const input = String(rawPath || "").trim();
  if (!input) {
    throw new Error("Path is empty.");
  }
  const resolved = path.resolve(workspaceRoot, input);
  if (!isInsideWorkspace(resolved)) {
    throw new Error("Path is outside workspace root.");
  }
  return resolved;
}

function toWorkspaceRelative(absPath) {
  const rel = path.relative(workspaceRoot, absPath);
  return rel || ".";
}

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
    sessions.set(sid, { messages: [], toolLogs: [] });
    res.setHeader("Set-Cookie", `sid=${encodeURIComponent(sid)}; HttpOnly; SameSite=Lax; Path=/`);
  }
  if (!sessions.has(sid)) {
    sessions.set(sid, { messages: [], toolLogs: [] });
  }
  const session = sessions.get(sid);
  if (!Array.isArray(session.messages)) {
    session.messages = [];
  }
  if (!Array.isArray(session.toolLogs)) {
    session.toolLogs = [];
  }
  return session;
}

function send(res, statusCode, body, contentType = "text/plain; charset=utf-8") {
  let payload;
  if (Buffer.isBuffer(body)) {
    payload = body;
  } else if (typeof body === "string") {
    payload = body;
  } else {
    payload = JSON.stringify(body);
  }
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

function truncateText(value, maxChars = maxToolOutputChars) {
  const text = String(value || "");
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars)}\n...(truncated ${text.length - maxChars} chars)`;
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

function appendToolLog(session, entry) {
  const safeEntry = {
    title: String(entry?.title || "tool"),
    summary: String(entry?.summary || ""),
    detail: truncateText(entry?.detail || "", maxToolOutputChars),
    createdAt: new Date().toISOString(),
  };
  session.toolLogs.push(safeEntry);
  if (session.toolLogs.length > Math.max(1, maxToolLogs)) {
    session.toolLogs = session.toolLogs.slice(session.toolLogs.length - Math.max(1, maxToolLogs));
  }
}

function buildToolContext(session) {
  if (!Array.isArray(session.toolLogs) || session.toolLogs.length === 0) {
    return "";
  }
  const rows = session.toolLogs
    .slice(-Math.max(1, toolContextEntries))
    .map((item, index) => {
      const num = index + 1;
      return [
        `[tool ${num}] ${item.title}`,
        item.summary ? `summary: ${item.summary}` : "",
        item.detail ? `detail:\n${item.detail}` : "",
      ].filter(Boolean).join("\n");
    });
  return rows.join("\n\n");
}

function renderToolResult({ title, meta = "", body = "", isError = false }) {
  const cls = isError ? "turn turn-error" : "turn turn-tool";
  const lines = [
    `<article class="${cls}">`,
    `<header class="turn-header">${escapeHtml(title)}</header>`,
  ];
  if (meta) {
    lines.push(`<div class="turn-meta">${escapeHtml(meta)}</div>`);
  }
  lines.push(`<pre class="turn-body">${escapeHtml(body)}</pre>`);
  lines.push("</article>");
  return lines.join("");
}

function hasUnsafeShellChars(command) {
  // Keep command execution intentionally narrow to avoid accidental chaining.
  return /[;&|><`\r\n]/.test(command);
}

function isAllowedShellCommand(command) {
  const normalized = String(command || "").trim().toLowerCase();
  if (!normalized) return false;
  if (hasUnsafeShellChars(normalized)) return false;
  return shellAllowlist.some((prefix) => normalized === prefix || normalized.startsWith(`${prefix} `));
}

function runShellCommand(command, cwd) {
  return new Promise((resolve) => {
    const started = Date.now();
    const args = process.platform === "win32"
      ? ["-NoProfile", "-Command", command]
      : ["-lc", command];
    const shellExec = process.platform === "win32" ? "powershell.exe" : "bash";

    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let exitCode = 0;
    let spawnError = "";
    let settled = false;

    const child = spawn(shellExec, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const finish = () => {
      if (settled) return;
      settled = true;
      resolve({
        stdout: truncateText(stdout, maxToolOutputChars),
        stderr: truncateText(stderr, maxToolOutputChars),
        exitCode,
        timedOut,
        spawnError,
        elapsedMs: Date.now() - started,
      });
    };

    const timer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill("SIGTERM");
      } catch {
        // ignore
      }
      setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {
          // ignore
        }
      }, 500);
    }, Math.max(1000, localShellTimeoutMs));

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      if (stdout.length > maxToolOutputChars * 2) {
        stdout = stdout.slice(-maxToolOutputChars * 2);
      }
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
      if (stderr.length > maxToolOutputChars * 2) {
        stderr = stderr.slice(-maxToolOutputChars * 2);
      }
    });

    child.on("error", (err) => {
      spawnError = err?.message || String(err);
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      exitCode = Number.isInteger(code) ? code : 1;
      finish();
    });
  });
}

async function runSearch(pattern, glob) {
  return new Promise((resolve, reject) => {
    const args = ["--line-number", "--no-heading", "--color", "never", "--max-count", "200", "--hidden"];
    if (glob) {
      args.push("--glob", glob);
    }
    args.push("--glob", "!.git/**");
    args.push(pattern, workspaceRoot);

    let stdout = "";
    let stderr = "";
    let spawnError = "";
    let closed = false;

    const child = spawn("rg", args, {
      cwd: workspaceRoot,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const done = (payload, isErr = false) => {
      if (closed) return;
      closed = true;
      if (isErr) {
        reject(payload);
      } else {
        resolve(payload);
      }
    };

    const timer = setTimeout(() => {
      try {
        child.kill("SIGTERM");
      } catch {
        // ignore
      }
      done(new Error("Search timed out."), true);
    }, Math.max(3000, localShellTimeoutMs));

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      if (stdout.length > maxToolOutputChars * 2) {
        stdout = stdout.slice(-maxToolOutputChars * 2);
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
      if (stderr.length > maxToolOutputChars * 2) {
        stderr = stderr.slice(-maxToolOutputChars * 2);
      }
    });

    child.on("error", (err) => {
      spawnError = err?.message || String(err);
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      if (spawnError) {
        done(new Error(spawnError), true);
        return;
      }
      if (code === 0) {
        done({
          status: "match",
          output: truncateText(stdout, maxToolOutputChars),
          error: truncateText(stderr, maxToolOutputChars),
        });
        return;
      }
      if (code === 1) {
        done({
          status: "no-match",
          output: "",
          error: truncateText(stderr, maxToolOutputChars),
        });
        return;
      }
      done(new Error(`rg exited with code ${code}. ${stderr}`), true);
    });
  });
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

  if (req.method === "GET" && pathname === "/api/workspace/info") {
    const text = [
      `root: ${workspaceRoot}`,
      `shell allowlist: ${shellAllowlist.join(", ")}`,
    ].join("\n");
    send(res, 200, `<pre class="workspace-box">${escapeHtml(text)}</pre>`, "text/html; charset=utf-8");
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
    session.toolLogs = [];
    send(res, 200, "", "text/html; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/reset") {
    const session = getOrCreateSession(req, res);
    session.toolLogs = [];
    send(res, 200, "", "text/html; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/read") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const rawPath = (data.get("path") || "").trim();
      const resolvedPath = resolveWorkspacePath(rawPath);
      const info = await stat(resolvedPath);
      if (!info.isFile()) {
        send(res, 200, renderToolResult({
          title: "Tool read error",
          body: `Not a file: ${rawPath}`,
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      if (info.size > Math.max(1024, maxReadBytes)) {
        send(res, 200, renderToolResult({
          title: "Tool read error",
          body: `File too large (${info.size} bytes). MAX_READ_BYTES=${maxReadBytes}.`,
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      const content = await readFile(resolvedPath, "utf8");
      const relPath = toWorkspaceRelative(resolvedPath);
      const shown = truncateText(content, maxToolOutputChars);
      appendToolLog(session, {
        title: `read ${relPath}`,
        summary: `bytes=${info.size}`,
        detail: shown,
      });
      send(res, 200, renderToolResult({
        title: `Tool read: ${relPath}`,
        meta: `bytes=${info.size}`,
        body: shown || "(empty file)",
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool read error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/search") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const pattern = (data.get("pattern") || "").trim();
      const glob = (data.get("glob") || "").trim();
      if (!pattern) {
        send(res, 200, renderToolResult({
          title: "Tool search error",
          body: "Pattern is empty.",
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      const result = await runSearch(pattern, glob);
      const body = result.status === "no-match"
        ? "No matches."
        : (result.output || "(no output)");
      appendToolLog(session, {
        title: `search pattern=${pattern}`,
        summary: glob ? `glob=${glob}` : "",
        detail: body,
      });
      send(res, 200, renderToolResult({
        title: "Tool search",
        meta: glob ? `pattern=${pattern} glob=${glob}` : `pattern=${pattern}`,
        body,
        isError: result.status !== "match" && result.status !== "no-match",
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool search error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/shell") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const command = (data.get("command") || "").trim();
      const approved = data.get("approved") === "on";
      if (!approved) {
        send(res, 200, renderToolResult({
          title: "Tool shell blocked",
          body: "Enable command approval checkbox before running shell command.",
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      if (!command) {
        send(res, 200, renderToolResult({
          title: "Tool shell error",
          body: "Command is empty.",
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      if (!isAllowedShellCommand(command)) {
        send(res, 200, renderToolResult({
          title: "Tool shell blocked",
          body: [
            `Command is not allowed: ${command}`,
            `Allowed prefixes: ${shellAllowlist.join(", ")}`,
            "Forbidden chars: ; & | > < ` and newline",
          ].join("\n"),
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      const result = await runShellCommand(command, workspaceRoot);
      const output = [
        `$ ${command}`,
        result.stdout ? `\n[stdout]\n${result.stdout}` : "",
        result.stderr ? `\n[stderr]\n${result.stderr}` : "",
      ].join("");
      appendToolLog(session, {
        title: `shell ${command}`,
        summary: `exit=${result.exitCode} timeout=${result.timedOut ? "yes" : "no"} elapsed=${result.elapsedMs}ms`,
        detail: output,
      });
      const statusText = `exit=${result.exitCode} timeout=${result.timedOut ? "yes" : "no"} elapsed=${result.elapsedMs}ms`;
      send(res, 200, renderToolResult({
        title: "Tool shell",
        meta: statusText,
        body: output || "(no output)",
        isError: result.exitCode !== 0 || result.timedOut || Boolean(result.spawnError),
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool shell error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/write") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const rawPath = (data.get("path") || "").trim();
      const content = String(data.get("content") || "");
      const confirmWrite = data.get("confirmWrite") === "on";
      if (!confirmWrite) {
        send(res, 200, renderToolResult({
          title: "Tool write blocked",
          body: "Enable write approval checkbox before writing file.",
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      const resolvedPath = resolveWorkspacePath(rawPath);
      await mkdir(path.dirname(resolvedPath), { recursive: true });
      await writeFile(resolvedPath, content, "utf8");
      const relPath = toWorkspaceRelative(resolvedPath);
      appendToolLog(session, {
        title: `write ${relPath}`,
        summary: `bytes=${Buffer.byteLength(content, "utf8")}`,
        detail: truncateText(content, maxToolOutputChars),
      });
      send(res, 200, renderToolResult({
        title: `Tool write: ${relPath}`,
        meta: `bytes=${Buffer.byteLength(content, "utf8")}`,
        body: "File written.",
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool write error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
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
      const includeToolContext = data.get("includeToolContext") === "on";
      const codingMode = data.get("codingMode") === "on";

      if (!prompt) {
        send(res, 400, renderError("Prompt is empty."), "text/html; charset=utf-8");
        return;
      }

      const messages = [];
      if (systemPrompt) {
        messages.push({ role: "system", content: systemPrompt });
      }
      if (codingMode) {
        messages.push({ role: "system", content: codingModeSystemPrompt });
      }
      if (includeToolContext) {
        const toolContext = buildToolContext(session);
        if (toolContext) {
          messages.push({
            role: "system",
            content: [
              "Local tool logs from the user's workspace are included below.",
              "Treat them as trusted local observations.",
              "",
              toolContext,
            ].join("\n"),
          });
        }
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
      let msg = "Failed to call RunPod endpoint.";
      if (err?.name === "AbortError") {
        msg = `RunPod request timed out (${timeoutMs} ms).`;
      } else if (typeof err?.message === "string" && err.message) {
        msg = err.message;
      }
      const statusCode = Number.isInteger(err?.statusCode) ? err.statusCode : 502;
      const payloadText =
        err?.payload && typeof err.payload === "object"
          ? JSON.stringify(err.payload)
          : "";
      if (payloadText) {
        msg = `${msg}\nHTTP ${statusCode}\n${payloadText.slice(0, 1200)}`;
      } else {
        msg = `${msg}\nHTTP ${statusCode}`;
      }

      // htmx is easier to operate when chat endpoint always returns 200 with html fragment.
      send(res, 200, renderError(msg), "text/html; charset=utf-8");
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
  console.log(`[node-htmx] workspace root: ${workspaceRoot}`);
});
