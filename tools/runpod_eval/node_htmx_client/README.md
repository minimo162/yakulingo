# RunPod Node + htmx Client

This is a lightweight local client app for RunPod LM Studio.

Goal:
- Keep VSCode + Codex on OpenAI.
- Use a separate local app for RunPod chat.
- Avoid heavy Open WebUI runtime size.
- Always use bundled Node.js runtime (`.runtime/node/node.exe`).

## Team Member Usage

Run only these files in this folder:

- `start.bat`
- `stop.bat`

Everything else is in `_internal`.

`start.bat` behavior:
- Uses bundled Node runtime only.
- If runtime is missing, auto-runs `_internal/prepare-node-runtime.ps1` once.

## First-Time Admin Setup

1. Open:
   - `tools/runpod_eval/node_htmx_client/_internal/.env.example`
2. Set:
   - `RUNPOD_BASE_URL=https://<pod-id>-11434.proxy.runpod.net/v1`
   - Keep `RUNPOD_API_KEY=__USE_DPAPI__`
3. Optional shared obfuscated key file (recommended for team):
   - Run `tools/runpod_eval/node_htmx_client/_internal/set-runpod-api-key-shared.bat`
   - This generates `_internal/runpod_api_key.obf`
4. Distribute this folder to members.

Recommended additional settings for local coding mode:
- `WORKSPACE_ROOT=.` (or your target repo path)
- `LOCAL_SHELL_TIMEOUT_MS=20000`
- `LOCAL_SHELL_ALLOWLIST=` (empty = built-in safe defaults)

## Per-User Behavior

Each launch reads config from shared file:
- `tools/runpod_eval/node_htmx_client/_internal/.env.example`

Per-user local files are:
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod_api_key.dpapi`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod-htmx-<username>.pid`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\logs\...`

`start.bat` behavior:
- Always uses shared `_internal/.env.example` as config source.
- Uses local DPAPI key if available.
- If no local key, imports shared obfuscated key from `_internal/runpod_api_key.obf`.
- Starts local Node server and opens browser.

## Optional: Prepare Portable Node Runtime

Bundled runtime is the default and required runtime:

1. Admin runs:
   - `tools/runpod_eval/node_htmx_client/_internal/prepare-node-runtime.bat`
2. This creates:
   - `tools/runpod_eval/node_htmx_client/.runtime/node/node.exe`
3. Members can then run `start.bat` without system Node.

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
- Read file (`/api/tools/read`)
- Search text with ripgrep (`/api/tools/search`)
- Run shell command with approval (`/api/tools/shell`)
- Write file with approval (`/api/tools/write`)

Tool results are stored in session and can be injected into chat context
using "Include local tool context". This lets RunPod model answers reference
actual local repository data.

Safety guardrails:
- All file operations are restricted to `WORKSPACE_ROOT`.
- Shell commands require explicit checkbox approval in UI.
- Shell commands are filtered by allowed prefixes (`LOCAL_SHELL_ALLOWLIST`).
- Shell command chaining chars (`;`, `&`, `|`, `>`, `<`, backtick, newline)
  are blocked.

## Notes

- API key is never shown in UI.
- Shared `runpod_api_key.obf` is obfuscation, not strong encryption.
- Use folder permissions as primary protection.
