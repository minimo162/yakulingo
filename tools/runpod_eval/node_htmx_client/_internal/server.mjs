import http from "node:http";
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

function parseBooleanEnv(rawValue, fallback = false) {
  const normalized = String(rawValue ?? "").trim().toLowerCase();
  if (!normalized) return fallback;
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return fallback;
}

function parseIntEnv(rawValue, fallback, minValue, maxValue) {
  const parsed = Number.parseInt(String(rawValue ?? "").trim(), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maxValue, Math.max(minValue, parsed));
}

function parseFloatEnv(rawValue, fallback, minValue, maxValue) {
  const parsed = Number.parseFloat(String(rawValue ?? "").trim());
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maxValue, Math.max(minValue, parsed));
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publicDir = path.join(__dirname, "public");
const officeHelperScript = path.join(__dirname, "office_rw.py");
const configuredUvBin = (process.env.UV_BIN || "").trim();
const configuredPythonBin = (process.env.PYTHON_BIN || "").trim();

const appPort = Number.parseInt(process.env.APP_PORT || "3030", 10);
const appBind = process.env.APP_BIND || "127.0.0.1";
const timeoutMs = Number.parseInt(process.env.RUNPOD_REQUEST_TIMEOUT_MS || "90000", 10);
const appTimeZone = (process.env.APP_TIME_ZONE || "Asia/Tokyo").trim() || "Asia/Tokyo";
const runPodHttpRetryMaxAttempts = parseIntEnv(process.env.RUNPOD_HTTP_RETRY_MAX_ATTEMPTS, 4, 1, 12);
const runPodHttpRetryDelayMs = parseIntEnv(process.env.RUNPOD_HTTP_RETRY_DELAY_MS, 1500, 0, 30000);
const runPodHttpRetryMaxDelayMs = parseIntEnv(process.env.RUNPOD_HTTP_RETRY_MAX_DELAY_MS, 6000, 0, 120000);
const runPodBaseUrl = (process.env.RUNPOD_BASE_URL || "").trim().replace(/\/+$/, "");
const runPodApiKey = (process.env.RUNPOD_API_KEY || "").trim();
const defaultModel = (process.env.DEFAULT_MODEL || "gpt-oss-swallow-120b-iq4xs").trim();
const maxHistoryPairs = Number.parseInt(process.env.MAX_HISTORY_PAIRS || "8", 10);
const maxToolLogs = Number.parseInt(process.env.MAX_TOOL_LOGS || "10", 10);
const toolContextEntries = Number.parseInt(process.env.TOOL_CONTEXT_ENTRIES || "6", 10);
const maxToolOutputChars = Number.parseInt(process.env.MAX_TOOL_OUTPUT_CHARS || "12000", 10);
const maxProcessOutputChars = Number.parseInt(process.env.MAX_PROCESS_OUTPUT_CHARS || "400000", 10);
const generationTemperatureDefault = parseFloatEnv(process.env.GENERATION_TEMPERATURE, 0.6, 0, 2);
const generationTopP = parseFloatEnv(process.env.GENERATION_TOP_P, 0.95, 0, 1);
const generationTopK = parseIntEnv(process.env.GENERATION_TOP_K, 20, 0, 200);
const generationMinP = parseFloatEnv(process.env.GENERATION_MIN_P, 0, 0, 1);
const generationMaxContextTokens = parseIntEnv(process.env.GENERATION_MAX_CONTEXT_TOKENS, 32768, 2048, 262144);
const generationContextReserveTokens = parseIntEnv(process.env.GENERATION_CONTEXT_RESERVE_TOKENS, 512, 0, 8192);
const maxReadBytes = Number.parseInt(process.env.MAX_READ_BYTES || "262144", 10);
const maxPdfReadBytes = Number.parseInt(process.env.MAX_PDF_READ_BYTES || "20971520", 10);
const maxPdfReadPages = Number.parseInt(process.env.MAX_PDF_READ_PAGES || "20", 10);
const maxPdfReadChars = Number.parseInt(process.env.MAX_PDF_READ_CHARS || "80000", 10);
const maxOfficeReadBytes = Number.parseInt(process.env.MAX_OFFICE_READ_BYTES || "20971520", 10);
const maxOfficeReadChars = Number.parseInt(process.env.MAX_OFFICE_READ_CHARS || "80000", 10);
const maxOfficeReadItems = Number.parseInt(process.env.MAX_OFFICE_READ_ITEMS || "4000", 10);
const localShellTimeoutMs = Number.parseInt(process.env.LOCAL_SHELL_TIMEOUT_MS || "20000", 10);
const autoToolMaxSteps = Number.parseInt(process.env.AUTO_TOOL_MAX_STEPS || "8", 10);
const autoToolMaxTokens = Number.parseInt(process.env.AUTO_TOOL_MAX_TOKENS || "2200", 10);
const autoToolResultChars = Number.parseInt(process.env.AUTO_TOOL_RESULT_CHARS || "8000", 10);
const autoToolJsonRepairRetries = Number.parseInt(process.env.AUTO_TOOL_JSON_REPAIR_RETRIES || "1", 10);
const autoToolJsonRepairMaxChars = Number.parseInt(process.env.AUTO_TOOL_JSON_REPAIR_MAX_CHARS || "8000", 10);
const parsedAutoToolTemperature = Number.parseFloat(process.env.AUTO_TOOL_TEMPERATURE || String(generationTemperatureDefault));
const autoToolTemperature = Number.isFinite(parsedAutoToolTemperature) ? parsedAutoToolTemperature : generationTemperatureDefault;
const autonomousLoopMaxIters = Number.parseInt(process.env.AUTONOMOUS_LOOP_MAX_ITERS || "3", 10);
const autonomousMaxFilesPerIter = Number.parseInt(process.env.AUTONOMOUS_MAX_FILES_PER_ITER || "4", 10);
const autonomousMaxFileContextChars = Number.parseInt(process.env.AUTONOMOUS_MAX_FILE_CONTEXT_CHARS || "12000", 10);
const autonomousMaxValidationCommands = Number.parseInt(process.env.AUTONOMOUS_MAX_VALIDATION_COMMANDS || "4", 10);
const autonomousModelMaxTokens = Number.parseInt(process.env.AUTONOMOUS_MODEL_MAX_TOKENS || "4000", 10);
const playwrightMcpEnabled = parseBooleanEnv(process.env.PLAYWRIGHT_MCP_ENABLED, true);
const playwrightMcpBrowser = (process.env.PLAYWRIGHT_MCP_BROWSER || "chromium").trim().toLowerCase() || "chromium";
const playwrightMcpHeadless = parseBooleanEnv(process.env.PLAYWRIGHT_MCP_HEADLESS, true);
const playwrightMcpTimeoutMs = Number.parseInt(process.env.PLAYWRIGHT_MCP_TIMEOUT_MS || "300000", 10);
const playwrightMcpMaxResults = Number.parseInt(process.env.PLAYWRIGHT_MCP_MAX_RESULTS || "5", 10);
const playwrightMcpPackage = (process.env.PLAYWRIGHT_MCP_PACKAGE || "@playwright/mcp@latest").trim();
const mcpInspectorPackage = (process.env.MCP_INSPECTOR_PACKAGE || "@modelcontextprotocol/inspector@latest").trim();
const clientAutostopEnabled = parseBooleanEnv(process.env.CLIENT_AUTOSTOP_ENABLED, true);
const clientHeartbeatIntervalMs = Number.parseInt(process.env.CLIENT_HEARTBEAT_INTERVAL_MS || "15000", 10);
const clientHeartbeatStaleMs = Number.parseInt(process.env.CLIENT_HEARTBEAT_STALE_MS || "45000", 10);
const clientAutostopIdleMs = Number.parseInt(process.env.CLIENT_AUTOSTOP_IDLE_MS || "30000", 10);
const clientHeartbeatSweepMs = Number.parseInt(process.env.CLIENT_HEARTBEAT_SWEEP_MS || "5000", 10);
const clientAutostopRequestGraceMs = Number.parseInt(process.env.CLIENT_AUTOSTOP_REQUEST_GRACE_MS || "30000", 10);
const streamKeepaliveIntervalMs = Number.parseInt(process.env.STREAM_KEEPALIVE_INTERVAL_MS || "10000", 10);
const defaultWorkspaceRoot = path.join(__dirname, "..", "workspace");
const workspaceRoot = path.resolve(defaultWorkspaceRoot);
await mkdir(workspaceRoot, { recursive: true });
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
const autoToolSystemPrompt = [
  "You are a practical coding agent for a local repository.",
  "Return ONLY one JSON object. Do not include markdown.",
  "You must choose exactly one format:",
  '{"type":"tool","tool":"read|read_file|list_dir|search|shell|write|apply_patch|update_plan|web_search","args":{},"reason":"short reason"}',
  '{"type":"final","message":"final answer for the user in Japanese"}',
  "Tool args schema:",
  'read: {"path":"workspace-relative path"}',
  'read_file: {"path":"workspace-relative path","offset":"optional 1-index line","limit":"optional 1-400"}',
  'list_dir: {"path":"optional workspace-relative dir","recursive":"optional true|false","max_depth":"optional 0-6","limit":"optional 1-500"}',
  'search: {"pattern":"text or regex","glob":"optional glob"}',
  'shell: {"command":"single allowlisted command"}',
  'write: {"path":"relative/path","content":"full file content"}',
  'write office hints: .docx content can be plain text or {"paragraphs":[...]}; .xlsx can use {"sheets":[{"name":"Sheet1","rows":[["A1","B1"]]}]}; .pptx can use {"slides":[{"title":"...","lines":[...]}]}',
  'apply_patch: {"patch":"codex apply_patch style patch text"}',
  'update_plan: {"explanation":"optional","plan":[{"step":"string","status":"pending|in_progress|completed"}]}',
  'web_search: {"query":"internet search query","max_results":"optional 1-10"}',
  "For web_search, always provide a non-empty query string.",
  "read is allowed only inside workspace_root. It can extract PDF and Office (.xlsx/.docx/.pptx) text.",
  "Prefer read_file for text/code files to avoid oversized context.",
  "write is allowed only inside workspace_root.",
  "For .xlsx/.docx/.pptx write, content can be plain text or JSON.",
  "apply_patch is allowed only inside workspace_root and should be preferred for partial edits.",
  "If the user message includes a file path, call read first instead of claiming you cannot access local files.",
  "If the user asks to create/update a file in workspace, you must call write or apply_patch before final.",
  "Do not finish with instructions-only text when a file write was explicitly requested.",
  "Use web_search for latest/current external information needs.",
  "Current date context will be provided as current_date_jst/current_utc_iso in system messages.",
  "Resolve relative dates (today/今日/tomorrow/明日/yesterday/昨日) strictly from the provided date context.",
  "For weather/news questions asking about today, do not invent arbitrary calendar dates.",
  "Use one tool call at a time and wait for the tool result.",
  "Prefer list_dir/read_file/search before write/apply_patch. Use shell only when needed.",
  "When task is complete, return type=final.",
].join("\n");
const autoToolJsonRepairSystemPrompt = [
  "You repair malformed JSON emitted by another assistant.",
  "Output ONLY one valid JSON object. No markdown.",
  "Target schema (choose one):",
  '{"type":"tool","tool":"read|read_file|list_dir|search|shell|write|apply_patch|update_plan|web_search","args":{},"reason":"short reason"}',
  '{"type":"final","message":"final answer for the user in Japanese"}',
  "Preserve original intent. If unclear, return type=final.",
].join("\n");
const autonomousPlannerSystemPrompt = [
  "You are an autonomous coding planner.",
  "Return ONLY valid JSON object.",
  "Plan one iteration for local repository changes.",
  "Do not include markdown.",
  "Schema:",
  '{"summary":"string","tasks":["string"],"target_files":[{"path":"relative/path","reason":"string"}],"validation_commands":["allowed command"],"done":false,"next_focus":"string"}',
].join("\n");
const autonomousEditorSystemPrompt = [
  "You are an autonomous coding editor.",
  "Return ONLY valid JSON object.",
  "For each change, provide FULL file content after edit.",
  "Do not include markdown.",
  "Do not use absolute paths.",
  "Schema:",
  '{"summary":"string","changes":[{"path":"relative/path","action":"update|create","content":"full file content"}],"done":false,"final_message":"string"}',
].join("\n");

if (!runPodBaseUrl) {
  console.error("[node-htmx] RUNPOD_BASE_URL is not set.");
  process.exit(1);
}
if (!runPodApiKey) {
  console.error("[node-htmx] RUNPOD_API_KEY is not set.");
  process.exit(1);
}

const sessions = new Map();
const clientHeartbeats = new Map();
let hasSeenAnyClient = false;
let noClientSinceMs = Date.now();
let shutdownRequestedByClientIdle = false;
let activeHttpRequestCount = 0;
let lastHttpActivityMs = Date.now();

function normalizeClientId(rawValue) {
  const value = String(rawValue || "").trim();
  if (!value) return "";
  const normalized = value.replace(/[^A-Za-z0-9_-]/g, "");
  if (!normalized) return "";
  return normalized.slice(0, 80);
}

function markClientHeartbeat(rawClientId) {
  const clientId = normalizeClientId(rawClientId);
  if (!clientId) return "";
  hasSeenAnyClient = true;
  clientHeartbeats.set(clientId, Date.now());
  noClientSinceMs = 0;
  return clientId;
}

function markClientDisconnected(rawClientId) {
  const clientId = normalizeClientId(rawClientId);
  if (!clientId) return false;
  const deleted = clientHeartbeats.delete(clientId);
  if (deleted && clientHeartbeats.size === 0) {
    noClientSinceMs = Date.now();
  }
  return deleted;
}

function sweepClientHeartbeats(nowMs = Date.now()) {
  const staleMs = Math.max(1000, clientHeartbeatStaleMs);
  for (const [clientId, lastSeenMs] of clientHeartbeats.entries()) {
    if (nowMs - lastSeenMs > staleMs) {
      clientHeartbeats.delete(clientId);
    }
  }
  return clientHeartbeats.size;
}

function requestIdleShutdown(idleMs) {
  if (shutdownRequestedByClientIdle) return;
  shutdownRequestedByClientIdle = true;
  const roundedIdle = Math.max(0, Math.round(idleMs));
  console.log(`[node-htmx] no active browser client for ${roundedIdle} ms; shutting down.`);
  setTimeout(() => {
    process.exit(0);
  }, 50);
}

function runClientAutostopSweep() {
  if (!clientAutostopEnabled || shutdownRequestedByClientIdle) return;
  const nowMs = Date.now();
  if (activeHttpRequestCount > 0) {
    return;
  }
  if (nowMs - lastHttpActivityMs < Math.max(1000, clientAutostopRequestGraceMs)) {
    return;
  }
  const activeCount = sweepClientHeartbeats(nowMs);
  if (activeCount > 0) {
    noClientSinceMs = 0;
    return;
  }
  if (!hasSeenAnyClient) {
    return;
  }
  if (noClientSinceMs <= 0) {
    noClientSinceMs = nowMs;
    return;
  }
  const idleMs = nowMs - noClientSinceMs;
  if (idleMs < Math.max(1000, clientAutostopIdleMs)) {
    return;
  }
  requestIdleShutdown(idleMs);
}

const clientSweepTimer = setInterval(runClientAutostopSweep, Math.max(1000, clientHeartbeatSweepMs));
if (typeof clientSweepTimer.unref === "function") {
  clientSweepTimer.unref();
}

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

function isLikelyBinaryBuffer(buffer) {
  if (!buffer || buffer.length === 0) return false;
  const sample = buffer.subarray(0, Math.min(buffer.length, 4096));
  for (const byte of sample) {
    if (byte === 0) return true;
  }
  return false;
}

const officeFileExts = new Set([".xlsx", ".docx", ".pptx"]);

function isOfficeFileExtension(ext) {
  return officeFileExts.has(String(ext || "").trim().toLowerCase());
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
    sessions.set(sid, { messages: [], toolLogs: [], plan: [] });
    res.setHeader("Set-Cookie", `sid=${encodeURIComponent(sid)}; HttpOnly; SameSite=Lax; Path=/`);
  }
  if (!sessions.has(sid)) {
    sessions.set(sid, { messages: [], toolLogs: [], plan: [] });
  }
  const session = sessions.get(sid);
  if (!Array.isArray(session.messages)) {
    session.messages = [];
  }
  if (!Array.isArray(session.toolLogs)) {
    session.toolLogs = [];
  }
  if (!Array.isArray(session.plan)) {
    session.plan = [];
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

function beginNdjson(res, statusCode = 200) {
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/x-ndjson; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  if (typeof res.flushHeaders === "function") {
    res.flushHeaders();
  }
}

function writeNdjson(res, payload) {
  if (res.writableEnded || res.destroyed) return;
  const line = `${JSON.stringify(payload)}\n`;
  res.write(line);
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

function formatYmdInTimeZone(date, timeZone) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = formatter.formatToParts(date);
  const year = parts.find((item) => item.type === "year")?.value || "0000";
  const month = parts.find((item) => item.type === "month")?.value || "01";
  const day = parts.find((item) => item.type === "day")?.value || "01";
  return `${year}-${month}-${day}`;
}

function getTemporalContext(now = new Date()) {
  const utcIso = now.toISOString();
  const currentDateByAppTimeZone = formatYmdInTimeZone(now, appTimeZone);
  const currentDateJst = formatYmdInTimeZone(now, "Asia/Tokyo");
  return {
    utcIso,
    appTimeZone,
    currentDateByAppTimeZone,
    currentDateJst,
  };
}

function promptAsksTodayWeather(rawPrompt) {
  const text = String(rawPrompt || "");
  if (!/(今日|きょう|本日|today)/i.test(text)) return false;
  return /(天気|weather|気温|降水|雨|晴れ|曇|雪|forecast)/i.test(text);
}

function normalizeYmd(yearRaw, monthRaw, dayRaw) {
  const year = Number.parseInt(String(yearRaw || ""), 10);
  const month = Number.parseInt(String(monthRaw || ""), 10);
  const day = Number.parseInt(String(dayRaw || ""), 10);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return "";
  }
  if (year < 1900 || year > 2200 || month < 1 || month > 12 || day < 1 || day > 31) {
    return "";
  }
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function rewriteMismatchedExplicitDatesAsToday(text, todayYmd) {
  const source = String(text || "");
  const pattern = /(\d{4})\s*[\/\-.年]\s*(\d{1,2})\s*[\/\-.月]\s*(\d{1,2})\s*日?/g;
  let mismatchCount = 0;
  const replaced = source.replace(pattern, (full, year, month, day) => {
    const normalized = normalizeYmd(year, month, day);
    if (!normalized || normalized === todayYmd) {
      return full;
    }
    mismatchCount += 1;
    return "本日";
  });
  return {
    text: replaced,
    mismatchCount,
  };
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

function appendWithLimit(current, chunk, limit = maxProcessOutputChars) {
  const merged = `${String(current || "")}${String(chunk || "")}`;
  if (merged.length <= limit) return merged;
  return merged.slice(merged.length - limit);
}

function runProcessCapture(command, args, { cwd = workspaceRoot, timeoutMs = localShellTimeoutMs, env = process.env } = {}) {
  return new Promise((resolve) => {
    const started = Date.now();
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let exitCode = 0;
    let spawnError = "";
    let settled = false;

    const child = spawn(command, args, {
      cwd,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const finish = () => {
      if (settled) return;
      settled = true;
      resolve({
        command,
        args,
        stdout,
        stderr,
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
    }, Math.max(1000, timeoutMs));

    child.stdout.on("data", (chunk) => {
      stdout = appendWithLimit(stdout, chunk.toString("utf8"));
    });

    child.stderr.on("data", (chunk) => {
      stderr = appendWithLimit(stderr, chunk.toString("utf8"));
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

function getNpxCommandCandidates() {
  const candidates = [];
  if (process.execPath) {
    const npxFromNode = path.join(path.dirname(process.execPath), process.platform === "win32" ? "npx.cmd" : "npx");
    candidates.push(npxFromNode);
  }
  if (process.platform === "win32") {
    candidates.push("npx.cmd");
  }
  candidates.push("npx");
  return [...new Set(candidates)];
}

function getNpxExecutionCandidates() {
  const candidates = [];
  const seen = new Set();
  const keyFor = (command, prefixArgs) => `${String(command || "")}\n${prefixArgs.join("\n")}`;
  const pushCandidate = (command, prefixArgs = [], label = "") => {
    const cmd = String(command || "").trim();
    if (!cmd) return;
    const normalizedPrefix = Array.isArray(prefixArgs)
      ? prefixArgs.map((item) => String(item || "")).filter(Boolean)
      : [];
    const key = keyFor(cmd, normalizedPrefix);
    if (seen.has(key)) return;
    seen.add(key);
    candidates.push({
      command: cmd,
      prefixArgs: normalizedPrefix,
      label: label || cmd,
    });
  };

  const addNodeNpxCliCandidate = (nodePath, label) => {
    const nodeExec = String(nodePath || "").trim();
    if (!nodeExec || !existsSync(nodeExec)) return;
    const npxCli = path.join(path.dirname(nodeExec), "node_modules", "npm", "bin", "npx-cli.js");
    if (!existsSync(npxCli)) return;
    pushCandidate(nodeExec, [npxCli], label);
  };

  addNodeNpxCliCandidate(process.execPath, "node+npx-cli (process)");

  const bundledNode = path.join(__dirname, "..", ".runtime", "node", process.platform === "win32" ? "node.exe" : "node");
  addNodeNpxCliCandidate(path.resolve(bundledNode), "node+npx-cli (bundled)");

  for (const command of getNpxCommandCandidates()) {
    pushCandidate(command, [], `npx (${command})`);
  }

  return candidates;
}

async function runNpxWithFallback(args, { timeoutMs = playwrightMcpTimeoutMs } = {}) {
  const spawnErrors = [];
  const candidates = getNpxExecutionCandidates();
  for (const candidate of candidates) {
    const result = await runProcessCapture(candidate.command, [...candidate.prefixArgs, ...args], {
      cwd: workspaceRoot,
      timeoutMs,
    });
    if (result.spawnError) {
      spawnErrors.push(`${candidate.label}: ${result.spawnError}`);
      continue;
    }
    return {
      ...result,
      runner: candidate.label,
    };
  }
  return {
    command: candidates[0]?.command || "npx",
    args: [...(candidates[0]?.prefixArgs || []), ...args],
    stdout: "",
    stderr: "",
    exitCode: 1,
    timedOut: false,
    spawnError: spawnErrors.join("\n") || "No working npx runner found.",
    elapsedMs: 0,
    runner: "",
  };
}

async function createPlaywrightMcpConfig() {
  const tempDir = await mkdtemp(path.join(tmpdir(), "loca-playwright-mcp-"));
  const configPath = path.join(tempDir, "mcp-config.json");
  const serverArgs = [playwrightMcpPackage];
  if (playwrightMcpHeadless) {
    serverArgs.push("--headless");
  }
  if (playwrightMcpBrowser) {
    serverArgs.push("--browser", playwrightMcpBrowser);
  }
  const config = {
    mcpServers: {
      playwright: {
        command: "npx",
        args: serverArgs,
      },
    },
  };
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
  return {
    tempDir,
    configPath,
  };
}

async function callPlaywrightMcpInspector({
  method,
  toolName = "",
  toolArgs = {},
  timeoutMs = playwrightMcpTimeoutMs,
}) {
  if (!playwrightMcpEnabled) {
    throw new Error("Playwright MCP is disabled. Set PLAYWRIGHT_MCP_ENABLED=1.");
  }

  const { tempDir, configPath } = await createPlaywrightMcpConfig();
  try {
    const args = [
      mcpInspectorPackage,
      "--cli",
      "--config",
      configPath,
      "--server",
      "playwright",
      "--method",
      method,
    ];
    if (toolName) {
      args.push("--tool-name", toolName);
    }
    for (const [key, value] of Object.entries(toolArgs || {})) {
      if (value === undefined || value === null) continue;
      args.push("--tool-arg", `${key}=${String(value)}`);
    }

    const runResult = await runNpxWithFallback(args, {
      timeoutMs: Math.max(10000, timeoutMs),
    });

    if (runResult.timedOut) {
      throw new Error(`Playwright MCP command timed out (${Math.max(10000, timeoutMs)} ms).`);
    }
    if (runResult.spawnError) {
      throw new Error([
        `Failed to start MCP command (${runResult.command}).`,
        runResult.spawnError,
      ].filter(Boolean).join("\n"));
    }
    if (runResult.exitCode !== 0) {
      throw new Error([
        `MCP command failed (exit=${runResult.exitCode})`,
        runResult.stderr ? `stderr:\n${truncateText(runResult.stderr, 1600)}` : "",
        runResult.stdout ? `stdout:\n${truncateText(runResult.stdout, 1600)}` : "",
      ].filter(Boolean).join("\n\n"));
    }

    let payload = null;
    try {
      payload = parseModelJsonObject(runResult.stdout);
    } catch (err) {
      throw new Error([
        `Failed to parse MCP output JSON. ${err?.message || String(err)}`,
        runResult.stdout ? `stdout:\n${truncateText(runResult.stdout, 1200)}` : "",
        runResult.stderr ? `stderr:\n${truncateText(runResult.stderr, 1200)}` : "",
      ].filter(Boolean).join("\n\n"));
    }

    return {
      payload,
      command: runResult.command,
      stdout: runResult.stdout,
      stderr: runResult.stderr,
      elapsedMs: runResult.elapsedMs,
    };
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
}

function extractMcpToolText(payload) {
  const root = payload?.result && typeof payload.result === "object" ? payload.result : payload;
  const content = Array.isArray(root?.content) ? root.content : [];
  const textParts = [];
  for (const item of content) {
    if (typeof item === "string") {
      textParts.push(item);
      continue;
    }
    if (item && typeof item.text === "string") {
      textParts.push(item.text);
      continue;
    }
    if (item && item.type === "json" && item.json && typeof item.json === "object") {
      textParts.push(JSON.stringify(item.json));
    }
  }
  if (textParts.length > 0) {
    return textParts.join("\n").trim();
  }
  if (typeof root?.text === "string") {
    return root.text.trim();
  }
  return "";
}

async function runPlaywrightMcpTool(toolName, toolArgs = {}, { timeoutMs = playwrightMcpTimeoutMs } = {}) {
  const result = await callPlaywrightMcpInspector({
    method: "tools/call",
    toolName,
    toolArgs,
    timeoutMs,
  });
  const root = result.payload?.result && typeof result.payload.result === "object"
    ? result.payload.result
    : result.payload;
  const text = extractMcpToolText(result.payload);
  if (root?.isError === true || result.payload?.isError === true) {
    throw new Error(text || truncateText(result.stderr || result.stdout || `MCP tool ${toolName} failed.`, 2000));
  }
  return {
    text,
    payload: result.payload,
    command: result.command,
    stdout: result.stdout,
    stderr: result.stderr,
    elapsedMs: result.elapsedMs,
  };
}

function extractPageUrlFromMcpText(rawText) {
  const text = String(rawText || "");
  const match = text.match(/- Page URL:\s*([^\r\n]+)/);
  return String(match?.[1] || "").trim();
}

function resolveSnapshotUrl(rawUrl, pageUrl) {
  const value = String(rawUrl || "").trim();
  if (!value) return "";
  if (/^javascript:/i.test(value)) return "";
  try {
    if (/^https?:\/\//i.test(value)) {
      return value;
    }
    if (pageUrl) {
      return new URL(value, pageUrl).toString();
    }
    return "";
  } catch {
    return "";
  }
}

function isSearchEngineInternalUrl(urlValue, engineName) {
  const value = String(urlValue || "").trim();
  if (!value) return true;
  let parsed = null;
  try {
    parsed = new URL(value);
  } catch {
    return true;
  }
  const host = String(parsed.hostname || "").toLowerCase();
  if (!host) return true;
  if (engineName === "yahoo") {
    return host === "search.yahoo.co.jp" || host === "www.yahoo.co.jp";
  }
  if (engineName === "bing") {
    return host === "bing.com" || host.endsWith(".bing.com");
  }
  if (engineName === "duckduckgo") {
    return host === "duckduckgo.com" || host === "html.duckduckgo.com" || host.endsWith(".duckduckgo.com");
  }
  return false;
}

function isLowValueSearchLink(title, urlValue, engineName) {
  const normalizedTitle = String(title || "").replace(/\s+/g, " ").trim().toLowerCase();
  const genericTitles = new Set([
    "ログイン",
    "検索",
    "すべて",
    "画像",
    "動画",
    "ニュース",
    "地図",
    "知恵袋",
    "条件指定",
    "検索設定",
    "yahoo! japan",
    "bing 検索に戻る",
    "duckduckgo home",
  ]);
  if (genericTitles.has(normalizedTitle)) return true;

  let host = "";
  try {
    host = new URL(String(urlValue || "")).hostname.toLowerCase();
  } catch {
    return true;
  }
  const lowValueHosts = new Set([
    "login.yahoo.co.jp",
    "www.yahoo.co.jp",
    "chiebukuro.yahoo.co.jp",
    "map.yahoo.co.jp",
  ]);
  if (lowValueHosts.has(host)) return true;
  if (engineName === "bing" && (host === "bing.com" || host.endsWith(".bing.com"))) return true;
  if (engineName === "yahoo" && host === "search.yahoo.co.jp") return true;
  return false;
}

function scoreSearchResult({ title = "", url = "", snippet = "" }) {
  const haystack = `${title}\n${url}\n${snippet}`.toLowerCase();
  let score = 0;
  if (/天気|weather|forecast|予報|気象/.test(haystack)) score += 10;
  if (/weather\.yahoo\.co\.jp|tenki\.jp|weathernews\.jp|jma\.go\.jp|nhk\.or\.jp/.test(haystack)) score += 8;
  if (/ログイン|検索設定|知恵袋|地図/.test(haystack)) score -= 8;
  return score;
}

function extractSearchResultsFromSnapshotText(rawText, { pageUrl = "", engineName = "", maxResults = 5 } = {}) {
  const text = String(rawText || "");
  const lines = text.split(/\r?\n/);
  const seen = new Set();
  const rows = [];
  const limit = Math.max(1, Math.min(10, Number.isInteger(maxResults) ? maxResults : playwrightMcpMaxResults));

  for (let i = 0; i < lines.length; i += 1) {
    const titleMatch = lines[i].match(/^\s*-\s+link\s+"([^"]+)"/);
    if (!titleMatch) continue;
    const title = String(titleMatch[1] || "").replace(/\s+/g, " ").trim();
    if (!title) continue;

    let rawUrl = "";
    let snippet = "";
    for (let j = i + 1; j < Math.min(lines.length, i + 18); j += 1) {
      if (!rawUrl) {
        const urlMatch = lines[j].match(/^\s*-\s+\/url:\s*(.+)$/);
        if (urlMatch) {
          rawUrl = String(urlMatch[1] || "").trim();
          continue;
        }
      }
      if (!snippet) {
        const paragraphMatch = lines[j].match(/^\s*-\s+paragraph(?:\s+\[[^\]]+\])?:\s*(.+)$/);
        if (paragraphMatch) {
          snippet = String(paragraphMatch[1] || "").replace(/\s+/g, " ").trim();
          continue;
        }
        const textMatch = lines[j].match(/^\s*-\s+text:\s*(.+)$/);
        if (textMatch) {
          snippet = String(textMatch[1] || "").replace(/\s+/g, " ").trim();
          continue;
        }
      }
      if (j > i + 1 && /^\s*-\s+link\s+"/.test(lines[j])) {
        break;
      }
    }

    const url = resolveSnapshotUrl(rawUrl, pageUrl);
    if (!url) continue;
    if (isSearchEngineInternalUrl(url, engineName)) continue;
    if (isLowValueSearchLink(title, url, engineName)) continue;
    if (seen.has(url)) continue;
    seen.add(url);
    rows.push({
      title,
      url,
      snippet: truncateText(snippet, 400),
      score: scoreSearchResult({ title, url, snippet }),
    });
  }

  return rows
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map(({ title, url, snippet }) => ({ title, url, snippet }));
}

async function runPlaywrightNavigateWithInstall(url) {
  try {
    return await runPlaywrightMcpTool("browser_navigate", { url });
  } catch (err) {
    const message = err?.message || String(err);
    if (!/browser.*not installed|run browser_install|please install/i.test(message)) {
      throw err;
    }
    await runPlaywrightMcpTool(
      "browser_install",
      {},
      { timeoutMs: Math.max(playwrightMcpTimeoutMs, 600000) },
    );
    return runPlaywrightMcpTool("browser_navigate", { url });
  }
}

async function runPlaywrightWebSearch(query, requestedMaxResults) {
  if (!playwrightMcpEnabled) {
    throw new Error("Playwright MCP is disabled. Set PLAYWRIGHT_MCP_ENABLED=1.");
  }

  const normalizedQuery = String(query || "").replace(/\s+/g, " ").trim();
  if (!normalizedQuery) {
    throw new Error("Query is empty.");
  }

  const parsedMax = Number.parseInt(String(requestedMaxResults ?? ""), 10);
  const maxResults = Math.max(
    1,
    Math.min(10, Number.isInteger(parsedMax) ? parsedMax : playwrightMcpMaxResults),
  );

  const targets = [
    {
      engine: "yahoo",
      url: `https://search.yahoo.co.jp/search?p=${encodeURIComponent(normalizedQuery)}`,
    },
    {
      engine: "bing",
      url: `https://www.bing.com/search?q=${encodeURIComponent(normalizedQuery)}`,
    },
  ];

  const failures = [];
  for (const target of targets) {
    try {
      const navigation = await runPlaywrightNavigateWithInstall(target.url);
      const snapshotText = String(navigation.text || "");
      const pageUrl = extractPageUrlFromMcpText(snapshotText) || target.url;
      const results = extractSearchResultsFromSnapshotText(snapshotText, {
        pageUrl,
        engineName: target.engine,
        maxResults,
      });

      if (results.length > 0) {
        return {
          query: normalizedQuery,
          source: pageUrl,
          results,
          command: navigation.command,
          elapsedMs: navigation.elapsedMs,
        };
      }

      const challengeDetected = /captcha|challenge|ボット|automated queries|forbidden|429/i.test(snapshotText);
      failures.push([
        `${target.engine}: no parseable results`,
        challengeDetected ? "challenge_detected=yes" : "challenge_detected=no",
      ].join(" "));
    } catch (err) {
      failures.push(`${target.engine}: ${err?.message || String(err)}`);
    }
  }

  throw new Error([
    "Playwright web search returned no parseable results.",
    ...failures.slice(0, 4),
  ].join("\n"));
}

function buildPythonSpawnCandidates(basePythonArgs) {
  const pyArgs = Array.isArray(basePythonArgs) ? basePythonArgs : [];
  const candidates = [];
  const addCandidate = (command, args) => {
    const cmd = String(command || "").trim();
    if (!cmd) return;
    const normalized = `${cmd}\u0000${JSON.stringify(args || [])}`;
    if (candidates.some((item) => item.key === normalized)) {
      return;
    }
    candidates.push({
      key: normalized,
      command: cmd,
      args: Array.isArray(args) ? args : [],
    });
  };

  if (configuredPythonBin) {
    addCandidate(configuredPythonBin, pyArgs);
  }
  if (configuredUvBin) {
    addCandidate(configuredUvBin, ["run", "python", ...pyArgs]);
  }
  addCandidate("python", pyArgs);
  addCandidate("uv", ["run", "python", ...pyArgs]);
  return candidates;
}

async function extractPdfTextViaPython(absPath) {
  const script = [
    "import json, sys",
    "import fitz",
    "pdf_path = sys.argv[1]",
    "max_pages = int(sys.argv[2])",
    "max_chars = int(sys.argv[3])",
    "doc = fitz.open(pdf_path)",
    "total_pages = doc.page_count",
    "read_pages = min(total_pages, max_pages)",
    "chunks = []",
    "for i in range(read_pages):",
    "    text = doc.load_page(i).get_text('text') or ''",
    "    text = text.strip()",
    "    if text:",
    "        chunks.append(f'--- page {i + 1} ---\\n{text}')",
    "joined = '\\n\\n'.join(chunks).strip()",
    "truncated = False",
    "if len(joined) > max_chars:",
    "    joined = joined[:max_chars]",
    "    truncated = True",
    "payload = {",
    "  'ok': True,",
    "  'total_pages': total_pages,",
    "  'read_pages': read_pages,",
    "  'truncated': truncated,",
    "  'text': joined,",
    "}",
    "print(json.dumps(payload, ensure_ascii=False))",
  ].join("\n");

  const runExtractor = (command, args) => new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    let settled = false;

    const child = spawn(command, args, {
      cwd: workspaceRoot,
      env: {
        ...process.env,
        PYTHONUTF8: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    const finish = (err, payload = null) => {
      if (settled) return;
      settled = true;
      if (err) {
        reject(err);
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
      finish(new Error("PDF extraction timed out."));
    }, Math.max(5000, localShellTimeoutMs * 2));

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      if (stdout.length > maxToolOutputChars * 4) {
        stdout = stdout.slice(-maxToolOutputChars * 4);
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
      if (stderr.length > maxToolOutputChars * 2) {
        stderr = stderr.slice(-maxToolOutputChars * 2);
      }
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      finish(new Error(err?.message || String(err)));
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        finish(new Error(`PDF extraction failed (exit=${code}). ${truncateText(stderr, 800)}`));
        return;
      }
      try {
        const parsed = JSON.parse(String(stdout || "").trim());
        if (!parsed || typeof parsed !== "object") {
          throw new Error("Invalid extractor payload.");
        }
        finish(null, parsed);
      } catch (err) {
        finish(new Error(`PDF extraction parse failed. ${err?.message || String(err)}`));
      }
    });
  });

  const pythonArgs = [
    "-c",
    script,
    absPath,
    String(Math.max(1, maxPdfReadPages)),
    String(Math.max(2000, maxPdfReadChars)),
  ];
  const candidates = buildPythonSpawnCandidates(pythonArgs);
  let lastError = null;
  for (const candidate of candidates) {
    try {
      return await runExtractor(candidate.command, candidate.args);
    } catch (err) {
      lastError = err;
    }
  }
  throw (lastError || new Error("PDF extraction failed."));
}

async function runOfficeHelperViaPython({ action, absPath, content = "", maxChars = maxOfficeReadChars, maxItems = maxOfficeReadItems }) {
  const normalizedAction = String(action || "").trim().toLowerCase();
  if (normalizedAction !== "read" && normalizedAction !== "write") {
    throw new Error(`Unsupported office helper action: ${action}`);
  }

  const readArgs = normalizedAction === "read"
    ? [
        String(Math.max(1000, maxChars)),
        String(Math.max(1, maxItems)),
      ]
    : [];

  const runHelper = (command, args) => new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    let settled = false;
    const child = spawn(command, args, {
      cwd: workspaceRoot,
      env: {
        ...process.env,
        PYTHONUTF8: "1",
      },
      stdio: ["pipe", "pipe", "pipe"],
    });

    const finish = (err, payload = null) => {
      if (settled) return;
      settled = true;
      if (err) {
        reject(err);
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
      finish(new Error("Office helper timed out."));
    }, Math.max(5000, localShellTimeoutMs * 3));

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      if (stdout.length > maxToolOutputChars * 4) {
        stdout = stdout.slice(-maxToolOutputChars * 4);
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
      if (stderr.length > maxToolOutputChars * 2) {
        stderr = stderr.slice(-maxToolOutputChars * 2);
      }
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      finish(new Error(err?.message || String(err)));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      let parsed = null;
      try {
        const text = String(stdout || "").trim();
        parsed = text ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      if (code !== 0) {
        const errMessage = String(parsed?.error || "").trim()
          || truncateText(stderr || stdout || `office helper failed (exit=${code})`, 800);
        finish(new Error(errMessage));
        return;
      }
      if (!parsed || typeof parsed !== "object") {
        finish(new Error("Office helper parse failed."));
        return;
      }
      if (parsed.ok !== true) {
        const errMessage = String(parsed.error || "").trim() || "Office helper returned an error.";
        finish(new Error(errMessage));
        return;
      }
      finish(null, parsed);
    });

    if (normalizedAction === "write") {
      try {
        child.stdin.write(String(content || ""), "utf8");
      } catch {
        // ignore write errors and allow process to fail naturally.
      }
    }
    try {
      child.stdin.end();
    } catch {
      // ignore
    }
  });

  const pythonArgs = [officeHelperScript, normalizedAction, absPath, ...readArgs];
  const candidates = buildPythonSpawnCandidates(pythonArgs);
  let lastError = null;
  for (const candidate of candidates) {
    try {
      return await runHelper(candidate.command, candidate.args);
    } catch (err) {
      lastError = err;
    }
  }
  throw (lastError || new Error("Office helper failed."));
}

async function extractOfficeTextViaPython(absPath) {
  return runOfficeHelperViaPython({
    action: "read",
    absPath,
    maxChars: maxOfficeReadChars,
    maxItems: maxOfficeReadItems,
  });
}

async function writeOfficeFileViaPython(absPath, content) {
  return runOfficeHelperViaPython({
    action: "write",
    absPath,
    content,
  });
}

async function readLocalFileForTool(rawPath) {
  const resolvedPath = resolveWorkspacePath(rawPath);
  const info = await stat(resolvedPath);
  if (!info.isFile()) {
    throw new Error(`Not a file: ${rawPath}`);
  }

  const ext = path.extname(resolvedPath).toLowerCase();
  const isPdf = ext === ".pdf";
  const isOffice = isOfficeFileExtension(ext);
  const allowedReadBytes = isPdf
    ? Math.max(1024, maxPdfReadBytes)
    : (isOffice ? Math.max(1024, maxOfficeReadBytes) : Math.max(1024, maxReadBytes));
  if (info.size > allowedReadBytes) {
    const limitName = isPdf ? "MAX_PDF_READ_BYTES" : (isOffice ? "MAX_OFFICE_READ_BYTES" : "MAX_READ_BYTES");
    throw new Error(`File too large (${info.size} bytes). ${limitName}=${allowedReadBytes}.`);
  }

  const displayPath = toWorkspaceRelative(resolvedPath);
  let content = "";
  let meta = `bytes=${info.size}`;
  let modelPayload = {};

  if (isPdf) {
    const extracted = await extractPdfTextViaPython(resolvedPath);
    content = String(extracted?.text || "").trim();
    const totalPages = Number.isInteger(extracted?.total_pages) ? extracted.total_pages : 0;
    const readPages = Number.isInteger(extracted?.read_pages) ? extracted.read_pages : 0;
    const truncated = extracted?.truncated === true;
    meta = [
      `bytes=${info.size}`,
      `pages=${totalPages}`,
      `read_pages=${readPages}`,
      `truncated=${truncated ? "yes" : "no"}`,
    ].join(" ");
    if (!content) {
      content = "(No extractable text found in PDF.)";
    }
    modelPayload = {
      format: "pdf",
      totalPages,
      readPages,
      truncated,
    };
  } else if (isOffice) {
    const extracted = await extractOfficeTextViaPython(resolvedPath);
    content = String(extracted?.text || "").trim();
    const format = String(extracted?.format || ext.replace(/^\./, "")).toLowerCase();
    const truncated = extracted?.truncated === true;

    const metaParts = [
      `bytes=${info.size}`,
      `format=${format}`,
    ];
    if (Number.isInteger(extracted?.sheets)) {
      metaParts.push(`sheets=${extracted.sheets}`);
    }
    if (Number.isInteger(extracted?.cells)) {
      metaParts.push(`cells=${extracted.cells}`);
    }
    if (Number.isInteger(extracted?.paragraphs)) {
      metaParts.push(`paragraphs=${extracted.paragraphs}`);
    }
    if (Number.isInteger(extracted?.slides)) {
      metaParts.push(`slides=${extracted.slides}`);
    }
    if (Number.isInteger(extracted?.text_runs)) {
      metaParts.push(`text_runs=${extracted.text_runs}`);
    }
    metaParts.push(`truncated=${truncated ? "yes" : "no"}`);
    meta = metaParts.join(" ");
    if (!content) {
      content = "(No extractable text found in Office document.)";
    }
    modelPayload = {
      format,
      parser: String(extracted?.parser || "openxml-zip"),
      truncated,
      sheets: Number.isInteger(extracted?.sheets) ? extracted.sheets : undefined,
      cells: Number.isInteger(extracted?.cells) ? extracted.cells : undefined,
      paragraphs: Number.isInteger(extracted?.paragraphs) ? extracted.paragraphs : undefined,
      slides: Number.isInteger(extracted?.slides) ? extracted.slides : undefined,
      textRuns: Number.isInteger(extracted?.text_runs) ? extracted.text_runs : undefined,
    };
  } else {
    const fileBuffer = await readFile(resolvedPath);
    if (isLikelyBinaryBuffer(fileBuffer)) {
      const previewHex = fileBuffer.subarray(0, Math.min(64, fileBuffer.length)).toString("hex");
      content = [
        `Binary file (${fileBuffer.length} bytes).`,
        `hex_preview=${previewHex}`,
        "Use a dedicated parser if text extraction is required.",
      ].join("\n");
      modelPayload = {
        format: "binary",
        hexPreview: previewHex,
      };
    } else {
      content = fileBuffer.toString("utf8");
      modelPayload = {
        format: "text",
      };
    }
  }

  return {
    resolvedPath,
    displayPath,
    sizeBytes: info.size,
    meta,
    content,
    shown: truncateText(content, maxToolOutputChars),
    modelPayload,
  };
}

function sanitizeModelPath(value) {
  return String(value || "")
    .trim()
    .replace(/^\.([\\/])/, "")
    .replaceAll("\\", "/");
}

async function readWorkspaceTextIfExists(relPath) {
  const normalized = sanitizeModelPath(relPath);
  try {
    const resolvedPath = resolveWorkspacePath(normalized);
    const info = await stat(resolvedPath);
    if (!info.isFile()) {
      throw new Error("Path is not a file.");
    }
    if (info.size > Math.max(1024, maxReadBytes)) {
      throw new Error(`File is too large (${info.size} bytes).`);
    }
    const content = await readFile(resolvedPath, "utf8");
    return {
      exists: true,
      relPath: toWorkspaceRelative(resolvedPath),
      resolvedPath,
      content,
      sizeBytes: info.size,
      error: "",
    };
  } catch (err) {
    if (err?.code === "ENOENT") {
      return {
        exists: false,
        relPath: normalized,
        resolvedPath: "",
        content: "",
        sizeBytes: 0,
        error: "",
      };
    }
    return {
      exists: false,
      relPath: normalized,
      resolvedPath: "",
      content: "",
      sizeBytes: 0,
      error: err?.message || String(err),
    };
  }
}

function clampInteger(value, fallback, min, max) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isInteger(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function splitTextLines(text) {
  const normalized = String(text || "").replaceAll("\r\n", "\n");
  if (normalized.length === 0) {
    return { lines: [], hasTrailingNewline: false };
  }
  const hasTrailingNewline = normalized.endsWith("\n");
  const lines = normalized.split("\n");
  if (hasTrailingNewline) {
    lines.pop();
  }
  return { lines, hasTrailingNewline };
}

async function readTextFileSliceForTool(rawPath, offsetRaw, limitRaw) {
  const relPath = sanitizeModelPath(rawPath);
  if (!relPath) {
    throw new Error("Path is empty.");
  }
  const resolvedPath = resolveWorkspacePath(relPath);
  const info = await stat(resolvedPath);
  if (!info.isFile()) {
    throw new Error(`Not a file: ${relPath}`);
  }
  if (info.size > Math.max(1024, maxReadBytes)) {
    throw new Error(`File is too large (${info.size} bytes). MAX_READ_BYTES=${Math.max(1024, maxReadBytes)}.`);
  }
  const ext = path.extname(resolvedPath).toLowerCase();
  if (isOfficeFileExtension(ext)) {
    throw new Error("Office file cannot be read with read_file. Use read instead.");
  }

  const fileBuffer = await readFile(resolvedPath);
  if (isLikelyBinaryBuffer(fileBuffer)) {
    throw new Error("Binary file cannot be read with read_file. Use read instead.");
  }
  const text = fileBuffer.toString("utf8");
  const split = splitTextLines(text);
  const totalLines = split.lines.length;
  const offset = clampInteger(offsetRaw, 1, 1, Math.max(1, totalLines || 1));
  const limit = clampInteger(limitRaw, 120, 1, 400);
  const fromIndex = offset - 1;
  const toIndexExclusive = Math.min(totalLines, fromIndex + limit);
  const selected = split.lines.slice(fromIndex, toIndexExclusive);
  const numbered = selected.map((line, idx) => {
    const lineNo = fromIndex + idx + 1;
    return `${String(lineNo).padStart(6, " ")}\t${line}`;
  });

  return {
    relPath: toWorkspaceRelative(resolvedPath).replaceAll("\\", "/"),
    sizeBytes: info.size,
    totalLines,
    offset,
    limit,
    returnedLines: selected.length,
    content: numbered.join("\n"),
  };
}

async function listWorkspaceEntriesForTool({
  rawPath = ".",
  recursive = false,
  maxDepth = 2,
  limit = 200,
} = {}) {
  const relPath = sanitizeModelPath(rawPath || ".") || ".";
  const resolvedPath = resolveWorkspacePath(relPath);
  const rootInfo = await stat(resolvedPath);
  const maxEntries = Math.max(1, Math.min(500, limit));
  const depthLimit = Math.max(0, Math.min(6, maxDepth));

  if (rootInfo.isFile()) {
    return {
      root: toWorkspaceRelative(resolvedPath).replaceAll("\\", "/"),
      entries: [{
        path: toWorkspaceRelative(resolvedPath).replaceAll("\\", "/"),
        type: "file",
        size: rootInfo.size,
      }],
      truncated: false,
    };
  }

  if (!rootInfo.isDirectory()) {
    throw new Error(`Not a directory: ${relPath}`);
  }

  const entries = [];
  let truncated = false;
  const walk = async (currentAbsPath, depth) => {
    if (entries.length >= maxEntries) {
      truncated = true;
      return;
    }
    let children = await readdir(currentAbsPath, { withFileTypes: true });
    children = children
      .filter((entry) => entry.name !== ".git")
      .sort((a, b) => a.name.localeCompare(b.name, "en"));
    for (const child of children) {
      if (entries.length >= maxEntries) {
        truncated = true;
        break;
      }
      const childAbs = path.join(currentAbsPath, child.name);
      const childRel = toWorkspaceRelative(childAbs).replaceAll("\\", "/");
      if (child.isDirectory()) {
        entries.push({ path: childRel, type: "dir" });
        if (recursive && depth < depthLimit) {
          await walk(childAbs, depth + 1);
        }
        continue;
      }
      if (child.isFile()) {
        let size = 0;
        try {
          size = (await stat(childAbs)).size;
        } catch {
          size = 0;
        }
        entries.push({ path: childRel, type: "file", size });
        continue;
      }
      entries.push({ path: childRel, type: "other" });
    }
  };
  await walk(resolvedPath, 0);
  return {
    root: toWorkspaceRelative(resolvedPath).replaceAll("\\", "/"),
    entries,
    truncated,
  };
}

function parseUpdatePatchLines(rawLines) {
  const lines = Array.isArray(rawLines) ? rawLines : [];
  const chunks = [];
  let current = [];
  for (const rawLine of lines) {
    const line = String(rawLine || "");
    if (line.startsWith("@@")) {
      if (current.length > 0) {
        chunks.push(current);
        current = [];
      }
      continue;
    }
    if (line === "\\ No newline at end of file") {
      continue;
    }
    const op = line[0];
    if (op === " " || op === "+" || op === "-") {
      current.push({ op, text: line.slice(1) });
      continue;
    }
    throw new Error(`Invalid patch line in update section: ${line}`);
  }
  if (current.length > 0) {
    chunks.push(current);
  }
  return chunks;
}

function findLineSequence(lines, needle, startIndex = 0) {
  if (!Array.isArray(lines) || !Array.isArray(needle)) return -1;
  if (needle.length === 0) return Math.max(0, startIndex);
  const maxStart = lines.length - needle.length;
  for (let i = Math.max(0, startIndex); i <= maxStart; i += 1) {
    let matched = true;
    for (let j = 0; j < needle.length; j += 1) {
      if (lines[i + j] !== needle[j]) {
        matched = false;
        break;
      }
    }
    if (matched) return i;
  }
  return -1;
}

function applyUpdateChunksToText(oldText, chunks) {
  const split = splitTextLines(oldText);
  const oldLines = split.lines;
  const outLines = [];
  let cursor = 0;

  for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex += 1) {
    const chunk = chunks[chunkIndex];
    const anchor = chunk
      .filter((token) => token.op !== "+")
      .map((token) => token.text);
    let start = cursor;
    if (anchor.length > 0) {
      start = findLineSequence(oldLines, anchor, cursor);
      if (start < 0) {
        start = findLineSequence(oldLines, anchor, 0);
      }
      if (start < 0) {
        throw new Error(`Patch hunk #${chunkIndex + 1} does not match target file.`);
      }
    }

    outLines.push(...oldLines.slice(cursor, start));
    let readIndex = start;
    for (const token of chunk) {
      if (token.op === " ") {
        if (oldLines[readIndex] !== token.text) {
          throw new Error(`Patch context mismatch in hunk #${chunkIndex + 1}.`);
        }
        outLines.push(oldLines[readIndex]);
        readIndex += 1;
      } else if (token.op === "-") {
        if (oldLines[readIndex] !== token.text) {
          throw new Error(`Patch deletion mismatch in hunk #${chunkIndex + 1}.`);
        }
        readIndex += 1;
      } else if (token.op === "+") {
        outLines.push(token.text);
      }
    }
    cursor = readIndex;
  }

  outLines.push(...oldLines.slice(cursor));
  let updatedText = outLines.join("\n");
  if (split.hasTrailingNewline) {
    updatedText += "\n";
  }
  return updatedText;
}

function parseApplyPatchOperations(rawPatch) {
  const text = String(rawPatch || "").replaceAll("\r\n", "\n");
  if (!text.trim()) {
    throw new Error("Patch text is empty.");
  }
  const lines = text.split("\n");
  let idx = 0;
  while (idx < lines.length && !lines[idx].trim()) idx += 1;
  if (lines[idx] !== "*** Begin Patch") {
    throw new Error("Patch must start with '*** Begin Patch'.");
  }
  idx += 1;

  const operations = [];
  while (idx < lines.length) {
    const line = String(lines[idx] || "");
    if (!line.trim()) {
      idx += 1;
      continue;
    }
    if (line === "*** End Patch") {
      idx += 1;
      break;
    }
    if (line.startsWith("*** Add File: ")) {
      const relPath = sanitizeModelPath(line.slice("*** Add File: ".length));
      if (!relPath) throw new Error("Add File path is empty.");
      idx += 1;
      const contentLines = [];
      while (idx < lines.length && !String(lines[idx] || "").startsWith("*** ")) {
        const row = String(lines[idx] || "");
        if (!row.startsWith("+")) {
          throw new Error(`Add File expects '+' lines only: ${row}`);
        }
        contentLines.push(row);
        idx += 1;
      }
      if (contentLines.length === 0) {
        throw new Error(`Add File has no content: ${relPath}`);
      }
      operations.push({
        type: "add",
        path: relPath,
        contentLines,
      });
      continue;
    }
    if (line.startsWith("*** Delete File: ")) {
      const relPath = sanitizeModelPath(line.slice("*** Delete File: ".length));
      if (!relPath) throw new Error("Delete File path is empty.");
      idx += 1;
      operations.push({
        type: "delete",
        path: relPath,
      });
      continue;
    }
    if (line.startsWith("*** Update File: ")) {
      const relPath = sanitizeModelPath(line.slice("*** Update File: ".length));
      if (!relPath) throw new Error("Update File path is empty.");
      idx += 1;
      let moveTo = "";
      if (idx < lines.length && String(lines[idx] || "").startsWith("*** Move to: ")) {
        moveTo = sanitizeModelPath(String(lines[idx] || "").slice("*** Move to: ".length));
        if (!moveTo) throw new Error("Move to path is empty.");
        idx += 1;
      }
      const patchLines = [];
      while (idx < lines.length && !String(lines[idx] || "").startsWith("*** ")) {
        patchLines.push(String(lines[idx] || ""));
        idx += 1;
      }
      operations.push({
        type: "update",
        path: relPath,
        moveTo,
        patchLines,
      });
      continue;
    }

    throw new Error(`Unknown patch section header: ${line}`);
  }

  if (operations.length === 0) {
    throw new Error("Patch has no operations.");
  }
  return operations;
}

async function applyPatchOperations(rawPatch) {
  const operations = parseApplyPatchOperations(rawPatch);
  const results = [];

  for (const op of operations) {
    if (op.type === "add") {
      const relPath = sanitizeModelPath(op.path);
      const resolvedPath = resolveWorkspacePath(relPath);
      if (existsSync(resolvedPath)) {
        throw new Error(`Add File target already exists: ${relPath}`);
      }
      const content = `${op.contentLines.map((line) => line.slice(1)).join("\n")}\n`;
      await mkdir(path.dirname(resolvedPath), { recursive: true });
      await writeFile(resolvedPath, content, "utf8");
      const diff = await createPreviewDiff({
        relPath,
        oldContent: "",
        newContent: content,
      });
      results.push({
        action: "add",
        path: relPath,
        bytes: Buffer.byteLength(content, "utf8"),
        diff,
      });
      continue;
    }

    if (op.type === "delete") {
      const relPath = sanitizeModelPath(op.path);
      const snapshot = await readWorkspaceTextIfExists(relPath);
      if (!snapshot.exists || !snapshot.resolvedPath) {
        throw new Error(`Delete File target not found: ${relPath}`);
      }
      await unlink(snapshot.resolvedPath);
      const diff = await createPreviewDiff({
        relPath,
        oldContent: snapshot.content,
        newContent: "",
      });
      results.push({
        action: "delete",
        path: relPath,
        bytes: 0,
        diff,
      });
      continue;
    }

    if (op.type === "update") {
      const fromRelPath = sanitizeModelPath(op.path);
      const snapshot = await readWorkspaceTextIfExists(fromRelPath);
      if (!snapshot.exists || !snapshot.resolvedPath) {
        throw new Error(`Update File target not found: ${fromRelPath}`);
      }
      const chunks = parseUpdatePatchLines(op.patchLines);
      const newContent = chunks.length === 0
        ? snapshot.content
        : applyUpdateChunksToText(snapshot.content, chunks);

      const toRelPath = op.moveTo ? sanitizeModelPath(op.moveTo) : fromRelPath;
      const toResolvedPath = resolveWorkspacePath(toRelPath);
      if (fromRelPath !== toRelPath && existsSync(toResolvedPath)) {
        throw new Error(`Move destination already exists: ${toRelPath}`);
      }
      await mkdir(path.dirname(toResolvedPath), { recursive: true });
      await writeFile(toResolvedPath, newContent, "utf8");
      if (fromRelPath !== toRelPath) {
        await unlink(snapshot.resolvedPath);
      }
      const diff = await createPreviewDiff({
        relPath: toRelPath,
        oldContent: snapshot.content,
        newContent,
      });
      results.push({
        action: fromRelPath === toRelPath ? "update" : "move_update",
        path: toRelPath,
        fromPath: fromRelPath === toRelPath ? "" : fromRelPath,
        bytes: Buffer.byteLength(newContent, "utf8"),
        diff,
      });
    }
  }

  return results;
}

function extractJsonObjectCandidates(rawText) {
  const text = String(rawText || "").trim();
  if (!text) return [];

  const candidates = [text];
  const blockRegex = /```(?:json)?\s*([\s\S]*?)```/gi;
  for (const match of text.matchAll(blockRegex)) {
    if (match[1]) {
      candidates.push(String(match[1]).trim());
    }
  }

  const extractFirstBalancedObject = (source) => {
    const s = String(source || "");
    const start = s.indexOf("{");
    if (start < 0) return "";
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let i = start; i < s.length; i += 1) {
      const ch = s[i];
      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (ch === "\\") {
          escaped = true;
        } else if (ch === "\"") {
          inString = false;
        }
        continue;
      }
      if (ch === "\"") {
        inString = true;
        continue;
      }
      if (ch === "{") {
        depth += 1;
        continue;
      }
      if (ch === "}") {
        depth -= 1;
        if (depth === 0) {
          return s.slice(start, i + 1).trim();
        }
      }
    }
    return "";
  };

  const firstBalanced = extractFirstBalancedObject(text);
  if (firstBalanced) {
    candidates.push(firstBalanced);
  }

  const firstBrace = text.indexOf("{");
  const lastBrace = text.lastIndexOf("}");
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    candidates.push(text.slice(firstBrace, lastBrace + 1).trim());
  }

  return [...new Set(candidates.map((item) => String(item || "").trim()).filter(Boolean))];
}

function tryParseJsonObjectCandidate(candidate) {
  const sample = String(candidate || "").trim();
  if (!sample) return null;
  try {
    const parsed = JSON.parse(sample);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed;
    }
  } catch {
    // ignore
  }
  return null;
}

function normalizeJsonLikeObjectText(rawText) {
  let text = String(rawText || "").trim();
  if (!text) return "";

  text = text
    .replace(/^\uFEFF/, "")
    .replaceAll("\r\n", "\n")
    .replace(/[\u201C\u201D]/g, "\"")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/\bTrue\b/g, "true")
    .replace(/\bFalse\b/g, "false")
    .replace(/\bNone\b/g, "null");

  // trailing commas are common in model JSON-like output
  text = text.replace(/,\s*([}\]])/g, "$1");

  // quote unquoted keys: {type: "tool"} -> {"type": "tool"}
  text = text.replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)/g, "$1\"$2\"$3");

  // single quoted strings -> JSON double quoted strings
  text = text.replace(/'([^'\\]*(?:\\.[^'\\]*)*)'/g, (_match, inner) => {
    const source = String(inner || "")
      .replace(/\\'/g, "'")
      .replace(/\r/g, "\\r")
      .replace(/\n/g, "\\n")
      .replace(/\t/g, "\\t");
    const escaped = source.replace(/\\/g, "\\\\").replace(/\"/g, "\\\"");
    return `"${escaped}"`;
  });

  return text.trim();
}

function parseModelJsonObject(rawText) {
  const text = String(rawText || "").trim();
  if (!text) {
    throw new Error("Model response is empty.");
  }

  const candidates = extractJsonObjectCandidates(text);
  for (const candidate of candidates) {
    const parsed = tryParseJsonObjectCandidate(candidate);
    if (parsed) {
      return parsed;
    }
  }

  const repairedCandidates = [
    ...new Set(candidates.map((candidate) => normalizeJsonLikeObjectText(candidate)).filter(Boolean)),
  ];
  for (const candidate of repairedCandidates) {
    const parsed = tryParseJsonObjectCandidate(candidate);
    if (parsed) {
      return parsed;
    }
  }

  throw new Error(`Model JSON parse failed. raw=${truncateText(text, 1200)}`);
}

async function repairModelJsonObjectViaModel({ rawText, model }) {
  const repairedRaw = await callRunPodChatText({
    model,
    temperature: 0,
    messages: [
      { role: "system", content: autoToolJsonRepairSystemPrompt },
      {
        role: "user",
        content: [
          "Convert this malformed output into one valid JSON object following the schema.",
          "raw_output:",
          truncateText(rawText, Math.max(1200, autoToolJsonRepairMaxChars)),
        ].join("\n\n"),
      },
    ],
    maxTokens: Math.min(Math.max(512, autoToolMaxTokens), 1400),
  });
  return parseModelJsonObject(repairedRaw);
}

function normalizePlanObject(rawObject) {
  const obj = rawObject && typeof rawObject === "object" ? rawObject : {};
  const tasksRaw = Array.isArray(obj.tasks) ? obj.tasks : [];
  const targetRaw = Array.isArray(obj.target_files)
    ? obj.target_files
    : (Array.isArray(obj.targetFiles) ? obj.targetFiles : []);
  const validationRaw = Array.isArray(obj.validation_commands)
    ? obj.validation_commands
    : (Array.isArray(obj.validationCommands) ? obj.validationCommands : []);

  const targetFiles = targetRaw
    .map((item) => {
      if (typeof item === "string") {
        return { path: sanitizeModelPath(item), reason: "" };
      }
      if (!item || typeof item !== "object") {
        return null;
      }
      const p = sanitizeModelPath(item.path);
      if (!p) return null;
      return { path: p, reason: String(item.reason || "").trim() };
    })
    .filter(Boolean)
    .slice(0, Math.max(1, autonomousMaxFilesPerIter));

  return {
    summary: String(obj.summary || "").trim(),
    tasks: tasksRaw
      .map((item) => String(item || "").trim())
      .filter(Boolean)
      .slice(0, 12),
    targetFiles,
    validationCommands: validationRaw
      .map((item) => String(item || "").trim())
      .filter(Boolean)
      .slice(0, Math.max(1, autonomousMaxValidationCommands)),
    done: obj.done === true,
    nextFocus: String(obj.next_focus || obj.nextFocus || "").trim(),
  };
}

function normalizeProposalObject(rawObject) {
  const obj = rawObject && typeof rawObject === "object" ? rawObject : {};
  const changesRaw = Array.isArray(obj.changes) ? obj.changes : (Array.isArray(obj.files) ? obj.files : []);
  const changes = changesRaw
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const relPath = sanitizeModelPath(item.path);
      if (!relPath) return null;
      const action = String(item.action || "update").trim().toLowerCase();
      if (action !== "update" && action !== "create") {
        return null;
      }
      return {
        path: relPath,
        action,
        content: String(item.content || ""),
      };
    })
    .filter(Boolean)
    .slice(0, Math.max(1, autonomousMaxFilesPerIter));

  return {
    summary: String(obj.summary || "").trim(),
    changes,
    done: obj.done === true,
    finalMessage: String(obj.final_message || obj.finalMessage || "").trim(),
  };
}

function normalizeAgentDecision(rawObject) {
  const obj = rawObject && typeof rawObject === "object" ? rawObject : {};
  const rawType = String(obj.type || obj.kind || obj.mode || obj.action || "").trim().toLowerCase();
  const directTool = [
    "read",
    "read_file",
    "list_dir",
    "search",
    "shell",
    "write",
    "apply_patch",
    "update_plan",
    "web_search",
  ].includes(rawType) ? rawType : "";

  const message = String(
    obj.message || obj.final_message || obj.finalMessage || obj.answer || obj.response || "",
  ).trim();
  if (rawType === "final" || rawType === "answer" || rawType === "done" || rawType === "complete") {
    return {
      type: "final",
      message,
    };
  }

  const tool = String(obj.tool || obj.tool_name || obj.toolName || obj.name || directTool).trim().toLowerCase();
  if (rawType === "tool" || rawType === "call" || directTool || tool) {
    const directArgs = obj.args || obj.arguments || obj.input || obj.params || null;
    let args = {};
    if (directArgs && typeof directArgs === "object" && !Array.isArray(directArgs)) {
      args = { ...directArgs };
    }
    if (Object.keys(args).length === 0) {
      const passthrough = { ...obj };
      const reservedKeys = new Set([
        "type",
        "kind",
        "mode",
        "action",
        "tool",
        "tool_name",
        "toolName",
        "name",
        "message",
        "final_message",
        "finalMessage",
        "answer",
        "response",
        "reason",
      ]);
      for (const key of Object.keys(passthrough)) {
        if (!reservedKeys.has(key)) {
          args[key] = passthrough[key];
        }
      }
    }
    return {
      type: "tool",
      tool,
      args,
      reason: String(obj.reason || "").trim(),
    };
  }

  if (message) {
    return {
      type: "final",
      message,
    };
  }

  return {
    type: "invalid",
    message: "",
  };
}

function summarizeToolArgs(toolName, args) {
  const tool = String(toolName || "").trim().toLowerCase();
  const payload = args && typeof args === "object" ? args : {};
  if (tool === "read") {
    const rel = sanitizeModelPath(payload.path || payload.file || payload.target || "");
    return rel ? `path=${rel}` : "(path missing)";
  }
  if (tool === "read_file") {
    const rel = sanitizeModelPath(payload.path || payload.file || payload.target || "");
    const offset = clampInteger(payload.offset || payload.line || payload.start_line, 1, 1, 1_000_000);
    const limit = clampInteger(payload.limit || payload.max_lines || payload.lines, 120, 1, 400);
    if (!rel) return "(path missing)";
    return `path=${rel} offset=${offset} limit=${limit}`;
  }
  if (tool === "list_dir") {
    const rel = sanitizeModelPath(payload.path || payload.dir || payload.target || ".") || ".";
    const recursive = parseBooleanEnv(payload.recursive, false);
    const maxDepth = clampInteger(payload.max_depth || payload.maxDepth, 2, 0, 6);
    const limit = clampInteger(payload.limit || payload.max_entries || payload.maxEntries, 200, 1, 500);
    return `path=${rel} recursive=${recursive ? "yes" : "no"} max_depth=${maxDepth} limit=${limit}`;
  }
  if (tool === "search") {
    const pattern = String(payload.pattern || payload.query || "").trim();
    const glob = String(payload.glob || "").trim();
    if (!pattern) return "(pattern missing)";
    return glob ? `pattern=${pattern} glob=${glob}` : `pattern=${pattern}`;
  }
  if (tool === "shell") {
    const command = String(payload.command || payload.cmd || "").trim();
    return command ? `command=${command}` : "(command missing)";
  }
  if (tool === "write") {
    const rel = sanitizeModelPath(payload.path || payload.file || payload.target || "");
    let content = "";
    if (typeof payload.content === "string") {
      content = payload.content;
    } else if (payload.content !== null && payload.content !== undefined) {
      content = JSON.stringify(payload.content, null, 2);
    }
    return `path=${rel || "(missing)"} bytes=${Buffer.byteLength(content, "utf8")}`;
  }
  if (tool === "apply_patch") {
    const patchText = String(payload.patch || payload.text || payload.content || "");
    return `patch_bytes=${Buffer.byteLength(patchText, "utf8")}`;
  }
  if (tool === "update_plan") {
    const planItems = Array.isArray(payload.plan) ? payload.plan.length : 0;
    const explanation = String(payload.explanation || "").trim();
    const parts = [`items=${planItems}`];
    if (explanation) {
      parts.push(`explanation=${truncateText(explanation, 120)}`);
    }
    return parts.join(" ");
  }
  if (tool === "web_search") {
    const query = String(payload.query || payload.q || "").replace(/\s+/g, " ").trim();
    const maxResults = Number.parseInt(String(payload.max_results || payload.maxResults || payload.limit || ""), 10);
    if (!query) return "(query missing)";
    if (Number.isInteger(maxResults)) return `query=${query} max_results=${Math.max(1, Math.min(10, maxResults))}`;
    return `query=${query}`;
  }
  return truncateText(JSON.stringify(payload), 300);
}

function normalizeSearchQuery(rawValue) {
  return String(rawValue || "").replace(/\s+/g, " ").trim();
}

function extractLastWebSearchQuery(session) {
  if (!session || !Array.isArray(session.toolLogs)) {
    return "";
  }
  for (let i = session.toolLogs.length - 1; i >= 0; i -= 1) {
    const item = session.toolLogs[i];
    const title = String(item?.title || "");
    const fromTitle = title.match(/web_search\s+query=(.+)$/i);
    if (fromTitle && fromTitle[1]) {
      const value = normalizeSearchQuery(fromTitle[1]);
      if (value) return value;
    }
    const detail = String(item?.detail || "");
    const fromDetail = detail.match(/(?:^|\n)query=([^\n\r]+)/i);
    if (fromDetail && fromDetail[1]) {
      const value = normalizeSearchQuery(fromDetail[1]);
      if (value) return value;
    }
  }
  return "";
}

async function executeAutoToolCall({ session, toolName, args, fallbackWebSearchQuery = "" }) {
  const tool = String(toolName || "").trim().toLowerCase();
  const payload = args && typeof args === "object" ? args : {};

  try {
    if (tool === "read") {
      const rawPath = String(payload.path || payload.file || payload.target || "").trim();
      if (!rawPath) {
        throw new Error("Path is empty.");
      }
      const fileData = await readLocalFileForTool(rawPath);
      appendToolLog(session, {
        title: `read ${fileData.displayPath}`,
        summary: fileData.meta,
        detail: fileData.shown,
      });
      return {
        html: renderToolResult({
          title: `Tool read: ${fileData.displayPath}`,
          meta: fileData.meta,
          body: fileData.shown || "(empty file)",
        }),
        modelResult: {
          ok: true,
          tool: "read",
          path: fileData.displayPath,
          absolutePath: fileData.resolvedPath,
          sizeBytes: fileData.sizeBytes,
          ...fileData.modelPayload,
          content: truncateText(fileData.content, autoToolResultChars),
        },
      };
    }

    if (tool === "read_file") {
      const rawPath = String(payload.path || payload.file || payload.target || "").trim();
      const fileSlice = await readTextFileSliceForTool(
        rawPath,
        payload.offset || payload.line || payload.start_line,
        payload.limit || payload.max_lines || payload.lines,
      );
      const meta = [
        `bytes=${fileSlice.sizeBytes}`,
        `lines=${fileSlice.totalLines}`,
        `offset=${fileSlice.offset}`,
        `limit=${fileSlice.limit}`,
        `returned=${fileSlice.returnedLines}`,
      ].join(" ");
      appendToolLog(session, {
        title: `read_file ${fileSlice.relPath}`,
        summary: meta,
        detail: fileSlice.content || "(no lines)",
      });
      return {
        html: renderToolResult({
          title: `Tool read_file: ${fileSlice.relPath}`,
          meta,
          body: fileSlice.content || "(no lines)",
        }),
        modelResult: {
          ok: true,
          tool: "read_file",
          path: fileSlice.relPath,
          totalLines: fileSlice.totalLines,
          offset: fileSlice.offset,
          limit: fileSlice.limit,
          returnedLines: fileSlice.returnedLines,
          content: truncateText(fileSlice.content, autoToolResultChars),
        },
      };
    }

    if (tool === "list_dir") {
      const rawPath = String(payload.path || payload.dir || payload.target || ".").trim();
      const recursive = parseBooleanEnv(payload.recursive, false);
      const maxDepth = clampInteger(payload.max_depth || payload.maxDepth, 2, 0, 6);
      const limit = clampInteger(payload.limit || payload.max_entries || payload.maxEntries, 200, 1, 500);
      const listing = await listWorkspaceEntriesForTool({
        rawPath,
        recursive,
        maxDepth,
        limit,
      });
      const lines = [
        `root=${listing.root}`,
        `entries=${listing.entries.length}`,
        `truncated=${listing.truncated ? "yes" : "no"}`,
        "",
      ];
      for (const item of listing.entries) {
        if (item.type === "file") {
          lines.push(`- [file] ${item.path} (${item.size} bytes)`);
        } else if (item.type === "dir") {
          lines.push(`- [dir] ${item.path}`);
        } else {
          lines.push(`- [other] ${item.path}`);
        }
      }
      const body = lines.join("\n");
      appendToolLog(session, {
        title: `list_dir ${listing.root}`,
        summary: `entries=${listing.entries.length} truncated=${listing.truncated ? "yes" : "no"}`,
        detail: body,
      });
      return {
        html: renderToolResult({
          title: "Tool list_dir",
          meta: `entries=${listing.entries.length} truncated=${listing.truncated ? "yes" : "no"}`,
          body,
        }),
        modelResult: {
          ok: true,
          tool: "list_dir",
          root: listing.root,
          truncated: listing.truncated,
          entries: listing.entries,
        },
      };
    }

    if (tool === "update_plan") {
      const rawPlan = Array.isArray(payload.plan) ? payload.plan : [];
      const explanation = String(payload.explanation || payload.note || "").trim();
      const allowedStatus = new Set(["pending", "in_progress", "completed"]);
      const normalizedPlan = rawPlan
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const step = String(item.step || "").trim();
          if (!step) return null;
          const rawStatus = String(item.status || "").trim().toLowerCase();
          const status = allowedStatus.has(rawStatus) ? rawStatus : "pending";
          return { step, status };
        })
        .filter(Boolean)
        .slice(0, 30);
      let hasInProgress = false;
      for (const item of normalizedPlan) {
        if (item.status === "in_progress") {
          if (hasInProgress) {
            item.status = "pending";
          } else {
            hasInProgress = true;
          }
        }
      }
      session.plan = normalizedPlan;
      const body = JSON.stringify({
        explanation,
        plan: normalizedPlan,
      }, null, 2);
      appendToolLog(session, {
        title: "update_plan",
        summary: `items=${normalizedPlan.length}`,
        detail: body,
      });
      return {
        html: renderToolResult({
          title: "Tool update_plan",
          meta: `items=${normalizedPlan.length}`,
          body,
        }),
        modelResult: {
          ok: true,
          tool: "update_plan",
          explanation,
          plan: normalizedPlan,
        },
      };
    }

    if (tool === "search") {
      const pattern = String(payload.pattern || payload.query || "").trim();
      const glob = String(payload.glob || "").trim();
      if (!pattern) {
        throw new Error("Pattern is empty.");
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
      return {
        html: renderToolResult({
          title: "Tool search",
          meta: glob ? `pattern=${pattern} glob=${glob}` : `pattern=${pattern}`,
          body,
          isError: result.status !== "match" && result.status !== "no-match",
        }),
        modelResult: {
          ok: true,
          tool: "search",
          status: result.status,
          output: truncateText(result.output || "", autoToolResultChars),
          error: truncateText(result.error || "", autoToolResultChars),
        },
      };
    }

    if (tool === "shell") {
      const command = String(payload.command || payload.cmd || "").trim();
      if (!command) {
        throw new Error("Command is empty.");
      }
      if (!isAllowedShellCommand(command)) {
        throw new Error([
          `Command is not allowed: ${command}`,
          `Allowed prefixes: ${shellAllowlist.join(", ")}`,
          "Forbidden chars: ; & | > < ` and newline",
        ].join("\n"));
      }
      const result = await runShellCommand(command, workspaceRoot);
      const output = [
        `$ ${command}`,
        result.stdout ? `\n[stdout]\n${result.stdout}` : "",
        result.stderr ? `\n[stderr]\n${result.stderr}` : "",
      ].join("");
      const statusText = `exit=${result.exitCode} timeout=${result.timedOut ? "yes" : "no"} elapsed=${result.elapsedMs}ms`;
      appendToolLog(session, {
        title: `shell ${command}`,
        summary: statusText,
        detail: output,
      });
      return {
        html: renderToolResult({
          title: "Tool shell",
          meta: statusText,
          body: output || "(no output)",
          isError: result.exitCode !== 0 || result.timedOut || Boolean(result.spawnError),
        }),
        modelResult: {
          ok: result.exitCode === 0 && !result.timedOut && !result.spawnError,
          tool: "shell",
          exitCode: result.exitCode,
          timedOut: result.timedOut,
          spawnError: result.spawnError || "",
          stdout: truncateText(result.stdout || "", autoToolResultChars),
          stderr: truncateText(result.stderr || "", autoToolResultChars),
          elapsedMs: result.elapsedMs,
        },
      };
    }

    if (tool === "apply_patch") {
      const patchText = String(payload.patch || payload.text || payload.content || "");
      if (!patchText.trim()) {
        throw new Error("Patch text is empty.");
      }
      const applyResults = await applyPatchOperations(patchText);
      const summaryLines = [
        `operations=${applyResults.length}`,
      ];
      for (const row of applyResults) {
        const moved = row.fromPath ? ` from=${row.fromPath}` : "";
        summaryLines.push(`- ${row.action} path=${row.path}${moved} bytes=${row.bytes}`);
      }
      const body = summaryLines.join("\n");
      const detailParts = [body];
      for (const row of applyResults) {
        detailParts.push("");
        detailParts.push(`# diff ${row.path}`);
        detailParts.push(row.diff || "(no diff)");
      }
      const detail = detailParts.join("\n");
      appendToolLog(session, {
        title: "apply_patch",
        summary: `operations=${applyResults.length}`,
        detail,
      });
      return {
        html: renderToolResult({
          title: "Tool apply_patch",
          meta: `operations=${applyResults.length}`,
          body: detail,
        }),
        modelResult: {
          ok: true,
          tool: "apply_patch",
          operations: applyResults.map((row) => ({
            action: row.action,
            path: row.path,
            fromPath: row.fromPath || "",
            bytes: row.bytes,
          })),
        },
      };
    }

    if (tool === "web_search") {
      const searchTemporalContext = getTemporalContext();
      let query = normalizeSearchQuery(payload.query || payload.q || payload.keyword || "");
      let querySource = "provided";
      if (!query) {
        const lastQuery = extractLastWebSearchQuery(session);
        if (lastQuery) {
          query = lastQuery;
          querySource = "previous_web_search";
        }
      }
      if (!query) {
        const promptFallback = normalizeSearchQuery(fallbackWebSearchQuery);
        if (promptFallback) {
          query = promptFallback;
          querySource = "user_prompt";
        }
      }
      const maxResults = Number.parseInt(String(payload.max_results || payload.maxResults || payload.limit || ""), 10);
      if (!query) {
        throw new Error("Query is empty.");
      }
      const result = await runPlaywrightWebSearch(query, maxResults);
      const bodyLines = [
        `query=${result.query}`,
        querySource !== "provided" ? `query_source=${querySource}` : "",
        `observed_at_utc=${searchTemporalContext.utcIso}`,
        `current_date_jst=${searchTemporalContext.currentDateJst}`,
        result.source ? `source=${result.source}` : "",
        `results=${result.results.length}`,
        "",
      ];
      for (let i = 0; i < result.results.length; i += 1) {
        const item = result.results[i];
        bodyLines.push(`[${i + 1}] ${item.title}`);
        bodyLines.push(item.url);
        if (item.snippet) {
          bodyLines.push(item.snippet);
        }
        bodyLines.push("");
      }
      const body = bodyLines.join("\n").trim();
      appendToolLog(session, {
        title: `web_search query=${result.query}`,
        summary: `results=${result.results.length}`,
        detail: body,
      });
      return {
        html: renderToolResult({
          title: "Tool web_search",
          meta: [
            `results=${result.results.length}`,
            querySource !== "provided" ? `query_source=${querySource}` : "",
          ].filter(Boolean).join(" "),
          body,
        }),
        modelResult: {
          ok: true,
          tool: "web_search",
          query: result.query,
          querySource,
          observedAtUtc: searchTemporalContext.utcIso,
          currentDateJst: searchTemporalContext.currentDateJst,
          source: result.source,
          command: result.command,
          elapsedMs: result.elapsedMs,
          results: result.results,
        },
      };
    }

    if (tool === "write") {
      const rawPath = String(payload.path || payload.file || payload.target || "").trim();
      if (!rawPath) {
        throw new Error("Path is empty.");
      }
      const contentValue = payload.content;
      let content = "";
      if (typeof contentValue === "string") {
        content = contentValue;
      } else if (contentValue !== null && contentValue !== undefined) {
        content = JSON.stringify(contentValue, null, 2);
      }
      const relPath = sanitizeModelPath(rawPath);
      const resolvedPath = resolveWorkspacePath(relPath);
      const ext = path.extname(relPath).toLowerCase();

      if (isOfficeFileExtension(ext)) {
        let oldContent = "";
        let hadPreviousText = false;
        try {
          const beforeRead = await readLocalFileForTool(relPath);
          oldContent = String(beforeRead.content || "");
          hadPreviousText = true;
        } catch {
          hadPreviousText = false;
        }

        await mkdir(path.dirname(resolvedPath), { recursive: true });
        const writePayload = await writeOfficeFileViaPython(resolvedPath, content);
        const afterRead = await readLocalFileForTool(relPath);
        const newContent = String(afterRead.content || "");
        const diffText = await createPreviewDiff({ relPath, oldContent, newContent });
        const changed = !hadPreviousText || oldContent !== newContent;
        const bytes = Number.isFinite(Number(writePayload?.bytes))
          ? Number(writePayload.bytes)
          : ((await stat(resolvedPath)).size || 0);

        const summaryParts = [`bytes=${bytes}`, `format=${String(writePayload?.format || ext.replace(/^\./, ""))}`];
        if (Number.isInteger(writePayload?.sheets)) {
          summaryParts.push(`sheets=${writePayload.sheets}`);
        }
        if (Number.isInteger(writePayload?.cells)) {
          summaryParts.push(`cells=${writePayload.cells}`);
        }
        if (Number.isInteger(writePayload?.paragraphs)) {
          summaryParts.push(`paragraphs=${writePayload.paragraphs}`);
        }
        if (Number.isInteger(writePayload?.slides)) {
          summaryParts.push(`slides=${writePayload.slides}`);
        }
        if (Number.isInteger(writePayload?.text_lines)) {
          summaryParts.push(`text_lines=${writePayload.text_lines}`);
        }
        summaryParts.push(`changed=${changed ? "yes" : "no"}`);
        const summary = summaryParts.join(" ");

        appendToolLog(session, {
          title: `write diff ${relPath}`,
          summary: changed ? "changed=yes" : "changed=no",
          detail: diffText,
        });
        appendToolLog(session, {
          title: `write ${relPath}`,
          summary,
          detail: truncateText(newContent || "(empty document)", maxToolOutputChars),
        });

        const diffCard = renderToolResult({
          title: `Tool write diff: ${relPath}`,
          meta: changed ? "changed=yes" : "changed=no",
          body: diffText,
        });
        const applyCard = renderToolResult({
          title: `Tool write: ${relPath}`,
          meta: summary,
          body: changed ? "Office document written." : "No content change.",
        });

        return {
          html: `${diffCard}${applyCard}`,
          modelResult: {
            ok: true,
            tool: "write",
            path: relPath,
            bytes,
            changed,
            format: String(writePayload?.format || ext.replace(/^\./, "")),
            sheets: Number.isInteger(writePayload?.sheets) ? writePayload.sheets : undefined,
            cells: Number.isInteger(writePayload?.cells) ? writePayload.cells : undefined,
            paragraphs: Number.isInteger(writePayload?.paragraphs) ? writePayload.paragraphs : undefined,
            slides: Number.isInteger(writePayload?.slides) ? writePayload.slides : undefined,
            textLines: Number.isInteger(writePayload?.text_lines) ? writePayload.text_lines : undefined,
          },
        };
      }

      const snapshot = await readWorkspaceTextIfExists(relPath);
      const oldContent = snapshot.exists ? snapshot.content : "";
      const diffText = await createPreviewDiff({ relPath, oldContent, newContent: content });

      await mkdir(path.dirname(resolvedPath), { recursive: true });
      await writeFile(resolvedPath, content, "utf8");
      const changed = oldContent !== content;
      const bytes = Buffer.byteLength(content, "utf8");

      appendToolLog(session, {
        title: `write diff ${relPath}`,
        summary: changed ? "changed=yes" : "changed=no",
        detail: diffText,
      });
      appendToolLog(session, {
        title: `write ${relPath}`,
        summary: `bytes=${bytes}`,
        detail: changed ? "File written." : "No content change.",
      });

      const diffCard = renderToolResult({
        title: `Tool write diff: ${relPath}`,
        meta: changed ? "changed=yes" : "changed=no",
        body: diffText,
      });
      const applyCard = renderToolResult({
        title: `Tool write: ${relPath}`,
        meta: `bytes=${bytes}`,
        body: changed ? "File written." : "No content change.",
      });

      return {
        html: `${diffCard}${applyCard}`,
        modelResult: {
          ok: true,
          tool: "write",
          path: relPath,
          bytes,
          changed,
        },
      };
    }

    throw new Error(`Unsupported tool: ${tool || "(empty)"}`);
  } catch (err) {
    const message = err?.message || String(err);
    appendToolLog(session, {
      title: `tool error ${tool || "(unknown)"}`,
      summary: "failed",
      detail: message,
    });
    return {
      html: renderToolResult({
        title: `Tool ${tool || "unknown"} error`,
        body: message,
        isError: true,
      }),
      modelResult: {
        ok: false,
        tool: tool || "",
        error: message,
      },
    };
  }
}

async function runAutoToolChat({ session, prompt, model, temperature, onEvent = null }) {
  const temporalContext = getTemporalContext();
  const emit = typeof onEvent === "function"
    ? (payload) => {
        try {
          onEvent(payload);
        } catch {
          // ignore streaming callback errors
        }
      }
    : null;
  const chatMessages = [
    { role: "system", content: autoToolSystemPrompt },
    {
      role: "system",
      content: [
        `workspace_root=${workspaceRoot}`,
        `current_utc_iso=${temporalContext.utcIso}`,
        `current_date_app_tz=${temporalContext.currentDateByAppTimeZone}`,
        `current_date_jst=${temporalContext.currentDateJst}`,
        `app_time_zone=${temporalContext.appTimeZone}`,
        `max_read_bytes=${maxReadBytes}`,
        `shell_allowlist=${shellAllowlist.join(", ")}`,
        "available_tools=read,read_file,list_dir,search,shell,write,apply_patch,update_plan,web_search",
        "allow_write=yes",
        "allow_apply_patch=yes",
        "write_scope=workspace_root_only",
        `web_search_enabled=${playwrightMcpEnabled ? "yes" : "no"}`,
        `web_search_max_results=${Math.max(1, Math.min(10, playwrightMcpMaxResults))}`,
        `playwright_browser=${playwrightMcpBrowser}`,
      ].join("\n"),
    },
  ];

  const toolContext = buildToolContext(session);
  if (toolContext) {
    chatMessages.push({
      role: "system",
      content: `Recent local tool logs:\n${toolContext}`,
    });
  }
  if (Array.isArray(session.plan) && session.plan.length > 0) {
    chatMessages.push({
      role: "system",
      content: `Current plan snapshot:\n${JSON.stringify(session.plan)}`,
    });
  }

  for (const msg of session.messages) {
    chatMessages.push(msg);
  }
  chatMessages.push({ role: "user", content: prompt });

  const htmlParts = [];
  let finalText = "";
  const pushCard = (html) => {
    const card = String(html || "");
    if (!card) return;
    htmlParts.push(card);
    if (emit) {
      emit({
        type: "tool_card",
        html: card,
      });
    }
  };

  for (let step = 1; step <= Math.max(1, autoToolMaxSteps); step += 1) {
    if (emit) {
      emit({
        type: "status",
        step,
        message: `step ${step}: deciding next action`,
      });
    }
    let raw = "";
    try {
      raw = await callRunPodChatText({
        model,
        temperature: Number.isFinite(temperature) ? temperature : autoToolTemperature,
        messages: chatMessages,
        maxTokens: Math.max(256, autoToolMaxTokens),
      });
    } catch (err) {
      if (!isContextExceededError(err)) {
        throw err;
      }
      const compacted = compactMessagesForContextRetry(chatMessages);
      if (compacted.length >= chatMessages.length) {
        throw err;
      }
      chatMessages.length = 0;
      chatMessages.push(...compacted);
      appendToolLog(session, {
        title: "auto-tool context trimmed",
        summary: `step=${step}`,
        detail: "Context size exceeded. Trimmed chat history and retrying once.",
      });
      pushCard(renderToolResult({
        title: "Auto tool context trimmed",
        meta: `step=${step}`,
        body: "Context size exceeded. Retrying with shorter history.",
      }));
      raw = await callRunPodChatText({
        model,
        temperature: Number.isFinite(temperature) ? temperature : autoToolTemperature,
        messages: chatMessages,
        maxTokens: Math.max(256, autoToolMaxTokens),
      });
    }

    let decisionObject = null;
    let parseRecovered = false;
    let parseErrorMessage = "";
    try {
      decisionObject = parseModelJsonObject(raw);
    } catch (parseErr) {
      parseErrorMessage = parseErr?.message || String(parseErr);
      for (let retry = 1; retry <= Math.max(0, autoToolJsonRepairRetries); retry += 1) {
        try {
          decisionObject = await repairModelJsonObjectViaModel({ rawText: raw, model });
          parseRecovered = true;
          break;
        } catch (repairErr) {
          parseErrorMessage = repairErr?.message || String(repairErr);
        }
      }
    }

    if (!decisionObject) {
      appendToolLog(session, {
        title: "auto-tool json parse failed",
        summary: `step=${step}`,
        detail: [
          parseErrorMessage || "JSON parse failed.",
          "",
          "raw_output:",
          truncateText(raw, 1200),
        ].join("\n"),
      });
      pushCard(renderToolResult({
        title: "Auto tool JSON parse failed",
        meta: `step=${step}`,
        body: [
          parseErrorMessage || "JSON parse failed.",
          "",
          "raw output (truncated):",
          truncateText(raw, 1200),
        ].join("\n"),
        isError: true,
      }));
      finalText = [
        "Model returned malformed JSON and recovery also failed.",
        "Please retry with a shorter or more specific prompt.",
      ].join("\n");
      break;
    }

    if (parseRecovered) {
      appendToolLog(session, {
        title: "auto-tool json recovered",
        summary: `step=${step}`,
        detail: "Recovered malformed JSON response via repair pass.",
      });
      pushCard(renderToolResult({
        title: "Auto tool JSON recovered",
        meta: `step=${step}`,
        body: "Recovered malformed JSON response and continued.",
      }));
    }

    const decision = normalizeAgentDecision(decisionObject);
    if (decision.type === "final") {
      finalText = decision.message || "(empty response)";
      break;
    }
    if (decision.type !== "tool" || !decision.tool) {
      finalText = raw || "Model returned an invalid decision object.";
      break;
    }

    const callMeta = [
      `step=${step}`,
      decision.reason ? `reason=${decision.reason}` : "",
    ].filter(Boolean).join(" ");
    pushCard(renderToolResult({
      title: `Auto tool: ${decision.tool}`,
      meta: callMeta,
      body: summarizeToolArgs(decision.tool, decision.args),
    }));

    const toolOutcome = await executeAutoToolCall({
      session,
      toolName: decision.tool,
      args: decision.args,
      fallbackWebSearchQuery: prompt,
    });
    pushCard(toolOutcome.html);

    chatMessages.push({
      role: "assistant",
      content: JSON.stringify({
        type: "tool",
        tool: decision.tool,
        args: decision.args,
      }),
    });
    chatMessages.push({
      role: "user",
      content: `Tool result:\n${JSON.stringify(toolOutcome.modelResult)}`,
    });
  }

  if (!finalText) {
    finalText = [
      `Auto tool loop reached step limit (${Math.max(1, autoToolMaxSteps)}).`,
      "Run again with a follow-up instruction if more work is needed.",
    ].join("\n");
  }

  // Guardrail for weather "today" prompts: avoid stale explicit calendar dates.
  if (promptAsksTodayWeather(prompt)) {
    const rewrite = rewriteMismatchedExplicitDatesAsToday(finalText, temporalContext.currentDateJst);
    finalText = rewrite.text;
    if (rewrite.mismatchCount > 0) {
      appendToolLog(session, {
        title: "auto-tool temporal date normalized",
        summary: `rewritten_dates=${rewrite.mismatchCount}`,
        detail: [
          `prompt=${truncateText(prompt, 400)}`,
          `current_date_jst=${temporalContext.currentDateJst}`,
          "Replaced mismatched explicit dates in final answer with '本日'.",
        ].join("\n"),
      });
    }
  }

  return {
    html: htmlParts.join(""),
    assistantText: finalText,
  };
}

function normalizeChatRole(rawRole) {
  const role = String(rawRole || "").trim().toLowerCase();
  if (role === "system" || role === "user" || role === "assistant" || role === "tool") {
    return role;
  }
  return "user";
}

function normalizeChatContent(rawContent) {
  if (typeof rawContent === "string") {
    return rawContent;
  }
  if (rawContent === null || rawContent === undefined) {
    return "";
  }
  try {
    return JSON.stringify(rawContent);
  } catch {
    return String(rawContent);
  }
}

function normalizeChatMessages(messages) {
  const rows = Array.isArray(messages) ? messages : [];
  return rows
    .filter((row) => row && typeof row === "object")
    .map((row) => ({
      role: normalizeChatRole(row.role),
      content: normalizeChatContent(row.content),
    }));
}

function estimateMessageCharWeight(message) {
  const roleChars = String(message?.role || "").length;
  const contentChars = String(message?.content || "").length;
  return roleChars + contentChars + 24;
}

function estimateMessagesCharWeight(messages) {
  const rows = Array.isArray(messages) ? messages : [];
  let total = 0;
  for (const row of rows) {
    total += estimateMessageCharWeight(row);
  }
  return total;
}

function trimMessagesToApproxContextChars(messages, maxChars) {
  const normalized = normalizeChatMessages(messages);
  const budget = Math.max(1024, Number.parseInt(String(maxChars || 0), 10) || 0);
  if (normalized.length <= 1) {
    return normalized;
  }
  if (estimateMessagesCharWeight(normalized) <= budget) {
    return normalized;
  }

  const keepIndexes = new Set();
  const stableSystemMax = Math.min(3, normalized.length);
  for (let i = 0; i < stableSystemMax; i += 1) {
    if (normalized[i].role === "system") {
      keepIndexes.add(i);
    }
  }
  keepIndexes.add(normalized.length - 1);

  let used = 0;
  for (const index of keepIndexes) {
    used += estimateMessageCharWeight(normalized[index]);
  }

  for (let i = normalized.length - 2; i >= 0; i -= 1) {
    if (keepIndexes.has(i)) continue;
    const next = used + estimateMessageCharWeight(normalized[i]);
    if (next <= budget) {
      keepIndexes.add(i);
      used = next;
    }
  }

  const selected = [];
  for (let i = 0; i < normalized.length; i += 1) {
    if (keepIndexes.has(i)) {
      selected.push({ ...normalized[i] });
    }
  }

  let totalChars = estimateMessagesCharWeight(selected);
  if (totalChars > budget && selected.length > 0) {
    const lastIndex = selected.length - 1;
    const original = String(selected[lastIndex].content || "");
    const overflow = totalChars - budget;
    const shrinkBy = Math.min(Math.max(0, overflow + 256), Math.max(0, original.length - 256));
    if (shrinkBy > 0) {
      selected[lastIndex].content = original.slice(shrinkBy);
      totalChars = estimateMessagesCharWeight(selected);
    }
  }

  if (totalChars > budget && selected.length > 6) {
    return selected.slice(-6);
  }
  return selected;
}

function buildChatCompletionBody({
  model,
  messages,
  temperature,
  maxTokens,
  stream = false,
}) {
  const safeModel = String(model || defaultModel).trim() || defaultModel;
  const safeMaxContextTokens = Math.max(1024, generationMaxContextTokens);
  const safeMaxTokensRaw = Math.max(1, Number.parseInt(String(maxTokens || 0), 10) || 0);
  const safeMaxTokens = Math.min(safeMaxContextTokens, Math.max(256, safeMaxTokensRaw));
  const inputTokenBudget = Math.max(
    256,
    safeMaxContextTokens - safeMaxTokens - Math.max(0, generationContextReserveTokens),
  );
  const approxInputCharBudget = Math.max(1024, inputTokenBudget * 4);
  const safeMessages = trimMessagesToApproxContextChars(messages, approxInputCharBudget);
  const safeTemperature = Number.isFinite(temperature)
    ? Math.min(2, Math.max(0, temperature))
    : generationTemperatureDefault;

  return {
    model: safeModel,
    messages: safeMessages,
    temperature: safeTemperature,
    top_p: generationTopP,
    top_k: generationTopK,
    min_p: generationMinP,
    max_tokens: safeMaxTokens,
    stream: Boolean(stream),
  };
}

function isLikelyUnsupportedGenerationParamError(err) {
  if (!err) return false;
  const status = Number.parseInt(String(err.statusCode || ""), 10);
  if (!Number.isInteger(status) || status < 400 || status >= 500) {
    return false;
  }
  const text = [
    err?.message || "",
    err?.payload?.error || "",
    err?.payload?.message || "",
    err?.payload?.detail || "",
    err?.payload?.raw || "",
  ].join("\n");
  if (!/top_k|min_p|top_p/i.test(text)) {
    return false;
  }
  return /unknown|unexpected|unsupported|invalid|not allowed|additional property/i.test(text);
}

async function callRunPodChatText({
  model = defaultModel,
  temperature = generationTemperatureDefault,
  messages,
  maxTokens = autonomousModelMaxTokens,
}) {
  const requestBody = buildChatCompletionBody({
    model,
    messages,
    temperature,
    maxTokens,
    stream: false,
  });

  let response;
  try {
    response = await callRunPodJson("/chat/completions", requestBody);
  } catch (err) {
    if (!isLikelyUnsupportedGenerationParamError(err)) {
      throw err;
    }
    const fallbackBody = { ...requestBody };
    delete fallbackBody.top_k;
    delete fallbackBody.min_p;
    response = await callRunPodJson("/chat/completions", fallbackBody);
  }
  return extractAssistantText(response) || "";
}

function normalizeTempDiffPaths(diffText, beforePath, afterPath, relPath) {
  const rel = sanitizeModelPath(relPath);
  const beforeCandidates = [beforePath, beforePath.replaceAll("\\", "/"), beforePath.replaceAll("/", "\\")];
  const afterCandidates = [afterPath, afterPath.replaceAll("\\", "/"), afterPath.replaceAll("/", "\\")];

  let text = String(diffText || "");
  for (const item of beforeCandidates) {
    if (item) {
      text = text.split(item).join(`a/${rel}`);
    }
  }
  for (const item of afterCandidates) {
    if (item) {
      text = text.split(item).join(`b/${rel}`);
    }
  }
  // Git may print short 8.3 temp paths on Windows; normalize header lines as a fallback.
  text = text.replace(/^diff --git .+$/m, `diff --git a/${rel} b/${rel}`);
  text = text.replace(/^--- .+$/m, `--- a/${rel}`);
  text = text.replace(/^\+\+\+ .+$/m, `+++ b/${rel}`);
  return text;
}

async function createPreviewDiff({ relPath, oldContent, newContent }) {
  if (String(oldContent) === String(newContent)) {
    return "No textual changes.";
  }

  const tempDir = await mkdtemp(path.join(tmpdir(), "runpod-loop-diff-"));
  const beforePath = path.join(tempDir, "before.txt");
  const afterPath = path.join(tempDir, "after.txt");

  await writeFile(beforePath, String(oldContent || ""), "utf8");
  await writeFile(afterPath, String(newContent || ""), "utf8");

  try {
    const result = await new Promise((resolve) => {
      let stdout = "";
      let stderr = "";
      let spawnError = "";

      const child = spawn("git", ["--no-pager", "diff", "--no-index", "--", beforePath, afterPath], {
        cwd: workspaceRoot,
        stdio: ["ignore", "pipe", "pipe"],
      });

      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString("utf8");
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk.toString("utf8");
      });
      child.on("error", (err) => {
        spawnError = err?.message || String(err);
      });
      child.on("close", (code) => {
        resolve({
          code: Number.isInteger(code) ? code : 1,
          stdout,
          stderr,
          spawnError,
        });
      });
    });

    if (result.spawnError) {
      throw new Error(result.spawnError);
    }
    if (result.code !== 0 && result.code !== 1) {
      throw new Error(result.stderr || `git diff exited with code ${result.code}`);
    }
    const diff = normalizeTempDiffPaths(result.stdout || "", beforePath, afterPath, relPath);
    if (diff.trim()) {
      return truncateText(diff, maxToolOutputChars);
    }
  } catch {
    // fallback to a simplified preview when git diff is unavailable.
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }

  return [
    `diff fallback for ${sanitizeModelPath(relPath)}`,
    "[before]",
    truncateText(oldContent || "", 1800),
    "",
    "[after]",
    truncateText(newContent || "", 1800),
  ].join("\n");
}

async function runAutonomousLoop({
  session,
  objective,
  model,
  temperature,
  includeToolContext,
  maxIterations,
  autoApply,
  runValidation,
}) {
  const htmlParts = [];
  const appliedPaths = [];
  let previousOutcome = "";

  for (let iter = 1; iter <= maxIterations; iter += 1) {
    const plannerMessages = [
      { role: "system", content: autonomousPlannerSystemPrompt },
    ];
    if (includeToolContext) {
      const toolContext = buildToolContext(session);
      if (toolContext) {
        plannerMessages.push({
          role: "system",
          content: `Local tool context:\n${toolContext}`,
        });
      }
    }
    plannerMessages.push({
      role: "user",
      content: [
        `Goal:\n${objective}`,
        previousOutcome ? `Previous outcome:\n${previousOutcome}` : "",
        `Iteration: ${iter}/${maxIterations}`,
      ].filter(Boolean).join("\n\n"),
    });

    const plannerRaw = await callRunPodChatText({
      model,
      temperature,
      messages: plannerMessages,
      maxTokens: Math.min(autonomousModelMaxTokens, 2000),
    });
    const plan = normalizePlanObject(parseModelJsonObject(plannerRaw));
    const planText = JSON.stringify(plan, null, 2);
    appendToolLog(session, {
      title: `autoloop plan #${iter}`,
      summary: plan.summary || `iteration ${iter}`,
      detail: planText,
    });
    htmlParts.push(renderToolResult({
      title: `Autoloop plan #${iter}`,
      meta: plan.summary || `iteration ${iter}`,
      body: planText,
    }));

    if (plan.done) {
      previousOutcome = "Planner marked work as done.";
      break;
    }

    if (plan.targetFiles.length === 0) {
      previousOutcome = "Planner returned no target_files.";
      htmlParts.push(renderToolResult({
        title: `Autoloop stopped #${iter}`,
        body: previousOutcome,
        isError: true,
      }));
      break;
    }

    const fileContexts = [];
    for (const target of plan.targetFiles.slice(0, Math.max(1, autonomousMaxFilesPerIter))) {
      const snapshot = await readWorkspaceTextIfExists(target.path);
      if (snapshot.error) {
        fileContexts.push({
          path: snapshot.relPath,
          exists: false,
          error: snapshot.error,
          content: "",
        });
        continue;
      }
      fileContexts.push({
        path: snapshot.relPath,
        exists: snapshot.exists,
        reason: target.reason || "",
        size_bytes: snapshot.sizeBytes,
        content: truncateText(snapshot.content, autonomousMaxFileContextChars),
      });
    }

    const editorMessages = [
      { role: "system", content: autonomousEditorSystemPrompt },
    ];
    if (includeToolContext) {
      const toolContext = buildToolContext(session);
      if (toolContext) {
        editorMessages.push({
          role: "system",
          content: `Local tool context:\n${toolContext}`,
        });
      }
    }
    editorMessages.push({
      role: "user",
      content: [
        `Goal:\n${objective}`,
        `Plan:\n${JSON.stringify(plan, null, 2)}`,
        `Target file contexts:\n${JSON.stringify(fileContexts, null, 2)}`,
      ].join("\n\n"),
    });

    const editorRaw = await callRunPodChatText({
      model,
      temperature,
      messages: editorMessages,
      maxTokens: autonomousModelMaxTokens,
    });
    const proposal = normalizeProposalObject(parseModelJsonObject(editorRaw));
    const proposalText = JSON.stringify(proposal, null, 2);
    appendToolLog(session, {
      title: `autoloop proposal #${iter}`,
      summary: proposal.summary || `changes=${proposal.changes.length}`,
      detail: proposalText,
    });
    htmlParts.push(renderToolResult({
      title: `Autoloop proposal #${iter}`,
      meta: proposal.summary || `changes=${proposal.changes.length}`,
      body: proposalText,
    }));

    if (proposal.changes.length === 0) {
      previousOutcome = "Editor returned no changes.";
      if (proposal.done) {
        break;
      }
      htmlParts.push(renderToolResult({
        title: `Autoloop stopped #${iter}`,
        body: previousOutcome,
        isError: true,
      }));
      break;
    }

    let appliedInIter = 0;
    for (const change of proposal.changes.slice(0, Math.max(1, autonomousMaxFilesPerIter))) {
      try {
        const relPath = sanitizeModelPath(change.path);
        const snapshot = await readWorkspaceTextIfExists(relPath);
        const oldContent = snapshot.exists ? snapshot.content : "";
        const newContent = String(change.content || "");
        const diffText = await createPreviewDiff({ relPath, oldContent, newContent });
        appendToolLog(session, {
          title: `autoloop diff #${iter} ${relPath}`,
          summary: `action=${change.action}`,
          detail: diffText,
        });
        htmlParts.push(renderToolResult({
          title: `Autoloop diff #${iter}: ${relPath}`,
          meta: `action=${change.action}`,
          body: diffText,
        }));

        if (!autoApply) {
          continue;
        }
        if (oldContent === newContent) {
          continue;
        }
        const resolvedPath = resolveWorkspacePath(relPath);
        await mkdir(path.dirname(resolvedPath), { recursive: true });
        await writeFile(resolvedPath, newContent, "utf8");
        appliedPaths.push(relPath);
        appliedInIter += 1;
        appendToolLog(session, {
          title: `autoloop apply #${iter} ${relPath}`,
          summary: `bytes=${Buffer.byteLength(newContent, "utf8")}`,
          detail: "Applied successfully.",
        });
        htmlParts.push(renderToolResult({
          title: `Autoloop apply #${iter}: ${relPath}`,
          meta: `bytes=${Buffer.byteLength(newContent, "utf8")}`,
          body: "Applied successfully.",
        }));
      } catch (err) {
        const relPath = sanitizeModelPath(change.path);
        const message = err?.message || String(err);
        appendToolLog(session, {
          title: `autoloop change error #${iter} ${relPath}`,
          summary: "skipped",
          detail: message,
        });
        htmlParts.push(renderToolResult({
          title: `Autoloop change error #${iter}: ${relPath}`,
          body: message,
          isError: true,
        }));
      }
    }

    previousOutcome = `Applied ${appliedInIter} file(s).`;

    if (runValidation && autoApply && plan.validationCommands.length > 0) {
      for (const command of plan.validationCommands.slice(0, Math.max(1, autonomousMaxValidationCommands))) {
        if (!isAllowedShellCommand(command)) {
          const text = `Validation command blocked by allowlist: ${command}`;
          appendToolLog(session, {
            title: `autoloop validate blocked #${iter}`,
            summary: command,
            detail: text,
          });
          htmlParts.push(renderToolResult({
            title: `Autoloop validation blocked #${iter}`,
            body: text,
            isError: true,
          }));
          continue;
        }
        const result = await runShellCommand(command, workspaceRoot);
        const output = [
          `$ ${command}`,
          result.stdout ? `\n[stdout]\n${result.stdout}` : "",
          result.stderr ? `\n[stderr]\n${result.stderr}` : "",
        ].join("");
        appendToolLog(session, {
          title: `autoloop validate #${iter}`,
          summary: `exit=${result.exitCode}`,
          detail: output,
        });
        htmlParts.push(renderToolResult({
          title: `Autoloop validation #${iter}`,
          meta: `exit=${result.exitCode} timeout=${result.timedOut ? "yes" : "no"}`,
          body: output || "(no output)",
          isError: result.exitCode !== 0 || result.timedOut || Boolean(result.spawnError),
        }));
      }
    }

    if (proposal.done || plan.done) {
      break;
    }
  }

  const uniqueApplied = [...new Set(appliedPaths)];
  return {
    html: htmlParts.join(""),
    appliedPaths: uniqueApplied,
  };
}

function sleepMs(ms) {
  const safeMs = Math.max(0, Number.parseInt(ms, 10) || 0);
  return new Promise((resolve) => setTimeout(resolve, safeMs));
}

function isTransientRunPodStatus(statusCode) {
  return [408, 425, 429, 500, 502, 503, 504].includes(Number.parseInt(statusCode, 10));
}

function isAbortError(err) {
  const name = String(err?.name || "");
  if (name === "AbortError") return true;
  const message = String(err?.message || "");
  return /aborted|timed out|timeout|und_err_connect_timeout/i.test(message);
}

function isTransientRunPodError(err) {
  if (isAbortError(err)) return true;
  if (isTransientRunPodStatus(err?.statusCode)) return true;
  const message = String(err?.message || "");
  return /fetch failed|econnreset|econnrefused|etimedout|enotfound|eai_again|network/i.test(message);
}

async function callRunPodWithRetry(label, executor) {
  const attempts = Math.max(1, runPodHttpRetryMaxAttempts);
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await executor();
    } catch (err) {
      lastError = err;
      const canRetry = attempt < attempts && isTransientRunPodError(err);
      if (!canRetry) {
        throw err;
      }

      const baseDelay = Math.max(0, runPodHttpRetryDelayMs);
      const maxDelay = Math.max(0, runPodHttpRetryMaxDelayMs);
      const backoffDelay = baseDelay * Math.max(1, 2 ** (attempt - 1));
      const waitMs = maxDelay > 0 ? Math.min(backoffDelay, maxDelay) : backoffDelay;
      const statusPart = Number.isInteger(err?.statusCode) ? `HTTP ${err.statusCode}` : (err?.name || "network");
      console.warn(`[node-htmx] ${label} transient error (${statusPart}) attempt ${attempt}/${attempts}; retry in ${waitMs} ms.`);
      await sleepMs(waitMs);
    }
  }

  throw lastError || new Error(`RunPod request failed: ${label}`);
}

async function callRunPodJson(endpointPath, body) {
  const url = `${runPodBaseUrl}${endpointPath}`;
  return callRunPodWithRetry(`POST ${endpointPath}`, async () => {
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
  });
}

async function callRunPodModels() {
  const url = `${runPodBaseUrl}/models`;
  return callRunPodWithRetry("GET /models", async () => {
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
  });
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

function isContextExceededError(err) {
  const message = String(err?.message || "");
  if (/context size has been exceeded/i.test(message)) {
    return true;
  }
  const payloadError = String(
    err?.payload?.error
    || err?.payload?.message
    || err?.payload?.detail
    || "",
  );
  return /context size has been exceeded/i.test(payloadError);
}

function compactMessagesForContextRetry(messages) {
  const rows = Array.isArray(messages) ? messages : [];
  if (rows.length <= 6) {
    return rows;
  }
  const stableSystem = rows
    .filter((row, index) => index < 2 && row?.role === "system")
    .map((row) => ({ role: row.role, content: row.content }));
  const tail = rows
    .slice(-6)
    .filter((row) => row && typeof row === "object")
    .map((row) => ({ role: row.role, content: row.content }));
  return [...stableSystem, ...tail];
}

function renderUserTurn(userPrompt) {
  return [
    '<article class="turn turn-user">',
    '<header class="turn-header">You</header>',
    `<pre class="turn-body">${escapeHtml(userPrompt)}</pre>`,
    "</article>",
  ].join("");
}

function renderAssistantTurn({ assistantText, model, elapsedMs }) {
  return [
    '<article class="turn turn-assistant">',
    `<header class="turn-header">LocaLingo (${escapeHtml(model)})</header>`,
    `<pre class="turn-body">${escapeHtml(assistantText)}</pre>`,
    `<footer class="turn-footer">${elapsedMs} ms</footer>`,
    "</article>",
  ].join("");
}

function renderTurn({
  userPrompt,
  assistantText,
  model,
  elapsedMs,
  middleHtml = "",
  includeUserTurn = true,
  includeMiddleHtml = true,
}) {
  const parts = [];
  if (includeUserTurn) {
    parts.push(renderUserTurn(userPrompt));
  }
  if (includeMiddleHtml && middleHtml) {
    parts.push(middleHtml);
  }
  parts.push(renderAssistantTurn({ assistantText, model, elapsedMs }));
  return parts.join("");
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
  activeHttpRequestCount += 1;
  lastHttpActivityMs = Date.now();
  let requestSettled = false;
  const settleRequest = () => {
    if (requestSettled) return;
    requestSettled = true;
    activeHttpRequestCount = Math.max(0, activeHttpRequestCount - 1);
    lastHttpActivityMs = Date.now();
  };
  res.on("finish", settleRequest);
  res.on("close", settleRequest);

  const reqUrl = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  const pathname = reqUrl.pathname;

  if (req.method === "GET" && pathname === "/health") {
    send(res, 200, { ok: true, service: "node-htmx-client" }, "application/json; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/client/ping") {
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const clientId = markClientHeartbeat(data.get("clientId") || data.get("client_id") || "");
      if (!clientId) {
        send(res, 400, { ok: false, error: "clientId is required." }, "application/json; charset=utf-8");
        return;
      }
      send(res, 204, "", "text/plain; charset=utf-8");
    } catch {
      send(res, 400, { ok: false, error: "invalid ping request." }, "application/json; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/client/disconnect") {
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const clientId = normalizeClientId(data.get("clientId") || data.get("client_id") || "");
      if (!clientId) {
        send(res, 400, { ok: false, error: "clientId is required." }, "application/json; charset=utf-8");
        return;
      }
      markClientDisconnected(clientId);
      send(res, 204, "", "text/plain; charset=utf-8");
    } catch {
      send(res, 400, { ok: false, error: "invalid disconnect request." }, "application/json; charset=utf-8");
    }
    return;
  }

  if (req.method === "GET" && pathname === "/api/workspace/info") {
    const text = [
      `root: ${workspaceRoot}`,
      `shell allowlist: ${shellAllowlist.join(", ")}`,
      `uv_bin: ${configuredUvBin || "(auto lookup)"}`,
      `python_bin: ${configuredPythonBin || "(auto lookup)"}`,
      `generation: temperature=${generationTemperatureDefault} top_p=${generationTopP} top_k=${generationTopK} min_p=${generationMinP}`,
      `generation context: max_tokens=${generationMaxContextTokens} reserve=${generationContextReserveTokens}`,
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
    session.plan = [];
    send(res, 200, "", "text/html; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/reset") {
    const session = getOrCreateSession(req, res);
    session.toolLogs = [];
    session.plan = [];
    send(res, 200, "", "text/html; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/read") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const rawPath = (data.get("path") || "").trim();
      const fileData = await readLocalFileForTool(rawPath);
      appendToolLog(session, {
        title: `read ${fileData.displayPath}`,
        summary: fileData.meta,
        detail: fileData.shown,
      });
      send(res, 200, renderToolResult({
        title: `Tool read: ${fileData.displayPath}`,
        meta: fileData.meta,
        body: fileData.shown || "(empty file)",
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

  if (req.method === "POST" && pathname === "/api/tools/read_file") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const fileSlice = await readTextFileSliceForTool(
        (data.get("path") || "").trim(),
        data.get("offset") || data.get("line") || data.get("start_line"),
        data.get("limit") || data.get("max_lines") || data.get("lines"),
      );
      const meta = [
        `bytes=${fileSlice.sizeBytes}`,
        `lines=${fileSlice.totalLines}`,
        `offset=${fileSlice.offset}`,
        `limit=${fileSlice.limit}`,
        `returned=${fileSlice.returnedLines}`,
      ].join(" ");
      appendToolLog(session, {
        title: `read_file ${fileSlice.relPath}`,
        summary: meta,
        detail: fileSlice.content || "(no lines)",
      });
      send(res, 200, renderToolResult({
        title: `Tool read_file: ${fileSlice.relPath}`,
        meta,
        body: fileSlice.content || "(no lines)",
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool read_file error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/list_dir") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const recursive = parseBooleanEnv(data.get("recursive"), false);
      const maxDepth = clampInteger(data.get("max_depth") || data.get("maxDepth"), 2, 0, 6);
      const limit = clampInteger(data.get("limit") || data.get("max_entries") || data.get("maxEntries"), 200, 1, 500);
      const listing = await listWorkspaceEntriesForTool({
        rawPath: (data.get("path") || data.get("dir") || data.get("target") || ".").trim(),
        recursive,
        maxDepth,
        limit,
      });
      const lines = [
        `root=${listing.root}`,
        `entries=${listing.entries.length}`,
        `truncated=${listing.truncated ? "yes" : "no"}`,
        "",
      ];
      for (const item of listing.entries) {
        if (item.type === "file") {
          lines.push(`- [file] ${item.path} (${item.size} bytes)`);
        } else if (item.type === "dir") {
          lines.push(`- [dir] ${item.path}`);
        } else {
          lines.push(`- [other] ${item.path}`);
        }
      }
      const body = lines.join("\n");
      appendToolLog(session, {
        title: `list_dir ${listing.root}`,
        summary: `entries=${listing.entries.length} truncated=${listing.truncated ? "yes" : "no"}`,
        detail: body,
      });
      send(res, 200, renderToolResult({
        title: "Tool list_dir",
        meta: `entries=${listing.entries.length} truncated=${listing.truncated ? "yes" : "no"}`,
        body,
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool list_dir error",
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
      if (!rawPath) {
        throw new Error("Path is empty.");
      }
      const content = String(data.get("content") || "");
      const resolvedPath = resolveWorkspacePath(rawPath);
      const relPath = toWorkspaceRelative(resolvedPath);
      const ext = path.extname(relPath).toLowerCase();

      if (isOfficeFileExtension(ext)) {
        await mkdir(path.dirname(resolvedPath), { recursive: true });
        const writePayload = await writeOfficeFileViaPython(resolvedPath, content);
        const readBack = await readLocalFileForTool(relPath);
        const bytes = Number.isFinite(Number(writePayload?.bytes))
          ? Number(writePayload.bytes)
          : readBack.sizeBytes;
        const summaryParts = [`bytes=${bytes}`, `format=${String(writePayload?.format || ext.replace(/^\./, ""))}`];
        if (Number.isInteger(writePayload?.sheets)) {
          summaryParts.push(`sheets=${writePayload.sheets}`);
        }
        if (Number.isInteger(writePayload?.cells)) {
          summaryParts.push(`cells=${writePayload.cells}`);
        }
        if (Number.isInteger(writePayload?.paragraphs)) {
          summaryParts.push(`paragraphs=${writePayload.paragraphs}`);
        }
        if (Number.isInteger(writePayload?.slides)) {
          summaryParts.push(`slides=${writePayload.slides}`);
        }
        if (Number.isInteger(writePayload?.text_lines)) {
          summaryParts.push(`text_lines=${writePayload.text_lines}`);
        }
        const summary = summaryParts.join(" ");
        appendToolLog(session, {
          title: `write ${relPath}`,
          summary,
          detail: readBack.shown || "(empty document)",
        });
        send(res, 200, renderToolResult({
          title: `Tool write: ${relPath}`,
          meta: summary,
          body: "Office document written.",
        }), "text/html; charset=utf-8");
      } else {
        await mkdir(path.dirname(resolvedPath), { recursive: true });
        await writeFile(resolvedPath, content, "utf8");
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
      }
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool write error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/apply_patch") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const patchText = String(data.get("patch") || data.get("content") || data.get("text") || "");
      if (!patchText.trim()) {
        send(res, 200, renderToolResult({
          title: "Tool apply_patch error",
          body: "Patch text is empty.",
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      const applyResults = await applyPatchOperations(patchText);
      const summaryLines = [
        `operations=${applyResults.length}`,
      ];
      for (const row of applyResults) {
        const moved = row.fromPath ? ` from=${row.fromPath}` : "";
        summaryLines.push(`- ${row.action} path=${row.path}${moved} bytes=${row.bytes}`);
      }
      const body = summaryLines.join("\n");
      const detailParts = [body];
      for (const row of applyResults) {
        detailParts.push("");
        detailParts.push(`# diff ${row.path}`);
        detailParts.push(row.diff || "(no diff)");
      }
      const detail = detailParts.join("\n");
      appendToolLog(session, {
        title: "apply_patch",
        summary: `operations=${applyResults.length}`,
        detail,
      });
      send(res, 200, renderToolResult({
        title: "Tool apply_patch",
        meta: `operations=${applyResults.length}`,
        body: detail,
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool apply_patch error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/tools/update_plan") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const planRaw = String(data.get("plan") || "[]");
      let parsedPlan = [];
      try {
        const parsed = JSON.parse(planRaw);
        parsedPlan = Array.isArray(parsed) ? parsed : [];
      } catch {
        parsedPlan = [];
      }
      const allowedStatus = new Set(["pending", "in_progress", "completed"]);
      const normalizedPlan = parsedPlan
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const step = String(item.step || "").trim();
          if (!step) return null;
          const statusRaw = String(item.status || "").trim().toLowerCase();
          return {
            step,
            status: allowedStatus.has(statusRaw) ? statusRaw : "pending",
          };
        })
        .filter(Boolean)
        .slice(0, 30);
      session.plan = normalizedPlan;
      const explanation = String(data.get("explanation") || "").trim();
      const detail = JSON.stringify({ explanation, plan: normalizedPlan }, null, 2);
      appendToolLog(session, {
        title: "update_plan",
        summary: `items=${normalizedPlan.length}`,
        detail,
      });
      send(res, 200, renderToolResult({
        title: "Tool update_plan",
        meta: `items=${normalizedPlan.length}`,
        body: detail,
      }), "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Tool update_plan error",
        body: err?.message || String(err),
        isError: true,
      }), "text/html; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/autoloop/run") {
    const session = getOrCreateSession(req, res);
    try {
      const bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const objective = (data.get("objective") || "").trim();
      const model = (data.get("model") || defaultModel).trim() || defaultModel;
      const temperatureRaw = (data.get("temperature") || String(generationTemperatureDefault)).trim();
      const loopRaw = (data.get("maxIterations") || "1").trim();
      const includeToolContext = data.get("includeToolContext") === "on";
      const autoApply = data.get("autoApply") === "on";
      const approveAutoApply = data.get("approveAutoApply") === "on";
      const runValidation = data.get("runValidation") === "on";

      if (!objective) {
        send(res, 200, renderToolResult({
          title: "Autoloop error",
          body: "Objective is empty.",
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }
      if (autoApply && !approveAutoApply) {
        send(res, 200, renderToolResult({
          title: "Autoloop blocked",
          body: "Enable \"I approve autonomous apply\" before auto-apply mode.",
          isError: true,
        }), "text/html; charset=utf-8");
        return;
      }

      const parsedTemperature = Number.parseFloat(temperatureRaw);
      const parsedLoops = Number.parseInt(loopRaw, 10);
      const maxIterations = Math.min(
        Math.max(1, Number.isInteger(parsedLoops) ? parsedLoops : 1),
        Math.max(1, autonomousLoopMaxIters),
      );
      const temperature = Number.isFinite(parsedTemperature) ? parsedTemperature : generationTemperatureDefault;

      const startMeta = [
        `model=${model}`,
        `iterations=${maxIterations}`,
        `autoApply=${autoApply ? "yes" : "no"}`,
        `validation=${runValidation ? "yes" : "no"}`,
      ].join(" ");
      appendToolLog(session, {
        title: "autoloop start",
        summary: startMeta,
        detail: objective,
      });

      const started = Date.now();
      const loopResult = await runAutonomousLoop({
        session,
        objective,
        model,
        temperature,
        includeToolContext,
        maxIterations,
        autoApply,
        runValidation,
      });
      const elapsedMs = Date.now() - started;
      const finalBody = [
        `elapsed=${elapsedMs}ms`,
        `applied_files=${loopResult.appliedPaths.length}`,
        loopResult.appliedPaths.length > 0 ? `paths=${loopResult.appliedPaths.join(", ")}` : "",
      ].filter(Boolean).join("\n");
      appendToolLog(session, {
        title: "autoloop finished",
        summary: `elapsed=${elapsedMs}ms applied=${loopResult.appliedPaths.length}`,
        detail: finalBody,
      });

      const finishCard = renderToolResult({
        title: "Autoloop finished",
        meta: `elapsed=${elapsedMs}ms`,
        body: finalBody,
      });
      send(res, 200, `${loopResult.html}${finishCard}`, "text/html; charset=utf-8");
    } catch (err) {
      send(res, 200, renderToolResult({
        title: "Autoloop error",
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
      const omitUserTurn = parseBooleanEnv(data.get("omit_user_turn") || data.get("omitUserTurn"), false);
      const omitMiddleHtml = parseBooleanEnv(data.get("omit_middle_html") || data.get("omitMiddleHtml"), false);
      const model = defaultModel;
      const temperatureRaw = (data.get("temperature") || String(autoToolTemperature)).trim();
      const temperature = Number.parseFloat(temperatureRaw);

      if (!prompt) {
        send(res, 400, renderError("Prompt is empty."), "text/html; charset=utf-8");
        return;
      }

      const started = Date.now();
      const autoResult = await runAutoToolChat({
        session,
        prompt,
        model,
        temperature,
      });
      const assistantText = autoResult.assistantText || "(empty response)";
      const elapsedMs = Date.now() - started;

      session.messages.push({ role: "user", content: prompt });
      session.messages.push({ role: "assistant", content: assistantText });
      session.messages = trimHistory(session.messages);

      send(
        res,
        200,
        renderTurn({
          userPrompt: prompt,
          assistantText,
          model,
          elapsedMs,
          middleHtml: autoResult.html,
          includeUserTurn: !omitUserTurn,
          includeMiddleHtml: !omitMiddleHtml,
        }),
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

  if (req.method === "POST" && pathname === "/api/chat/stream") {
    const session = getOrCreateSession(req, res);
    let bodyText = "";
    let keepaliveTimer = null;
    const tuneStreamSocket = () => {
      try {
        if (typeof req.setTimeout === "function") {
          req.setTimeout(0);
        }
      } catch {
        // ignore
      }
      try {
        if (typeof res.setTimeout === "function") {
          res.setTimeout(0);
        }
      } catch {
        // ignore
      }
      try {
        if (res.socket) {
          if (typeof res.socket.setTimeout === "function") {
            res.socket.setTimeout(0);
          }
          if (typeof res.socket.setKeepAlive === "function") {
            res.socket.setKeepAlive(true, Math.max(1000, streamKeepaliveIntervalMs));
          }
        }
      } catch {
        // ignore
      }
    };
    const clearKeepalive = () => {
      if (keepaliveTimer) {
        clearInterval(keepaliveTimer);
        keepaliveTimer = null;
      }
    };
    try {
      bodyText = await readBody(req);
      const data = new URLSearchParams(bodyText);
      const prompt = (data.get("prompt") || "").trim();
      const model = defaultModel;
      const temperatureRaw = (data.get("temperature") || String(autoToolTemperature)).trim();
      const temperature = Number.parseFloat(temperatureRaw);

      beginNdjson(res, 200);
      tuneStreamSocket();
      keepaliveTimer = setInterval(() => {
        writeNdjson(res, { type: "keepalive" });
      }, Math.max(2000, streamKeepaliveIntervalMs));
      if (typeof keepaliveTimer.unref === "function") {
        keepaliveTimer.unref();
      }
      if (!prompt) {
        writeNdjson(res, {
          type: "error",
          message: "Prompt is empty.",
        });
        clearKeepalive();
        res.end();
        return;
      }

      writeNdjson(res, {
        type: "user_turn",
        html: renderUserTurn(prompt),
      });

      const started = Date.now();
      const autoResult = await runAutoToolChat({
        session,
        prompt,
        model,
        temperature,
        onEvent: (eventPayload) => {
          writeNdjson(res, eventPayload);
        },
      });
      const assistantText = autoResult.assistantText || "(empty response)";
      const elapsedMs = Date.now() - started;

      session.messages.push({ role: "user", content: prompt });
      session.messages.push({ role: "assistant", content: assistantText });
      session.messages = trimHistory(session.messages);

      writeNdjson(res, {
        type: "assistant_turn",
        html: renderAssistantTurn({ assistantText, model, elapsedMs }),
      });
      writeNdjson(res, {
        type: "done",
        elapsedMs,
      });
      clearKeepalive();
      res.end();
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

      if (!res.headersSent) {
        beginNdjson(res, 200);
      }
      writeNdjson(res, {
        type: "error",
        message: msg,
      });
      clearKeepalive();
      res.end();
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
  if (configuredUvBin) {
    console.log(`[node-htmx] bundled uv: ${configuredUvBin}`);
  }
  if (configuredPythonBin) {
    console.log(`[node-htmx] bundled python: ${configuredPythonBin}`);
  }
  console.log(
    `[node-htmx] generation defaults: temperature=${generationTemperatureDefault} top_p=${generationTopP} top_k=${generationTopK} min_p=${generationMinP}`,
  );
  console.log(
    `[node-htmx] generation context: max_context_tokens=${generationMaxContextTokens} reserve_tokens=${generationContextReserveTokens}`,
  );
  console.log(`[node-htmx] playwright mcp: ${playwrightMcpEnabled ? "enabled" : "disabled"} (${playwrightMcpBrowser})`);
  console.log(
    `[node-htmx] client autostop: ${clientAutostopEnabled ? "enabled" : "disabled"} `
    + `(heartbeat=${Math.max(1000, clientHeartbeatIntervalMs)}ms stale=${Math.max(1000, clientHeartbeatStaleMs)}ms idle=${Math.max(1000, clientAutostopIdleMs)}ms)`,
  );
  console.log(
    `[node-htmx] stream keepalive: every ${Math.max(2000, streamKeepaliveIntervalMs)}ms, autostop_grace=${Math.max(1000, clientAutostopRequestGraceMs)}ms`,
  );
});
