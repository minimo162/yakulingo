# LocaLingo (RunPod FastAPI + HTMX Client)

This is a lightweight local client app for RunPod LM Studio.

Goal:
- Keep VSCode + Codex on OpenAI.
- Use a separate local app for RunPod chat.
- Avoid heavy Open WebUI runtime size.
- Use bundled Python runtime + bundled Node runtime.
- FastAPI serves UI/API gateway; Node engine (`server.mjs`) runs internally.

UI/Server stack:
- FastAPI
- HTMX
- Alpine.js
- Tailwind CSS

Inference backend:
- fixed to `codex_cli` (`codex exec --json` via FastAPI bridge)

## Team Member Usage

Run only these files in this folder:

- `start.bat`

Everything else is in `_internal`.

`start.bat` behavior:
- Starts FastAPI frontend (`uvicorn`) on `APP_PORT`.
- FastAPI auto-starts internal Node engine on `ENGINE_PORT`.
- If bundled Node/Codex runtime is missing, auto-runs `_internal/prepare-node-runtime.ps1` once.
- If bundled Python runtime is missing, auto-runs `_internal/prepare-python-runtime.ps1` once.
- If a previous LocaLingo process exists, it is stopped and restarted automatically.

`stop.bat` behavior:
- Deprecated (no-op message only).
- Close browser tabs or run `start.bat` again to refresh/restart process.

## First-Time Admin Setup

1. Keep shared defaults in:
   - `tools/runpod_eval/node_htmx_client/_internal/.env.example`
2. Create local (not tracked) config:
   - Copy `tools/runpod_eval/node_htmx_client/_internal/.env.local.example`
   - To `tools/runpod_eval/node_htmx_client/_internal/.env.local`
3. Set in `.env.local`:
   - `RUNPOD_BASE_URL=https://<pod-id>-11434.proxy.runpod.net/v1`
   - Keep `RUNPOD_API_KEY=__USE_DPAPI__`
4. Codex CLI backend is always enabled:
   - Bundled codex is auto-installed under `.runtime/codex` and always used.
   - Default policy: `CODEX_REQUIRE_BUNDLED=1`
   - Package can be pinned with `CODEX_BUNDLED_PACKAGE=@openai/codex@<version>`
   - Keep `DEFAULT_MODEL` as your RunPod model ID
   - Keep `CODEX_EXEC_MODEL` aligned with your LM Studio model id (usually same as `DEFAULT_MODEL`)
   - Optional provider id override: `CODEX_LMSTUDIO_PROVIDER_ID=lmstudio-runpod`
   - RunPod endpoint must support `Responses API` (`/v1/responses`)
5. Optional shared obfuscated key file (recommended for team):
   - Run `tools/runpod_eval/node_htmx_client/_internal/set-runpod-api-key-shared.bat`
   - This generates `_internal/runpod_api_key.obf`
6. Distribute this folder to members.

Recommended additional settings for local coding mode:
- `LOCAL_SHELL_TIMEOUT_MS=20000`
- `LOCAL_SHELL_ALLOWLIST=` (empty = built-in safe defaults)

Workspace root default:
- `tools/runpod_eval/node_htmx_client/workspace`
- You can change workspace at runtime from UI ("Select Workspace...").
- Selected workspace is persisted and restored on next launch.

## Per-User Behavior

Each launch reads config in this order:
- `tools/runpod_eval/node_htmx_client/_internal/.env.local` (primary, untracked)
- `tools/runpod_eval/node_htmx_client/_internal/.env.example` (fallback)

Per-user local files are:
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod_api_key.dpapi`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod-htmx-<username>.pid` (FastAPI process id)
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\logs\...`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\workspace-state.json`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\codex-home\...`

`start.bat` behavior:
- Uses `_internal/.env.local` first, then `_internal/.env.example`.
- Uses local DPAPI key if available.
- If no local key, imports shared obfuscated key from `_internal/runpod_api_key.obf`.
- Starts local FastAPI server and opens browser.

## Optional: Prepare Portable Runtime

Bundled runtime is the default and required runtime:

1. Admin runs:
   - `tools/runpod_eval/node_htmx_client/_internal/prepare-node-runtime.bat`
   - `tools/runpod_eval/node_htmx_client/_internal/prepare-python-runtime.bat`
2. This creates:
   - `tools/runpod_eval/node_htmx_client/.runtime/node/node.exe`
   - `tools/runpod_eval/node_htmx_client/.runtime/uv/uv.exe`
   - `tools/runpod_eval/node_htmx_client/.runtime/python-managed/...`
3. Members can run `start.bat` without system Node/Python.

Runtime size notes:
- Python is provisioned via uv managed standalone runtime (no system install).
- uv download cache is stored under `%LOCALAPPDATA%\YakuLingoRunpodHtmx\uv-cache` to avoid bloating repo folder.

## Connection Test

Run:

- `tools/runpod_eval/node_htmx_client/_internal/test-runpod-connection.ps1`

Expected:
- model IDs are displayed.

## RunPod Eval Integration

You can reuse this client's shared config + local DPAPI key to run the
evaluation scripts in `tools/runpod_eval` without re-entering API key.

Run:

- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/runpod_eval/run_eval_with_node_htmx.ps1`

Options:

- `-SkipStep8`
- `-SkipBenchmark`
- `-SkipContinuity`
- `-ContinuityApiMode chat|responses`
- `-OutputDir <path>`
- `-BaseUrl <url>` (override env)
- `-ApiKey <token>` (override secure store)

## Local Coder Mode (Codex-like MVP)

The UI now includes local workspace tools in addition to chat:
- Read file (`/api/tools/read`) - text/PDF/Office (`.xlsx/.docx/.pptx`)
- Read file by line range (`/api/tools/read_file`)
- List directory (`/api/tools/list_dir`)
- Search text with ripgrep (`/api/tools/search`)
- Run shell command with approval (`/api/tools/shell`)
- Write file (`/api/tools/write`, workspace only, supports `.xlsx/.docx/.pptx`)
- Apply patch (`/api/tools/apply_patch`, Codex-style patch blocks)
- Update plan (`/api/tools/update_plan`, step/status checklist)
- Web search via Playwright MCP (`web_search`, auto tool selection)

Tool results are stored in session and can be injected into chat context
using "Include local tool context". This lets RunPod model answers reference
actual local repository data.

Safety guardrails:
- `read` / `read_file` can access local files outside workspace and can also read `http(s)` URLs.
- `list_dir` / `write` / `apply_patch` remain restricted to the currently selected workspace folder.
- Shell commands are filtered by allowed prefixes (`LOCAL_SHELL_ALLOWLIST`).
- Shell command chaining chars (`;`, `&`, `|`, `>`, `<`, backtick, newline)
  are blocked.
- Web search runs in isolated Playwright MCP session and returns only extracted summaries/links.

Codex-like behavior:
- Model can auto-select `list_dir -> read_file -> apply_patch -> shell` workflow.
- Partial edits can be applied without rewriting full file content.
- Plan snapshots can be stored in-session via `update_plan`.
- Tool decisions support Codex-style `tool_call` schema with `call_id` and `arguments`.
- Runtime normalizes `tool_call`/`tool_output` pairs and auto-completes missing outputs.
- Session history now uses compaction checkpoints (summary + recent turns) instead of tail-only trimming.
- Tool harness schema can be fetched via `GET /api/tools/specs`.

Office read/write notes:
- `read` extracts text from `.xlsx/.docx/.pptx` and returns normalized plain text.
- `write` for `.docx/.xlsx/.pptx` accepts plain text or JSON payload.
- `.docx` JSON example: `{"paragraphs":["line1","line2"]}`
- `.xlsx` JSON example: `{"sheets":[{"name":"Sheet1","rows":[["A1","B1"],["A2","B2"]]}]}`
- `.pptx` JSON example: `{"slides":[{"title":"Slide 1","lines":["point1","point2"]}]}`

Playwright MCP settings:
- `PLAYWRIGHT_MCP_ENABLED=1`
- `PLAYWRIGHT_MCP_BROWSER=chromium`
- `PLAYWRIGHT_MCP_HEADLESS=1`
- `PLAYWRIGHT_MCP_TIMEOUT_MS=300000`
- `PLAYWRIGHT_MCP_MAX_RESULTS=5`

Browser-close auto-stop settings:
- `CLIENT_AUTOSTOP_ENABLED=1`
- `CLIENT_HEARTBEAT_INTERVAL_MS=15000`
- `CLIENT_HEARTBEAT_STALE_MS=45000`
- `CLIENT_AUTOSTOP_IDLE_MS=30000`
- `CLIENT_HEARTBEAT_SWEEP_MS=5000`
- `CLIENT_AUTOSTOP_REQUEST_GRACE_MS=30000`

Long-running stream stability:
- `STREAM_KEEPALIVE_INTERVAL_MS=10000`
- During active HTTP/stream requests, auto-stop is paused.

Codex exec send-condition knobs:
- `CODEX_REQUIRE_BUNDLED=1`
- `CODEX_BUNDLED_PACKAGE=@openai/codex@latest`
- `CODEX_PROVIDER_REQUEST_MAX_RETRIES=1`
- `CODEX_PROVIDER_STREAM_MAX_RETRIES=1`
- `CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS=45000`
- `CODEX_MODEL_CONTEXT_WINDOW=32768`
- `CODEX_NATIVE_MODE=1`
- `CODEX_MINIMAL_MODEL_INSTRUCTIONS=0`
- `CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE=` (optional)
- `CODEX_MODEL_REASONING_EFFORT=minimal`
- `CODEX_MODEL_REASONING_SUMMARY=auto`
- `CODEX_MODEL_VERBOSITY=low`
- `CODEX_EXEC_MODEL=<your-lmstudio-model-id>`
- `CODEX_LMSTUDIO_PROVIDER_ID=lmstudio-runpod`
- `CODEX_PROJECT_DOC_MAX_BYTES=0`
- `CODEX_PROMPT_MAX_CHARS=12000`
- `CODEX_PROMPT_COMPRESSION_ENABLED=0`
- `CODEX_PROMPT_COMPRESSION_TRIGGER_CHARS=9000`
- `CODEX_PROMPT_COMPRESSION_TARGET_CHARS=7600`
- `CODEX_PROMPT_KEEP_HEAD_CHARS=2400`
- `CODEX_PROMPT_KEEP_TAIL_CHARS=3200`
- `CODEX_PROMPT_KEY_LINES_LIMIT=40`
- `CODEX_EXEC_PROGRESS_PING_INTERVAL_MS=8000`
- `CODEX_EXEC_RETRY_MAX_ATTEMPTS=1`
- `CODEX_EXEC_RETRY_BASE_DELAY_MS=800`
- `CODEX_EXEC_RETRY_MAX_DELAY_MS=4000`
- `CODEX_STREAM_RECOVERY_FALLBACK_ENABLED=0`
- `CODEX_STREAM_RECOVERY_TIMEOUT_MS=90000`
- `CODEX_WEB_SEARCH_MODE=live`
- `CODEX_TOOL_FALLBACK_TO_ENGINE=0`
- `CODEX_TOOL_FALLBACK_FORCE_FOR_LIVE_WEB=0`
- `RUNPOD_BASE_URL_CANDIDATES=` (comma separated)
- `RUNPOD_ROUTE_PROBE_ENABLED=1`
- `RUNPOD_ROUTE_PROBE_TIMEOUT_MS=6000`
- `RUNPOD_ROUTE_COOLDOWN_SEC=90`
- `RUNPOD_RESPONSES_BACKGROUND_ENABLED=1`
- `RUNPOD_RESPONSES_POLL_INTERVAL_MS=1500`
- `RUNPOD_RESPONSES_POLL_TIMEOUT_MS=90000`
- Prompt text larger than `CODEX_PROMPT_MAX_CHARS` is truncated before `codex exec --json` send.
- Route failover rotates `RUNPOD_BASE_URL`/`RUNPOD_BASE_URL_CANDIDATES` when transport errors happen.
- In native mode, Codex CLI request flow is kept as close as possible to upstream behavior (RunPod connection and UI wrapper only).

RunPod upstream transient retry:
- `RUNPOD_REQUEST_TIMEOUT_MS=120000`
- `RUNPOD_MODELS_TIMEOUT_MS=30000`
- `RUNPOD_CHAT_TIMEOUT_MS=120000`
- `RUNPOD_HTTP_RETRY_MAX_ATTEMPTS=5`
- `RUNPOD_HTTP_RETRY_DELAY_MS=1200`
- `RUNPOD_HTTP_RETRY_MAX_DELAY_MS=10000`
- `RUNPOD_HEALTHCHECK_ON_CHAT=1`
- `RUNPOD_HEALTHCHECK_TTL_MS=20000`
- Applies to `/v1/models` and `/v1/chat/completions` calls.

RunPod startup connection test retry:
- `RUNPOD_CONNECTION_TEST_MODE=soft|strict` (`strict` default)
- `RUNPOD_CONNECTION_TEST_MAX_ATTEMPTS=4`
- `RUNPOD_CONNECTION_TEST_RETRY_DELAY_SEC=2`
- `RUNPOD_CONNECTION_TEST_TIMEOUT_SEC=8`
- Transient HTTP `499/502/503/504/520-526/429` and timeout-type errors are retried automatically.
- In `soft` mode, startup continues with warning even if retries are exhausted.

Relative date handling (today/tomorrow):
- `APP_TIME_ZONE=Asia/Tokyo` (default)
- Auto tool chat injects `current_date_jst/current_utc_iso` into system context.
- For weather "today" prompts, mismatched explicit past/future calendar dates are normalized.

Generation best-practice settings:
- `GENERATION_TEMPERATURE=0.6`
- `GENERATION_TOP_P=0.95`
- `GENERATION_TOP_K=20`
- `GENERATION_MIN_P=0`
- `GENERATION_MAX_CONTEXT_TOKENS=32768`
- Server trims message history by approximate budget to keep context within cap.
- If upstream rejects non-standard fields (`top_k`/`min_p`), server retries without them.

Context compaction knobs:
- `HISTORY_COMPACTION_KEEP_RECENT_PAIRS=4`
- `HISTORY_COMPACTION_SUMMARY_MAX_CHARS=18000`
- `CONTEXT_RETRY_KEEP_RECENT_MESSAGES=8`

Notes:
- First web search may trigger browser installation (`browser_install`) automatically.
- Some search pages may show anti-bot challenge; in that case result extraction can fail.
- When all browser tabs are closed, server exits after idle timeout.

## Autonomous Loop (plan -> diff -> auto apply)

The app includes an autonomous loop form:
- Planner step: model returns JSON plan (`target_files`, `tasks`, validations)
- Diff step: model returns full-file JSON edits and server generates diff preview
- Apply step: if enabled, edits are written to local files automatically

Notes:
- `auto apply` requires explicit approval checkbox in UI.
- Diff preview is generated before write.
- Validation commands are executed only if they pass shell allowlist.

Env knobs:
- `AUTONOMOUS_LOOP_MAX_ITERS`
- `AUTONOMOUS_MAX_FILES_PER_ITER`
- `AUTONOMOUS_MAX_FILE_CONTEXT_CHARS`
- `AUTONOMOUS_MAX_VALIDATION_COMMANDS`
- `AUTONOMOUS_MODEL_MAX_TOKENS`

## Notes

- API key is never shown in UI.
- Shared `runpod_api_key.obf` is obfuscation, not strong encryption.
- Use folder permissions as primary protection.
