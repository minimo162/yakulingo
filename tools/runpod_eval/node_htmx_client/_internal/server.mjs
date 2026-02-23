import http from "node:http";
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, unlink, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
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
const timeoutMs = Number.parseInt(process.env.RUNPOD_REQUEST_TIMEOUT_MS || "120000", 10);
const runPodModelsTimeoutMs = parseIntEnv(
  process.env.RUNPOD_MODELS_TIMEOUT_MS,
  Math.min(30000, Math.max(5000, timeoutMs)),
  3000,
  300000,
);
const runPodChatTimeoutMs = parseIntEnv(
  process.env.RUNPOD_CHAT_TIMEOUT_MS,
  Math.max(120000, timeoutMs),
  10000,
  900000,
);
const runPodHealthcheckOnChat = parseBooleanEnv(process.env.RUNPOD_HEALTHCHECK_ON_CHAT, true);
const runPodHealthcheckTtlMs = parseIntEnv(process.env.RUNPOD_HEALTHCHECK_TTL_MS, 20000, 0, 600000);
const appTimeZone = (process.env.APP_TIME_ZONE || "Asia/Tokyo").trim() || "Asia/Tokyo";
const runPodHttpRetryMaxAttempts = parseIntEnv(process.env.RUNPOD_HTTP_RETRY_MAX_ATTEMPTS, 5, 1, 12);
const runPodHttpRetryDelayMs = parseIntEnv(process.env.RUNPOD_HTTP_RETRY_DELAY_MS, 1200, 0, 30000);
const runPodHttpRetryMaxDelayMs = parseIntEnv(process.env.RUNPOD_HTTP_RETRY_MAX_DELAY_MS, 10000, 0, 120000);
const runPodBaseUrl = (process.env.RUNPOD_BASE_URL || "").trim().replace(/\/+$/, "");
const runPodApiKey = (process.env.RUNPOD_API_KEY || "").trim();
const defaultModel = (process.env.DEFAULT_MODEL || "gpt-oss-swallow-120b-iq4xs").trim();
const maxHistoryPairs = parseIntEnv(process.env.MAX_HISTORY_PAIRS, 16, 4, 128);
const historyCompactionKeepRecentPairs = parseIntEnv(
  process.env.HISTORY_COMPACTION_KEEP_RECENT_PAIRS,
  4,
  1,
  64,
);
const historyCompactionSummaryMaxChars = parseIntEnv(
  process.env.HISTORY_COMPACTION_SUMMARY_MAX_CHARS,
  18000,
  2000,
  120000,
);
const sessionAutoCompactTokenLimit = parseIntEnv(
  process.env.SESSION_AUTO_COMPACT_TOKEN_LIMIT,
  22000,
  1024,
  262144,
);
const sessionCompactionTargetRatio = parseFloatEnv(process.env.SESSION_COMPACTION_TARGET_RATIO, 0.68, 0.4, 0.95);
const sessionCompactionSystemPromptReserveTokens = parseIntEnv(
  process.env.SESSION_COMPACTION_SYSTEM_PROMPT_RESERVE_TOKENS,
  2400,
  256,
  65536,
);
const contextRetryKeepRecentMessages = parseIntEnv(
  process.env.CONTEXT_RETRY_KEEP_RECENT_MESSAGES,
  8,
  4,
  48,
);
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
const showInternalRecoveryCards = parseBooleanEnv(process.env.SHOW_INTERNAL_RECOVERY_CARDS, false);
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
const assistantStreamEnabled = parseBooleanEnv(process.env.ASSISTANT_STREAM_ENABLED, true);
const assistantStreamChunkChars = parseIntEnv(process.env.ASSISTANT_STREAM_CHUNK_CHARS, 48, 8, 512);
const assistantStreamChunkDelayMs = parseIntEnv(process.env.ASSISTANT_STREAM_CHUNK_DELAY_MS, 12, 0, 250);
const defaultWorkspaceRoot = path.join(__dirname, "..", "workspace");
const configuredWorkspaceRoot = path.resolve((process.env.WORKSPACE_ROOT || defaultWorkspaceRoot).trim() || defaultWorkspaceRoot);
const configuredWorkspaceStateFile = (process.env.WORKSPACE_STATE_FILE || "").trim();
const workspaceStateFile = resolveWorkspaceStateFile();
let workspaceRoot = configuredWorkspaceRoot;
const restoredWorkspaceRoot = await loadWorkspaceRootFromStateFile();
if (restoredWorkspaceRoot) {
  workspaceRoot = restoredWorkspaceRoot;
}
try {
  await mkdir(workspaceRoot, { recursive: true });
} catch (err) {
  if (restoredWorkspaceRoot) {
    console.warn(`[node-htmx] failed to use restored workspace root (${workspaceRoot}): ${err?.message || String(err)}`);
    workspaceRoot = configuredWorkspaceRoot;
    await mkdir(workspaceRoot, { recursive: true });
  } else {
    throw err;
  }
}
await persistWorkspaceRootState();
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
const autoToolNames = [
  "read",
  "read_file",
  "list_dir",
  "search",
  "shell",
  "write",
  "apply_patch",
  "update_plan",
  "web_search",
];

function normalizeToolAlias(rawName) {
  const name = String(rawName || "").trim().toLowerCase();
  const aliasMap = {
    shell_command: "shell",
    exec_command: "shell",
    applypatch: "apply_patch",
    readfile: "read_file",
    listdir: "list_dir",
    websearch: "web_search",
  };
  return aliasMap[name] || name;
}

const autoToolDecisionSchemaDescription = {
  oneOf: [
    {
      type: "tool_call",
      call_id: "string (recommended, optional; generated if omitted)",
      tool_name: autoToolNames.join("|"),
      arguments: "{...}",
      reason: "short reason",
    },
    {
      type: "final",
      message: "final answer for the user in Japanese",
    },
  ],
  compatibility: [
    '{"type":"tool","tool":"...","args":{...}}',
    '{"type":"answer","message":"..."}',
    '{"type":"function_call","call_id":"...","name":"...","arguments":"{\\"path\\":\\"...\\"}"}',
    '{"type":"response.output_item.done","item":{"type":"function_call","call_id":"...","name":"...","arguments":"{\\"path\\":\\"...\\"}"}}',
  ],
};
const autoToolSpecs = [
  {
    name: "read",
    strict: false,
    description: "Read local file or URL. Supports PDF and Office text extraction.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        path: { type: "string", description: "Local absolute/relative path or http(s) URL." },
      },
      required: ["path"],
    },
  },
  {
    name: "read_file",
    strict: false,
    description: "Read text file slices (line-based). Also supports URL fetch.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        path: { type: "string" },
        offset: { type: "number" },
        limit: { type: "number" },
      },
      required: ["path"],
    },
  },
  {
    name: "list_dir",
    strict: false,
    description: "List files/dirs under workspace root.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        path: { type: "string" },
        recursive: { type: "boolean" },
        max_depth: { type: "number" },
        limit: { type: "number" },
      },
      required: [],
    },
  },
  {
    name: "search",
    strict: false,
    description: "Search text/regex in workspace files.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        pattern: { type: "string" },
        glob: { type: "string" },
      },
      required: ["pattern"],
    },
  },
  {
    name: "shell",
    strict: false,
    description: "Run one allowlisted local shell command.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        command: { type: "string" },
      },
      required: ["command"],
    },
  },
  {
    name: "write",
    strict: false,
    description: "Write file content into workspace root only.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        path: { type: "string" },
        content: {
          anyOf: [
            { type: "string" },
            { type: "object" },
            { type: "array" },
            { type: "number" },
            { type: "boolean" },
            { type: "null" },
          ],
        },
      },
      required: ["path", "content"],
    },
  },
  {
    name: "apply_patch",
    strict: false,
    description: "Apply codex-style patch text inside workspace root only.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        patch: { type: "string" },
      },
      required: ["patch"],
    },
  },
  {
    name: "update_plan",
    strict: false,
    description: "Update in-session plan snapshot.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        explanation: { type: "string" },
        plan: {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            properties: {
              step: { type: "string" },
              status: { type: "string" },
            },
            required: ["step", "status"],
          },
        },
      },
      required: ["plan"],
    },
  },
  {
    name: "web_search",
    strict: false,
    description: "Search web via Playwright MCP and return summarized results.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        query: { type: "string" },
        max_results: { type: "number" },
      },
      required: ["query"],
    },
  },
];
const autoToolSystemPrompt = [
  "You are a practical coding agent for a local repository.",
  "Return ONLY one JSON object. Do not include markdown.",
  "Prefer codex-like format with call_id and explicit tool_name.",
  "Codex compatibility: function_call with JSON-string arguments is accepted.",
  "Decision schema:",
  JSON.stringify(autoToolDecisionSchemaDescription),
  "Tool specs (JSON schema style):",
  JSON.stringify(autoToolSpecs),
  "For web_search, always provide a non-empty query string.",
  "read can read any local file path and also http(s) URLs. It can extract PDF and Office (.xlsx/.docx/.pptx) text.",
  "When answering after URL reads, focus on the user's question and ignore navigation/ads/link lists unless explicitly asked.",
  "Prefer read_file for text/code files to avoid oversized context.",
  "write is allowed only inside workspace_root.",
  "For .xlsx/.docx/.pptx write, content can be plain text or JSON.",
  "apply_patch is allowed only inside workspace_root and should be preferred for partial edits.",
  "If the user message includes a file path, call read first instead of claiming you cannot access local files.",
  "If the user asks to create/update a file in workspace, you must call write or apply_patch before final.",
  "Do not finish with instructions-only text when a file write was explicitly requested.",
  "Use web_search for latest/current external information needs.",
  "For latest news requests: do web_search, then open at least one result URL with read before final.",
  "For latest news final answers: cite concrete source URLs from gathered evidence.",
  "Current date context will be provided as current_date_jst/current_utc_iso in system messages.",
  "Resolve relative dates (today/今日/tomorrow/明日/yesterday/昨日) strictly from the provided date context.",
  "For weather/news questions asking about today, do not invent arbitrary calendar dates.",
  "For latest/current questions without explicit historical date in prompt, avoid old 'as of YYYY-MM' phrasing.",
  "Use one tool call at a time and wait for the tool result.",
  "Prefer list_dir/read_file/search before write/apply_patch. Use shell only when needed.",
  "Every tool_call should include a stable call_id. If omitted, runtime will assign one.",
  "When you call a tool, use arguments object (not args string).",
  "If you output codex-style function_call, arguments may be JSON string but must be valid JSON object text.",
  "Do not repeat the same tool call with identical arguments immediately after it just ran.",
  "Assume the runtime enforces tool_call/output pairing and may synthesize missing outputs.",
  "Read compacted session summary (if provided) and keep thread continuity.",
  "Keep the original user question in focus across all steps. Do not drift to a side detail.",
  "Before returning final, verify it still answers the original user question.",
  "When task is complete, return type=final.",
].join("\n");
const autoToolJsonRepairSystemPrompt = [
  "You repair malformed JSON emitted by another assistant.",
  "Output ONLY one valid JSON object. No markdown.",
  "Target schema:",
  JSON.stringify(autoToolDecisionSchemaDescription),
  "Tool specs:",
  JSON.stringify(autoToolSpecs),
  "Codex compatibility: function_call + arguments(JSON string) is acceptable if valid.",
  "Preserve original intent. If unclear, return type=final.",
].join("\n");
const autoToolFinalRewriteSystemPrompt = [
  "You are a response quality guard for a tool-augmented assistant.",
  "Return ONLY the final user-facing answer in Japanese.",
  "Answer the latest user question directly and concisely.",
  "Preserve the requested scope; do not collapse broad questions into one narrow detail.",
  "If the user asked for latest news/summary/list, provide multiple concrete items when evidence exists.",
  "For latest news answers, include source URLs from tool evidence.",
  "For time-sensitive prompts (latest/current/today/tomorrow/yesterday), strictly align with provided current_date_jst/current_utc_iso.",
  "If the prompt does not request a historical date explicitly, do not answer with an old 'as of YYYY-MM' anchor.",
  "If exact publication dates are unclear from evidence, avoid inventing dates and state uncertainty plainly.",
  "Use tool evidence when available; ignore unrelated navigation, ads, and boilerplate links.",
  "If evidence is insufficient, say so plainly and avoid fabrication.",
  "Do not output JSON, markdown headings, or raw tool dumps.",
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
const runPodHealthState = {
  lastOkAtMs: 0,
  lastCheckedAtMs: 0,
  inFlightPromise: null,
  lastError: "",
};

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

function resolveWorkspaceStateFile() {
  if (configuredWorkspaceStateFile) {
    return path.resolve(configuredWorkspaceStateFile);
  }
  const localAppData = (process.env.LOCALAPPDATA || "").trim();
  if (localAppData) {
    return path.join(localAppData, "YakuLingoRunpodHtmx", "workspace-state.json");
  }
  const xdgStateHome = (process.env.XDG_STATE_HOME || "").trim();
  if (xdgStateHome) {
    return path.join(xdgStateHome, "localingo", "workspace-state.json");
  }
  return path.join(homedir(), ".local", "state", "localingo", "workspace-state.json");
}

async function loadWorkspaceRootFromStateFile() {
  try {
    const raw = await readFile(workspaceStateFile, "utf8");
    const parsed = JSON.parse(raw);
    const candidate = String(parsed?.workspaceRoot || "").trim();
    if (!candidate) return null;
    return path.resolve(candidate);
  } catch (err) {
    if (err?.code !== "ENOENT") {
      console.warn(`[node-htmx] failed to read workspace state (${workspaceStateFile}): ${err?.message || String(err)}`);
    }
    return null;
  }
}

async function persistWorkspaceRootState() {
  const payload = {
    version: 1,
    workspaceRoot,
    updatedAt: new Date().toISOString(),
  };
  await mkdir(path.dirname(workspaceStateFile), { recursive: true });
  await writeFile(workspaceStateFile, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function isInsideWorkspace(absPath) {
  const normalizedPath = normalizeForCompare(path.resolve(absPath));
  const normalizedRoot = normalizeForCompare(workspaceRoot);
  return normalizedPath === normalizedRoot || normalizedPath.startsWith(`${normalizedRoot}${path.sep}`);
}

async function setWorkspaceRoot(nextPath, { createIfMissing = true } = {}) {
  const raw = String(nextPath || "").trim();
  if (!raw) {
    throw new Error("Workspace path is empty.");
  }
  const resolved = path.resolve(raw);
  let info = null;
  try {
    info = await stat(resolved);
  } catch (err) {
    if (err?.code !== "ENOENT" || !createIfMissing) {
      throw err;
    }
    await mkdir(resolved, { recursive: true });
    info = await stat(resolved);
  }
  if (!info?.isDirectory || !info.isDirectory()) {
    throw new Error(`Workspace is not a directory: ${resolved}`);
  }
  workspaceRoot = resolved;
  await persistWorkspaceRootState();
  return workspaceRoot;
}

function getWorkspaceState() {
  return {
    workspaceRoot,
    defaultWorkspaceRoot: path.resolve(defaultWorkspaceRoot),
    shellAllowlist,
    readScope: "local_files_anywhere_and_http_urls",
    listDirScope: "workspace_root_only",
    writeScope: "workspace_root_only",
    uvBin: configuredUvBin || "",
    pythonBin: configuredPythonBin || "",
    workspaceStateFile,
  };
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

function isHttpUrlPath(rawPath) {
  return /^https?:\/\//i.test(String(rawPath || "").trim());
}

function resolveReadTarget(rawPath) {
  const input = String(rawPath || "").trim();
  if (!input) {
    throw new Error("Path is empty.");
  }
  if (isHttpUrlPath(input)) {
    let normalized = input;
    try {
      normalized = new URL(input).toString();
    } catch {
      throw new Error(`Invalid URL: ${input}`);
    }
    return {
      kind: "url",
      pathInput: input,
      url: normalized,
    };
  }

  const resolvedPath = path.isAbsolute(input)
    ? path.resolve(input)
    : path.resolve(workspaceRoot, input);
  return {
    kind: "file",
    pathInput: input,
    resolvedPath,
  };
}

function toReadableDisplayPath(absPath) {
  if (isInsideWorkspace(absPath)) {
    return toWorkspaceRelative(absPath).replaceAll("\\", "/");
  }
  return path.resolve(absPath);
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

function createSessionState() {
  return {
    messages: [],
    toolLogs: [],
    plan: [],
    turnJournal: [],
    compactSummary: "",
    compactVersion: 0,
    nextToolCallSeq: 1,
  };
}

function ensureSessionShape(session) {
  const target = session && typeof session === "object" ? session : createSessionState();
  if (!Array.isArray(target.messages)) {
    target.messages = [];
  }
  if (!Array.isArray(target.toolLogs)) {
    target.toolLogs = [];
  }
  if (!Array.isArray(target.plan)) {
    target.plan = [];
  }
  if (!Array.isArray(target.turnJournal)) {
    target.turnJournal = [];
  }
  if (typeof target.compactSummary !== "string") {
    target.compactSummary = "";
  }
  if (!Number.isInteger(target.compactVersion) || target.compactVersion < 0) {
    target.compactVersion = 0;
  }
  if (!Number.isInteger(target.nextToolCallSeq) || target.nextToolCallSeq < 1) {
    target.nextToolCallSeq = 1;
  }
  return target;
}

function getOrCreateSession(req, res) {
  const cookies = parseCookies(req.headers.cookie || "");
  let sid = cookies.sid;
  if (!sid || !sessions.has(sid)) {
    sid = randomBytes(16).toString("hex");
    sessions.set(sid, createSessionState());
    res.setHeader("Set-Cookie", `sid=${encodeURIComponent(sid)}; HttpOnly; SameSite=Lax; Path=/`);
  }
  if (!sessions.has(sid)) {
    sessions.set(sid, createSessionState());
  }
  const session = ensureSessionShape(sessions.get(sid));
  sessions.set(sid, session);
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

function splitAssistantTextForStream(rawText, chunkChars = assistantStreamChunkChars) {
  const text = String(rawText || "");
  if (!text) return [];
  const safeChunkChars = Math.max(8, Number.parseInt(String(chunkChars || 0), 10) || 48);
  const chunks = [];
  let cursor = 0;

  while (cursor < text.length) {
    let end = Math.min(text.length, cursor + safeChunkChars);
    if (end < text.length) {
      const searchStart = Math.max(cursor, end - Math.floor(safeChunkChars * 0.6));
      const window = text.slice(searchStart, end + 1);
      const relNewline = Math.max(window.lastIndexOf("\n"), window.lastIndexOf("\r"));
      const relPunct = Math.max(
        window.lastIndexOf("。"),
        window.lastIndexOf("、"),
        window.lastIndexOf("."),
        window.lastIndexOf("!"),
        window.lastIndexOf("?"),
        window.lastIndexOf("！"),
        window.lastIndexOf("？"),
      );
      const relBreak = Math.max(relNewline, relPunct);
      if (relBreak >= 0) {
        const candidate = searchStart + relBreak + 1;
        if (candidate > cursor && candidate <= text.length) {
          end = candidate;
        }
      }
    }
    if (end <= cursor) {
      end = Math.min(text.length, cursor + safeChunkChars);
    }
    chunks.push(text.slice(cursor, end));
    cursor = end;
  }
  return chunks;
}

async function emitAssistantStreamEvents({ res, assistantText, model, elapsedMs }) {
  if (!assistantStreamEnabled) return false;
  const text = String(assistantText || "");
  const chunks = splitAssistantTextForStream(text, assistantStreamChunkChars);

  writeNdjson(res, {
    type: "assistant_stream_start",
    model: String(model || defaultModel),
    totalChars: text.length,
  });

  if (chunks.length === 0) {
    writeNdjson(res, {
      type: "assistant_stream_done",
      elapsedMs,
      totalChars: 0,
    });
    return true;
  }

  for (let index = 0; index < chunks.length; index += 1) {
    if (res.writableEnded || res.destroyed) {
      return true;
    }
    writeNdjson(res, {
      type: "assistant_stream_delta",
      index: index + 1,
      totalChunks: chunks.length,
      delta: chunks[index],
    });
    if (assistantStreamChunkDelayMs > 0 && index < chunks.length - 1) {
      await sleepMs(assistantStreamChunkDelayMs);
    }
  }

  writeNdjson(res, {
    type: "assistant_stream_done",
    elapsedMs,
    totalChars: text.length,
  });
  return true;
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

function parseYmdToUtcMs(rawYmd) {
  const text = String(rawYmd || "").trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return Number.NaN;
  const year = Number.parseInt(match[1], 10);
  const month = Number.parseInt(match[2], 10);
  const day = Number.parseInt(match[3], 10);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return Number.NaN;
  }
  return Date.UTC(year, month - 1, day, 0, 0, 0, 0);
}

function formatYmdAsJapanese(rawYmd) {
  const text = String(rawYmd || "").trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return text;
  const month = Number.parseInt(match[2], 10);
  const day = Number.parseInt(match[3], 10);
  return `${match[1]}年${month}月${day}日`;
}

function hasExplicitCalendarDateInText(rawText) {
  const text = String(rawText || "");
  return /(20\d{2})\s*(?:[\/\-.]|\u5e74)\s*\d{1,2}/i.test(text);
}

function collectExplicitDateMentions(rawText) {
  const text = String(rawText || "");
  const ymdPattern = /(20\d{2})\s*(?:[\/\-.]|\u5e74)\s*(\d{1,2})\s*(?:[\/\-.]|\u6708)\s*(\d{1,2})\s*(?:\u65e5)?/g;
  const ymPointPattern = /(20\d{2})\s*\u5e74\s*(\d{1,2})\s*\u6708(?:\s*(\d{1,2})\s*\u65e5)?\s*(?:\u6642\u70b9|\u73fe\u5728)/g;
  const out = [];
  const seen = new Set();

  let match = null;
  while ((match = ymdPattern.exec(text)) !== null) {
    const ymd = normalizeYmd(match[1], match[2], match[3]);
    if (!ymd || seen.has(ymd)) continue;
    seen.add(ymd);
    out.push({
      ymd,
      raw: String(match[0] || "").trim(),
      kind: "ymd",
    });
  }

  while ((match = ymPointPattern.exec(text)) !== null) {
    const ymd = normalizeYmd(match[1], match[2], match[3] || 1);
    if (!ymd || seen.has(ymd)) continue;
    seen.add(ymd);
    out.push({
      ymd,
      raw: String(match[0] || "").trim(),
      kind: "as_of",
    });
  }

  return out;
}

function isTemporalSensitivePrompt(rawPrompt) {
  const prompt = String(rawPrompt || "");
  if (!prompt.trim()) return false;
  if (/(latest|recent|current|today|tomorrow|yesterday|as of|now)/i.test(prompt)) return true;
  return /(?:\u6700\u65b0|\u76f4\u8fd1|\u73fe\u5728|\u4eca\u65e5|\u672c\u65e5|\u660e\u65e5|\u6628\u65e5|\u304d\u3087\u3046|\u3042\u3059|\u304d\u306e\u3046|\u3044\u307e|\u6642\u70b9)/.test(prompt);
}

function promptAsksToday(rawPrompt) {
  const prompt = String(rawPrompt || "");
  if (/\btoday\b/i.test(prompt)) return true;
  return /(?:\u4eca\u65e5|\u672c\u65e5|\u304d\u3087\u3046)/.test(prompt);
}

function promptAsksLatestCurrent(rawPrompt) {
  const prompt = String(rawPrompt || "");
  if (/(latest|recent|current|now)/i.test(prompt)) return true;
  return /(?:\u6700\u65b0|\u76f4\u8fd1|\u73fe\u5728|\u3044\u307e)/.test(prompt);
}

function evaluateTemporalAnswerIssues({ prompt, finalText, temporalContext }) {
  const issues = [];
  const promptText = String(prompt || "");
  const answer = String(finalText || "");
  const currentDateJst = String(temporalContext?.currentDateJst || "").trim();
  if (!answer.trim() || !currentDateJst) return issues;
  if (!isTemporalSensitivePrompt(promptText)) return issues;
  if (hasExplicitCalendarDateInText(promptText)) return issues;

  const currentMs = parseYmdToUtcMs(currentDateJst);
  if (!Number.isFinite(currentMs)) return issues;

  const dateMentions = collectExplicitDateMentions(answer);
  if (promptAsksToday(promptText)) {
    const mismatched = dateMentions.filter((item) => item.ymd !== currentDateJst);
    if (mismatched.length > 0) {
      issues.push("answer contains explicit date that does not match current_date_jst");
    }
  }

  if (promptAsksLatestCurrent(promptText)) {
    const staleThresholdDays = 31;
    const staleAsOf = dateMentions.some((item) => {
      if (item.kind !== "as_of") return false;
      const itemMs = parseYmdToUtcMs(item.ymd);
      if (!Number.isFinite(itemMs)) return false;
      const ageDays = Math.floor((currentMs - itemMs) / 86400000);
      return ageDays > staleThresholdDays;
    });
    if (staleAsOf) {
      issues.push("answer uses stale 'as of' date for a latest/current request");
    }
  }

  return issues;
}

function rewriteStaleAsOfDatesForLatestPrompt({ prompt, text, currentDateJst }) {
  const source = String(text || "");
  const promptText = String(prompt || "");
  const currentYmd = String(currentDateJst || "").trim();
  if (!source.trim() || !currentYmd) {
    return { text: source, rewriteCount: 0 };
  }
  if (!promptAsksLatestCurrent(promptText)) {
    return { text: source, rewriteCount: 0 };
  }
  if (hasExplicitCalendarDateInText(promptText)) {
    return { text: source, rewriteCount: 0 };
  }

  const currentMs = parseYmdToUtcMs(currentYmd);
  if (!Number.isFinite(currentMs)) {
    return { text: source, rewriteCount: 0 };
  }

  let rewriteCount = 0;
  const staleThresholdDays = 31;
  const replacementJa = `${formatYmdAsJapanese(currentYmd)}時点`;
  let rewritten = source.replace(
    /(20\d{2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?\s*(?:時点|現在)/g,
    (full, year, month, day) => {
      const ymd = normalizeYmd(year, month, day || 1);
      if (!ymd) return full;
      const oldMs = parseYmdToUtcMs(ymd);
      if (!Number.isFinite(oldMs)) return full;
      const ageDays = Math.floor((currentMs - oldMs) / 86400000);
      if (ageDays <= staleThresholdDays) return full;
      rewriteCount += 1;
      return replacementJa;
    },
  );

  rewritten = rewritten.replace(
    /as of\s*(20\d{2})[\/\-.](\d{1,2})(?:[\/\-.](\d{1,2}))?/gi,
    (full, year, month, day) => {
      const ymd = normalizeYmd(year, month, day || 1);
      if (!ymd) return full;
      const oldMs = parseYmdToUtcMs(ymd);
      if (!Number.isFinite(oldMs)) return full;
      const ageDays = Math.floor((currentMs - oldMs) / 86400000);
      if (ageDays <= staleThresholdDays) return full;
      rewriteCount += 1;
      return `as of ${currentYmd}`;
    },
  );

  return {
    text: rewritten,
    rewriteCount,
  };
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

function isLowValueSnapshotLine(line) {
  const text = String(line || "");
  if (!text) return true;
  if (/taboola|sponsored|advertising unit|^pr$|^-pr-$/i.test(text)) return true;
  if (/javascript:void\(0\)/i.test(text)) return true;
  if (/new tab|opens dialog|learn about this recommendation/i.test(text)) return true;
  return false;
}

function normalizeSnapshotLine(rawLine) {
  return String(rawLine || "")
    .replaceAll("\\n", " ")
    .replace(/\s+/g, " ")
    .trim();
}

function extractStructuredWebPageText(rawText, pageUrl) {
  const text = String(rawText || "");
  if (!text.trim()) return "";

  const pageTitleMatch = text.match(/- Page Title:\s*([^\r\n]+)/);
  const pageTitle = String(pageTitleMatch?.[1] || "").trim();
  const headings = [];
  const weatherLines = [];
  const bodyLines = [];
  const links = [];
  const seen = new Set();

  const weatherPattern = /天気|予報|気温|最高|最低|降水|風|湿度|晴|曇|雨|雪|thunder|weather|forecast|temperature|\b\d{1,2}\/\d{1,2}\b|\d{1,2}\s*℃/i;

  const lines = text.split(/\r?\n/);
  for (const rawLine of lines) {
    const line = normalizeSnapshotLine(rawLine);
    if (!line) continue;

    const headingMatch = line.match(/^- heading "([^"]+)"/);
    if (headingMatch) {
      const value = normalizeSnapshotLine(headingMatch[1]);
      if (value && !isLowValueSnapshotLine(value) && !seen.has(`h:${value}`)) {
        seen.add(`h:${value}`);
        headings.push(value);
      }
      continue;
    }

    const paragraphMatch = line.match(/^- paragraph(?: \[[^\]]+\])?:\s*(.+)$/);
    if (paragraphMatch) {
      const value = normalizeSnapshotLine(paragraphMatch[1]);
      if (value && !isLowValueSnapshotLine(value) && !seen.has(`p:${value}`)) {
        seen.add(`p:${value}`);
        bodyLines.push(value);
        if (weatherPattern.test(value)) {
          weatherLines.push(value);
        }
      }
      continue;
    }

    const textMatch = line.match(/^- text:\s*(.+)$/);
    if (textMatch) {
      const value = normalizeSnapshotLine(textMatch[1]);
      if (value && !isLowValueSnapshotLine(value) && !seen.has(`t:${value}`)) {
        seen.add(`t:${value}`);
        bodyLines.push(value);
        if (weatherPattern.test(value)) {
          weatherLines.push(value);
        }
      }
      continue;
    }

    const linkMatch = line.match(/^- link "([^"]+)"/);
    if (linkMatch) {
      const value = normalizeSnapshotLine(linkMatch[1]);
      if (value && !isLowValueSnapshotLine(value) && !seen.has(`l:${value}`)) {
        seen.add(`l:${value}`);
        links.push(value);
      }
      continue;
    }
  }

  const out = [];
  out.push(`Page URL: ${pageUrl}`);
  if (pageTitle) {
    out.push(`Page Title: ${pageTitle}`);
  }
  out.push("");

  const weatherUnique = [...new Set(weatherLines)]
    .filter((line) => !isLowValueSnapshotLine(line))
    .slice(0, 16);
  if (weatherUnique.length > 0) {
    out.push("Weather clues:");
    for (const row of weatherUnique) {
      out.push(`- ${row}`);
    }
    out.push("");
  }

  const headingUnique = [...new Set(headings)]
    .filter((line) => !isLowValueSnapshotLine(line))
    .slice(0, 12);
  if (headingUnique.length > 0) {
    out.push("Headings:");
    for (const row of headingUnique) {
      out.push(`- ${row}`);
    }
    out.push("");
  }

  const bodyUnique = [...new Set(bodyLines)]
    .filter((line) => !isLowValueSnapshotLine(line))
    .slice(0, 20);
  if (bodyUnique.length > 0) {
    out.push("Key text:");
    for (const row of bodyUnique) {
      out.push(`- ${row}`);
    }
    out.push("");
  }

  const linkUnique = [...new Set(links)]
    .filter((line) => !isLowValueSnapshotLine(line))
    .slice(0, 10);
  if (linkUnique.length > 0) {
    out.push("Top links:");
    for (const row of linkUnique) {
      out.push(`- ${row}`);
    }
  }

  return out.join("\n").trim();
}

function extractPromptKeywords(rawPrompt) {
  const text = String(rawPrompt || "").toLowerCase();
  const stopWords = new Set([
    "です",
    "ます",
    "ください",
    "して",
    "について",
    "お願い",
    "こと",
    "もの",
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
  ]);
  const tokens = new Set();
  const re = /[a-z0-9]{3,}|[\u4e00-\u9fff]{1,}|[\u3040-\u309f]{2,}|[\u30a0-\u30ff]{2,}/g;
  const matches = text.match(re) || [];
  for (const raw of matches) {
    const token = String(raw || "").trim();
    if (!token) continue;
    if (stopWords.has(token)) continue;
    if (/^\d+$/.test(token)) continue;
    tokens.add(token);
  }
  return [...tokens].slice(0, 24);
}

function countKeywordOverlap(keywords, rawText) {
  const haystack = String(rawText || "").toLowerCase();
  let hit = 0;
  for (const kw of keywords) {
    if (!kw) continue;
    if (haystack.includes(kw.toLowerCase())) {
      hit += 1;
    }
  }
  return hit;
}

function looksLikeLinkDump(rawText) {
  const text = String(rawText || "");
  const urlMatches = text.match(/https?:\/\/\S+/g) || [];
  const bulletCount = text.split(/\r?\n/).filter((line) => /^\s*[-*・]\s+/.test(line)).length;
  if (/主なリンク|提供された構造データ|抽出したリンク/i.test(text)) return true;
  if (urlMatches.length >= 3 && bulletCount >= 3) return true;
  return false;
}

function shouldRunFocusedFinalRewrite({ prompt, draftText, toolCallCount }) {
  if (!Number.isInteger(toolCallCount) || toolCallCount <= 0) return false;
  if (isTemporalSensitivePrompt(prompt)) return true;
  const draft = String(draftText || "").trim();
  if (!draft) return true;
  if (looksLikeLinkDump(draft) && !/リンク|url|一覧|list/i.test(String(prompt || ""))) {
    return true;
  }
  const keywords = extractPromptKeywords(prompt);
  if (keywords.length === 0) return false;
  const overlap = countKeywordOverlap(keywords, draft);
  const requiredOverlap = keywords.length >= 3 ? 2 : 1;
  return overlap < requiredOverlap;
}

function detectPromptIntent(rawPrompt) {
  const prompt = String(rawPrompt || "").trim();
  const lower = prompt.toLowerCase();
  const asksNews = /(news|ニュース|報道|トピック)/i.test(prompt);
  const asksLatest = /(latest|recent|最新|直近|今日|本日|いま|現在|now|today|current)/i.test(prompt);
  const asksList = /(まとめ|一覧|list|top|箇条書き|教えて|紹介|要約|summary)/i.test(prompt);
  const asksSingleFact = /(とは|what is|意味|定義|who is|なに|何)/i.test(prompt);
  const requiresBreadth = (asksNews && (asksLatest || asksList)) || (asksList && !asksSingleFact);
  const expectedMinItems = requiresBreadth ? (asksNews ? 3 : 2) : 1;
  return {
    prompt,
    lower,
    asksNews,
    asksLatest,
    asksList,
    asksSingleFact,
    requiresBreadth,
    expectedMinItems,
  };
}

function countLikelyAnswerItems(rawText) {
  const text = String(rawText || "");
  if (!text.trim()) return 0;
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  let count = 0;
  for (const line of lines) {
    if (/^[-*•]\s+/.test(line)) {
      count += 1;
      continue;
    }
    if (/^\d{1,2}[.)]\s+/.test(line)) {
      count += 1;
      continue;
    }
    if (/^\[\d{1,2}\]/.test(line)) {
      count += 1;
      continue;
    }
    if (/^20\d{2}\s*[\/\-.年]\s*\d{1,2}/.test(line)) {
      count += 1;
      continue;
    }
    if (/^\|/.test(line) && /\|/.test(line.slice(1))) {
      if (!/^\|?\s*-{2,}\s*\|/.test(line)) {
        count += 1;
      }
    }
  }

  if (count > 0) return count;
  const dateLikeHits = text.match(/20\d{2}\s*[\/\-.年]\s*\d{1,2}/g) || [];
  return dateLikeHits.length;
}

function createToolStats() {
  return {
    executedToolCalls: 0,
    failedToolCalls: 0,
    webSearchCalls: 0,
    readCalls: 0,
    readUrlCount: 0,
    searchResultItems: 0,
    evidenceUrlSet: new Set(),
    evidenceTextChunks: [],
    recentTools: [],
  };
}

function pushToolEvidenceText(toolStats, rawText, maxChars = 800) {
  if (!toolStats || typeof toolStats !== "object") return;
  if (!Array.isArray(toolStats.evidenceTextChunks)) {
    toolStats.evidenceTextChunks = [];
  }
  const normalized = normalizeSnapshotLine(rawText);
  if (!normalized || normalized.length < 4) return;
  const chunk = normalized.slice(0, Math.max(80, maxChars));
  if (toolStats.evidenceTextChunks.includes(chunk)) return;
  toolStats.evidenceTextChunks.push(chunk);
  if (toolStats.evidenceTextChunks.length > 48) {
    toolStats.evidenceTextChunks = toolStats.evidenceTextChunks.slice(-48);
  }
}

function buildToolEvidenceCorpus(toolStats) {
  if (!toolStats || !Array.isArray(toolStats.evidenceTextChunks)) {
    return "";
  }
  return toolStats.evidenceTextChunks.join("\n");
}

function extractUrlsFromText(rawText) {
  const text = String(rawText || "");
  const matches = text.match(/https?:\/\/[^\s)\]>"]+/gi) || [];
  const unique = [];
  const seen = new Set();
  for (const item of matches) {
    const value = String(item || "").trim();
    if (!value) continue;
    if (seen.has(value)) continue;
    seen.add(value);
    unique.push(value);
  }
  return unique;
}

function normalizeUrlForMatch(rawUrl) {
  const text = String(rawUrl || "").trim();
  if (!text) return "";
  try {
    const parsed = new URL(text);
    const pathname = parsed.pathname.replace(/\/+$/, "");
    return `${parsed.origin}${pathname}`.toLowerCase();
  } catch {
    return text.replace(/\/+$/, "").toLowerCase();
  }
}

function countCitedEvidenceUrls(answerText, evidenceUrlSet) {
  const evidenceRows = evidenceUrlSet instanceof Set ? [...evidenceUrlSet] : [];
  if (evidenceRows.length === 0) return 0;
  const normalizedEvidence = new Set(
    evidenceRows
      .map((item) => normalizeUrlForMatch(item))
      .filter(Boolean),
  );
  if (normalizedEvidence.size === 0) return 0;

  let count = 0;
  const answerUrls = extractUrlsFromText(answerText)
    .map((item) => normalizeUrlForMatch(item))
    .filter(Boolean);
  for (const answerUrl of answerUrls) {
    for (const evidenceUrl of normalizedEvidence) {
      if (answerUrl === evidenceUrl || answerUrl.startsWith(evidenceUrl) || evidenceUrl.startsWith(answerUrl)) {
        count += 1;
        break;
      }
    }
  }
  return count;
}

function summarizeToolStats(toolStats) {
  const stats = toolStats && typeof toolStats === "object" ? toolStats : createToolStats();
  return [
    `executed=${stats.executedToolCalls || 0}`,
    `failed=${stats.failedToolCalls || 0}`,
    `web_search=${stats.webSearchCalls || 0}`,
    `read=${stats.readCalls || 0}`,
    `evidence_urls=${stats.readUrlCount || 0}`,
    `search_items=${stats.searchResultItems || 0}`,
    stats.recentTools && stats.recentTools.length > 0
      ? `recent_tools=${stats.recentTools.join(" > ")}`
      : "",
  ].filter(Boolean).join(" ");
}

function recordToolEvidence(toolStats, modelResult) {
  if (!toolStats || typeof toolStats !== "object") return;
  const result = modelResult && typeof modelResult === "object" ? modelResult : {};
  const tool = String(result.tool || "").trim().toLowerCase();
  if (!tool) return;

  toolStats.executedToolCalls += 1;
  toolStats.recentTools.push(tool);
  if (toolStats.recentTools.length > 8) {
    toolStats.recentTools = toolStats.recentTools.slice(-8);
  }

  if (result.ok !== true) {
    toolStats.failedToolCalls += 1;
    return;
  }

  if (tool === "web_search") {
    toolStats.webSearchCalls += 1;
    if (typeof result.query === "string" && result.query.trim()) {
      pushToolEvidenceText(toolStats, `query=${result.query}`);
    }
    if (typeof result.currentDateJst === "string" && result.currentDateJst.trim()) {
      pushToolEvidenceText(toolStats, `current_date_jst=${result.currentDateJst}`);
    }
    if (Array.isArray(result.results)) {
      toolStats.searchResultItems += result.results.length;
      for (const item of result.results) {
        const url = String(item?.url || "").trim();
        if (url) {
          toolStats.evidenceUrlSet.add(url);
        }
        pushToolEvidenceText(toolStats, item?.title || "", 300);
        pushToolEvidenceText(toolStats, item?.snippet || "", 500);
        pushToolEvidenceText(toolStats, url, 400);
      }
    }
  }

  if (tool === "read" || tool === "read_file") {
    toolStats.readCalls += 1;
    const source = String(result.source || "").trim().toLowerCase();
    const pathValue = String(result.path || "").trim();
    if (source === "url" || /^https?:\/\//i.test(pathValue)) {
      if (pathValue) {
        toolStats.evidenceUrlSet.add(pathValue);
      }
      pushToolEvidenceText(toolStats, pathValue, 400);
      pushToolEvidenceText(toolStats, result.content || result.output || "", 1200);
    }
  }

  toolStats.readUrlCount = toolStats.evidenceUrlSet.size;
}

function buildTaskFocusSystemMessage({ prompt, promptIntent, toolStats, step }) {
  const intent = promptIntent && typeof promptIntent === "object" ? promptIntent : detectPromptIntent(prompt);
  const rows = [
    "Task focus guard (controller hint):",
    `original_user_question=${String(prompt || "").trim()}`,
    `step=${Number.isInteger(step) ? step : 0}`,
    `requires_breadth=${intent.requiresBreadth ? "yes" : "no"}`,
    intent.requiresBreadth ? `expected_min_items=${intent.expectedMinItems}` : "",
    `tool_progress=${summarizeToolStats(toolStats)}`,
    "Never lose the original user question.",
    "When question asks latest/news/summary, avoid finishing with a single narrow detail.",
    intent.asksNews && intent.asksLatest
      ? "For latest news: run web_search + read(url), then include source URLs in final answer."
      : "",
    "Before returning final, ensure the answer directly addresses the original question.",
  ];
  return rows.filter(Boolean).join("\n");
}

function evaluateFinalAnswerCoverage({
  prompt,
  finalText,
  promptIntent,
  toolStats,
  temporalContext,
}) {
  const reasons = [];
  const answer = String(finalText || "").trim();
  const intent = promptIntent && typeof promptIntent === "object" ? promptIntent : detectPromptIntent(prompt);
  const stats = toolStats && typeof toolStats === "object" ? toolStats : createToolStats();

  if (!answer) {
    reasons.push("final answer is empty");
  }

  const keywords = extractPromptKeywords(prompt);
  if (keywords.length > 0) {
    const overlap = countKeywordOverlap(keywords, answer);
    if (overlap <= 0) {
      reasons.push("answer-topic overlap with user prompt is too low");
    }
  }

  if (intent.requiresBreadth) {
    const itemCount = countLikelyAnswerItems(answer);
    if (itemCount < intent.expectedMinItems) {
      reasons.push(`answer item count is too small (${itemCount}/${intent.expectedMinItems})`);
    }
    if ((stats.webSearchCalls || 0) <= 0 && (stats.readUrlCount || 0) <= 0) {
      reasons.push("insufficient external evidence");
    }
    if ((stats.searchResultItems || 0) <= 0 && (stats.readUrlCount || 0) <= 0) {
      reasons.push("no search/read evidence captured");
    }
  }

  if (intent.asksNews && intent.asksLatest) {
    if ((stats.webSearchCalls || 0) <= 0) {
      reasons.push("latest news response requires web_search evidence");
    }
    if ((stats.readUrlCount || 0) <= 0) {
      reasons.push("latest news response requires reading at least one result URL");
    }

    const evidenceCorpus = buildToolEvidenceCorpus(stats);
    const answerKeywords = extractPromptKeywords(answer).slice(0, 40);
    const evidenceOverlap = countKeywordOverlap(answerKeywords, evidenceCorpus);
    if (answerKeywords.length >= 6 && evidenceOverlap < 2) {
      reasons.push("answer has low overlap with collected web evidence");
    }

    const citedEvidenceUrls = countCitedEvidenceUrls(answer, stats.evidenceUrlSet);
    if (citedEvidenceUrls <= 0) {
      reasons.push("latest news response should cite at least one gathered source URL");
    }
  }

  const temporalIssues = evaluateTemporalAnswerIssues({
    prompt,
    finalText: answer,
    temporalContext,
  });
  if (temporalIssues.length > 0) {
    reasons.push(...temporalIssues);
  }

  return {
    ok: reasons.length === 0,
    reasons,
  };
}

function compactToolResultForFinal(rawResult) {
  const result = rawResult && typeof rawResult === "object" ? rawResult : {};
  const compact = {
    ok: result.ok === true,
    tool: String(result.tool || "").trim(),
  };

  if (typeof result.query === "string" && result.query.trim()) {
    compact.query = result.query.trim();
  }
  if (typeof result.path === "string" && result.path.trim()) {
    compact.path = result.path.trim();
  }
  if (typeof result.source === "string" && result.source.trim()) {
    compact.source = result.source.trim();
  }
  if (typeof result.currentDateJst === "string" && result.currentDateJst.trim()) {
    compact.currentDateJst = result.currentDateJst.trim();
  }
  if (typeof result.content === "string" && result.content.trim()) {
    compact.content = truncateText(result.content.trim(), 2000);
  }
  if (typeof result.output === "string" && result.output.trim()) {
    compact.output = truncateText(result.output.trim(), 1200);
  }
  if (typeof result.error === "string" && result.error.trim()) {
    compact.error = truncateText(result.error.trim(), 800);
  }
  if (Array.isArray(result.results)) {
    compact.results = result.results.slice(0, 5).map((item) => ({
      title: truncateText(String(item?.title || "").trim(), 180),
      url: truncateText(String(item?.url || "").trim(), 280),
      snippet: truncateText(String(item?.snippet || "").trim(), 240),
    }));
  }

  return compact;
}

async function rewriteFinalAnswerWithToolEvidence({
  prompt,
  draftText,
  model,
  temperature,
  toolResults,
  temporalContext,
  promptIntent,
  toolStats,
}) {
  const compactResults = Array.isArray(toolResults) ? toolResults.slice(-5) : [];
  const intent = promptIntent && typeof promptIntent === "object" ? promptIntent : detectPromptIntent(prompt);
  const progressSummary = summarizeToolStats(toolStats);
  const messages = [
    { role: "system", content: autoToolFinalRewriteSystemPrompt },
    {
      role: "user",
      content: [
        `question: ${String(prompt || "").trim()}`,
        "",
        `draft_answer: ${truncateText(String(draftText || "").trim(), 2000)}`,
        "",
        `current_utc_iso: ${String(temporalContext?.utcIso || "")}`,
        `current_date_jst: ${String(temporalContext?.currentDateJst || "")}`,
        `requires_breadth: ${intent.requiresBreadth ? "yes" : "no"}`,
        intent.requiresBreadth ? `expected_min_items: ${intent.expectedMinItems}` : "",
        `tool_progress: ${progressSummary}`,
        "",
        "tool_evidence_json:",
        truncateText(JSON.stringify(compactResults, null, 2), 7000),
      ].join("\n"),
    },
  ];

  const rewritten = await callRunPodChatText({
    model,
    temperature: Number.isFinite(temperature) ? Math.min(0.4, Math.max(0, temperature)) : 0.2,
    messages,
    maxTokens: 900,
  });
  return String(rewritten || "").trim();
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

function renderContextCompactedCard(info) {
  const compactVersion = Number.isInteger(info?.compactVersion) ? info.compactVersion : 0;
  const droppedMessages = Number.isInteger(info?.droppedMessages) ? info.droppedMessages : 0;
  const keptMessages = Number.isInteger(info?.keptMessages) ? info.keptMessages : 0;
  const checkpointChars = Number.isInteger(info?.checkpointChars) ? info.checkpointChars : 0;
  const tokenBudget = Number.isFinite(Number(info?.tokenBudget)) ? Number(info.tokenBudget) : 0;
  const totalTokensBefore = Number.isFinite(Number(info?.totalTokensBefore)) ? Number(info.totalTokensBefore) : 0;
  const totalTokensAfter = Number.isFinite(Number(info?.totalTokensAfter)) ? Number(info.totalTokensAfter) : 0;
  const body = [
    "Older conversation turns were summarized to keep context stable.",
    `dropped_messages=${droppedMessages}`,
    `kept_messages=${keptMessages}`,
    tokenBudget > 0 ? `token_estimate=${totalTokensBefore} -> ${totalTokensAfter} / budget ${tokenBudget}` : "",
    checkpointChars > 0 ? `checkpoint_chars=${checkpointChars}` : "",
  ].filter(Boolean).join("\n");
  return renderToolResult({
    title: "Context compacted",
    meta: `version=${compactVersion}`,
    body,
  });
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

function runProcessCapture(command, args, { cwd = workspaceRoot, timeoutMs = localShellTimeoutMs, env = process.env, windowsHide = true } = {}) {
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
      windowsHide: !!windowsHide,
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

async function openNativeFolderPicker(initialPath = workspaceRoot) {
  if (process.platform !== "win32") {
    throw new Error("Native folder picker is currently supported on Windows only.");
  }

  const normalizedInitial = String(initialPath || "").replaceAll("'", "''");
  const script = [
    "$ErrorActionPreference='Stop'",
    "Add-Type -AssemblyName System.Windows.Forms",
    "Add-Type -AssemblyName System.Drawing",
    "$signature = 'using System; using System.Runtime.InteropServices; public static class Win32PickerHost { public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1); public const UInt32 SWP_NOSIZE = 0x0001; public const UInt32 SWP_NOMOVE = 0x0002; public const UInt32 SWP_SHOWWINDOW = 0x0040; [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd); [DllImport(\"user32.dll\")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, UInt32 uFlags); }'",
    "Add-Type -TypeDefinition $signature",
    "$dialog = New-Object System.Windows.Forms.OpenFileDialog",
    "$dialog.Title = 'Select workspace folder'",
    "$dialog.Filter = 'Folders|*.none'",
    "$dialog.CheckFileExists = $false",
    "$dialog.CheckPathExists = $true",
    "$dialog.ValidateNames = $false",
    "$dialog.RestoreDirectory = $true",
    "$dialog.ShowHelp = $false",
    "$dialog.FileName = 'Select this folder'",
    `$initial = '${normalizedInitial}'`,
    "if ($initial -and (Test-Path $initial)) {",
    "  $item = Get-Item $initial",
    "  if ($item.PSIsContainer) { $dialog.InitialDirectory = $item.FullName } else { $dialog.InitialDirectory = $item.DirectoryName }",
    "}",
    "$owner = New-Object System.Windows.Forms.Form",
    "$owner.Text = 'LocaLingo Picker Host'",
    "$owner.TopMost = $true",
    "$owner.ShowInTaskbar = $false",
    "$owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedToolWindow",
    "$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen",
    "$owner.Size = New-Object System.Drawing.Size(320, 120)",
    "$owner.Opacity = 0.01",
    "$selected = ''",
    "try {",
    "  $owner.Show()",
    "  [void][Win32PickerHost]::SetWindowPos($owner.Handle, [Win32PickerHost]::HWND_TOPMOST, 0, 0, 0, 0, [Win32PickerHost]::SWP_NOMOVE -bor [Win32PickerHost]::SWP_NOSIZE -bor [Win32PickerHost]::SWP_SHOWWINDOW)",
    "  [void][Win32PickerHost]::SetForegroundWindow($owner.Handle)",
    "  $owner.Activate()",
    "  [System.Windows.Forms.Application]::DoEvents()",
    "  $result = $dialog.ShowDialog($owner)",
    "  if ($result -eq [System.Windows.Forms.DialogResult]::OK) {",
    "    $candidate = [string]$dialog.FileName",
    "    if (-not [string]::IsNullOrWhiteSpace($candidate)) {",
    "      if (Test-Path $candidate) {",
    "        $pick = Get-Item $candidate",
    "        if ($pick.PSIsContainer) { $selected = $pick.FullName }",
    "        else { $selected = $pick.DirectoryName }",
    "      } else {",
    "        $parent = Split-Path -Parent $candidate",
    "        if ($parent -and (Test-Path $parent)) { $selected = (Resolve-Path $parent).Path }",
    "      }",
    "    }",
    "  }",
    "} finally {",
    "  if ($owner) {",
    "    $owner.Close()",
    "    $owner.Dispose()",
    "  }",
    "}",
    "if (-not [string]::IsNullOrWhiteSpace($selected)) { [Console]::Out.Write($selected) }",
  ].join("; ");

  const run = await runProcessCapture("powershell", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-STA",
    "-Command",
    script,
  ], {
    timeoutMs: Math.max(30000, Math.min(180000, localShellTimeoutMs * 6)),
    windowsHide: false,
  });

  if (run.spawnError) {
    throw new Error(run.spawnError);
  }
  if (run.timedOut) {
    throw new Error("Folder picker timed out.");
  }
  if (run.exitCode !== 0) {
    throw new Error(`Folder picker failed (exit=${run.exitCode}). ${truncateText(run.stderr || run.stdout, 500)}`);
  }
  const selected = String(run.stdout || "").trim();
  if (!selected) {
    return "";
  }
  return path.resolve(selected);
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

async function readRemoteUrlForTool(rawPath) {
  const target = resolveReadTarget(rawPath);
  if (target.kind !== "url") {
    throw new Error("URL path is required.");
  }
  if (!playwrightMcpEnabled) {
    throw new Error("URL read requires Playwright MCP. Set PLAYWRIGHT_MCP_ENABLED=1.");
  }

  const navigation = await runPlaywrightNavigateWithInstall(target.url);
  const snapshotTextRaw = String(navigation.text || "").trim();
  const pageUrl = extractPageUrlFromMcpText(snapshotTextRaw) || target.url;
  const structuredContent = extractStructuredWebPageText(snapshotTextRaw, pageUrl);
  const contentRaw = structuredContent || snapshotTextRaw || "(No snapshot text returned by Playwright MCP.)";
  const content = truncateText(contentRaw, Math.max(maxToolOutputChars * 2, 20000));
  const truncated = content !== contentRaw;
  const sizeBytes = Buffer.byteLength(contentRaw, "utf8");
  const meta = [
    "source=url",
    `bytes=${sizeBytes}`,
    `structured=${structuredContent ? "yes" : "no"}`,
    `truncated=${truncated ? "yes" : "no"}`,
    `elapsed=${Math.max(0, Number.parseInt(String(navigation.elapsedMs || 0), 10) || 0)}ms`,
    `page=${pageUrl}`,
  ].join(" ");

  return {
    resolvedPath: target.url,
    displayPath: pageUrl,
    sizeBytes,
    meta,
    content,
    shown: truncateText(content, maxToolOutputChars),
    modelPayload: {
      format: "url",
      pageUrl,
      structured: Boolean(structuredContent),
      truncated,
      elapsedMs: navigation.elapsedMs,
      command: navigation.command,
    },
  };
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
  const target = resolveReadTarget(rawPath);
  if (target.kind === "url") {
    return readRemoteUrlForTool(target.url);
  }

  const resolvedPath = target.resolvedPath;
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

  const displayPath = toReadableDisplayPath(resolvedPath);
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
  const target = resolveReadTarget(rawPath);
  if (target.kind === "url") {
    const remote = await readRemoteUrlForTool(target.url);
    const split = splitTextLines(remote.content);
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
      relPath: remote.displayPath,
      sizeBytes: remote.sizeBytes,
      totalLines,
      offset,
      limit,
      returnedLines: selected.length,
      content: numbered.join("\n"),
    };
  }

  const resolvedPath = target.resolvedPath;
  const info = await stat(resolvedPath);
  if (!info.isFile()) {
    throw new Error(`Not a file: ${target.pathInput}`);
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
    relPath: toReadableDisplayPath(resolvedPath),
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

  const extractFirstBalancedArray = (source) => {
    const s = String(source || "");
    const start = s.indexOf("[");
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
      if (ch === "[") {
        depth += 1;
        continue;
      }
      if (ch === "]") {
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
  const firstBalancedArray = extractFirstBalancedArray(text);
  if (firstBalancedArray) {
    candidates.push(firstBalancedArray);
  }

  const firstBrace = text.indexOf("{");
  const lastBrace = text.lastIndexOf("}");
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    candidates.push(text.slice(firstBrace, lastBrace + 1).trim());
  }
  const firstBracket = text.indexOf("[");
  const lastBracket = text.lastIndexOf("]");
  if (firstBracket >= 0 && lastBracket > firstBracket) {
    candidates.push(text.slice(firstBracket, lastBracket + 1).trim());
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

function tryParseJsonAnyCandidate(candidate) {
  const sample = String(candidate || "").trim();
  if (!sample) return null;
  try {
    return JSON.parse(sample);
  } catch {
    return null;
  }
}

function extractFirstObjectFromParsedJsonValue(value) {
  if (!value) return null;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const extracted = extractFirstObjectFromParsedJsonValue(item);
      if (extracted) return extracted;
    }
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
    const parsedAny = tryParseJsonAnyCandidate(candidate);
    const extracted = extractFirstObjectFromParsedJsonValue(parsedAny);
    if (extracted) {
      return extracted;
    }
    const parsed = tryParseJsonObjectCandidate(candidate);
    if (parsed) {
      return parsed;
    }
  }

  const repairedCandidates = [
    ...new Set(candidates.map((candidate) => normalizeJsonLikeObjectText(candidate)).filter(Boolean)),
  ];
  for (const candidate of repairedCandidates) {
    const parsedAny = tryParseJsonAnyCandidate(candidate);
    const extracted = extractFirstObjectFromParsedJsonValue(parsedAny);
    if (extracted) {
      return extracted;
    }
    const parsed = tryParseJsonObjectCandidate(candidate);
    if (parsed) {
      return parsed;
    }
  }

  throw new Error(`Model JSON parse failed. raw=${truncateText(text, 1200)}`);
}

function decodeEscapedText(rawValue) {
  let text = String(rawValue || "");
  text = text.replace(/\\u([0-9a-fA-F]{4})/g, (_m, hex) => {
    try {
      return String.fromCharCode(Number.parseInt(hex, 16));
    } catch {
      return _m;
    }
  });
  text = text
    .replace(/\\r/g, "\r")
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, "\"")
    .replace(/\\\\/g, "\\");
  return text;
}

function cleanupRecoveredMessage(rawValue) {
  let text = decodeEscapedText(rawValue);
  text = text
    .replace(/\s*"\s*}\s*$/s, "")
    .replace(/\s*}\s*$/s, "")
    .trim();
  return text;
}

function extractPossiblyMalformedFinalMessage(rawText) {
  const text = String(rawText || "");
  if (!text) return "";

  const keyMatch = text.match(/["']message["']\s*:\s*/i);
  if (!keyMatch || keyMatch.index === undefined) {
    return "";
  }
  const startIdx = keyMatch.index + keyMatch[0].length;
  let tail = text.slice(startIdx).trimStart();
  if (!tail) return "";

  const first = tail[0];
  if (first !== "\"" && first !== "'") {
    const direct = tail.match(/^([^\r\n}]+)/);
    return cleanupRecoveredMessage(direct ? direct[1] : tail);
  }

  const quote = first;
  tail = tail.slice(1);
  let out = "";
  let escaped = false;
  for (let i = 0; i < tail.length; i += 1) {
    const ch = tail[i];
    if (escaped) {
      out += ch;
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      out += ch;
      escaped = true;
      continue;
    }
    if (ch === quote) {
      const rest = tail.slice(i + 1);
      if (/^\s*(,|\}|$)/.test(rest)) {
        return cleanupRecoveredMessage(out);
      }
    }
    out += ch;
  }
  // Truncated string: return the best-effort partial message.
  return cleanupRecoveredMessage(out);
}

function recoverAgentDecisionFromMalformedText(rawText) {
  const text = String(rawText || "").trim();
  if (!text) return null;

  const hasJsonShape = text.startsWith("{") || text.includes("\"type\"") || text.includes("'type'");
  const hasToolHint = /["']tool["']\s*:|["']name["']\s*:|["']type["']\s*:\s*["'](?:tool|function_call)["']/i.test(text);
  const hasFinalHint = /["']type["']\s*:\s*["']final["']/i.test(text);

  if (hasFinalHint) {
    const message = extractPossiblyMalformedFinalMessage(text);
    if (message) {
      return {
        type: "final",
        message,
      };
    }
  }

  if (!hasJsonShape) {
    return {
      type: "final",
      message: text,
    };
  }

  if (!hasToolHint) {
    const message = extractPossiblyMalformedFinalMessage(text);
    if (message) {
      return {
        type: "final",
        message,
      };
    }
  }

  const toolMatch = text.match(/["'](?:tool_name|tool|name)["']\s*:\s*["']([a-zA-Z0-9_:-]+)["']/i);
  const rawTool = normalizeToolAlias(String(toolMatch?.[1] || "").trim().toLowerCase());
  if (autoToolNames.includes(rawTool)) {
    const callIdMatch = text.match(/["']call_id["']\s*:\s*["']([^"']+)["']/i);
    const callId = String(callIdMatch?.[1] || "").trim();
    let args = {};
    const argsMatch = text.match(/["']arguments["']\s*:\s*("(?:\\.|[^"])*"|\{[\s\S]*?\})/i);
    if (argsMatch && argsMatch[1]) {
      const argsTextRaw = String(argsMatch[1] || "").trim();
      if (argsTextRaw.startsWith("\"")) {
        const unquoted = decodeEscapedText(argsTextRaw.slice(1, -1));
        args = parseArgumentsObjectMaybeString(unquoted);
      } else {
        args = parseArgumentsObjectMaybeString(argsTextRaw);
      }
    }
    return {
      type: "tool",
      tool: rawTool,
      args,
      reason: "recovered_from_malformed_json",
      callId,
    };
  }

  return null;
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

function firstNonEmptyString(values) {
  const rows = Array.isArray(values) ? values : [];
  for (const row of rows) {
    if (typeof row !== "string") continue;
    const text = row.trim();
    if (text) return text;
  }
  return "";
}

function extractTextFromContentBlocks(rawContent) {
  if (typeof rawContent === "string") {
    return rawContent.trim();
  }
  if (Array.isArray(rawContent)) {
    const parts = [];
    for (const item of rawContent) {
      if (typeof item === "string") {
        const text = item.trim();
        if (text) parts.push(text);
        continue;
      }
      if (!item || typeof item !== "object") continue;
      const text = firstNonEmptyString([
        typeof item.text === "string" ? item.text : "",
        typeof item.output_text === "string" ? item.output_text : "",
        typeof item.input_text === "string" ? item.input_text : "",
        typeof item.content === "string" ? item.content : "",
      ]);
      if (text) parts.push(text);
    }
    return parts.join("").trim();
  }
  if (rawContent && typeof rawContent === "object") {
    return firstNonEmptyString([
      typeof rawContent.text === "string" ? rawContent.text : "",
      typeof rawContent.output_text === "string" ? rawContent.output_text : "",
      typeof rawContent.content === "string" ? rawContent.content : "",
    ]);
  }
  return "";
}

function parseArgumentsObjectMaybeString(rawValue) {
  if (rawValue && typeof rawValue === "object" && !Array.isArray(rawValue)) {
    return { ...rawValue };
  }
  const text = String(rawValue || "").trim();
  if (!text) return {};
  const parsedDirect = tryParseJsonObjectCandidate(text);
  if (parsedDirect) {
    return parsedDirect;
  }
  const normalized = normalizeJsonLikeObjectText(text);
  const parsedNormalized = tryParseJsonObjectCandidate(normalized);
  if (parsedNormalized) {
    return parsedNormalized;
  }
  return {};
}

function extractToolCallFromToolCallsArray(rawToolCalls) {
  const toolCalls = Array.isArray(rawToolCalls) ? rawToolCalls : [];
  for (const item of toolCalls) {
    if (!item || typeof item !== "object") continue;
    const functionObject = item.function && typeof item.function === "object" ? item.function : null;
    const rawName = firstNonEmptyString([
      typeof item.name === "string" ? item.name : "",
      typeof item.tool_name === "string" ? item.tool_name : "",
      functionObject && typeof functionObject.name === "string" ? functionObject.name : "",
    ]);
    if (!rawName) continue;
    return {
      type: "function_call",
      call_id: firstNonEmptyString([
        typeof item.call_id === "string" ? item.call_id : "",
        typeof item.id === "string" ? item.id : "",
      ]),
      name: rawName,
      arguments: functionObject
        ? (functionObject.arguments !== undefined ? functionObject.arguments : functionObject.args)
        : (item.arguments !== undefined ? item.arguments : item.args),
    };
  }
  return null;
}

function extractFirstDecisionItemFromArray(rawItems) {
  const items = Array.isArray(rawItems) ? rawItems : [];
  let fallbackObject = null;
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    if (!fallbackObject) fallbackObject = item;
    if (Array.isArray(item.tool_calls)) return item;
    if (item.item && typeof item.item === "object") {
      const itemType = String(item.type || "").trim().toLowerCase();
      if (itemType === "response.output_item.done" || itemType === "response.output_item.added") {
        return item.item;
      }
    }
    const itemType = String(item.type || "").trim().toLowerCase();
    if ([
      "function_call",
      "tool_call",
      "custom_tool_call",
      "local_shell_call",
      "message",
      "final",
      "answer",
    ].includes(itemType)) {
      return item;
    }
    if (typeof item.message === "string" || typeof item.answer === "string") {
      return item;
    }
  }
  return fallbackObject;
}

function extractDecisionSourceObject(rawObject) {
  const obj = rawObject && typeof rawObject === "object" ? rawObject : {};

  // OpenAI Chat Completions-like wrapper
  const choices = Array.isArray(obj.choices) ? obj.choices : [];
  if (choices.length > 0) {
    const firstChoice = choices.find((item) => item && typeof item === "object") || null;
    const message = firstChoice && firstChoice.message && typeof firstChoice.message === "object"
      ? firstChoice.message
      : null;
    if (message) {
      const toolCall = extractToolCallFromToolCallsArray(message.tool_calls);
      if (toolCall) return toolCall;
      if (message.function_call && typeof message.function_call === "object") {
        return {
          type: "function_call",
          call_id: firstNonEmptyString([
            typeof message.call_id === "string" ? message.call_id : "",
            typeof message.id === "string" ? message.id : "",
          ]),
          name: firstNonEmptyString([
            typeof message.function_call.name === "string" ? message.function_call.name : "",
            typeof message.name === "string" ? message.name : "",
          ]),
          arguments: message.function_call.arguments,
          reason: typeof message.reason === "string" ? message.reason : "",
        };
      }
      const contentText = extractTextFromContentBlocks(message.content);
      if (contentText) {
        return {
          type: "final",
          message: contentText,
        };
      }
    }
  }

  // Codex/OpenAI Responses SSE-like wrapper
  const envelopeType = String(obj.type || "").trim().toLowerCase();
  if ((envelopeType === "response.output_item.done" || envelopeType === "response.output_item.added")
    && obj.item && typeof obj.item === "object") {
    return obj.item;
  }

  if (obj.item && typeof obj.item === "object" && typeof obj.item.type === "string") {
    return obj.item;
  }

  if (obj.response && typeof obj.response === "object") {
    const responseObj = obj.response;
    const responseOutput = extractFirstDecisionItemFromArray(responseObj.output);
    if (responseOutput) return responseOutput;
    const responseItems = extractFirstDecisionItemFromArray(responseObj.items);
    if (responseItems) return responseItems;
    if (responseObj.item && typeof responseObj.item === "object") {
      return responseObj.item;
    }
    const toolCall = extractToolCallFromToolCallsArray(responseObj.tool_calls);
    if (toolCall) return toolCall;
  }

  const outputItem = extractFirstDecisionItemFromArray(obj.output);
  if (outputItem) return outputItem;
  const itemsItem = extractFirstDecisionItemFromArray(obj.items);
  if (itemsItem) return itemsItem;

  const toolCall = extractToolCallFromToolCallsArray(obj.tool_calls);
  if (toolCall) return toolCall;

  return obj;
}

function normalizeAgentDecision(rawObject) {
  const obj = rawObject && typeof rawObject === "object" ? rawObject : {};
  const source = extractDecisionSourceObject(obj);
  const rawType = String(source.type || source.kind || source.mode || source.action || "").trim().toLowerCase();
  const rawTypeAsTool = normalizeToolAlias(rawType);
  const directTool = autoToolNames.includes(rawTypeAsTool) ? rawTypeAsTool : "";

  const message = firstNonEmptyString([
    typeof source.message === "string" ? source.message : "",
    typeof source.final_message === "string" ? source.final_message : "",
    typeof source.finalMessage === "string" ? source.finalMessage : "",
    typeof source.answer === "string" ? source.answer : "",
    typeof source.response === "string" ? source.response : "",
    typeof source.text === "string" ? source.text : "",
    extractTextFromContentBlocks(source.content),
  ]);
  const isFinalLikeType = [
    "final",
    "answer",
    "done",
    "complete",
    "message",
  ].includes(rawType);
  if (isFinalLikeType && message) {
    return {
      type: "final",
      message,
    };
  }

  const rawTool = normalizeToolAlias(String(
    source.tool_name
    || source.tool
    || source.toolName
    || source.name
    || source.function
    || (source.function_call && typeof source.function_call === "object" ? source.function_call.name : "")
    || directTool,
  ).trim().toLowerCase());
  const tool = autoToolNames.includes(rawTool) ? rawTool : "";
  const isToolLikeType = [
    "tool_call",
    "tool",
    "call",
    "function_call",
    "custom_tool_call",
    "local_shell_call",
  ].includes(rawType);
  if (isToolLikeType || directTool || tool) {
    const callId = String(source.call_id || source.callId || source.id || "")
      .trim()
      .replace(/[^A-Za-z0-9:_-]/g, "")
      .slice(0, 80);

    const directArgsRaw =
      source.args
      || source.arguments
      || source.input
      || source.params
      || source.parameters
      || (source.function_call && typeof source.function_call === "object"
        ? source.function_call.arguments
        : null);
    let args = parseArgumentsObjectMaybeString(directArgsRaw);

    if (Object.keys(args).length === 0 && rawType === "custom_tool_call") {
      args = parseArgumentsObjectMaybeString(source.input);
    }
    if (Object.keys(args).length === 0 && rawType === "local_shell_call") {
      const action = source.action && typeof source.action === "object" ? source.action : null;
      if (action) {
        if (Array.isArray(action.command)) {
          args = {
            command: action.command.map((item) => String(item || "")).join(" ").trim(),
          };
        } else if (typeof action.command === "string" && action.command.trim()) {
          args = {
            command: action.command.trim(),
          };
        }
      }
    }

    if (Object.keys(args).length === 0) {
      const passthrough = { ...source };
      const reservedKeys = new Set([
        "type",
        "kind",
        "mode",
        "action",
        "tool",
        "tool_name",
        "toolName",
        "name",
        "function",
        "function_call",
        "message",
        "final_message",
        "finalMessage",
        "answer",
        "response",
        "reason",
        "call_id",
        "callId",
        "id",
        "arguments",
        "args",
        "params",
        "input",
        "content",
        "status",
      ]);
      for (const key of Object.keys(passthrough)) {
        if (!reservedKeys.has(key)) {
          args[key] = passthrough[key];
        }
      }
    }
    if (!tool) {
      return {
        type: "invalid",
        message: "",
      };
    }
    return {
      type: "tool",
      tool,
      args,
      reason: String(source.reason || "").trim(),
      callId,
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
    const rawPath = String(payload.path || payload.file || payload.target || "").trim();
    return rawPath ? `path=${rawPath}` : "(path missing)";
  }
  if (tool === "read_file") {
    const rawPath = String(payload.path || payload.file || payload.target || "").trim();
    const offset = clampInteger(payload.offset || payload.line || payload.start_line, 1, 1, 1_000_000);
    const limit = clampInteger(payload.limit || payload.max_lines || payload.lines, 120, 1, 400);
    if (!rawPath) return "(path missing)";
    return `path=${rawPath} offset=${offset} limit=${limit}`;
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

function renderListDirBody(listing) {
  const safeListing = listing && typeof listing === "object" ? listing : {};
  const entries = Array.isArray(safeListing.entries) ? safeListing.entries : [];
  const lines = [
    `root=${String(safeListing.root || ".")}`,
    `entries=${entries.length}`,
    `truncated=${safeListing.truncated ? "yes" : "no"}`,
    "",
  ];
  if (entries.length === 0) {
    lines.push("(no entries)");
    lines.push("Workspace is empty. Set workspace folder or create files in workspace.");
    return lines.join("\n");
  }
  for (const item of entries) {
    if (item.type === "file") {
      lines.push(`- [file] ${item.path} (${item.size} bytes)`);
    } else if (item.type === "dir") {
      lines.push(`- [dir] ${item.path}`);
    } else {
      lines.push(`- [other] ${item.path}`);
    }
  }
  return lines.join("\n");
}

function stableSerializeForToolSignature(value) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" || typeof value === "boolean") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerializeForToolSignature(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort((a, b) => a.localeCompare(b, "en"));
    return `{${keys.map((key) => `${JSON.stringify(key)}:${stableSerializeForToolSignature(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(String(value));
}

function normalizeToolArgsForSignature(toolName, args) {
  const tool = String(toolName || "").trim().toLowerCase();
  const payload = args && typeof args === "object" && !Array.isArray(args) ? args : {};
  if (tool === "list_dir") {
    return {
      path: sanitizeModelPath(payload.path || payload.dir || payload.target || ".") || ".",
      recursive: parseBooleanEnv(payload.recursive, false),
      maxDepth: clampInteger(payload.max_depth || payload.maxDepth, 2, 0, 6),
      limit: clampInteger(payload.limit || payload.max_entries || payload.maxEntries, 200, 1, 500),
    };
  }
  if (tool === "read") {
    return {
      path: String(payload.path || payload.file || payload.target || "").trim(),
    };
  }
  if (tool === "read_file") {
    return {
      path: String(payload.path || payload.file || payload.target || "").trim(),
      offset: clampInteger(payload.offset || payload.line || payload.start_line, 1, 1, 1_000_000),
      limit: clampInteger(payload.limit || payload.max_lines || payload.lines, 120, 1, 400),
    };
  }
  if (tool === "search") {
    return {
      pattern: String(payload.pattern || payload.query || "").trim(),
      glob: String(payload.glob || "").trim(),
    };
  }
  if (tool === "web_search") {
    return {
      query: normalizeSearchQuery(payload.query || payload.q || payload.keyword || ""),
      maxResults: clampInteger(payload.max_results || payload.maxResults || payload.limit, 5, 1, 10),
    };
  }
  return payload;
}

function buildToolCallSignature(toolName, args) {
  const tool = String(toolName || "").trim().toLowerCase();
  if (!tool) return "";
  const normalizedArgs = normalizeToolArgsForSignature(tool, args);
  return `${tool}:${stableSerializeForToolSignature(normalizedArgs)}`;
}

function normalizeSearchQuery(rawValue) {
  return String(rawValue || "").replace(/\s+/g, " ").trim();
}

function normalizeLatestNewsSearchQuery(query, {
  prompt = "",
  promptIntent = null,
} = {}) {
  const rawQuery = normalizeSearchQuery(query);
  if (!rawQuery) return "";
  const intent = promptIntent && typeof promptIntent === "object"
    ? promptIntent
    : detectPromptIntent(prompt);
  if (!(intent?.asksNews && intent?.asksLatest)) {
    return rawQuery;
  }
  if (hasExplicitCalendarDateInText(prompt)) {
    return rawQuery;
  }

  let next = rawQuery
    .replace(/\b20\d{2}\s*(?:年|\/|-|\.|)?\s*(?:\d{1,2}\s*月)?\s*(?:末|初頭|年初|時点|頃|ごろ)?/g, " ")
    .replace(/\b(?:as of|from|since)\s*20\d{2}(?:[\/\-.]\d{1,2})?/gi, " ");
  next = normalizeSearchQuery(next);
  if (!next) {
    next = "最新 AI ニュース";
  }
  if (!/(最新|直近|today|current|latest|recent)/i.test(next)) {
    next = normalizeSearchQuery(`${next} 最新`);
  }
  return next;
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

async function executeAutoToolCall({
  session,
  toolName,
  args,
  fallbackWebSearchQuery = "",
  prompt = "",
  promptIntent = null,
}) {
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
      const body = renderListDirBody(listing);
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
      query = normalizeLatestNewsSearchQuery(query, {
        prompt,
        promptIntent,
      });
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
  const safeSession = ensureSessionShape(session);
  const temporalContext = getTemporalContext();
  const promptIntent = detectPromptIntent(prompt);
  const toolStats = createToolStats();
  const emit = typeof onEvent === "function"
    ? (payload) => {
        try {
          onEvent(payload);
        } catch {
          // ignore streaming callback errors
        }
      }
    : null;
  const preSamplingCompaction = compactSessionHistoryIfNeeded(safeSession, {
    pendingMessages: [{ role: "user", content: String(prompt || "").trim() }],
    maxOutputTokens: Math.max(256, autoToolMaxTokens),
    reason: "pre_sampling",
  });
  if (preSamplingCompaction?.compacted) {
    appendToolLog(safeSession, {
      title: "session pre-sampling compacted",
      summary: `version=${preSamplingCompaction.compactVersion}`,
      detail: [
        `prompt=${truncateText(prompt, 300)}`,
        `tokens=${preSamplingCompaction.totalTokensBefore} -> ${preSamplingCompaction.totalTokensAfter}`,
        `budget=${preSamplingCompaction.tokenBudget}`,
      ].join("\n"),
    });
  }
  let chatMessages = [
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
        `available_tools=${autoToolNames.join(",")}`,
        "read_scope=local_files_anywhere_and_http_urls",
        "read_file_scope=local_files_anywhere_and_http_urls",
        "list_dir_scope=workspace_root_only",
        "allow_write=yes",
        "allow_apply_patch=yes",
        "write_scope=workspace_root_only",
        `web_search_enabled=${playwrightMcpEnabled ? "yes" : "no"}`,
        `web_search_max_results=${Math.max(1, Math.min(10, playwrightMcpMaxResults))}`,
        `playwright_browser=${playwrightMcpBrowser}`,
        "harness_mode=codex_style_tool_call",
      ].join("\n"),
    },
    {
      role: "system",
      content: buildTaskFocusSystemMessage({
        prompt,
        promptIntent,
        toolStats,
        step: 0,
      }),
    },
  ];

  const compactedSessionContext = buildSessionCompactedContextMessage(safeSession);
  if (compactedSessionContext) {
    chatMessages.push({
      role: "system",
      content: compactedSessionContext,
    });
  }
  const toolContext = buildToolContext(safeSession);
  if (toolContext) {
    chatMessages.push({
      role: "system",
      content: `Recent local tool logs:\n${toolContext}`,
    });
  }
  if (Array.isArray(safeSession.plan) && safeSession.plan.length > 0) {
    chatMessages.push({
      role: "system",
      content: `Current plan snapshot:\n${JSON.stringify(safeSession.plan)}`,
    });
  }

  for (const msg of safeSession.messages) {
    chatMessages.push(msg);
  }
  chatMessages.push({ role: "user", content: prompt });
  chatMessages = normalizeHarnessMessagesForPrompt(chatMessages);

  const htmlParts = [];
  let finalText = "";
  let executedToolCount = 0;
  let lastExecutedToolSignature = "";
  const compactToolResults = [];
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
  if (preSamplingCompaction?.compacted) {
    pushCard(renderContextCompactedCard(preSamplingCompaction));
  }

  for (let step = 1; step <= Math.max(1, autoToolMaxSteps); step += 1) {
    if (emit) {
      emit({
        type: "status",
        step,
        message: `step ${step}: deciding next action`,
      });
    }
    const stepFocusMessage = {
      role: "system",
      content: buildTaskFocusSystemMessage({
        prompt,
        promptIntent,
        toolStats,
        step,
      }),
    };

    let raw = "";
    try {
      raw = await callRunPodChatText({
        model,
        temperature: Number.isFinite(temperature) ? temperature : autoToolTemperature,
        messages: [...chatMessages, stepFocusMessage],
        maxTokens: Math.max(256, autoToolMaxTokens),
      });
    } catch (err) {
      if (!isContextExceededError(err)) {
        throw err;
      }
      const compacted = compactMessagesForContextRetry(chatMessages, {
        step,
        reason: "context_exceeded",
      });
      const compactedWeight = estimateMessagesCharWeight(compacted);
      const originalWeight = estimateMessagesCharWeight(chatMessages);
      if (compacted.length >= chatMessages.length && compactedWeight >= originalWeight) {
        throw err;
      }
      chatMessages.length = 0;
      chatMessages.push(...compacted);
      appendToolLog(safeSession, {
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
        messages: [...chatMessages, stepFocusMessage],
        maxTokens: Math.max(256, autoToolMaxTokens),
      });
    }

    let decisionObject = null;
    let parseRecovered = false;
    let parseRecoveredByFallback = false;
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
      const fallbackDecision = recoverAgentDecisionFromMalformedText(raw);
      if (fallbackDecision) {
        decisionObject = fallbackDecision;
        parseRecovered = true;
        parseRecoveredByFallback = true;
      }
    }

    if (!decisionObject) {
      appendToolLog(safeSession, {
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
      appendToolLog(safeSession, {
        title: "auto-tool json recovered",
        summary: `step=${step}`,
        detail: parseRecoveredByFallback
          ? "Recovered malformed response via local fallback parser."
          : "Recovered malformed JSON response via repair pass.",
      });
      if (showInternalRecoveryCards) {
        pushCard(renderToolResult({
          title: "Auto tool JSON recovered",
          meta: `step=${step}`,
          body: parseRecoveredByFallback
            ? "Recovered malformed response locally and continued."
            : "Recovered malformed JSON response and continued.",
        }));
      }
    }

    const decision = normalizeAgentDecision(decisionObject);
    if (decision.type === "final") {
      const candidateFinalText = decision.message || "(empty response)";
      const coverage = evaluateFinalAnswerCoverage({
        prompt,
        finalText: candidateFinalText,
        promptIntent,
        toolStats,
        temporalContext,
      });
      if (!coverage.ok && step < Math.max(1, autoToolMaxSteps)) {
        const reasonText = coverage.reasons.join("; ");
        appendToolLog(safeSession, {
          title: "auto-tool final rejected",
          summary: `step=${step}`,
          detail: [
            "Controller rejected premature final answer.",
            `reasons=${reasonText}`,
            "",
            "candidate_final:",
            truncateText(candidateFinalText, 1200),
          ].join("\n"),
        });
        pushCard(renderToolResult({
          title: "Auto tool final rejected",
          meta: `step=${step}`,
          body: `Controller requested continuation: ${reasonText}`,
          isError: true,
        }));
        chatMessages.push({
          role: "assistant",
          content: JSON.stringify({
            type: "final",
            message: candidateFinalText,
          }),
        });
        chatMessages.push({
          role: "user",
          content: [
            "Controller validation failed for your previous final answer.",
            `reasons: ${reasonText}`,
            `original_user_question: ${prompt}`,
            `task_progress: ${summarizeToolStats(toolStats)}`,
            promptIntent.requiresBreadth
              ? `requirement: provide at least ${promptIntent.expectedMinItems} concrete items if evidence allows.`
              : "",
            "Continue with additional tool calls and then return a better final answer.",
          ].filter(Boolean).join("\n"),
        });
        chatMessages = normalizeHarnessMessagesForPrompt(chatMessages);
        continue;
      }
      finalText = candidateFinalText;
      break;
    }
    if (decision.type !== "tool" || !decision.tool) {
      finalText = raw || "Model returned an invalid decision object.";
      break;
    }

    const toolCallId = decision.callId || nextSessionToolCallId(safeSession);
    const toolCallSignature = buildToolCallSignature(decision.tool, decision.args);
    if (toolCallSignature && toolCallSignature === lastExecutedToolSignature) {
      const duplicateResult = {
        ok: false,
        tool: decision.tool,
        skipped: true,
        error: "duplicate_tool_call_suppressed",
        detail: "Identical tool call with identical arguments was already executed in the previous step.",
      };
      appendToolLog(safeSession, {
        title: "auto-tool duplicate suppressed",
        summary: `step=${step} tool=${decision.tool}`,
        detail: [
          `call_id=${toolCallId}`,
          `signature=${toolCallSignature}`,
          `args=${truncateText(safeJsonStringify(decision.args || {}), 600)}`,
        ].join("\n"),
      });
      pushCard(renderToolResult({
        title: `Auto tool duplicate skipped: ${decision.tool}`,
        meta: `step=${step} call_id=${toolCallId}`,
        body: "Same tool call was just executed. Choose a different action or return final.",
        isError: true,
      }));
      chatMessages.push({
        role: "assistant",
        content: JSON.stringify({
          type: "tool_call",
          call_id: toolCallId,
          tool_name: decision.tool,
          arguments: decision.args,
          reason: decision.reason || "",
        }),
      });
      const duplicateOutputPayload = normalizeToolOutputPayload({
        type: "tool_output",
        call_id: toolCallId,
        tool_name: decision.tool,
        ok: false,
        result: duplicateResult,
      }, {
        callIdFallback: toolCallId,
        toolNameFallback: decision.tool,
      });
      chatMessages.push({
        role: "user",
        content: safeJsonStringify(duplicateOutputPayload),
      });
      chatMessages = normalizeHarnessMessagesForPrompt(chatMessages);
      continue;
    }
    const callMeta = [
      `step=${step}`,
      `call_id=${toolCallId}`,
      decision.reason ? `reason=${decision.reason}` : "",
    ].filter(Boolean).join(" ");
    pushCard(renderToolResult({
      title: `Auto tool: ${decision.tool}`,
      meta: callMeta,
      body: summarizeToolArgs(decision.tool, decision.args),
    }));

    const toolOutcome = await executeAutoToolCall({
      session: safeSession,
      toolName: decision.tool,
      args: decision.args,
      fallbackWebSearchQuery: prompt,
      prompt,
      promptIntent,
    });
    pushCard(toolOutcome.html);
    recordToolEvidence(toolStats, toolOutcome.modelResult);
    executedToolCount += 1;
    compactToolResults.push(compactToolResultForFinal(toolOutcome.modelResult));
    if (compactToolResults.length > 8) {
      compactToolResults.shift();
    }

    chatMessages.push({
      role: "assistant",
      content: JSON.stringify({
        type: "tool_call",
        call_id: toolCallId,
        tool_name: decision.tool,
        arguments: decision.args,
        reason: decision.reason || "",
      }),
    });
    const toolOutputPayload = normalizeToolOutputPayload({
      type: "tool_output",
      call_id: toolCallId,
      tool_name: decision.tool,
      ok: toolOutcome?.modelResult?.ok === true,
      result: toolOutcome.modelResult,
    }, {
      callIdFallback: toolCallId,
      toolNameFallback: decision.tool,
    });
    chatMessages.push({
      role: "user",
      content: safeJsonStringify(toolOutputPayload),
    });
    chatMessages = normalizeHarnessMessagesForPrompt(chatMessages);
    lastExecutedToolSignature = toolCallSignature;
  }

  if (!finalText) {
    finalText = [
      `Auto tool loop reached step limit (${Math.max(1, autoToolMaxSteps)}).`,
      "Run again with a follow-up instruction if more work is needed.",
    ].join("\n");
  }

  if (shouldRunFocusedFinalRewrite({
    prompt,
    draftText: finalText,
    toolCallCount: executedToolCount,
  })) {
    try {
      const rewritten = await rewriteFinalAnswerWithToolEvidence({
        prompt,
        draftText: finalText,
        model,
        temperature,
        toolResults: compactToolResults,
        temporalContext,
        promptIntent,
        toolStats,
      });
      if (rewritten) {
        appendToolLog(safeSession, {
          title: "auto-tool final rewritten",
          summary: `tool_calls=${executedToolCount}`,
          detail: [
            "Final answer was rewritten to improve question relevance.",
            "",
            "[before]",
            truncateText(finalText, 1200),
            "",
            "[after]",
            truncateText(rewritten, 1200),
          ].join("\n"),
        });
        finalText = rewritten;
      }
    } catch (rewriteErr) {
      appendToolLog(safeSession, {
        title: "auto-tool final rewrite skipped",
        summary: "failed",
        detail: rewriteErr?.message || String(rewriteErr),
      });
    }
  }

  const staleAsOfRewrite = rewriteStaleAsOfDatesForLatestPrompt({
    prompt,
    text: finalText,
    currentDateJst: temporalContext.currentDateJst,
  });
  if (staleAsOfRewrite.rewriteCount > 0) {
    finalText = staleAsOfRewrite.text;
    appendToolLog(safeSession, {
      title: "auto-tool stale date normalized",
      summary: `rewritten_dates=${staleAsOfRewrite.rewriteCount}`,
      detail: [
        `prompt=${truncateText(prompt, 400)}`,
        `current_date_jst=${temporalContext.currentDateJst}`,
        "Replaced stale 'as of' dates for a latest/current query.",
      ].join("\n"),
    });
  }

  // Guardrail for weather "today" prompts: avoid stale explicit calendar dates.
  if (promptAsksTodayWeather(prompt)) {
    const rewrite = rewriteMismatchedExplicitDatesAsToday(finalText, temporalContext.currentDateJst);
    finalText = rewrite.text;
    if (rewrite.mismatchCount > 0) {
      appendToolLog(safeSession, {
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
    executedToolCount,
    toolStats,
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

function approxTokensFromCharWeight(charWeight) {
  const safeChars = Math.max(0, Number.parseInt(String(charWeight || 0), 10) || 0);
  return Math.max(0, Math.ceil(safeChars / 4));
}

function estimateMessagesTokenUsage(messages) {
  return approxTokensFromCharWeight(estimateMessagesCharWeight(messages));
}

function estimateTextTokenUsage(text) {
  return approxTokensFromCharWeight(String(text || "").length);
}

function computeSessionHistoryTokenBudget(maxOutputTokens = autoToolMaxTokens) {
  const safeOutputTokens = Math.max(256, Number.parseInt(String(maxOutputTokens || 0), 10) || 0);
  const byContextWindow = Math.max(
    1024,
    generationMaxContextTokens
      - generationContextReserveTokens
      - safeOutputTokens
      - sessionCompactionSystemPromptReserveTokens,
  );
  return Math.max(1024, Math.min(sessionAutoCompactTokenLimit, byContextWindow));
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

  const invokeChat = async (body, phaseLabel) => {
    for (let pass = 1; pass <= 2; pass += 1) {
      try {
        if (runPodHealthcheckOnChat) {
          await ensureRunPodHealthy({
            force: pass > 1,
            reason: `${phaseLabel}-pass${pass}`,
          });
        }
      } catch (healthErr) {
        // If health check itself is transient, still attempt chat call.
        if (!isTransientRunPodError(healthErr)) {
          throw healthErr;
        }
      }

      try {
        return await callRunPodJson("/chat/completions", body, {
          timeoutMs: runPodChatTimeoutMs,
          retryLabel: `POST /chat/completions (${phaseLabel} pass=${pass})`,
        });
      } catch (err) {
        if (pass >= 2 || !isTransientRunPodError(err)) {
          throw err;
        }
        const statusPart = Number.isInteger(err?.statusCode) ? `HTTP ${err.statusCode}` : (err?.name || "network");
        console.warn(`[node-htmx] chat transient failure during ${phaseLabel} (${statusPart}); forcing health check and retry.`);
        try {
          await ensureRunPodHealthy({ force: true, reason: `${phaseLabel}-forced-retry` });
        } catch {
          // ignore and continue to second pass
        }
        await sleepMs(Math.max(250, Math.min(2500, runPodHttpRetryDelayMs)));
      }
    }
    throw new Error("RunPod chat request failed after recovery attempts.");
  };

  let response;
  try {
    response = await invokeChat(requestBody, "primary");
  } catch (err) {
    if (!isLikelyUnsupportedGenerationParamError(err)) {
      throw err;
    }
    const fallbackBody = { ...requestBody };
    delete fallbackBody.top_k;
    delete fallbackBody.min_p;
    response = await invokeChat(fallbackBody, "fallback-no-topk-minp");
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
  const code = Number.parseInt(statusCode, 10);
  return [
    0,
    408,
    409,
    425,
    429,
    499,
    500,
    502,
    503,
    504,
    520,
    521,
    522,
    523,
    524,
    525,
    526,
  ].includes(code);
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
  return /fetch failed|econnreset|econnrefused|etimedout|enotfound|eai_again|network|socket hang up|premature close|terminated|ECONNRESET|UND_ERR|TLS|SSL|EOF/i.test(message);
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
      const cappedDelay = maxDelay > 0 ? Math.min(backoffDelay, maxDelay) : backoffDelay;
      const jitter = Math.floor(cappedDelay * 0.2 * Math.random());
      const waitMs = Math.max(0, cappedDelay + jitter);
      const statusPart = Number.isInteger(err?.statusCode) ? `HTTP ${err.statusCode}` : (err?.name || "network");
      console.warn(`[node-htmx] ${label} transient error (${statusPart}) attempt ${attempt}/${attempts}; retry in ${waitMs} ms.`);
      await sleepMs(waitMs);
    }
  }

  throw lastError || new Error(`RunPod request failed: ${label}`);
}

async function callRunPodJson(endpointPath, body, options = {}) {
  const url = `${runPodBaseUrl}${endpointPath}`;
  const effectiveTimeoutMs = parseIntEnv(
    options?.timeoutMs,
    timeoutMs,
    1000,
    900000,
  );
  const retryLabel = String(options?.retryLabel || `POST ${endpointPath}`).trim() || `POST ${endpointPath}`;
  return callRunPodWithRetry(retryLabel, async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), effectiveTimeoutMs);
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

async function callRunPodModels(options = {}) {
  const url = `${runPodBaseUrl}/models`;
  const effectiveTimeoutMs = parseIntEnv(
    options?.timeoutMs,
    runPodModelsTimeoutMs,
    1000,
    900000,
  );
  const retryLabel = String(options?.retryLabel || "GET /models").trim() || "GET /models";
  return callRunPodWithRetry(retryLabel, async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), effectiveTimeoutMs);
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
      runPodHealthState.lastOkAtMs = Date.now();
      runPodHealthState.lastCheckedAtMs = runPodHealthState.lastOkAtMs;
      runPodHealthState.lastError = "";
      return parsed;
    } finally {
      clearTimeout(timeout);
    }
  });
}

function isRunPodHealthFresh() {
  if (runPodHealthcheckTtlMs <= 0) return false;
  if (runPodHealthState.lastOkAtMs <= 0) return false;
  return Date.now() - runPodHealthState.lastOkAtMs <= runPodHealthcheckTtlMs;
}

async function ensureRunPodHealthy({ force = false, reason = "chat" } = {}) {
  if (!force && !runPodHealthcheckOnChat) {
    return;
  }
  if (!force && isRunPodHealthFresh()) {
    return;
  }
  if (runPodHealthState.inFlightPromise) {
    return runPodHealthState.inFlightPromise;
  }

  const promise = (async () => {
    try {
      await callRunPodModels({
        timeoutMs: runPodModelsTimeoutMs,
        retryLabel: `GET /models (healthcheck:${reason})`,
      });
    } catch (err) {
      runPodHealthState.lastCheckedAtMs = Date.now();
      runPodHealthState.lastError = err?.message || String(err);
      throw err;
    } finally {
      runPodHealthState.inFlightPromise = null;
    }
  })();

  runPodHealthState.inFlightPromise = promise;
  return promise;
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

function safeJsonStringify(value) {
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}

function tryParseJsonObjectText(rawText) {
  const text = String(rawText || "").trim();
  if (!text || text[0] !== "{") {
    return null;
  }
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed;
    }
  } catch {
    // ignore
  }
  return null;
}

function isToolCallMessageRow(row) {
  if (!row || row.role !== "assistant") return false;
  const parsed = tryParseJsonObjectText(row.content);
  if (!parsed) return false;
  const type = String(parsed.type || "").trim().toLowerCase();
  return type === "tool_call" || type === "tool";
}

function isToolOutputMessageRow(row) {
  if (!row || row.role !== "user") return false;
  const parsed = tryParseJsonObjectText(row.content);
  if (!parsed) return false;
  const type = String(parsed.type || "").trim().toLowerCase();
  return type === "tool_output" || type === "tool_result" || type === "tool_response";
}

function normalizeToolOutputResultObject(rawValue) {
  if (rawValue && typeof rawValue === "object" && !Array.isArray(rawValue)) {
    return rawValue;
  }
  if (Array.isArray(rawValue)) {
    return { items_count: rawValue.length };
  }
  if (typeof rawValue === "string") {
    const text = String(rawValue).trim();
    return text ? { text: truncateText(text, 800) } : {};
  }
  if (typeof rawValue === "number" || typeof rawValue === "boolean") {
    return { value: rawValue };
  }
  return {};
}

function buildToolOutputStructuredContent(result) {
  const source = normalizeToolOutputResultObject(result);
  const structured = {};
  if (source.ok === true || source.ok === false) {
    structured.ok = source.ok === true;
  }
  if (typeof source.tool === "string" && source.tool.trim()) {
    structured.tool = source.tool.trim();
  }
  if (typeof source.path === "string" && source.path.trim()) {
    structured.path = source.path.trim();
  }
  if (typeof source.query === "string" && source.query.trim()) {
    structured.query = source.query.trim();
  }
  if (typeof source.source === "string" && source.source.trim()) {
    structured.source = source.source.trim();
  }
  if (typeof source.error === "string" && source.error.trim()) {
    structured.error = truncateText(source.error.trim(), 280);
  }
  if (Number.isFinite(Number(source.bytes))) {
    structured.bytes = Number(source.bytes);
  }
  if (Number.isFinite(Number(source.elapsedMs))) {
    structured.elapsedMs = Number(source.elapsedMs);
  }
  if (Number.isFinite(Number(source.exitCode))) {
    structured.exitCode = Number(source.exitCode);
  }
  if (typeof source.changed === "boolean") {
    structured.changed = source.changed;
  }
  if (Array.isArray(source.results)) {
    structured.results_count = source.results.length;
  }
  if (Array.isArray(source.operations)) {
    structured.operations_count = source.operations.length;
  }
  if (Object.keys(structured).length === 0) {
    const preview = truncateText(safeJsonStringify(source), 280);
    if (preview) {
      structured.preview = preview;
    }
  }
  return structured;
}

function buildToolOutputContentBlocks(rawContent, result) {
  const blocks = [];
  if (Array.isArray(rawContent)) {
    for (const item of rawContent) {
      if (typeof item === "string") {
        const text = item.trim();
        if (text) {
          blocks.push({ type: "text", text: truncateText(text, 900) });
        }
        continue;
      }
      if (!item || typeof item !== "object") continue;
      const text = typeof item.text === "string"
        ? item.text.trim()
        : (typeof item.content === "string" ? item.content.trim() : "");
      if (!text) continue;
      blocks.push({ type: "text", text: truncateText(text, 900) });
    }
  } else if (typeof rawContent === "string") {
    const text = rawContent.trim();
    if (text) {
      blocks.push({ type: "text", text: truncateText(text, 900) });
    }
  }
  if (blocks.length > 0) {
    return blocks.slice(0, 4);
  }

  const structured = buildToolOutputStructuredContent(result);
  const preview = truncateText(safeJsonStringify(structured), 900) || "(empty tool output)";
  return [{ type: "text", text: preview }];
}

function normalizeToolOutputPayload(rawPayload, {
  callIdFallback = "",
  toolNameFallback = "",
} = {}) {
  // Codex-inspired shape: keep legacy fields while mirroring function_call_output metadata
  // and MCP-style content/structuredContent for downstream robustness.
  const parsed = rawPayload && typeof rawPayload === "object" ? rawPayload : {};
  const callId = String(
    parsed.call_id
    || parsed.callId
    || parsed.id
    || parsed?.function_call_output?.call_id
    || parsed?.response?.call_id
    || callIdFallback,
  ).trim();
  const toolName = String(
    parsed.tool_name
    || parsed.tool
    || parsed?.function_call_output?.name
    || parsed?.response?.name
    || toolNameFallback,
  ).trim().toLowerCase();

  const resultCandidate =
    (parsed.result && typeof parsed.result === "object" ? parsed.result : null)
    || (parsed.output && typeof parsed.output === "object" ? parsed.output : null)
    || (parsed?.response?.structuredContent && typeof parsed.response.structuredContent === "object"
      ? parsed.response.structuredContent
      : null)
    || {};
  const result = normalizeToolOutputResultObject(resultCandidate);

  const structuredCandidate =
    (parsed.structuredContent && typeof parsed.structuredContent === "object" && !Array.isArray(parsed.structuredContent)
      ? parsed.structuredContent
      : null)
    || (parsed.structured_content && typeof parsed.structured_content === "object" && !Array.isArray(parsed.structured_content)
      ? parsed.structured_content
      : null)
    || (parsed?.response?.structuredContent
      && typeof parsed.response.structuredContent === "object"
      && !Array.isArray(parsed.response.structuredContent)
      ? parsed.response.structuredContent
      : null)
    || buildToolOutputStructuredContent(result);

  const success = parsed.success === true
    || parsed.ok === true
    || parsed?.function_call_output?.success === true
    || parsed?.response?.success === true
    || result.ok === true;
  const content = buildToolOutputContentBlocks(
    parsed.content !== undefined ? parsed.content : parsed?.response?.content,
    result,
  );

  return {
    type: "tool_output",
    call_id: callId,
    tool_name: toolName,
    ok: success,
    success,
    result,
    content,
    structuredContent: structuredCandidate,
    function_call_output: {
      type: "function_call_output",
      call_id: callId,
      name: toolName,
      success,
    },
  };
}

function normalizeHarnessMessagesForPrompt(messages) {
  const rows = normalizeChatMessages(messages);
  if (rows.length === 0) return rows;

  const rewritten = [];
  const toolCallIds = new Set();
  const toolOutputIds = new Set();

  for (let i = 0; i < rows.length; i += 1) {
    const row = { ...rows[i] };
    if (isToolCallMessageRow(row)) {
      const parsed = tryParseJsonObjectText(row.content) || {};
      const toolName = String(parsed.tool_name || parsed.tool || "").trim().toLowerCase();
      const fallbackCallId = `call-auto-${i + 1}`;
      const callIdRaw = String(
        parsed.call_id || parsed.callId || parsed.id || fallbackCallId,
      ).trim();
      const callId = callIdRaw || fallbackCallId;
      const normalizedPayload = {
        type: "tool_call",
        call_id: callId,
        tool_name: toolName,
        arguments: parsed.arguments && typeof parsed.arguments === "object"
          ? parsed.arguments
          : (parsed.args && typeof parsed.args === "object" ? parsed.args : {}),
        reason: String(parsed.reason || "").trim(),
      };
      row.content = safeJsonStringify(normalizedPayload) || row.content;
      rewritten.push(row);
      toolCallIds.add(callId);
      continue;
    }

    if (isToolOutputMessageRow(row)) {
      const parsed = tryParseJsonObjectText(row.content) || {};
      const fallbackCallId = String(
        parsed.call_id
        || parsed.callId
        || parsed.id
        || parsed?.function_call_output?.call_id
        || "",
      ).trim();
      const normalizedPayload = normalizeToolOutputPayload(parsed, {
        callIdFallback: fallbackCallId,
        toolNameFallback: String(parsed.tool_name || parsed.tool || "").trim().toLowerCase(),
      });
      const callId = String(normalizedPayload.call_id || "").trim();
      if (!callId) {
        // Drop malformed outputs with no call_id.
        continue;
      }
      if (!toolCallIds.has(callId)) {
        // Remove orphan tool outputs to keep call/output pairing invariant.
        continue;
      }
      row.content = safeJsonStringify(normalizedPayload) || row.content;
      rewritten.push(row);
      toolOutputIds.add(callId);
      continue;
    }

    rewritten.push(row);
  }

  // Ensure every tool_call has a corresponding tool_output.
  for (const callId of toolCallIds) {
    if (toolOutputIds.has(callId)) continue;
    const synthesized = normalizeToolOutputPayload({
      type: "tool_output",
      call_id: callId,
      tool_name: "",
      ok: false,
      result: { error: "aborted" },
    }, {
      callIdFallback: callId,
      toolNameFallback: "",
    });
    rewritten.push({
      role: "user",
      content: safeJsonStringify(synthesized),
    });
  }

  return rewritten;
}

function buildCompactionCheckpointFromMessages(messages, {
  maxChars = 2600,
  includeHeader = true,
} = {}) {
  const rows = normalizeChatMessages(messages).filter((row) => {
    const content = String(row.content || "").trim();
    return Boolean(content);
  });
  if (rows.length === 0) {
    return "";
  }

  const parts = [];
  if (includeHeader) {
    parts.push("Context checkpoint (compacted history):");
  }
  const latestItems = rows.slice(-32);
  for (const row of latestItems) {
    const parsed = tryParseJsonObjectText(row.content);
    const role = row.role;
    if (parsed && String(parsed.type || "").trim().toLowerCase() === "tool_call") {
      const toolName = String(parsed.tool_name || parsed.tool || "").trim();
      const callId = String(parsed.call_id || "").trim();
      const argsPreview = truncateText(safeJsonStringify(parsed.arguments || {}), 220);
      parts.push(`[assistant/tool_call] ${toolName} call_id=${callId} args=${argsPreview}`);
      continue;
    }
    if (parsed && String(parsed.type || "").trim().toLowerCase() === "tool_output") {
      const normalized = normalizeToolOutputPayload(parsed);
      const callId = String(normalized.call_id || "").trim();
      const ok = normalized.success === true ? "ok" : "error";
      const structuredPreview = truncateText(
        safeJsonStringify(
          normalized.structuredContent && typeof normalized.structuredContent === "object"
            ? normalized.structuredContent
            : normalized.result,
        ),
        240,
      );
      parts.push(`[user/tool_output] call_id=${callId} ${ok} structured=${structuredPreview}`);
      continue;
    }
    parts.push(`[${role}] ${truncateText(row.content, 320)}`);
  }
  let summary = parts.join("\n");
  if (summary.length > maxChars) {
    summary = truncateText(summary, maxChars);
  }
  return summary;
}

function compactMessagesForContextRetry(messages, options = {}) {
  const rows = normalizeHarnessMessagesForPrompt(messages);
  if (rows.length <= Math.max(6, contextRetryKeepRecentMessages + 2)) {
    return rows;
  }

  const keepIndexes = new Set();
  const stableSystemMax = Math.min(3, rows.length);
  for (let i = 0; i < stableSystemMax; i += 1) {
    if (rows[i].role === "system") {
      keepIndexes.add(i);
    }
  }
  const tailCount = Math.max(4, contextRetryKeepRecentMessages);
  const tailStart = Math.max(0, rows.length - tailCount);
  for (let i = tailStart; i < rows.length; i += 1) {
    keepIndexes.add(i);
  }

  const dropped = [];
  const selected = [];
  for (let i = 0; i < rows.length; i += 1) {
    if (keepIndexes.has(i)) {
      selected.push(rows[i]);
    } else {
      dropped.push(rows[i]);
    }
  }

  const summary = buildCompactionCheckpointFromMessages(dropped, {
    maxChars: 2600,
    includeHeader: true,
  });
  const result = [];
  let insertedSummary = false;
  for (const row of selected) {
    const isStableSystem = row.role === "system" && !insertedSummary;
    result.push(row);
    if (isStableSystem && summary) {
      result.push({
        role: "system",
        content: [
          "<context_checkpoint>",
          summary,
          options?.reason ? `reason=${String(options.reason).trim()}` : "",
          options?.step ? `step=${Number(options.step) || 0}` : "",
          "</context_checkpoint>",
        ].filter(Boolean).join("\n"),
      });
      insertedSummary = true;
    }
  }
  if (!insertedSummary && summary) {
    result.unshift({
      role: "system",
      content: `<context_checkpoint>\n${summary}\n</context_checkpoint>`,
    });
  }
  return normalizeHarnessMessagesForPrompt(result);
}

function nextSessionToolCallId(session) {
  const safeSession = ensureSessionShape(session);
  const seq = safeSession.nextToolCallSeq;
  safeSession.nextToolCallSeq += 1;
  return `call-${String(seq).padStart(4, "0")}`;
}

function trimHistory(messages) {
  const maxMessages = Math.max(1, maxHistoryPairs) * 2;
  if (!Array.isArray(messages) || messages.length <= maxMessages) return messages;
  return messages.slice(messages.length - maxMessages);
}

function recordSessionTurnJournal(session, {
  prompt,
  assistantText,
  toolCallCount = 0,
  toolStats = null,
}) {
  const safeSession = ensureSessionShape(session);
  const stats = toolStats && typeof toolStats === "object"
    ? summarizeToolStats(toolStats)
    : "";
  safeSession.turnJournal.push({
    prompt: truncateText(String(prompt || "").trim(), 1600),
    assistant: truncateText(String(assistantText || "").trim(), 2400),
    toolCallCount: Number.isInteger(toolCallCount) ? toolCallCount : 0,
    stats,
    createdAt: new Date().toISOString(),
  });
  if (safeSession.turnJournal.length > 40) {
    safeSession.turnJournal = safeSession.turnJournal.slice(-40);
  }
}

function compactSessionHistoryIfNeeded(session, options = {}) {
  const safeSession = ensureSessionShape(session);
  const pendingMessages = normalizeChatMessages(options?.pendingMessages || []);
  const pendingTokens = estimateMessagesTokenUsage(pendingMessages);
  const tokenBudget = computeSessionHistoryTokenBudget(options?.maxOutputTokens);
  const maxMessages = Math.max(1, maxHistoryPairs) * 2;
  const normalizedHistory = normalizeChatMessages(safeSession.messages);
  const historyTokensBefore = estimateMessagesTokenUsage(normalizedHistory);
  const compactSummaryTokensBefore = estimateTextTokenUsage(safeSession.compactSummary);
  const totalTokensBefore = historyTokensBefore + compactSummaryTokensBefore + pendingTokens;
  const overMessageLimit = normalizedHistory.length > maxMessages;
  const overTokenLimit = totalTokensBefore > tokenBudget;

  if (!overMessageLimit && !overTokenLimit) {
    return {
      compacted: false,
      droppedMessages: 0,
      keptMessages: normalizedHistory.length,
      compactVersion: safeSession.compactVersion,
      checkpointChars: 0,
      tokenBudget,
      totalTokensBefore,
      totalTokensAfter: totalTokensBefore,
      historyTokensBefore,
      historyTokensAfter: historyTokensBefore,
      pendingTokens,
    };
  }

  let kept = normalizedHistory.slice();
  const dropped = [];

  const keepRecentMessages = Math.max(2, historyCompactionKeepRecentPairs) * 2;
  const keepStart = Math.max(0, kept.length - keepRecentMessages);
  if (keepStart > 0) {
    dropped.push(...kept.slice(0, keepStart));
    kept = kept.slice(keepStart);
  }

  const targetTotalTokens = Math.max(1024, Math.floor(tokenBudget * sessionCompactionTargetRatio));
  const minKeptMessages = 2;
  while (kept.length > minKeptMessages) {
    const currentTotalTokens =
      estimateMessagesTokenUsage(kept)
      + estimateTextTokenUsage(safeSession.compactSummary)
      + pendingTokens;
    if (currentTotalTokens <= targetTotalTokens && kept.length <= maxMessages) {
      break;
    }
    dropped.push(kept.shift());
  }

  while (kept.length > minKeptMessages && kept[0]?.role === "assistant") {
    dropped.push(kept.shift());
  }

  const checkpoint = buildCompactionCheckpointFromMessages(dropped, {
    maxChars: 4200,
    includeHeader: false,
  });
  const checkpointChars = checkpoint.length;
  if (checkpoint) {
    const block = [
      `# compact checkpoint v${safeSession.compactVersion + 1}`,
      `created_at=${new Date().toISOString()}`,
      checkpoint,
    ].join("\n");
    safeSession.compactSummary = safeSession.compactSummary
      ? `${safeSession.compactSummary}\n\n${block}`
      : block;
    safeSession.compactVersion += 1;
    if (safeSession.compactSummary.length > historyCompactionSummaryMaxChars) {
      safeSession.compactSummary = safeSession.compactSummary.slice(
        safeSession.compactSummary.length - historyCompactionSummaryMaxChars,
      );
    }
  }

  const compacted = dropped.length > 0;
  if (compacted) {
    safeSession.messages = trimHistory(kept);
  }

  const historyTokensAfter = estimateMessagesTokenUsage(safeSession.messages);
  const compactSummaryTokensAfter = estimateTextTokenUsage(safeSession.compactSummary);
  const totalTokensAfter = historyTokensAfter + compactSummaryTokensAfter + pendingTokens;

  if (!compacted) {
    safeSession.messages = trimHistory(normalizedHistory);
  }
  return {
    compacted,
    droppedMessages: dropped.length,
    keptMessages: safeSession.messages.length,
    compactVersion: safeSession.compactVersion,
    checkpointChars,
    tokenBudget,
    totalTokensBefore,
    totalTokensAfter,
    historyTokensBefore,
    historyTokensAfter,
    pendingTokens,
  };
}

function recordSessionConversationTurn(session, {
  prompt,
  assistantText,
  toolCallCount = 0,
  toolStats = null,
}) {
  const safeSession = ensureSessionShape(session);
  safeSession.messages.push({ role: "user", content: String(prompt || "").trim() });
  safeSession.messages.push({ role: "assistant", content: String(assistantText || "").trim() });
  recordSessionTurnJournal(safeSession, {
    prompt,
    assistantText,
    toolCallCount,
    toolStats,
  });
  const compactionInfo = compactSessionHistoryIfNeeded(safeSession, { reason: "post_turn" });
  safeSession.messages = trimHistory(safeSession.messages);
  return {
    ...(compactionInfo && typeof compactionInfo === "object" ? compactionInfo : {}),
    keptMessages: safeSession.messages.length,
  };
}

function buildSessionCompactedContextMessage(session) {
  const safeSession = ensureSessionShape(session);
  const blocks = [];
  if (safeSession.compactSummary) {
    blocks.push("Compacted prior context summary:");
    blocks.push(truncateText(safeSession.compactSummary, 4600));
  }
  if (safeSession.turnJournal.length > 0) {
    const recentTurns = safeSession.turnJournal.slice(-4);
    blocks.push("Recent turn journal:");
    for (let i = 0; i < recentTurns.length; i += 1) {
      const item = recentTurns[i];
      blocks.push([
        `- turn ${i + 1}:`,
        `question=${truncateText(item.prompt, 360)}`,
        `answer=${truncateText(item.assistant, 420)}`,
        `tool_calls=${item.toolCallCount}`,
        item.stats ? `stats=${item.stats}` : "",
      ].filter(Boolean).join("\n  "));
    }
  }
  const text = blocks.join("\n");
  return truncateText(text, 5600);
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
    const state = getWorkspaceState();
    const text = [
      `root: ${state.workspaceRoot}`,
      `default: ${state.defaultWorkspaceRoot}`,
      `shell allowlist: ${state.shellAllowlist.join(", ")}`,
      "read_scope: local files (anywhere) + http(s) URLs",
      "list_dir_scope: workspace root only",
      "write_scope: workspace root only",
      `uv_bin: ${state.uvBin || "(auto lookup)"}`,
      `python_bin: ${state.pythonBin || "(auto lookup)"}`,
      `generation: temperature=${generationTemperatureDefault} top_p=${generationTopP} top_k=${generationTopK} min_p=${generationMinP}`,
      `generation context: max_tokens=${generationMaxContextTokens} reserve=${generationContextReserveTokens}`,
    ].join("\n");
    send(res, 200, `<pre class="workspace-box">${escapeHtml(text)}</pre>`, "text/html; charset=utf-8");
    return;
  }

  if (req.method === "GET" && pathname === "/api/workspace/state") {
    const state = getWorkspaceState();
    send(res, 200, {
      ok: true,
      ...state,
    }, "application/json; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/workspace/reset") {
    try {
      const nextRoot = await setWorkspaceRoot(defaultWorkspaceRoot, { createIfMissing: true });
      send(res, 200, {
        ok: true,
        workspaceRoot: nextRoot,
      }, "application/json; charset=utf-8");
    } catch (err) {
      send(res, 200, {
        ok: false,
        error: err?.message || String(err),
      }, "application/json; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/workspace/set") {
    try {
      const bodyText = await readBody(req);
      const contentType = String(req.headers["content-type"] || "").toLowerCase();
      let nextPath = "";
      if (contentType.includes("application/json")) {
        try {
          const payload = JSON.parse(bodyText || "{}");
          nextPath = String(payload?.path || payload?.workspaceRoot || "").trim();
        } catch {
          nextPath = "";
        }
      } else {
        const form = new URLSearchParams(bodyText || "");
        nextPath = String(form.get("path") || form.get("workspaceRoot") || "").trim();
      }
      if (!nextPath) {
        send(res, 200, {
          ok: false,
          error: "Workspace path is required.",
          workspaceRoot,
        }, "application/json; charset=utf-8");
        return;
      }
      console.log(`[node-htmx] workspace set requested: ${nextPath}`);
      const nextRoot = await setWorkspaceRoot(nextPath, { createIfMissing: true });
      console.log(`[node-htmx] workspace set applied: ${nextRoot}`);
      send(res, 200, {
        ok: true,
        workspaceRoot: nextRoot,
      }, "application/json; charset=utf-8");
    } catch (err) {
      console.warn(`[node-htmx] workspace set failed: ${err?.message || String(err)}`);
      send(res, 200, {
        ok: false,
        error: err?.message || String(err),
        workspaceRoot,
      }, "application/json; charset=utf-8");
    }
    return;
  }

  if (req.method === "POST" && pathname === "/api/workspace/select") {
    try {
      console.log("[node-htmx] workspace select requested");
      const selected = await openNativeFolderPicker(workspaceRoot);
      if (!selected) {
        console.log("[node-htmx] workspace select canceled");
        send(res, 200, {
          ok: false,
          canceled: true,
          workspaceRoot,
        }, "application/json; charset=utf-8");
        return;
      }
      const nextRoot = await setWorkspaceRoot(selected, { createIfMissing: false });
      console.log(`[node-htmx] workspace select applied: ${nextRoot}`);
      send(res, 200, {
        ok: true,
        workspaceRoot: nextRoot,
      }, "application/json; charset=utf-8");
    } catch (err) {
      console.warn(`[node-htmx] workspace select failed: ${err?.message || String(err)}`);
      send(res, 200, {
        ok: false,
        error: err?.message || String(err),
      }, "application/json; charset=utf-8");
    }
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

  if (req.method === "GET" && pathname === "/api/tools/specs") {
    send(res, 200, {
      ok: true,
      harness: "codex_style_tool_call",
      decisionSchema: autoToolDecisionSchemaDescription,
      tools: autoToolSpecs,
      toolNames: autoToolNames,
    }, "application/json; charset=utf-8");
    return;
  }

  if (req.method === "POST" && pathname === "/api/session/reset") {
    const session = getOrCreateSession(req, res);
    session.messages = [];
    session.toolLogs = [];
    session.plan = [];
    session.turnJournal = [];
    session.compactSummary = "";
    session.compactVersion = 0;
    session.nextToolCallSeq = 1;
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
      const body = renderListDirBody(listing);
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

      const compactionInfo = recordSessionConversationTurn(session, {
        prompt,
        assistantText,
        toolCallCount: Number(autoResult.executedToolCount || 0),
        toolStats: autoResult.toolStats || null,
      });
      const compactionHtml = compactionInfo?.compacted ? renderContextCompactedCard(compactionInfo) : "";
      const middleHtml = `${autoResult.html || ""}${compactionHtml}`;

      send(
        res,
        200,
        renderTurn({
          userPrompt: prompt,
          assistantText,
          model,
          elapsedMs,
          middleHtml,
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

      const compactionInfo = recordSessionConversationTurn(session, {
        prompt,
        assistantText,
        toolCallCount: Number(autoResult.executedToolCount || 0),
        toolStats: autoResult.toolStats || null,
      });
      if (compactionInfo?.compacted) {
        writeNdjson(res, {
          type: "context_compacted",
          html: renderContextCompactedCard(compactionInfo),
          compactVersion: Number(compactionInfo.compactVersion || 0),
          droppedMessages: Number(compactionInfo.droppedMessages || 0),
          keptMessages: Number(compactionInfo.keptMessages || 0),
        });
      }

      const streamedAssistant = await emitAssistantStreamEvents({
        res,
        assistantText,
        model,
        elapsedMs,
      });
      writeNdjson(res, {
        type: "assistant_turn",
        html: renderAssistantTurn({ assistantText, model, elapsedMs }),
        streamed: streamedAssistant ? true : false,
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
  console.log(
    `[node-htmx] session compaction: auto_limit_tokens=${sessionAutoCompactTokenLimit} target_ratio=${sessionCompactionTargetRatio} system_prompt_reserve_tokens=${sessionCompactionSystemPromptReserveTokens} max_history_pairs=${maxHistoryPairs}`,
  );
  console.log(`[node-htmx] playwright mcp: ${playwrightMcpEnabled ? "enabled" : "disabled"} (${playwrightMcpBrowser})`);
  console.log(
    `[node-htmx] client autostop: ${clientAutostopEnabled ? "enabled" : "disabled"} `
    + `(heartbeat=${Math.max(1000, clientHeartbeatIntervalMs)}ms stale=${Math.max(1000, clientHeartbeatStaleMs)}ms idle=${Math.max(1000, clientAutostopIdleMs)}ms)`,
  );
  console.log(
    `[node-htmx] stream keepalive: every ${Math.max(2000, streamKeepaliveIntervalMs)}ms, autostop_grace=${Math.max(1000, clientAutostopRequestGraceMs)}ms`,
  );
  console.log(
    `[node-htmx] assistant stream: ${assistantStreamEnabled ? "enabled" : "disabled"} `
    + `(chunk_chars=${assistantStreamChunkChars} delay_ms=${assistantStreamChunkDelayMs})`,
  );
});
