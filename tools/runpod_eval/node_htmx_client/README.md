# LocaLingo (RunPod Node + htmx Client)

This is a lightweight local client app for RunPod LM Studio.

Goal:
- Keep VSCode + Codex on OpenAI.
- Use a separate local app for RunPod chat.
- Avoid heavy Open WebUI runtime size.
- Always use bundled Node.js runtime (`.runtime/node/node.exe`).

## Team Member Usage

Run only these files in this folder:

- `start.bat`

Everything else is in `_internal`.

`start.bat` behavior:
- Uses bundled Node runtime only.
- If runtime is missing, auto-runs `_internal/prepare-node-runtime.ps1` once.
- If bundled Python runtime is missing, auto-runs `_internal/prepare-python-runtime.ps1` once.
- If a previous LocaLingo server process exists, it is stopped and restarted automatically.

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
4. Optional shared obfuscated key file (recommended for team):
   - Run `tools/runpod_eval/node_htmx_client/_internal/set-runpod-api-key-shared.bat`
   - This generates `_internal/runpod_api_key.obf`
5. Distribute this folder to members.

Recommended additional settings for local coding mode:
- `LOCAL_SHELL_TIMEOUT_MS=20000`
- `LOCAL_SHELL_ALLOWLIST=` (empty = built-in safe defaults)

Workspace root is fixed to:
- `tools/runpod_eval/node_htmx_client/workspace`

## Per-User Behavior

Each launch reads config in this order:
- `tools/runpod_eval/node_htmx_client/_internal/.env.local` (primary, untracked)
- `tools/runpod_eval/node_htmx_client/_internal/.env.example` (fallback)

Per-user local files are:
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod_api_key.dpapi`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod-htmx-<username>.pid`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\logs\...`

`start.bat` behavior:
- Uses `_internal/.env.local` first, then `_internal/.env.example`.
- Uses local DPAPI key if available.
- If no local key, imports shared obfuscated key from `_internal/runpod_api_key.obf`.
- Starts local Node server and opens browser.

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
- All file operations are restricted to the fixed workspace folder (`tools/runpod_eval/node_htmx_client/workspace`).
- `read` / `read_file` / `list_dir` / `write` / `apply_patch` require workspace-relative paths.
- Shell commands are filtered by allowed prefixes (`LOCAL_SHELL_ALLOWLIST`).
- Shell command chaining chars (`;`, `&`, `|`, `>`, `<`, backtick, newline)
  are blocked.
- Web search runs in isolated Playwright MCP session and returns only extracted summaries/links.

Codex-like behavior:
- Model can auto-select `list_dir -> read_file -> apply_patch -> shell` workflow.
- Partial edits can be applied without rewriting full file content.
- Plan snapshots can be stored in-session via `update_plan`.

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

RunPod upstream transient retry:
- `RUNPOD_HTTP_RETRY_MAX_ATTEMPTS=4`
- `RUNPOD_HTTP_RETRY_DELAY_MS=1500`
- `RUNPOD_HTTP_RETRY_MAX_DELAY_MS=6000`
- Applies to `/v1/models` and `/v1/chat/completions` calls.

RunPod startup connection test retry:
- `RUNPOD_CONNECTION_TEST_MODE=soft|strict` (`soft` default)
- `RUNPOD_CONNECTION_TEST_MAX_ATTEMPTS=4`
- `RUNPOD_CONNECTION_TEST_RETRY_DELAY_SEC=2`
- `RUNPOD_CONNECTION_TEST_TIMEOUT_SEC=8`
- Transient HTTP `502/503/504/429` and timeout-type errors are retried automatically.
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
