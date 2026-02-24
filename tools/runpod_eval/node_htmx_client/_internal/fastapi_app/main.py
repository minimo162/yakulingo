import asyncio
from datetime import datetime
import html
import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Optional
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.templating import Jinja2Templates


def _get_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _get_enum_env(name: str, default: str, allowed: set[str]) -> str:
    raw = (os.getenv(name, "") or "").strip().lower()
    if raw in allowed:
        return raw
    return default


def _get_bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parents[2]
INTERNAL_DIR = BASE_DIR / "_internal"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

ENGINE_BIND = os.getenv("ENGINE_BIND", "127.0.0.1").strip() or "127.0.0.1"
ENGINE_PORT = int(os.getenv("ENGINE_PORT", "3031").strip() or "3031")
ENGINE_BASE_URL = f"http://{ENGINE_BIND}:{ENGINE_PORT}"
ENGINE_HEALTH_URL = f"{ENGINE_BASE_URL}/health"

NODE_BIN = (os.getenv("NODE_BIN", "") or "").strip()
ENGINE_SCRIPT = INTERNAL_DIR / "server.mjs"

REQUESTED_AGENT_BACKEND = (os.getenv("AGENT_BACKEND", "") or "").strip().lower()
# This app now always uses Codex CLI for generation.
AGENT_BACKEND = "codex_cli"

APP_NAME = "LocaLingo"
APP_TIME_ZONE = (os.getenv("APP_TIME_ZONE", "Asia/Tokyo") or "Asia/Tokyo").strip()
DEFAULT_MODEL = (os.getenv("DEFAULT_MODEL", "gpt-oss-swallow-120b-iq4xs") or "gpt-oss-swallow-120b-iq4xs").strip()
# Codex exec model defaults to the actual RunPod/LM Studio model ID.
# (can be overridden explicitly via CODEX_EXEC_MODEL when needed)
CODEX_EXEC_MODEL = (os.getenv("CODEX_EXEC_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL).strip()
RUNPOD_BASE_URL = (os.getenv("RUNPOD_BASE_URL", "") or "").strip().rstrip("/")
RUNPOD_API_KEY = (os.getenv("RUNPOD_API_KEY", "") or "").strip()
RUNPOD_BASE_URL_CANDIDATES_RAW = (os.getenv("RUNPOD_BASE_URL_CANDIDATES", "") or "").strip()
RUNPOD_ROUTE_PROBE_ENABLED = _get_bool_env("RUNPOD_ROUTE_PROBE_ENABLED", True)
RUNPOD_ROUTE_PROBE_TIMEOUT_MS = _get_int_env(
    "RUNPOD_ROUTE_PROBE_TIMEOUT_MS",
    6000,
    minimum=1000,
    maximum=60000,
)
RUNPOD_ROUTE_COOLDOWN_SEC = _get_int_env(
    "RUNPOD_ROUTE_COOLDOWN_SEC",
    90,
    minimum=0,
    maximum=3600,
)
RUNPOD_RESPONSES_BACKGROUND_ENABLED = _get_bool_env(
    "RUNPOD_RESPONSES_BACKGROUND_ENABLED",
    True,
)
RUNPOD_RESPONSES_POLL_INTERVAL_MS = _get_int_env(
    "RUNPOD_RESPONSES_POLL_INTERVAL_MS",
    1500,
    minimum=200,
    maximum=10000,
)
RUNPOD_RESPONSES_POLL_TIMEOUT_MS = _get_int_env(
    "RUNPOD_RESPONSES_POLL_TIMEOUT_MS",
    90000,
    minimum=5000,
    maximum=600000,
)
RUNPOD_RESPONSES_TOOLS_ENABLED = _get_bool_env("RUNPOD_RESPONSES_TOOLS_ENABLED", True)
RUNPOD_RESPONSES_TOOL_TYPES_RAW = (os.getenv("RUNPOD_RESPONSES_TOOL_TYPES", "") or "").strip()
RUNPOD_RESPONSES_FUNCTION_TOOLS_JSON = (
    os.getenv("RUNPOD_RESPONSES_FUNCTION_TOOLS_JSON", "") or ""
).strip()
RUNPOD_RESPONSES_MCP_TOOLS_JSON = (
    os.getenv("RUNPOD_RESPONSES_MCP_TOOLS_JSON", "") or ""
).strip()
RUNPOD_RESPONSES_TOOL_CHOICE = _get_enum_env(
    "RUNPOD_RESPONSES_TOOL_CHOICE",
    "auto",
    {"none", "auto", "required"},
)
RUNPOD_RESPONSES_LIVE_WEB_TOOL_CHOICE = _get_enum_env(
    "RUNPOD_RESPONSES_LIVE_WEB_TOOL_CHOICE",
    "auto",
    {"inherit", "none", "auto", "required"},
)
RUNPOD_RESPONSES_REQUIRE_TOOL_FOR_LIVE_WEB = _get_bool_env(
    "RUNPOD_RESPONSES_REQUIRE_TOOL_FOR_LIVE_WEB",
    True,
)
RUNPOD_RESPONSES_HARD_FAIL_ON_MISSING_TOOL = _get_bool_env(
    "RUNPOD_RESPONSES_HARD_FAIL_ON_MISSING_TOOL",
    False,
)
RUNPOD_LMSTUDIO_CHAT_PLUGIN_ENABLED = _get_bool_env(
    "RUNPOD_LMSTUDIO_CHAT_PLUGIN_ENABLED",
    True,
)
RUNPOD_LMSTUDIO_CHAT_PLUGIN_FOR_LIVE_WEB_ONLY = _get_bool_env(
    "RUNPOD_LMSTUDIO_CHAT_PLUGIN_FOR_LIVE_WEB_ONLY",
    True,
)
RUNPOD_LMSTUDIO_CHAT_PLUGIN_ID = (
    os.getenv("RUNPOD_LMSTUDIO_CHAT_PLUGIN_ID", "mcp/playwright") or "mcp/playwright"
).strip()
RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_FALLBACK_ENABLED = _get_bool_env(
    "RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_FALLBACK_ENABLED",
    True,
)
RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_PRIMARY = _get_bool_env(
    "RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_PRIMARY",
    True,
)
RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_URL = (
    os.getenv("RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_URL", "http://localhost:8931/mcp")
    or "http://localhost:8931/mcp"
).strip()
RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_LABEL = (
    os.getenv("RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_LABEL", "playwright")
    or "playwright"
).strip()
RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_ALLOWED_TOOLS_RAW = (
    os.getenv(
        "RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_ALLOWED_TOOLS",
        "browser_navigate,browser_snapshot,browser_click,browser_type,browser_wait_for",
    )
    or ""
).strip()
RUNPOD_TLS_VERIFY = _get_bool_env("RUNPOD_TLS_VERIFY", True)
RUNPOD_CA_BUNDLE = (os.getenv("RUNPOD_CA_BUNDLE", "") or "").strip()
RUNPOD_TLS_USE_SYSTEM_STORE = _get_bool_env("RUNPOD_TLS_USE_SYSTEM_STORE", True)
RUNPOD_TLS_RETRY_NO_VERIFY = _get_bool_env("RUNPOD_TLS_RETRY_NO_VERIFY", False)
WORKSPACE_ROOT_ENV = (os.getenv("WORKSPACE_ROOT", "") or "").strip()
WORKSPACE_STATE_FILE = (os.getenv("WORKSPACE_STATE_FILE", "") or "").strip()
CODEX_BIN = (os.getenv("CODEX_BIN", "") or "").strip()
BUNDLED_CODEX_BIN = (os.getenv("BUNDLED_CODEX_BIN", "") or "").strip()
CODEX_REQUIRE_BUNDLED = _get_bool_env("CODEX_REQUIRE_BUNDLED", True)
CODEX_BUNDLED_PACKAGE = (os.getenv("CODEX_BUNDLED_PACKAGE", "@openai/codex@latest") or "@openai/codex@latest").strip()
CODEX_HOME_ENV = (os.getenv("CODEX_HOME", "") or "").strip()
CODEX_EXEC_TIMEOUT_SEC = max(30, int((os.getenv("CODEX_EXEC_TIMEOUT_SEC", "900") or "900").strip() or "900"))
CODEX_NATIVE_MODE_RAW = (os.getenv("CODEX_NATIVE_MODE", "") or "").strip()
CODEX_NATIVE_MODE = _get_bool_env("CODEX_NATIVE_MODE", False)
CODEX_EXEC_ROUTE_MODE_RAW = (os.getenv("CODEX_EXEC_ROUTE_MODE", "") or "").strip().lower()
_CODEX_EXEC_ROUTE_MODE_ALLOWED = {"native", "resilient", "background_poll"}
if CODEX_EXEC_ROUTE_MODE_RAW in _CODEX_EXEC_ROUTE_MODE_ALLOWED:
    CODEX_EXEC_ROUTE_MODE = CODEX_EXEC_ROUTE_MODE_RAW
elif CODEX_NATIVE_MODE_RAW:
    CODEX_EXEC_ROUTE_MODE = "native" if CODEX_NATIVE_MODE else "resilient"
else:
    CODEX_EXEC_ROUTE_MODE = "background_poll"
CODEX_FULL_AUTO = str(os.getenv("CODEX_FULL_AUTO", "1")).strip().lower() in {"1", "true", "yes", "on"}
CODEX_SKIP_GIT_REPO_CHECK = str(os.getenv("CODEX_SKIP_GIT_REPO_CHECK", "1")).strip().lower() in {"1", "true", "yes", "on"}
CODEX_DANGEROUS_BYPASS = str(os.getenv("CODEX_DANGEROUS_BYPASS", "0")).strip().lower() in {"1", "true", "yes", "on"}
CODEX_EXTRA_ARGS = (os.getenv("CODEX_EXTRA_ARGS", "") or "").strip()
CODEX_PROVIDER_REQUEST_MAX_RETRIES = _get_int_env(
    "CODEX_PROVIDER_REQUEST_MAX_RETRIES",
    1,
    minimum=0,
    maximum=100,
)
CODEX_PROVIDER_STREAM_MAX_RETRIES = _get_int_env(
    "CODEX_PROVIDER_STREAM_MAX_RETRIES",
    1,
    minimum=0,
    maximum=100,
)
CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS = _get_int_env(
    "CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS",
    45000,
    minimum=5000,
    maximum=600000,
)
CODEX_MODEL_CONTEXT_WINDOW = _get_int_env(
    "CODEX_MODEL_CONTEXT_WINDOW",
    32768,
    minimum=1024,
    maximum=2000000,
)
CODEX_PROJECT_DOC_MAX_BYTES = _get_int_env(
    "CODEX_PROJECT_DOC_MAX_BYTES",
    0,
    minimum=0,
    maximum=1048576,
)
CODEX_MINIMAL_MODEL_INSTRUCTIONS = _get_bool_env(
    "CODEX_MINIMAL_MODEL_INSTRUCTIONS",
    False,
)
CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE = (os.getenv("CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE", "") or "").strip()
CODEX_MODEL_REASONING_EFFORT = _get_enum_env(
    "CODEX_MODEL_REASONING_EFFORT",
    "minimal",
    {"none", "minimal", "low", "medium", "high", "xhigh"},
)
CODEX_MODEL_REASONING_SUMMARY = _get_enum_env(
    "CODEX_MODEL_REASONING_SUMMARY",
    "auto",
    {"none", "auto", "concise", "detailed"},
)
CODEX_MODEL_VERBOSITY = _get_enum_env(
    "CODEX_MODEL_VERBOSITY",
    "low",
    {"low", "medium", "high"},
)
CODEX_WEB_SEARCH_MODE = _get_enum_env(
    "CODEX_WEB_SEARCH_MODE",
    "live",
    {"disabled", "cached", "live"},
)
CODEX_TOOL_FALLBACK_TO_ENGINE = _get_bool_env(
    "CODEX_TOOL_FALLBACK_TO_ENGINE",
    True,
)
CODEX_TOOL_FALLBACK_FORCE_FOR_LIVE_WEB = _get_bool_env(
    "CODEX_TOOL_FALLBACK_FORCE_FOR_LIVE_WEB",
    True,
)
CODEX_PROMPT_MAX_CHARS = _get_int_env(
    "CODEX_PROMPT_MAX_CHARS",
    12000,
    minimum=512,
    maximum=200000,
)
CODEX_PROMPT_COMPRESSION_ENABLED = _get_bool_env(
    "CODEX_PROMPT_COMPRESSION_ENABLED",
    True,
)
CODEX_PROMPT_COMPRESSION_TRIGGER_CHARS = _get_int_env(
    "CODEX_PROMPT_COMPRESSION_TRIGGER_CHARS",
    9000,
    minimum=512,
    maximum=200000,
)
CODEX_PROMPT_COMPRESSION_TARGET_CHARS = _get_int_env(
    "CODEX_PROMPT_COMPRESSION_TARGET_CHARS",
    7600,
    minimum=512,
    maximum=200000,
)
CODEX_PROMPT_KEEP_HEAD_CHARS = _get_int_env(
    "CODEX_PROMPT_KEEP_HEAD_CHARS",
    2400,
    minimum=256,
    maximum=50000,
)
CODEX_PROMPT_KEEP_TAIL_CHARS = _get_int_env(
    "CODEX_PROMPT_KEEP_TAIL_CHARS",
    3200,
    minimum=256,
    maximum=50000,
)
CODEX_PROMPT_KEY_LINES_LIMIT = _get_int_env(
    "CODEX_PROMPT_KEY_LINES_LIMIT",
    40,
    minimum=0,
    maximum=200,
)
CODEX_EXEC_PROGRESS_PING_INTERVAL_MS = _get_int_env(
    "CODEX_EXEC_PROGRESS_PING_INTERVAL_MS",
    8000,
    minimum=2000,
    maximum=60000,
)
CODEX_EXEC_RETRY_MAX_ATTEMPTS = _get_int_env(
    "CODEX_EXEC_RETRY_MAX_ATTEMPTS",
    3,
    minimum=1,
    maximum=8,
)
CODEX_EXEC_RETRY_BASE_DELAY_MS = _get_int_env(
    "CODEX_EXEC_RETRY_BASE_DELAY_MS",
    800,
    minimum=100,
    maximum=30000,
)
CODEX_EXEC_RETRY_MAX_DELAY_MS = _get_int_env(
    "CODEX_EXEC_RETRY_MAX_DELAY_MS",
    4000,
    minimum=500,
    maximum=120000,
)
CODEX_STREAM_RECOVERY_FALLBACK_ENABLED = _get_bool_env(
    "CODEX_STREAM_RECOVERY_FALLBACK_ENABLED",
    True,
)
CODEX_STREAM_RECOVERY_TIMEOUT_MS = _get_int_env(
    "CODEX_STREAM_RECOVERY_TIMEOUT_MS",
    90000,
    minimum=5000,
    maximum=600000,
)
CODEX_LMSTUDIO_PROVIDER_ID = (
    os.getenv("CODEX_LMSTUDIO_PROVIDER_ID", "lmstudio-runpod") or "lmstudio-runpod"
).strip()

app = FastAPI(title=APP_NAME, version="2.1-fastapi-codex")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_engine_proc: Optional[subprocess.Popen] = None

MINIMAL_MODEL_INSTRUCTIONS_TEXT = (
    "You are Codex.\n"
    "You are running against an OpenAI-compatible Responses API endpoint.\n"
    "Be concise, accurate, and keep focus on the user's latest request.\n"
    "Use tools when needed, and preserve context across turns.\n"
    "Do not expose internal planning, tool selection rationale, or sandbox details.\n"
    "Do not mention AGENTS.md or skill names unless the user explicitly asks.\n"
    "If the user asks time-sensitive questions (today/latest/now), verify recency.\n"
)


def _normalize_base_url(raw_url: str) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""
    return value


def _build_runpod_base_url_candidates() -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()

    def add(raw_value: str) -> None:
        normalized = _normalize_base_url(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        rows.append(normalized)

    add(RUNPOD_BASE_URL)
    if RUNPOD_BASE_URL_CANDIDATES_RAW:
        normalized_rows = RUNPOD_BASE_URL_CANDIDATES_RAW.replace(";", ",").replace("\n", ",")
        for item in normalized_rows.split(","):
            add(item)
    return rows


RUNPOD_BASE_URL_CANDIDATES = _build_runpod_base_url_candidates()
_RUNPOD_ROUTE_STATE: dict[str, dict[str, float | str]] = {
    row: {"cooldown_until": 0.0, "last_error": ""} for row in RUNPOD_BASE_URL_CANDIDATES
}


def _route_status_label(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
        path = parsed.path or ""
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    except Exception:
        return base_url


def _runpod_httpx_verify_setting() -> bool | str | ssl.SSLContext:
    if not RUNPOD_TLS_VERIFY:
        return False
    if RUNPOD_CA_BUNDLE:
        path = Path(RUNPOD_CA_BUNDLE).expanduser()
        if path.exists():
            try:
                return ssl.create_default_context(cafile=str(path))
            except Exception:
                return str(path)
    if RUNPOD_TLS_USE_SYSTEM_STORE:
        try:
            import truststore  # type: ignore

            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            # Fallback to stdlib system default certificates.
            return ssl.create_default_context()
    return True


def _has_proxy_env() -> bool:
    keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    return any(bool((os.getenv(k, "") or "").strip()) for k in keys)


def _looks_like_tls_verify_failure(exc: Exception | str) -> bool:
    text = str(exc or "").lower()
    markers = (
        "certificate verify failed",
        "unable to get local issuer certificate",
        "self-signed certificate",
        "ssl: cert",
    )
    return any(marker in text for marker in markers)


def _runpod_auth_headers(*, include_content_type: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    token = str(RUNPOD_API_KEY or "").strip()
    if token:
        headers["x-api-key"] = token
        headers["authorization"] = f"Bearer {token}"
    if include_content_type:
        headers["content-type"] = "application/json"
    return headers


def _mark_runpod_route_success(base_url: str) -> None:
    if not base_url:
        return
    state = _RUNPOD_ROUTE_STATE.setdefault(base_url, {"cooldown_until": 0.0, "last_error": ""})
    state["cooldown_until"] = 0.0
    state["last_error"] = ""


def _mark_runpod_route_failure(base_url: str, reason: str) -> None:
    if not base_url:
        return
    state = _RUNPOD_ROUTE_STATE.setdefault(base_url, {"cooldown_until": 0.0, "last_error": ""})
    cooldown_until = time.monotonic() + max(0, RUNPOD_ROUTE_COOLDOWN_SEC)
    state["cooldown_until"] = cooldown_until
    state["last_error"] = str(reason or "").strip()[:400]


async def _probe_runpod_base_url(base_url: str) -> tuple[bool, str]:
    if not RUNPOD_ROUTE_PROBE_ENABLED:
        return True, ""
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return False, "invalid base url"
    probe_url = f"{normalized}/models"
    headers = _runpod_auth_headers()
    timeout_sec = max(1.0, RUNPOD_ROUTE_PROBE_TIMEOUT_MS / 1000.0)
    timeout = httpx.Timeout(connect=timeout_sec, read=timeout_sec, write=timeout_sec, pool=timeout_sec)
    verify_setting = _runpod_httpx_verify_setting()
    try:
        # Bypass OS proxy env for RunPod direct calls; proxy interception often breaks auth/TLS.
        async with httpx.AsyncClient(timeout=timeout, verify=verify_setting, trust_env=False) as client:
            response = await client.get(probe_url, headers=headers)
        if 200 <= response.status_code < 500:
            return True, ""
        return False, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)


async def _select_runpod_base_url(attempt_index: int = 1) -> str:
    candidates = RUNPOD_BASE_URL_CANDIDATES[:]
    if not candidates:
        return _normalize_base_url(RUNPOD_BASE_URL)

    start_index = 0
    if candidates:
        start_index = max(0, attempt_index - 1) % len(candidates)
    ordered = candidates[start_index:] + candidates[:start_index]
    now = time.monotonic()
    deferred: list[str] = []

    for base_url in ordered:
        state = _RUNPOD_ROUTE_STATE.setdefault(base_url, {"cooldown_until": 0.0, "last_error": ""})
        cooldown_until = float(state.get("cooldown_until", 0.0) or 0.0)
        if cooldown_until > now:
            deferred.append(base_url)
            continue
        ok, err = await _probe_runpod_base_url(base_url)
        if ok:
            _mark_runpod_route_success(base_url)
            return base_url
        _mark_runpod_route_failure(base_url, err)
        deferred.append(base_url)

    if deferred:
        return deferred[0]
    return ordered[0]


def _runpod_route_fallback_order(preferred_base_url: str) -> list[str]:
    candidates = RUNPOD_BASE_URL_CANDIDATES[:]
    normalized_preferred = _normalize_base_url(preferred_base_url)
    if normalized_preferred and normalized_preferred not in candidates:
        candidates.insert(0, normalized_preferred)
    if not candidates:
        return [normalized_preferred] if normalized_preferred else []
    if normalized_preferred and normalized_preferred in candidates:
        index = candidates.index(normalized_preferred)
        return candidates[index:] + candidates[:index]
    return candidates


def _build_engine_env() -> dict:
    env = dict(os.environ)
    env["APP_BIND"] = ENGINE_BIND
    env["APP_PORT"] = str(ENGINE_PORT)
    return env


def _escape_html(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_user_turn(prompt: str) -> str:
    return (
        '<article class="turn turn-user border border-slate-200 rounded-lg p-3 bg-white">'
        '<header class="turn-header font-semibold text-slate-700 mb-1">You</header>'
        f'<pre class="turn-body text-xs whitespace-pre-wrap break-words">{_escape_html(prompt)}</pre>'
        "</article>"
    )


def _render_assistant_turn(text: str, model: str, elapsed_ms: int) -> str:
    return (
        '<article class="turn turn-assistant border border-slate-200 rounded-lg p-3 bg-slate-50">'
        f'<header class="turn-header font-semibold text-slate-700 mb-1">LocaLingo ({_escape_html(model)})</header>'
        f'<pre class="turn-body text-xs whitespace-pre-wrap break-words">{_escape_html(text)}</pre>'
        f'<footer class="turn-footer text-[11px] text-slate-500 mt-2">{elapsed_ms} ms</footer>'
        "</article>"
    )


def _render_tool_card(title: str, body: str, meta: str = "", is_error: bool = False) -> str:
    if is_error:
        base_cls = "turn turn-error border border-rose-200 rounded-lg p-3 bg-rose-50"
        title_cls = "turn-header font-semibold text-rose-700 mb-1"
        meta_cls = "turn-meta text-[11px] text-rose-600 mb-1"
    else:
        base_cls = "turn turn-tool border border-sky-200 rounded-lg p-3 bg-sky-50"
        title_cls = "turn-header font-semibold text-sky-800 mb-1"
        meta_cls = "turn-meta text-[11px] text-sky-700 mb-1"
    parts = [f'<article class="{base_cls}">', f'<header class="{title_cls}">{_escape_html(title)}</header>']
    if meta:
        parts.append(f'<div class="{meta_cls}">{_escape_html(meta)}</div>')
    parts.append(f'<pre class="turn-body text-xs whitespace-pre-wrap break-words">{_escape_html(body)}</pre>')
    parts.append("</article>")
    return "".join(parts)


def _parse_form_urlencoded(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    out: dict[str, str] = {}
    for key, values in parsed.items():
        if not values:
            out[key] = ""
        else:
            out[key] = values[-1]
    return out


def _resolve_workspace_state_file() -> Path:
    if WORKSPACE_STATE_FILE:
        return Path(WORKSPACE_STATE_FILE).expanduser()
    local_app_data = (os.getenv("LOCALAPPDATA", "") or "").strip()
    if local_app_data:
        return Path(local_app_data) / "YakuLingoRunpodHtmx" / "workspace-state.json"
    return Path.home() / ".local" / "state" / "localingo" / "workspace-state.json"


def _resolve_workspace_root_for_agent() -> Path:
    state_file = _resolve_workspace_state_file()
    try:
        if state_file.exists():
            payload = json.loads(state_file.read_text(encoding="utf-8"))
            candidate = str(payload.get("workspaceRoot", "") or "").strip()
            if candidate:
                root = Path(candidate).expanduser().resolve()
                root.mkdir(parents=True, exist_ok=True)
                return root
    except Exception:
        pass

    if WORKSPACE_ROOT_ENV:
        root = Path(WORKSPACE_ROOT_ENV).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    fallback = (BASE_DIR / "workspace").resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _resolve_codex_home() -> Path:
    if CODEX_HOME_ENV:
        codex_home = Path(CODEX_HOME_ENV).expanduser().resolve()
    else:
        local_app_data = (os.getenv("LOCALAPPDATA", "") or "").strip()
        if local_app_data:
            codex_home = (Path(local_app_data) / "YakuLingoRunpodHtmx" / "codex-home").resolve()
        else:
            codex_home = (Path.home() / ".codex").resolve()
    codex_home.mkdir(parents=True, exist_ok=True)
    return codex_home


def _toml_quote(value: str) -> str:
    return json.dumps(str(value))


def _resolve_minimal_model_instructions_path(codex_home: Path) -> Path:
    if CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE:
        path = Path(CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE).expanduser()
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        return path
    return (codex_home / "model_instructions.min.md").resolve()


def _resolve_model_catalog_path(codex_home: Path) -> Path:
    return (codex_home / "model_catalog.runpod.json").resolve()


def _build_runpod_model_catalog_payload(
    *,
    model: str,
    context_window: int,
) -> dict:
    # Provide explicit metadata for custom RunPod model IDs so codex CLI does
    # not fall back to unknown-model defaults.
    safe_context_window = max(2048, int(context_window or 32768))
    auto_compact = max(1024, int(safe_context_window * 0.9))
    return {
        "models": [
            {
                "slug": model,
                "display_name": model,
                "description": "RunPod custom model",
                "default_reasoning_level": "medium",
                "supported_reasoning_levels": [
                    {"effort": "low", "description": "Low"},
                    {"effort": "medium", "description": "Medium"},
                    {"effort": "high", "description": "High"},
                ],
                "shell_type": "default",
                "visibility": "list",
                "supported_in_api": True,
                "priority": 1,
                "upgrade": None,
                "base_instructions": MINIMAL_MODEL_INSTRUCTIONS_TEXT.strip(),
                "model_messages": None,
                "supports_reasoning_summaries": False,
                "support_verbosity": False,
                "default_verbosity": None,
                "apply_patch_tool_type": None,
                "truncation_policy": {"mode": "bytes", "limit": 10000},
                "supports_parallel_tool_calls": False,
                "context_window": safe_context_window,
                "auto_compact_token_limit": auto_compact,
                "effective_context_window_percent": 95,
                "experimental_supported_tools": [],
                "input_modalities": ["text"],
                "prefer_websockets": False,
            }
        ]
    }


def _ensure_model_catalog_file(
    codex_home: Path,
    *,
    model: str,
    context_window: int,
) -> Path:
    path = _resolve_model_catalog_path(codex_home)
    payload = _build_runpod_model_catalog_payload(
        model=model,
        context_window=context_window,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    current = ""
    if path.exists():
        try:
            current = path.read_text(encoding="utf-8")
        except Exception:
            current = ""
    if current != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path


def _ensure_minimal_model_instructions_file(codex_home: Path) -> Optional[Path]:
    if not CODEX_MINIMAL_MODEL_INSTRUCTIONS:
        return None
    path = _resolve_minimal_model_instructions_path(codex_home)
    if CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE:
        if not path.exists():
            raise RuntimeError(
                "CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE is set but file does not exist: "
                f"{path}"
            )
        return path
    text = MINIMAL_MODEL_INSTRUCTIONS_TEXT.strip() + "\n"
    current = ""
    if path.exists():
        try:
            current = path.read_text(encoding="utf-8")
        except Exception:
            current = ""
    if current != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path


def _ensure_codex_config(
    codex_home: Path,
    profile: Optional[dict[str, int | str]] = None,
    *,
    base_url: str = "",
) -> Path:
    default_base_url = _normalize_base_url(RUNPOD_BASE_URL)
    if (not default_base_url) and RUNPOD_BASE_URL_CANDIDATES:
        default_base_url = RUNPOD_BASE_URL_CANDIDATES[0]
    resolved_base_url = _normalize_base_url(base_url) or default_base_url
    if not resolved_base_url:
        raise RuntimeError("RUNPOD_BASE_URL is empty. Set it before using codex_cli backend.")
    if not RUNPOD_API_KEY:
        raise RuntimeError("RUNPOD_API_KEY is empty. Set it before using codex_cli backend.")

    config_path = codex_home / "config.toml"
    profile = profile or {}
    model = CODEX_EXEC_MODEL or DEFAULT_MODEL
    model_context_window = int(profile.get("model_context_window", CODEX_MODEL_CONTEXT_WINDOW))
    project_doc_max_bytes = int(profile.get("project_doc_max_bytes", CODEX_PROJECT_DOC_MAX_BYTES))
    request_max_retries = int(profile.get("request_max_retries", CODEX_PROVIDER_REQUEST_MAX_RETRIES))
    stream_max_retries = int(profile.get("stream_max_retries", CODEX_PROVIDER_STREAM_MAX_RETRIES))
    stream_idle_timeout_ms = int(profile.get("stream_idle_timeout_ms", CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS))
    model_reasoning_effort = str(profile.get("model_reasoning_effort", CODEX_MODEL_REASONING_EFFORT) or "").strip().lower()
    model_reasoning_summary = str(profile.get("model_reasoning_summary", CODEX_MODEL_REASONING_SUMMARY) or "").strip().lower()
    model_verbosity = str(profile.get("model_verbosity", CODEX_MODEL_VERBOSITY) or "").strip().lower()
    web_search_mode = str(profile.get("web_search_mode", CODEX_WEB_SEARCH_MODE) or CODEX_WEB_SEARCH_MODE).strip().lower()
    model_instructions_file = _ensure_minimal_model_instructions_file(codex_home)
    model_catalog_file = _ensure_model_catalog_file(
        codex_home,
        model=model,
        context_window=model_context_window,
    )
    if model_reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        model_reasoning_effort = CODEX_MODEL_REASONING_EFFORT
    if model_reasoning_summary not in {"none", "auto", "concise", "detailed"}:
        model_reasoning_summary = CODEX_MODEL_REASONING_SUMMARY
    if model_verbosity not in {"low", "medium", "high"}:
        model_verbosity = ""
    if web_search_mode not in {"disabled", "cached", "live"}:
        web_search_mode = CODEX_WEB_SEARCH_MODE
    provider_id = str(CODEX_LMSTUDIO_PROVIDER_ID or "lmstudio-runpod").strip()
    if not provider_id:
        provider_id = "lmstudio-runpod"
    normalized_model_slug = re.sub(r"[^a-z0-9_-]+", "-", model.lower()).strip("-")
    if not normalized_model_slug:
        normalized_model_slug = "default"
    profile_name = f"runpod-{normalized_model_slug}"
    config_text = "\n".join(
        [
            f"profile = {_toml_quote(profile_name)}",
            f"model = {_toml_quote(model)}",
            f"model_provider = {_toml_quote(provider_id)}",
            "oss_provider = \"lmstudio\"",
            f"model_context_window = {model_context_window}",
            f"model_reasoning_effort = {_toml_quote(model_reasoning_effort)}",
            f"model_reasoning_summary = {_toml_quote(model_reasoning_summary)}",
            *([f"model_verbosity = {_toml_quote(model_verbosity)}"] if model_verbosity else []),
            f"web_search = {_toml_quote(web_search_mode)}",
            *([f"model_instructions_file = {_toml_quote(str(model_instructions_file))}"] if model_instructions_file else []),
            f"model_catalog_json = {_toml_quote(str(model_catalog_file))}",
            f"project_doc_max_bytes = {project_doc_max_bytes}",
            "",
            f"[model_providers.{provider_id}]",
            "name = \"LM Studio (RunPod)\"",
            f"base_url = {_toml_quote(resolved_base_url)}",
            "wire_api = \"responses\"",
            "requires_openai_auth = false",
            f"request_max_retries = {request_max_retries}",
            f"stream_max_retries = {stream_max_retries}",
            f"stream_idle_timeout_ms = {stream_idle_timeout_ms}",
            'env_http_headers = { "x-api-key" = "RUNPOD_API_KEY" }',
            "",
            f"[profiles.{profile_name}]",
            f"model = {_toml_quote(model)}",
            f"model_provider = {_toml_quote(provider_id)}",
            "",
        ]
    )
    current = ""
    if config_path.exists():
        try:
            current = config_path.read_text(encoding="utf-8")
        except Exception:
            current = ""
    if current != config_text:
        config_path.write_text(config_text, encoding="utf-8")
    return config_path


def _build_codex_exec_retry_profiles() -> list[dict[str, int | str]]:
    base_profile: dict[str, int | str] = {
        "model_context_window": CODEX_MODEL_CONTEXT_WINDOW,
        "project_doc_max_bytes": CODEX_PROJECT_DOC_MAX_BYTES,
        "request_max_retries": CODEX_PROVIDER_REQUEST_MAX_RETRIES,
        "stream_max_retries": max(0, CODEX_PROVIDER_STREAM_MAX_RETRIES),
        # Long prompts may delay first token. Keep first-pass idle timeout relaxed.
        "stream_idle_timeout_ms": max(CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS, 90000),
        "model_reasoning_effort": CODEX_MODEL_REASONING_EFFORT,
        "model_reasoning_summary": CODEX_MODEL_REASONING_SUMMARY,
        "model_verbosity": CODEX_MODEL_VERBOSITY,
        "web_search_mode": CODEX_WEB_SEARCH_MODE,
    }
    profiles = [base_profile]
    if CODEX_EXEC_RETRY_MAX_ATTEMPTS >= 2:
        profiles.append(
            {
                **base_profile,
                "request_max_retries": 0,
                "stream_max_retries": 0,
                "stream_idle_timeout_ms": min(CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS, 20000),
                "project_doc_max_bytes": min(CODEX_PROJECT_DOC_MAX_BYTES, 2048),
                "model_verbosity": "",
            }
        )
    if CODEX_EXEC_RETRY_MAX_ATTEMPTS >= 3:
        profiles.append(
            {
                **base_profile,
                "request_max_retries": 0,
                "stream_max_retries": 0,
                "stream_idle_timeout_ms": min(CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS, 12000),
                "project_doc_max_bytes": 0,
                "model_context_window": min(CODEX_MODEL_CONTEXT_WINDOW, 16384),
                "model_reasoning_effort": "none",
                "model_reasoning_summary": "auto",
                "model_verbosity": "",
            }
        )
    while len(profiles) < CODEX_EXEC_RETRY_MAX_ATTEMPTS:
        profiles.append(dict(profiles[-1]))
    return profiles[:CODEX_EXEC_RETRY_MAX_ATTEMPTS]


def _resolve_bundled_codex_command() -> list[str]:
    candidates: list[Path] = []
    if BUNDLED_CODEX_BIN:
        candidates.append(Path(BUNDLED_CODEX_BIN).expanduser())
    runtime_candidates = [
        BASE_DIR / ".runtime" / "codex" / "node_modules" / ".bin" / "codex.cmd",
        BASE_DIR / ".runtime" / "codex" / "node_modules" / ".bin" / "codex.ps1",
        BASE_DIR / ".runtime" / "codex" / "node_modules" / ".bin" / "codex",
    ]
    candidates.extend(runtime_candidates)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved.exists():
            return [str(resolved)]
    return []


def _resolve_codex_command() -> list[str]:
    bundled = _resolve_bundled_codex_command()
    if bundled:
        return bundled
    if CODEX_REQUIRE_BUNDLED:
        raise RuntimeError(
            "Bundled codex CLI was not found. Run _internal/prepare-node-runtime.ps1 "
            f"(package: {CODEX_BUNDLED_PACKAGE})."
        )

    if CODEX_BIN:
        explicit = Path(CODEX_BIN).expanduser()
        if explicit.exists():
            return [str(explicit)]
        raise RuntimeError(f"CODEX_BIN is set but file does not exist: {explicit}")

    codex_path = shutil.which("codex")
    if codex_path:
        return [codex_path]

    node_bin = (os.getenv("NODE_BIN", "") or "").strip()
    if node_bin:
        npx_cli_js = Path(node_bin).resolve().parent / "node_modules" / "npm" / "bin" / "npx-cli.js"
        if npx_cli_js.exists():
            return [node_bin, str(npx_cli_js), "--yes", "@openai/codex"]

    npx_path = shutil.which("npx") or shutil.which("npx.cmd")
    if npx_path:
        return [npx_path, "--yes", "@openai/codex"]

    raise RuntimeError(
        "codex CLI was not found. Install bundled codex or set CODEX_REQUIRE_BUNDLED=0 to allow PATH fallback."
    )


def _build_codex_exec_config_overrides(profile: dict[str, int | str], codex_home: Path) -> list[str]:
    overrides: list[str] = []
    model_context_window = int(profile.get("model_context_window", CODEX_MODEL_CONTEXT_WINDOW))
    project_doc_max_bytes = int(profile.get("project_doc_max_bytes", CODEX_PROJECT_DOC_MAX_BYTES))
    model_reasoning_effort = str(profile.get("model_reasoning_effort", CODEX_MODEL_REASONING_EFFORT) or "").strip().lower()
    model_reasoning_summary = str(profile.get("model_reasoning_summary", CODEX_MODEL_REASONING_SUMMARY) or "").strip().lower()
    model_verbosity = str(profile.get("model_verbosity", CODEX_MODEL_VERBOSITY) or "").strip().lower()
    web_search_mode = str(profile.get("web_search_mode", CODEX_WEB_SEARCH_MODE) or CODEX_WEB_SEARCH_MODE).strip().lower()

    overrides.append(f"model_context_window={model_context_window}")
    overrides.append(f"project_doc_max_bytes={project_doc_max_bytes}")
    if model_reasoning_effort:
        overrides.append(f"model_reasoning_effort={_toml_quote(model_reasoning_effort)}")
    if model_reasoning_summary:
        overrides.append(f"model_reasoning_summary={_toml_quote(model_reasoning_summary)}")
    if model_verbosity:
        overrides.append(f"model_verbosity={_toml_quote(model_verbosity)}")
    if web_search_mode in {"disabled", "cached", "live"}:
        overrides.append(f"web_search={_toml_quote(web_search_mode)}")

    model_instructions_file = _ensure_minimal_model_instructions_file(codex_home)
    if model_instructions_file is not None:
        overrides.append(f"model_instructions_file={_toml_quote(str(model_instructions_file))}")

    return overrides


def _build_codex_exec_command(
    prompt: str,
    workspace_root: Path,
    output_last_message_file: Path,
    profile: dict[str, int | str],
    codex_home: Path,
) -> list[str]:
    cmd = _resolve_codex_command()
    args = ["exec", "--json"]
    if CODEX_FULL_AUTO:
        args.append("--full-auto")
    if CODEX_SKIP_GIT_REPO_CHECK:
        args.append("--skip-git-repo-check")
    if CODEX_DANGEROUS_BYPASS:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    args.extend(
        [
            "-C",
            str(workspace_root),
            "-m",
            CODEX_EXEC_MODEL,
            "--output-last-message",
            str(output_last_message_file),
        ]
    )
    for override in _build_codex_exec_config_overrides(profile=profile, codex_home=codex_home):
        args.extend(["--config", override])
    if CODEX_EXTRA_ARGS:
        try:
            args.extend(shlex.split(CODEX_EXTRA_ARGS))
        except Exception:
            pass
    args.append(prompt)
    return cmd + args


def _build_codex_env(codex_home: Path, *, base_url: str) -> dict:
    default_base_url = _normalize_base_url(RUNPOD_BASE_URL)
    if (not default_base_url) and RUNPOD_BASE_URL_CANDIDATES:
        default_base_url = RUNPOD_BASE_URL_CANDIDATES[0]
    resolved_base_url = _normalize_base_url(base_url) or default_base_url
    if not resolved_base_url:
        raise RuntimeError("RUNPOD_BASE_URL is empty. Set it before using codex_cli backend.")
    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home)
    env["RUNPOD_API_KEY"] = RUNPOD_API_KEY
    env["OPENAI_BASE_URL"] = resolved_base_url
    # Keep this for compatibility with providers that still look at OPENAI_API_KEY.
    if RUNPOD_API_KEY and "OPENAI_API_KEY" not in env:
        env["OPENAI_API_KEY"] = RUNPOD_API_KEY
    return env


def _squeeze_text_middle(text: str, max_chars: int) -> str:
    value = str(text or "")
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    marker = "\n...[snip]...\n"
    if max_chars <= len(marker) + 32:
        return value[:max_chars]
    head_len = (max_chars - len(marker)) // 2
    tail_len = max_chars - len(marker) - head_len
    return f"{value[:head_len]}{marker}{value[-tail_len:]}"


def _normalize_prompt_text(prompt: str) -> str:
    value = str(prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = value.split("\n")
    compacted: list[str] = []
    blank_run = 0
    for line in lines:
        trimmed_line = line.rstrip()
        if not trimmed_line.strip():
            blank_run += 1
            if blank_run > 1:
                continue
            compacted.append("")
            continue
        blank_run = 0
        compacted.append(trimmed_line)
    return "\n".join(compacted).strip()


def _extract_priority_lines(text: str) -> list[str]:
    if CODEX_PROMPT_KEY_LINES_LIMIT <= 0:
        return []
    keywords = (
        "?",
        "requirement",
        "requirements",
        "constraint",
        "constraints",
        "objective",
        "goal",
        "latest",
        "today",
        "urgent",
        "important",
        "now",
        "must",
        "should",
        "error",
        "failed",
    )
    rows: list[str] = []
    seen: set[str] = set()
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if len(line) < 4:
            continue
        normalized_key = line.lower()
        if normalized_key in seen:
            continue
        if any(token in normalized_key for token in keywords):
            seen.add(normalized_key)
            rows.append(line)
            if len(rows) >= CODEX_PROMPT_KEY_LINES_LIMIT:
                break
    return rows


def _prepare_codex_prompt(prompt: str) -> tuple[str, dict[str, int | bool]]:
    original_prompt = str(prompt or "")
    original_len = len(original_prompt)
    normalized_prompt = _normalize_prompt_text(original_prompt)
    working = normalized_prompt if normalized_prompt else original_prompt

    info: dict[str, int | bool] = {
        "original_len": original_len,
        "normalized_len": len(working),
        "compressed": False,
        "truncated": False,
    }

    if CODEX_PROMPT_COMPRESSION_ENABLED and len(working) > CODEX_PROMPT_COMPRESSION_TRIGGER_CHARS:
        key_lines = _extract_priority_lines(working)
        head_excerpt = _squeeze_text_middle(working[:CODEX_PROMPT_KEEP_HEAD_CHARS], CODEX_PROMPT_KEEP_HEAD_CHARS)
        tail_excerpt = _squeeze_text_middle(
            working[-CODEX_PROMPT_KEEP_TAIL_CHARS:],
            CODEX_PROMPT_KEEP_TAIL_CHARS,
        )
        blocks: list[str] = [
            "[Prompt transport compaction applied]",
            f"original_chars={len(working)}",
            "Focus on latest user ask and explicit constraints.",
        ]
        if key_lines:
            blocks.append("Key directives:")
            blocks.extend(f"- {row}" for row in key_lines)
        blocks.extend(
            [
                "",
                "Head excerpt:",
                head_excerpt,
                "",
                "Tail excerpt (latest intent):",
                tail_excerpt,
            ]
        )
        working = "\n".join(blocks).strip()
        if len(working) > CODEX_PROMPT_COMPRESSION_TARGET_CHARS:
            working = _squeeze_text_middle(working, CODEX_PROMPT_COMPRESSION_TARGET_CHARS)
        info["compressed"] = True

    if len(working) > CODEX_PROMPT_MAX_CHARS:
        working = _squeeze_text_middle(working, CODEX_PROMPT_MAX_CHARS)
        if len(working) > CODEX_PROMPT_MAX_CHARS:
            working = working[:CODEX_PROMPT_MAX_CHARS]
        info["truncated"] = True

    info["prepared_len"] = len(working)
    return working, info


def _is_stream_disconnect_message(text: str) -> bool:
    normalized = str(text or "").lower()
    return (
        "stream disconnected before completion" in normalized
        or "stream closed before response.completed" in normalized
    )


def _is_empty_last_message_warning(text: str) -> bool:
    normalized = str(text or "").lower()
    return (
        "warning: no last agent message" in normalized
        and "output-last-message" in normalized
    ) or (
        "warning: no last agent message" in normalized
        and "last_message" in normalized
    )


def _is_transport_failure_message(text: str) -> bool:
    normalized = str(text or "").lower()
    transport_markers = (
        "timed out",
        "timeout",
        "econnreset",
        "connection reset",
        "connection refused",
        "broken pipe",
        "temporarily unavailable",
        "gateway",
        "service unavailable",
        "network error",
        "dns",
        "socket hang up",
        "upstream connect error",
    )
    return any(marker in normalized for marker in transport_markers)


def _prompt_likely_requires_live_web(prompt: str) -> bool:
    text = str(prompt or "").lower()
    if not text:
        return False
    markers = (
        "weather",
        "forecast",
        "latest news",
        "breaking",
        "today",
        "tomorrow",
        "current",
        "最新",
        "直近",
        "天気",
        "今日",
        "明日",
        "本日",
        "ニュース",
    )
    return any(marker in text for marker in markers)


def _looks_like_no_network_answer(text: str) -> bool:
    normalized = str(text or "").lower()
    if not normalized:
        return False
    markers = (
        "no network access",
        "cannot access the internet",
        "can't access the internet",
        "unable to query live",
        "can't fetch live",
        "sandbox that does not allow outbound network",
        "network communication is restricted",
        "ネットワーク通信が制限",
        "インターネットにアクセスでき",
        "リアルタイム",
        "取得できません",
    )
    return any(marker in normalized for marker in markers)


def _extract_turn_text_from_html(raw_html: str) -> str:
    value = str(raw_html or "")
    if not value:
        return ""
    match = re.search(
        r'<pre[^>]*class="[^"]*turn-body[^"]*"[^>]*>(.*?)</pre>',
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


async def _run_engine_tool_fallback(prompt: str) -> tuple[str, list[str], str]:
    url = f"{ENGINE_BASE_URL}/api/chat/stream"
    payload = {"prompt": prompt, "temperature": "0.6"}
    timeout = httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)
    tool_cards: list[str] = []
    deltas: list[str] = []
    assistant_text = ""
    try:
        # Internal engine is always loopback; bypass OS proxy env to avoid corporate proxy redirects.
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream("POST", url, data=payload) as res:
                if res.status_code >= 400:
                    preview = (await res.aread()).decode("utf-8", errors="replace")[:800]
                    return "", [], f"engine fallback HTTP {res.status_code}: {preview}"
                async for line in res.aiter_lines():
                    row = str(line or "").strip()
                    if not row:
                        continue
                    try:
                        event = json.loads(row)
                    except Exception:
                        continue
                    event_type = str(event.get("type", "") or "").strip().lower()
                    if event_type == "tool_card":
                        html_card = str(event.get("html", "") or "")
                        if html_card:
                            tool_cards.append(html_card)
                        continue
                    if event_type == "assistant_stream_delta":
                        delta = str(event.get("delta", "") or "")
                        if delta:
                            deltas.append(delta)
                        continue
                    if event_type == "assistant_turn":
                        text = str(event.get("text", "") or "").strip()
                        if not text:
                            text = _extract_turn_text_from_html(str(event.get("html", "") or ""))
                        if text:
                            assistant_text = text
    except Exception as exc:
        return "", [], str(exc)

    if not assistant_text and deltas:
        assistant_text = "".join(deltas).strip()
    return assistant_text, tool_cards, ""


def _compute_retry_delay_ms(attempt_index: int) -> int:
    # attempt_index is 1-based.
    raw = CODEX_EXEC_RETRY_BASE_DELAY_MS * (2 ** max(0, attempt_index - 1))
    return int(min(CODEX_EXEC_RETRY_MAX_DELAY_MS, raw))


def _extract_responses_output_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""

    # Some providers wrap the actual response payload.
    nested = payload.get("response")
    if isinstance(nested, dict):
        nested_text = _extract_responses_output_text(nested)
        if nested_text:
            return nested_text

    output_text = str(payload.get("output_text", "") or "").strip()
    if output_text:
        return output_text
    output_items = payload.get("output")
    if not isinstance(output_items, list):
        # ChatCompletions-compatible fallback (provider compatibility path).
        choices = payload.get("choices")
        if isinstance(choices, list):
            chunks: list[str] = []
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    chunks.append(content.strip())
                    continue
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, str) and block.strip():
                            chunks.append(block.strip())
                        elif isinstance(block, dict):
                            text = str(block.get("text", "") or "").strip()
                            if text:
                                chunks.append(text)
            if chunks:
                return "\n".join(chunks).strip()
        return ""

    # 1) Prefer assistant message blocks (most compatible with OpenAI-like responses).
    message_chunks: list[str] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "") or "").strip().lower() != "message":
            continue
        content = item.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text:
                message_chunks.append(text)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, str):
                text = block.strip()
                if text:
                    message_chunks.append(text)
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "") or "").strip().lower()
            if block_type in {"input_text", "reasoning_text"}:
                continue
            text = str(block.get("text", "") or "").strip()
            if text:
                message_chunks.append(text)
    if message_chunks:
        return "\n".join(message_chunks).strip()

    # 2) Fallback: generic text-like blocks.
    chunks: list[str] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text:
                chunks.append(text)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, str):
                text = block.strip()
                if text:
                    chunks.append(text)
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "") or "").strip().lower()
            if block_type in {"output_text", "text"}:
                text = str(block.get("text", "") or "").strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _extract_responses_status(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("status", "") or "").strip().lower()


def _extract_responses_id(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("id", "response_id"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _extract_lmstudio_chat_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    direct = str(payload.get("content", "") or "").strip()
    if direct:
        return direct
    output_items = payload.get("output")
    if isinstance(output_items, list):
        chunks: list[str] = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "") or "").strip().lower()
            if item_type != "message":
                continue
            content = item.get("content")
            if isinstance(content, str):
                text = content.strip()
                if text:
                    chunks.append(text)
                    continue
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        text = block.strip()
                        if text:
                            chunks.append(text)
                    elif isinstance(block, dict):
                        text = str(block.get("text", "") or "").strip()
                        if text:
                            chunks.append(text)
        if chunks:
            return "\n".join(chunks).strip()
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    chunks: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text:
                chunks.append(text)
            continue
        if isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    text = block.strip()
                    if text:
                        chunks.append(text)
                elif isinstance(block, dict):
                    text = str(block.get("text", "") or "").strip()
                    if text:
                        chunks.append(text)
    return "\n".join(chunks).strip()


def _build_lmstudio_chat_url(base_url: str) -> str:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return ""
    try:
        parsed = urlsplit(normalized)
        path = (parsed.path or "").rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        if not path:
            path = "/api/v1/chat"
        else:
            path = f"{path}/api/v1/chat"
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    except Exception:
        return ""


def _parse_csv(value: str) -> list[str]:
    rows: list[str] = []
    for item in str(value or "").replace(";", ",").split(","):
        row = str(item or "").strip()
        if row:
            rows.append(row)
    return rows


def _now_local_date_iso() -> str:
    tz_name = APP_TIME_ZONE or "Asia/Tokyo"
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.utcnow()
    return f"{now.year:04d}-{now.month:02d}-{now.day:02d}"


def _build_live_web_guarded_prompt(prompt: str) -> str:
    today = _now_local_date_iso()
    return (
        f"{prompt}\n\n"
        f"[Time Guard]\n"
        f"- Current date: {today} ({APP_TIME_ZONE}).\n"
        f"- Use live web results for this date.\n"
        f"- If exact date cannot be verified from fetched page, state that clearly.\n"
        f"- Do not invent past/future dates.\n"
    )


def _contains_date_mismatch(text: str, expected_date: str) -> bool:
    body = str(text or "")
    m = re.search(r"(20\d{2})[年/\-\.](\d{1,2})[月/\-\.](\d{1,2})日?", body)
    if not m:
        return False
    try:
        found = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    except Exception:
        return False
    return found != expected_date


async def _run_runpod_lmstudio_chat_plugin(prompt: str, *, base_url: str, live_web_query: bool) -> str:
    chat_url = _build_lmstudio_chat_url(base_url)
    if not chat_url:
        return ""
    if RUNPOD_LMSTUDIO_CHAT_PLUGIN_FOR_LIVE_WEB_ONLY and (not live_web_query):
        return ""
    plugin_id = str(RUNPOD_LMSTUDIO_CHAT_PLUGIN_ID or "").strip()
    if not plugin_id:
        return ""
    effective_prompt = _build_live_web_guarded_prompt(prompt) if live_web_query else prompt
    payload = {
        "model": DEFAULT_MODEL,
        "input": effective_prompt,
        "stream": False,
        "integrations": [plugin_id],
    }
    allowed_tools = _parse_csv(RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_ALLOWED_TOOLS_RAW)
    ephemeral_payload = {
        "model": DEFAULT_MODEL,
        "input": effective_prompt,
        "stream": False,
        "integrations": [
            {
                "type": "ephemeral_mcp",
                "server_label": RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_LABEL,
                "server_url": RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_URL,
                "allowed_tools": allowed_tools,
            }
        ],
    }
    headers = _runpod_auth_headers(include_content_type=True)
    timeout = httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=20.0)
    verify_setting = _runpod_httpx_verify_setting()
    async with httpx.AsyncClient(timeout=timeout, verify=verify_setting, trust_env=False) as client:
        if RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_PRIMARY:
            response = await client.post(chat_url, headers=headers, json=ephemeral_payload)
            if response.status_code >= 400:
                response = await client.post(chat_url, headers=headers, json=payload)
        else:
            response = await client.post(chat_url, headers=headers, json=payload)
            if (
                RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_FALLBACK_ENABLED
                and response.status_code in {400, 401, 403}
            ):
                preview = response.text[:1200] if response.text else ""
                if "permission denied to use plugin" in preview.lower():
                    response = await client.post(chat_url, headers=headers, json=ephemeral_payload)
    if response.status_code >= 400:
        preview = response.text[:800] if response.text else ""
        raise RuntimeError(f"lmstudio chat plugin failed: HTTP {response.status_code}. {preview}")
    data = response.json() if response.content else {}
    payload_data = data if isinstance(data, dict) else {}
    text = _extract_lmstudio_chat_text(payload_data)
    if live_web_query and text and _contains_date_mismatch(text, _now_local_date_iso()):
        retry_payload = dict(ephemeral_payload if RUNPOD_LMSTUDIO_CHAT_EPHEMERAL_MCP_PRIMARY else payload)
        retry_payload["input"] = (
            f"{effective_prompt}\n"
            f"- The prior answer contained a date mismatch. Use date={_now_local_date_iso()} only.\n"
        )
        async with httpx.AsyncClient(timeout=timeout, verify=verify_setting, trust_env=False) as client:
            retry = await client.post(chat_url, headers=headers, json=retry_payload)
        if retry.status_code < 400:
            retry_data = retry.json() if retry.content else {}
            retry_text = _extract_lmstudio_chat_text(retry_data if isinstance(retry_data, dict) else {})
            if retry_text:
                text = retry_text
    if not text:
        raise RuntimeError("lmstudio chat plugin returned no assistant text.")
    return text


def _build_responses_tools_payload() -> list[dict]:
    if not RUNPOD_RESPONSES_TOOLS_ENABLED:
        return []
    rows: list[dict] = []
    seen: set[str] = set()

    def add_tool(tool_payload: dict) -> None:
        if not isinstance(tool_payload, dict):
            return
        tool_type = str(tool_payload.get("type", "") or "").strip()
        if not tool_type:
            return
        key = json.dumps(tool_payload, ensure_ascii=False, sort_keys=True)
        if key in seen:
            return
        seen.add(key)
        rows.append(tool_payload)

    normalized_rows = RUNPOD_RESPONSES_TOOL_TYPES_RAW.replace(";", ",").replace("\n", ",")
    for item in normalized_rows.split(","):
        tool_type = str(item or "").strip()
        if not tool_type:
            continue
        add_tool({"type": tool_type})

    def parse_tools_json(raw_json: str, env_name: str, expected_type: str) -> None:
        text = str(raw_json or "").strip()
        if not text:
            return
        try:
            parsed = json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"{env_name} is not valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise RuntimeError(f"{env_name} must be a JSON array.")
        for index, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                raise RuntimeError(f"{env_name}[{index}] must be an object.")
            tool_type = str(item.get("type", "") or "").strip()
            if tool_type != expected_type:
                raise RuntimeError(
                    f"{env_name}[{index}] type must be '{expected_type}' (actual='{tool_type}')."
                )
            add_tool(item)

    parse_tools_json(
        RUNPOD_RESPONSES_FUNCTION_TOOLS_JSON,
        "RUNPOD_RESPONSES_FUNCTION_TOOLS_JSON",
        "function",
    )
    parse_tools_json(
        RUNPOD_RESPONSES_MCP_TOOLS_JSON,
        "RUNPOD_RESPONSES_MCP_TOOLS_JSON",
        "mcp",
    )
    return rows


def _responses_payload_has_tool_evidence(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    direct_tool_calls = payload.get("tool_calls")
    if isinstance(direct_tool_calls, list) and len(direct_tool_calls) > 0:
        return True

    output_items = payload.get("output")
    if not isinstance(output_items, list):
        return False

    for item in output_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "") or "").strip().lower()
        if "tool" in item_type or "web_search" in item_type:
            return True

        content = item.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type", "") or "").strip().lower()
                if "tool" in block_type or "web_search" in block_type:
                    return True
                annotations = block.get("annotations")
                if isinstance(annotations, list):
                    for annotation in annotations:
                        if not isinstance(annotation, dict):
                            continue
                        anno_type = str(annotation.get("type", "") or "").strip().lower()
                        if "url" in anno_type or "citation" in anno_type or "web" in anno_type:
                            return True
    return False


async def _run_runpod_responses_fallback(prompt: str, *, base_url: str = "") -> str:
    default_base_url = _normalize_base_url(RUNPOD_BASE_URL)
    if (not default_base_url) and RUNPOD_BASE_URL_CANDIDATES:
        default_base_url = RUNPOD_BASE_URL_CANDIDATES[0]
    resolved_base_url = _normalize_base_url(base_url) or default_base_url
    if not resolved_base_url:
        return ""
    url = f"{resolved_base_url}/responses"
    headers = _runpod_auth_headers(include_content_type=True)
    payload_base = {
        "model": DEFAULT_MODEL,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    }
    live_web_query = _prompt_likely_requires_live_web(prompt)
    if RUNPOD_LMSTUDIO_CHAT_PLUGIN_ENABLED and (
        (not RUNPOD_LMSTUDIO_CHAT_PLUGIN_FOR_LIVE_WEB_ONLY) or live_web_query
    ):
        return await _run_runpod_lmstudio_chat_plugin(
            prompt,
            base_url=resolved_base_url,
            live_web_query=live_web_query,
        )
    require_tool_for_prompt = RUNPOD_RESPONSES_REQUIRE_TOOL_FOR_LIVE_WEB and live_web_query
    enforce_tool_evidence = require_tool_for_prompt and RUNPOD_RESPONSES_HARD_FAIL_ON_MISSING_TOOL
    tool_choice = RUNPOD_RESPONSES_TOOL_CHOICE
    if live_web_query and RUNPOD_RESPONSES_LIVE_WEB_TOOL_CHOICE != "inherit":
        tool_choice = RUNPOD_RESPONSES_LIVE_WEB_TOOL_CHOICE
    responses_tools = _build_responses_tools_payload()
    if responses_tools and tool_choice != "none":
        payload_base["tools"] = responses_tools
        payload_base["tool_choice"] = tool_choice
    poll_timeout_ms = max(CODEX_STREAM_RECOVERY_TIMEOUT_MS, RUNPOD_RESPONSES_POLL_TIMEOUT_MS)
    poll_interval_sec = max(0.2, RUNPOD_RESPONSES_POLL_INTERVAL_MS / 1000.0)
    timeout = httpx.Timeout(
        connect=20.0,
        read=max(20.0, poll_timeout_ms / 1000.0),
        write=20.0,
        pool=20.0,
    )
    async def _run_once(verify_setting: bool | str) -> str:
        # Bypass OS proxy env for RunPod direct calls; proxy interception often breaks auth/TLS.
        async with httpx.AsyncClient(timeout=timeout, verify=verify_setting, trust_env=False) as client:
            async def _run_once_with_payload(payload: dict) -> str:
                background_error = ""
                if RUNPOD_RESPONSES_BACKGROUND_ENABLED:
                    background_payload = dict(payload)
                    background_payload["background"] = True
                    bg_res = await client.post(url, headers=headers, json=background_payload)
                    if bg_res.status_code < 400:
                        bg_data = bg_res.json() if bg_res.content else {}
                        bg_payload = bg_data if isinstance(bg_data, dict) else {}
                        bg_text = _extract_responses_output_text(bg_payload)
                        bg_status = _extract_responses_status(bg_payload)
                        bg_has_tool = _responses_payload_has_tool_evidence(bg_payload)
                        response_id = _extract_responses_id(bg_payload)
                        if bg_text and (
                            (not require_tool_for_prompt)
                            or bg_has_tool
                            or (not enforce_tool_evidence)
                        ):
                            return bg_text
                        if bg_status == "completed" and enforce_tool_evidence and (not bg_has_tool):
                            raise RuntimeError(
                                "responses tools were not executed for live-web prompt (completed without tool evidence)."
                            )
                        if response_id:
                            poll_url = f"{url}/{response_id}"
                            deadline = time.monotonic() + max(5.0, poll_timeout_ms / 1000.0)
                            poll_timed_out = True
                            while time.monotonic() < deadline:
                                await asyncio.sleep(poll_interval_sec)
                                poll_res = await client.get(poll_url, headers=_runpod_auth_headers())
                                if poll_res.status_code >= 400:
                                    preview = poll_res.text[:600] if poll_res.text else ""
                                    background_error = (
                                        f"background poll HTTP {poll_res.status_code}: {preview}"
                                    )
                                    poll_timed_out = False
                                    break
                                poll_data = poll_res.json() if poll_res.content else {}
                                poll_payload = poll_data if isinstance(poll_data, dict) else {}
                                poll_text = _extract_responses_output_text(poll_payload)
                                poll_status = _extract_responses_status(poll_payload)
                                poll_has_tool = _responses_payload_has_tool_evidence(poll_payload)
                                if poll_text and poll_status in {"completed", "in_progress", "running", "queued", "processing", ""} and (
                                    (not require_tool_for_prompt)
                                    or poll_has_tool
                                    or (not enforce_tool_evidence)
                                ):
                                    return poll_text
                                if poll_status == "completed":
                                    if enforce_tool_evidence and (not poll_has_tool):
                                        raise RuntimeError(
                                            "responses tools were not executed for live-web prompt (poll completed without tool evidence)."
                                        )
                                    poll_timed_out = False
                                    break
                                if poll_status in {"failed", "incomplete", "cancelled", "expired"}:
                                    background_error = f"background ended with status={poll_status}"
                                    poll_timed_out = False
                                    break
                            if poll_timed_out:
                                background_error = "background poll timed out before completion"
                            # Continue with non-background /responses call below.
                            # This keeps responses-mode alive even when background polling stalls.
                        if bg_status in {"failed", "incomplete", "cancelled", "expired"}:
                            background_error = f"background ended with status={bg_status}"
                    else:
                        preview = bg_res.text[:400] if bg_res.text else ""
                        background_error = f"background HTTP {bg_res.status_code}: {preview}"

                res = await client.post(url, headers=headers, json=payload)
                if res.status_code >= 400:
                    preview = res.text[:600] if res.text else ""
                    detail = f" {background_error}" if background_error else ""
                    raise RuntimeError(f"responses fallback failed: HTTP {res.status_code}. {preview}{detail}")
                data = res.json() if res.content else {}
                payload_data = data if isinstance(data, dict) else {}
                text = _extract_responses_output_text(payload_data)
                if not text:
                    raise RuntimeError("responses fallback returned no assistant text.")
                if enforce_tool_evidence and not _responses_payload_has_tool_evidence(payload_data):
                    raise RuntimeError(
                        "responses tools were not executed for live-web prompt (final response without tool evidence)."
                    )
                return text

            return await _run_once_with_payload(payload_base)

    verify_setting = _runpod_httpx_verify_setting()
    try:
        return await _run_once(verify_setting)
    except Exception as exc:
        # Optional insecure retry path. Disabled by default.
        if RUNPOD_TLS_VERIFY and _looks_like_tls_verify_failure(exc):
            if RUNPOD_TLS_RETRY_NO_VERIFY:
                try:
                    return await _run_once(False)
                except Exception as exc_retry:
                    raise RuntimeError(
                        "responses fallback TLS recovery failed: "
                        f"first={exc}; retry_no_verify={exc_retry}"
                    ) from exc_retry
            raise RuntimeError(
                "responses TLS verification failed. "
                f"{exc} "
                "Set RUNPOD_CA_BUNDLE to a trusted PEM or enable RUNPOD_TLS_USE_SYSTEM_STORE=1. "
                "As a last resort only, set RUNPOD_TLS_RETRY_NO_VERIFY=1."
            ) from exc
        raise


def _to_ndjson_line(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def _item_tool_summary(item: dict) -> tuple[str, str, str, bool]:
    detail_type = str(item.get("type", "") or "").strip().lower()
    item_id = str(item.get("id", "") or "").strip()
    if detail_type == "command_execution":
        command = str(item.get("command", "") or "").strip()
        status = str(item.get("status", "") or "").strip()
        output = str(item.get("aggregated_output", "") or "").strip()
        body = output if output else "(no output)"
        meta = f"item={item_id} status={status}"
        return "Codex command", meta, f"{command}\n\n{body}", status == "failed"
    if detail_type == "file_change":
        status = str(item.get("status", "") or "").strip()
        changes = item.get("changes", []) if isinstance(item.get("changes"), list) else []
        rows = []
        for row in changes[:20]:
            path = str(row.get("path", "") or "").strip()
            kind = str(row.get("kind", "") or "").strip()
            rows.append(f"- {kind}: {path}")
        body = "\n".join(rows) if rows else "(no file changes)"
        meta = f"item={item_id} status={status} changes={len(changes)}"
        return "Codex file change", meta, body, status == "failed"
    if detail_type == "mcp_tool_call":
        server = str(item.get("server", "") or "").strip()
        tool = str(item.get("tool", "") or "").strip()
        status = str(item.get("status", "") or "").strip()
        err_obj = item.get("error") if isinstance(item.get("error"), dict) else None
        err_text = str(err_obj.get("message", "") or "").strip() if err_obj else ""
        result = item.get("result")
        result_preview = ""
        if isinstance(result, dict):
            result_preview = json.dumps(result, ensure_ascii=False)[:1200]
        body = f"server={server}\ntool={tool}\n{result_preview or err_text or '(no result)'}"
        meta = f"item={item_id} status={status}"
        return "Codex MCP tool", meta, body, status == "failed"
    if detail_type == "web_search":
        query = str(item.get("query", "") or "").strip()
        action = str(item.get("action", "") or "").strip()
        meta = f"item={item_id} action={action}"
        return "Codex web search", meta, query or "(empty query)", False
    if detail_type == "todo_list":
        items = item.get("items", []) if isinstance(item.get("items"), list) else []
        rows = []
        for row in items[:20]:
            text = str(row.get("text", "") or "").strip()
            completed = bool(row.get("completed"))
            mark = "x" if completed else " "
            rows.append(f"[{mark}] {text}")
        meta = f"item={item_id} todo_items={len(items)}"
        return "Codex plan", meta, "\n".join(rows) if rows else "(empty plan)", False
    if detail_type == "reasoning":
        text = str(item.get("text", "") or "").strip()
        return "Codex reasoning", f"item={item_id}", text[:1200] if text else "(empty reasoning)", False
    if detail_type == "error":
        text = str(item.get("message", "") or "").strip()
        normalized = text.lower()
        if (
            "model metadata for" in normalized
            and "fallback metadata" in normalized
        ):
            # Known noisy warning on codex-cli when model slug is unknown.
            # We suppress this card to reduce user-facing noise.
            return "", "", "", False
        return "Codex error item", f"item={item_id}", text or "(empty error)", True
    return "", "", "", False


def _build_codex_exec_native_profile() -> dict[str, int | str]:
    return {
        "model_context_window": CODEX_MODEL_CONTEXT_WINDOW,
        "project_doc_max_bytes": CODEX_PROJECT_DOC_MAX_BYTES,
        "request_max_retries": CODEX_PROVIDER_REQUEST_MAX_RETRIES,
        "stream_max_retries": max(0, CODEX_PROVIDER_STREAM_MAX_RETRIES),
        # Native mode often sees delayed first token; keep idle timeout relaxed.
        "stream_idle_timeout_ms": max(CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS, 90000),
        "model_reasoning_effort": CODEX_MODEL_REASONING_EFFORT,
        "model_reasoning_summary": CODEX_MODEL_REASONING_SUMMARY,
        "model_verbosity": CODEX_MODEL_VERBOSITY,
        "web_search_mode": CODEX_WEB_SEARCH_MODE,
    }


async def _iter_codex_chat_events_native(prompt: str) -> AsyncIterator[dict]:
    started_at = time.monotonic()
    workspace_root = _resolve_workspace_root_for_agent()
    codex_home = _resolve_codex_home()
    profile = _build_codex_exec_native_profile()

    temp_dir = Path(tempfile.mkdtemp(prefix="localingo-codex-native-"))
    output_last_message_file = temp_dir / "last_message.txt"

    assistant_stream_started = False
    agent_text = ""
    stderr_lines: list[str] = []
    return_code = 1
    timed_out = False
    stream_disconnect_happened = False
    empty_last_message_happened = False
    transport_failure_happened = False

    yield {"type": "status", "step": 0, "message": "Codex CLI: starting (native mode)..."}

    attempt_base_url = await _select_runpod_base_url(attempt_index=1)
    if not attempt_base_url:
        raise RuntimeError("No RunPod base URL candidates are configured.")

    _ensure_codex_config(codex_home, profile=profile, base_url=attempt_base_url)
    env = _build_codex_env(codex_home, base_url=attempt_base_url)
    try:
        output_last_message_file.unlink(missing_ok=True)
    except Exception:
        pass

    cmd = _build_codex_exec_command(
        prompt=str(prompt or ""),
        workspace_root=workspace_root,
        output_last_message_file=output_last_message_file,
        profile=profile,
        codex_home=codex_home,
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(workspace_root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def read_stderr() -> None:
        if proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text and len(stderr_lines) < 240:
                stderr_lines.append(text)

    stderr_task = asyncio.create_task(read_stderr())

    try:
        if proc.stdout is not None:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                event_type = str(event.get("type", "") or "").strip().lower()

                if event_type == "turn.started":
                    yield {"type": "status", "step": 1, "message": "Codex CLI: thinking..."}
                    continue
                if event_type == "turn.completed":
                    yield {"type": "status", "step": 2, "message": "Codex CLI: finalizing..."}
                    continue
                if event_type == "error":
                    msg = str(event.get("message", "") or "").strip() or raw[:800]
                    if _is_stream_disconnect_message(msg):
                        stream_disconnect_happened = True
                        continue
                    yield {"type": "error", "message": msg}
                    continue
                if event_type not in {"item.started", "item.updated", "item.completed"}:
                    continue

                item = event.get("item") if isinstance(event.get("item"), dict) else {}
                detail_type = str(item.get("type", "") or "").strip().lower()
                if detail_type == "agent_message":
                    latest_text = str(item.get("text", "") or "")
                    if latest_text:
                        if not assistant_stream_started:
                            assistant_stream_started = True
                            yield {
                                "type": "assistant_stream_start",
                                "model": DEFAULT_MODEL,
                                "totalChars": len(latest_text),
                            }
                        if latest_text.startswith(agent_text):
                            delta = latest_text[len(agent_text):]
                        else:
                            delta = latest_text
                        agent_text = latest_text
                        if delta:
                            yield {"type": "assistant_stream_delta", "delta": delta}
                    continue

                title, meta, body, is_error = _item_tool_summary(item)
                if title:
                    yield {
                        "type": "tool_card",
                        "html": _render_tool_card(title=title, meta=meta, body=body, is_error=is_error),
                    }
    finally:
        try:
            await asyncio.wait_for(proc.wait(), timeout=CODEX_EXEC_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            await proc.wait()
            yield {"type": "error", "message": f"Codex CLI timed out ({CODEX_EXEC_TIMEOUT_SEC}s)."}
        await stderr_task

    return_code = proc.returncode if proc.returncode is not None else 1
    stderr_tail_joined = "\n".join(stderr_lines)
    if _is_stream_disconnect_message(stderr_tail_joined):
        stream_disconnect_happened = True
    if _is_empty_last_message_warning(stderr_tail_joined):
        empty_last_message_happened = True
    if _is_transport_failure_message(stderr_tail_joined):
        transport_failure_happened = True

    if return_code == 0:
        _mark_runpod_route_success(attempt_base_url)
    else:
        _mark_runpod_route_failure(attempt_base_url, stderr_tail_joined)

    if not agent_text and output_last_message_file.exists():
        try:
            agent_text = output_last_message_file.read_text(encoding="utf-8").strip()
        except Exception:
            agent_text = ""

    elapsed_ms = int((time.monotonic() - started_at) * 1000)

    if assistant_stream_started:
        yield {
            "type": "assistant_stream_done",
            "elapsedMs": elapsed_ms,
            "totalChars": len(agent_text),
        }
    elif agent_text:
        yield {"type": "assistant_stream_start", "model": DEFAULT_MODEL, "totalChars": len(agent_text)}
        yield {"type": "assistant_stream_delta", "delta": agent_text}
        yield {"type": "assistant_stream_done", "elapsedMs": elapsed_ms, "totalChars": len(agent_text)}

    should_fallback_to_resilient = (
        return_code != 0
        and (not agent_text)
        and (
            stream_disconnect_happened
            or empty_last_message_happened
            or transport_failure_happened
        )
    )
    if should_fallback_to_resilient:
        yield {
            "type": "status",
            "step": 2,
            "message": "Native stream was unstable. Switching to resilient mode...",
        }
        async for event in _iter_codex_chat_events_resilient(prompt):
            yield event
        return

    if return_code != 0:
        stderr_tail = "\n".join(stderr_lines[-20:]).strip()
        message = f"Codex CLI exited with code {return_code}."
        if stderr_tail:
            message = f"{message}\n\n{stderr_tail}"
        if timed_out:
            message = f"{message}\n\n(timeout)"
        yield {"type": "error", "message": message}
        if not agent_text:
            agent_text = "Codex CLI failed before producing a final answer."

    if not agent_text:
        agent_text = "(empty response)"

    yield {
        "type": "assistant_turn",
        "html": _render_assistant_turn(text=agent_text, model=DEFAULT_MODEL, elapsed_ms=elapsed_ms),
        "text": agent_text,
        "model": DEFAULT_MODEL,
        "elapsedMs": elapsed_ms,
        "streamed": True,
    }
    yield {"type": "done", "elapsedMs": elapsed_ms}

    try:
        if output_last_message_file.exists():
            output_last_message_file.unlink(missing_ok=True)
        temp_dir.rmdir()
    except Exception:
        pass


async def _iter_codex_chat_events(prompt: str) -> AsyncIterator[dict]:
    if CODEX_EXEC_ROUTE_MODE == "background_poll":
        async for event in _iter_codex_chat_events_background_poll(prompt):
            yield event
        return

    if CODEX_EXEC_ROUTE_MODE == "native":
        async for event in _iter_codex_chat_events_native(prompt):
            yield event
        return

    async for event in _iter_codex_chat_events_resilient(prompt):
        yield event


async def _iter_codex_chat_events_background_poll(prompt: str) -> AsyncIterator[dict]:
    started_at = time.monotonic()
    prepared_prompt, prompt_info = _prepare_codex_prompt(prompt)

    if bool(prompt_info.get("compressed")):
        yield {
            "type": "status",
            "step": 0,
            "message": (
                "Responses mode: prompt compacted for transport "
                f"{int(prompt_info.get('original_len', 0))} -> {int(prompt_info.get('prepared_len', 0))} chars."
            ),
        }
    if bool(prompt_info.get("truncated")):
        yield {
            "type": "status",
            "step": 0,
            "message": (
                f"Responses mode: prompt hard-capped {int(prompt_info.get('original_len', 0))} -> "
                f"{CODEX_PROMPT_MAX_CHARS} chars before send."
            ),
        }
    start_status_message = (
        "Responses mode: submitting background request..."
        if RUNPOD_RESPONSES_BACKGROUND_ENABLED
        else "Responses mode: submitting request..."
    )
    yield {"type": "status", "step": 0, "message": start_status_message}

    preferred_route = await _select_runpod_base_url(attempt_index=1)
    if not preferred_route:
        preferred_route = _normalize_base_url(RUNPOD_BASE_URL)
    fallback_routes = _runpod_route_fallback_order(preferred_route)

    recovery_error = ""
    recovered_text = ""
    used_route = ""
    for route in fallback_routes:
        used_route = route
        try:
            yield {
                "type": "status",
                "step": 1,
                "message": f"Responses mode: polling via {_route_status_label(route)}...",
            }
            recovered_text = await _run_runpod_responses_fallback(prepared_prompt, base_url=route)
            _mark_runpod_route_success(route)
            break
        except Exception as exc:
            recovery_error = str(exc)
            _mark_runpod_route_failure(route, recovery_error)
            continue

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    if recovered_text:
        yield {"type": "assistant_stream_start", "model": DEFAULT_MODEL, "totalChars": len(recovered_text)}
        yield {"type": "assistant_stream_delta", "delta": recovered_text}
        yield {"type": "assistant_stream_done", "elapsedMs": elapsed_ms, "totalChars": len(recovered_text)}
        yield {
            "type": "assistant_turn",
            "html": _render_assistant_turn(text=recovered_text, model=DEFAULT_MODEL, elapsed_ms=elapsed_ms),
            "text": recovered_text,
            "model": DEFAULT_MODEL,
            "elapsedMs": elapsed_ms,
            "streamed": True,
        }
        yield {"type": "done", "elapsedMs": elapsed_ms}
        return

    if recovery_error:
        yield {"type": "error", "message": f"Responses mode failed: {recovery_error}"}
    fallback_text = "Codex responses mode failed before producing a final answer."
    yield {
        "type": "assistant_turn",
        "html": _render_assistant_turn(text=fallback_text, model=DEFAULT_MODEL, elapsed_ms=elapsed_ms),
        "text": fallback_text,
        "model": DEFAULT_MODEL,
        "elapsedMs": elapsed_ms,
        "streamed": False,
    }
    yield {"type": "done", "elapsedMs": elapsed_ms}


async def _iter_codex_chat_events_resilient(prompt: str) -> AsyncIterator[dict]:
    started_at = time.monotonic()
    workspace_root = _resolve_workspace_root_for_agent()
    codex_home = _resolve_codex_home()
    prepared_prompt, prompt_info = _prepare_codex_prompt(prompt)
    retry_profiles = _build_codex_exec_retry_profiles()

    temp_dir = Path(tempfile.mkdtemp(prefix="localingo-codex-"))
    output_last_message_file = temp_dir / "last_message.txt"

    last_stderr_lines: list[str] = []
    agent_text = ""
    assistant_stream_started = False
    return_code = 1
    tool_card_count = 0
    stream_disconnect_happened = False
    retried_due_to_stream_disconnect = False
    retried_due_to_transport_failure = False
    last_base_url_used = ""

    if bool(prompt_info.get("compressed")):
        yield {
            "type": "status",
            "step": 0,
            "message": (
                "Codex CLI: prompt compacted for transport "
                f"{int(prompt_info.get('original_len', 0))} -> {int(prompt_info.get('prepared_len', 0))} chars."
            ),
        }
    if bool(prompt_info.get("truncated")):
        yield {
            "type": "status",
            "step": 0,
            "message": (
                f"Codex CLI: prompt hard-capped {int(prompt_info.get('original_len', 0))} -> "
                f"{CODEX_PROMPT_MAX_CHARS} chars before send."
            ),
        }
    yield {"type": "status", "step": 0, "message": "Codex CLI: starting..."}

    for attempt_index, profile in enumerate(retry_profiles, start=1):
        if attempt_index > 1:
            yield {
                "type": "status",
                "step": 0,
                "message": f"Codex CLI: retry attempt {attempt_index}/{len(retry_profiles)}...",
            }
        attempt_base_url = await _select_runpod_base_url(attempt_index=attempt_index)
        if not attempt_base_url:
            raise RuntimeError("No RunPod base URL candidates are configured.")
        last_base_url_used = attempt_base_url
        yield {
            "type": "status",
            "step": 0,
            "message": f"RunPod route: {_route_status_label(attempt_base_url)}",
        }

        _ensure_codex_config(codex_home, profile=profile, base_url=attempt_base_url)
        env = _build_codex_env(codex_home, base_url=attempt_base_url)
        try:
            output_last_message_file.unlink(missing_ok=True)
        except Exception:
            pass

        cmd = _build_codex_exec_command(
            prompt=prepared_prompt,
            workspace_root=workspace_root,
            output_last_message_file=output_last_message_file,
            profile=profile,
            codex_home=codex_home,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace_root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stderr_lines: list[str] = []
        attempt_agent_text = ""
        attempt_assistant_stream_started = False
        attempt_stream_disconnect = False
        timed_out = False

        async def read_stderr() -> None:
            if proc.stderr is None:
                return
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text and len(stderr_lines) < 240:
                    stderr_lines.append(text)

        stderr_task = asyncio.create_task(read_stderr())

        try:
            if proc.stdout is not None:
                while True:
                    progress_timeout_sec = max(0.5, CODEX_EXEC_PROGRESS_PING_INTERVAL_MS / 1000.0)
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=progress_timeout_sec)
                    except asyncio.TimeoutError:
                        yield {
                            "type": "status",
                            "step": 1,
                            "message": (
                                f"Codex CLI: waiting for model output... ({attempt_index}/{len(retry_profiles)})"
                            ),
                        }
                        continue
                    if not line:
                        break
                    raw = line.decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except Exception:
                        continue
                    event_type = str(event.get("type", "") or "").strip().lower()

                    if event_type == "turn.started":
                        yield {
                            "type": "status",
                            "step": 1,
                            "message": (
                                f"Codex CLI: thinking... ({attempt_index}/{len(retry_profiles)})"
                                if len(retry_profiles) > 1
                                else "Codex CLI: thinking..."
                            ),
                        }
                        continue

                    if event_type == "turn.completed":
                        yield {"type": "status", "step": 2, "message": "Codex CLI: finalizing..."}
                        continue

                    if event_type == "error":
                        msg = str(event.get("message", "") or "").strip() or raw[:800]
                        if _is_stream_disconnect_message(msg):
                            attempt_stream_disconnect = True
                            stream_disconnect_happened = True
                            continue
                        yield {"type": "error", "message": msg}
                        continue

                    if event_type not in {"item.started", "item.updated", "item.completed"}:
                        continue

                    item = event.get("item") if isinstance(event.get("item"), dict) else {}
                    detail_type = str(item.get("type", "") or "").strip().lower()
                    if detail_type == "agent_message":
                        latest_text = str(item.get("text", "") or "")
                        if latest_text:
                            if not attempt_assistant_stream_started:
                                attempt_assistant_stream_started = True
                                yield {
                                    "type": "assistant_stream_start",
                                    "model": DEFAULT_MODEL,
                                    "totalChars": len(latest_text),
                                }
                            if latest_text.startswith(attempt_agent_text):
                                delta = latest_text[len(attempt_agent_text):]
                            else:
                                delta = latest_text
                            attempt_agent_text = latest_text
                            if delta:
                                yield {"type": "assistant_stream_delta", "delta": delta}
                        continue

                    title, meta, body, is_error = _item_tool_summary(item)
                    if title:
                        tool_card_count += 1
                        yield {
                            "type": "tool_card",
                            "html": _render_tool_card(title=title, meta=meta, body=body, is_error=is_error),
                        }
        finally:
            try:
                await asyncio.wait_for(proc.wait(), timeout=CODEX_EXEC_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                timed_out = True
                proc.kill()
                await proc.wait()
                yield {"type": "error", "message": f"Codex CLI timed out ({CODEX_EXEC_TIMEOUT_SEC}s)."}
            await stderr_task

        attempt_return_code = proc.returncode if proc.returncode is not None else 1

        if not attempt_agent_text and output_last_message_file.exists():
            try:
                attempt_agent_text = output_last_message_file.read_text(encoding="utf-8").strip()
            except Exception:
                attempt_agent_text = ""

        stderr_tail_joined = "\n".join(stderr_lines)
        if _is_stream_disconnect_message(stderr_tail_joined):
            attempt_stream_disconnect = True
            stream_disconnect_happened = True
        attempt_transport_failure = _is_transport_failure_message(stderr_tail_joined)

        if attempt_return_code == 0:
            _mark_runpod_route_success(attempt_base_url)
        elif attempt_stream_disconnect or attempt_transport_failure:
            _mark_runpod_route_failure(attempt_base_url, stderr_tail_joined)

        should_retry = (
            attempt_return_code != 0
            and (attempt_stream_disconnect or attempt_transport_failure)
            and (not attempt_agent_text)
            and (not timed_out)
            and attempt_index < len(retry_profiles)
        )
        if should_retry:
            if attempt_stream_disconnect:
                retried_due_to_stream_disconnect = True
            if attempt_transport_failure:
                retried_due_to_transport_failure = True
            delay_ms = _compute_retry_delay_ms(attempt_index)
            retry_reason = "stream disconnect" if attempt_stream_disconnect else "transport error"
            yield {
                "type": "status",
                "step": 0,
                "message": (
                    f"Codex {retry_reason} on {_route_status_label(attempt_base_url)}. "
                    f"Retrying in {delay_ms}ms ({attempt_index + 1}/{len(retry_profiles)})..."
                ),
            }
            await asyncio.sleep(delay_ms / 1000.0)
            continue

        return_code = attempt_return_code
        agent_text = attempt_agent_text
        assistant_stream_started = attempt_assistant_stream_started
        last_stderr_lines = stderr_lines
        break

    elapsed_ms = int((time.monotonic() - started_at) * 1000)

    if assistant_stream_started:
        yield {
            "type": "assistant_stream_done",
            "elapsedMs": elapsed_ms,
            "totalChars": len(agent_text),
        }
    elif agent_text:
        yield {"type": "assistant_stream_start", "model": DEFAULT_MODEL, "totalChars": len(agent_text)}
        yield {"type": "assistant_stream_delta", "delta": agent_text}
        yield {"type": "assistant_stream_done", "elapsedMs": elapsed_ms, "totalChars": len(agent_text)}

    if (
        return_code != 0
        and stream_disconnect_happened
        and CODEX_STREAM_RECOVERY_FALLBACK_ENABLED
        and (not agent_text)
    ):
        fallback_routes = _runpod_route_fallback_order(last_base_url_used)
        recovery_error = ""
        recovered_text = ""
        used_recovery_route = ""
        for fallback_route in fallback_routes:
            used_recovery_route = fallback_route
            try:
                yield {
                    "type": "status",
                    "step": 2,
                    "message": (
                        "Codex stream recovery: switching to responses fallback via "
                        f"{_route_status_label(fallback_route)}..."
                    ),
                }
                recovered_text = await _run_runpod_responses_fallback(
                    prepared_prompt,
                    base_url=fallback_route,
                )
                _mark_runpod_route_success(fallback_route)
                break
            except Exception as exc:
                recovery_error = str(exc)
                _mark_runpod_route_failure(fallback_route, recovery_error)
                continue

        if recovered_text:
            if not assistant_stream_started:
                yield {"type": "assistant_stream_start", "model": DEFAULT_MODEL, "totalChars": len(recovered_text)}
                yield {"type": "assistant_stream_delta", "delta": recovered_text}
                yield {"type": "assistant_stream_done", "elapsedMs": elapsed_ms, "totalChars": len(recovered_text)}
            agent_text = recovered_text
            return_code = 0
            yield {
                "type": "tool_card",
                "html": _render_tool_card(
                    title="Codex stream recovery",
                    meta=f"fallback=responses route={_route_status_label(used_recovery_route)}",
                    body=(
                        "Stream completion was unstable, so a background-capable responses "
                        "fallback request was used."
                    ),
                    is_error=False,
                ),
            }
        elif recovery_error:
            yield {"type": "error", "message": f"Stream recovery fallback failed: {recovery_error}"}

    live_web_query = _prompt_likely_requires_live_web(prompt)
    no_network_answer = _looks_like_no_network_answer(agent_text)
    should_force_engine_fallback = (
        CODEX_TOOL_FALLBACK_TO_ENGINE
        and return_code == 0
        and tool_card_count == 0
        and live_web_query
        and (no_network_answer or CODEX_TOOL_FALLBACK_FORCE_FOR_LIVE_WEB)
    )
    if should_force_engine_fallback:
        fallback_reason = (
            "Codex returned a network-restricted answer without tool activity."
            if no_network_answer
            else "Codex returned no tool activity for a live-web query."
        )
        yield {
            "type": "status",
            "step": 2,
            "message": f"{fallback_reason} Switching to engine tool fallback...",
        }
        fallback_text, fallback_tool_cards, fallback_error = await _run_engine_tool_fallback(prompt)
        if fallback_tool_cards:
            for html_card in fallback_tool_cards:
                yield {"type": "tool_card", "html": html_card}
            tool_card_count += len(fallback_tool_cards)
        if fallback_text:
            agent_text = fallback_text
        elif fallback_error:
            yield {"type": "status", "step": 2, "message": f"Engine tool fallback failed: {fallback_error}"}

    if return_code != 0:
        stderr_tail = "\n".join(last_stderr_lines[-20:]).strip()
        message = f"Codex CLI exited with code {return_code}."
        if stderr_tail:
            message = f"{message}\n\n{stderr_tail}"
        if retried_due_to_stream_disconnect:
            message = f"{message}\n\n(retried after stream disconnects)"
        if retried_due_to_transport_failure:
            message = f"{message}\n\n(retried after transport failures)"
        yield {"type": "error", "message": message}
        if not agent_text:
            agent_text = "Codex CLI failed before producing a final answer."

    if not agent_text:
        agent_text = "(empty response)"

    yield {
        "type": "assistant_turn",
        "html": _render_assistant_turn(text=agent_text, model=DEFAULT_MODEL, elapsed_ms=elapsed_ms),
        "text": agent_text,
        "model": DEFAULT_MODEL,
        "elapsedMs": elapsed_ms,
        "streamed": True,
    }
    yield {"type": "done", "elapsedMs": elapsed_ms}

    try:
        if output_last_message_file.exists():
            output_last_message_file.unlink(missing_ok=True)
        temp_dir.rmdir()
    except Exception:
        pass


async def _wait_engine_ready(timeout_sec: float = 30.0) -> bool:
    started = asyncio.get_event_loop().time()
    # Loopback health probe must not honor HTTP(S)_PROXY.
    async with httpx.AsyncClient(timeout=2.5, trust_env=False) as client:
        while True:
            try:
                res = await client.get(ENGINE_HEALTH_URL)
                if res.status_code == 200:
                    return True
            except Exception:
                pass
            if (asyncio.get_event_loop().time() - started) >= timeout_sec:
                return False
            await asyncio.sleep(0.4)


def _kill_engine_proc() -> None:
    global _engine_proc
    proc = _engine_proc
    if not proc:
        return
    if proc.poll() is not None:
        _engine_proc = None
        return
    try:
        proc.terminate()
        proc.wait(timeout=6)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    _engine_proc = None


def _start_engine_proc() -> None:
    global _engine_proc
    if _engine_proc and _engine_proc.poll() is None:
        return
    if not NODE_BIN:
        raise RuntimeError("NODE_BIN is not set.")
    if not ENGINE_SCRIPT.exists():
        raise RuntimeError(f"Engine script not found: {ENGINE_SCRIPT}")
    _engine_proc = subprocess.Popen(
        [NODE_BIN, str(ENGINE_SCRIPT)],
        cwd=str(BASE_DIR),
        env=_build_engine_env(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _copy_proxy_response_headers(src: httpx.Response, dst: Response) -> None:
    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
    for key, value in src.headers.items():
        lower = key.lower().strip()
        if lower in hop_by_hop:
            continue
        if lower == "set-cookie":
            continue
        dst.headers[key] = value

    set_cookie_values = src.headers.get_list("set-cookie")
    for cookie_value in set_cookie_values:
        dst.headers.append("set-cookie", cookie_value)


def _build_upstream_headers(req: Request) -> dict:
    headers = {}
    for key, value in req.headers.items():
        lower = key.lower()
        if lower in {"host", "content-length", "connection"}:
            continue
        headers[key] = value
    return headers


@app.on_event("startup")
async def on_startup() -> None:
    _start_engine_proc()
    ready = await _wait_engine_ready(timeout_sec=35.0)
    if not ready:
        raise RuntimeError("Internal engine failed to start within timeout.")
    if AGENT_BACKEND == "codex_cli":
        _resolve_codex_home()
        _resolve_workspace_root_for_agent()
        _resolve_codex_command()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    _kill_engine_proc()


@app.get("/", response_class=HTMLResponse)
async def index(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": req,
            "app_name": APP_NAME,
            "agent_backend": AGENT_BACKEND,
        },
    )


@app.get("/health")
async def health() -> JSONResponse:
    engine_ok = False
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        try:
            res = await client.get(ENGINE_HEALTH_URL)
            engine_ok = res.status_code == 200
        except Exception:
            engine_ok = False

    codex_ready = True
    codex_error = ""
    runpod_primary_route = RUNPOD_BASE_URL_CANDIDATES[0] if RUNPOD_BASE_URL_CANDIDATES else _normalize_base_url(RUNPOD_BASE_URL)
    if AGENT_BACKEND == "codex_cli":
        try:
            _resolve_codex_command()
            _ensure_codex_config(_resolve_codex_home(), base_url=runpod_primary_route)
        except Exception as exc:
            codex_ready = False
            codex_error = str(exc)

    ok = engine_ok and codex_ready
    status_code = 200 if ok else 503
    return JSONResponse(
        {
            "ok": ok,
            "service": "fastapi-htmx-client",
            "engine_url": ENGINE_BASE_URL,
            "agent_backend": AGENT_BACKEND,
            "requested_agent_backend": REQUESTED_AGENT_BACKEND,
            "engine_ok": engine_ok,
            "codex_ready": codex_ready,
            "codex_error": codex_error,
            "codex_native_mode": CODEX_NATIVE_MODE,
            "codex_exec_route_mode": CODEX_EXEC_ROUTE_MODE,
            "runpod_route_probe_enabled": RUNPOD_ROUTE_PROBE_ENABLED,
            "runpod_routes": [_route_status_label(row) for row in RUNPOD_BASE_URL_CANDIDATES],
            "runpod_primary_route": _route_status_label(runpod_primary_route),
        },
        status_code=status_code,
    )


async def _proxy_non_stream(req: Request, path: str) -> Response:
    upstream_url = f"{ENGINE_BASE_URL}/{path.lstrip('/')}"
    body = await req.body()
    async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
        upstream_res = await client.request(
            req.method,
            upstream_url,
            params=req.query_params,
            content=body,
            headers=_build_upstream_headers(req),
        )
    content_type = upstream_res.headers.get("content-type", "")
    proxy_res = Response(
        content=upstream_res.content,
        status_code=upstream_res.status_code,
        media_type=None if not content_type else content_type.split(";")[0].strip(),
    )
    _copy_proxy_response_headers(upstream_res, proxy_res)
    return proxy_res


async def _proxy_chat_stream(req: Request) -> StreamingResponse:
    upstream_url = f"{ENGINE_BASE_URL}/api/chat/stream"
    body = await req.body()

    async def stream_bytes():
        timeout = httpx.Timeout(connect=20.0, read=None, write=60.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream(
                req.method,
                upstream_url,
                params=req.query_params,
                content=body,
                headers=_build_upstream_headers(req),
            ) as upstream_res:
                async for chunk in upstream_res.aiter_bytes():
                    if chunk:
                        yield chunk

    return StreamingResponse(stream_bytes(), media_type="application/x-ndjson")


@app.api_route("/api/chat/form", methods=["POST"])
async def api_chat_form(req: Request) -> Response:
    if AGENT_BACKEND != "codex_cli":
        return await _proxy_non_stream(req, "api/chat/form")

    body = await req.body()
    data = _parse_form_urlencoded(body)
    prompt = str(data.get("prompt", "") or "").strip()
    omit_user_turn = str(data.get("omit_user_turn", data.get("omitUserTurn", "0"))).strip().lower() in {"1", "true", "yes", "on"}
    omit_middle_html = str(data.get("omit_middle_html", data.get("omitMiddleHtml", "0"))).strip().lower() in {"1", "true", "yes", "on"}

    if not prompt:
        html = _render_tool_card("Error", "Prompt is empty.", is_error=True)
        return HTMLResponse(html, status_code=400)

    user_html = _render_user_turn(prompt)
    tool_html_parts: list[str] = []
    assistant_html = ""
    async for event in _iter_codex_chat_events(prompt):
        event_type = str(event.get("type", "") or "").strip().lower()
        if event_type == "tool_card":
            html = str(event.get("html", "") or "")
            if html:
                tool_html_parts.append(html)
        elif event_type == "error":
            message = str(event.get("message", "") or "").strip() or "Request failed."
            tool_html_parts.append(_render_tool_card("Error", message, is_error=True))
        elif event_type == "assistant_turn":
            assistant_html = str(event.get("html", "") or "")

    if not assistant_html:
        assistant_html = _render_assistant_turn("(empty response)", DEFAULT_MODEL, 0)

    parts: list[str] = []
    if not omit_user_turn:
        parts.append(user_html)
    if not omit_middle_html:
        parts.extend(tool_html_parts)
    parts.append(assistant_html)
    return HTMLResponse("".join(parts), status_code=200)


@app.api_route("/api/chat/stream", methods=["POST"])
async def api_chat_stream(req: Request) -> StreamingResponse:
    if AGENT_BACKEND != "codex_cli":
        return await _proxy_chat_stream(req)

    body = await req.body()
    data = _parse_form_urlencoded(body)
    prompt = str(data.get("prompt", "") or "").strip()

    async def codex_stream():
        if not prompt:
            yield _to_ndjson_line({"type": "error", "message": "Prompt is empty."})
            return
        yield _to_ndjson_line({"type": "user_turn", "html": _render_user_turn(prompt)})
        try:
            async for event in _iter_codex_chat_events(prompt):
                yield _to_ndjson_line(event)
        except Exception as exc:
            yield _to_ndjson_line(
                {
                    "type": "error",
                    "message": str(exc),
                }
            )

    return StreamingResponse(codex_stream(), media_type="application/x-ndjson")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_api(req: Request, path: str) -> Response:
    return await _proxy_non_stream(req, f"api/{path}")


@app.api_route("/workspace/{path:path}", methods=["GET", "POST"])
async def proxy_workspace(req: Request, path: str) -> Response:
    return await _proxy_non_stream(req, f"workspace/{path}")


@app.get("/favicon.ico")
async def favicon() -> PlainTextResponse:
    return PlainTextResponse("", status_code=204)


@app.get("/ping")
async def ping() -> JSONResponse:
    return JSONResponse({"ok": True, "service": APP_NAME, "agent_backend": AGENT_BACKEND})


if __name__ == "__main__":
    # For direct debug execution:
    # python -m fastapi_app.main
    import uvicorn

    host = os.getenv("APP_BIND", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "3030"))
    uvicorn.run("fastapi_app.main:app", host=host, port=port, reload=False)
