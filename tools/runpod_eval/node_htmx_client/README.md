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

## Per-User Behavior

At first launch, each user gets local files under:
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod-htmx.env`
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod_api_key.dpapi`

`start.bat` behavior:
- Copies `.env.example` to per-user env if needed.
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

## Notes

- API key is never shown in UI.
- Shared `runpod_api_key.obf` is obfuscation, not strong encryption.
- Use folder permissions as primary protection.
