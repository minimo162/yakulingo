from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


def _is_http_ready(url: str, *, timeout_s: float = 0.8) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    else:
        opener = urllib.request.build_opener()
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=timeout_s) as response:
            return bool(getattr(response, "status", 200) == 200)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _commit_text_input(text_input: object) -> None:
    blur = getattr(text_input, "blur", None)
    if callable(blur):
        blur()
    dispatch_event = getattr(text_input, "dispatch_event", None)
    if callable(dispatch_event):
        dispatch_event("change")


def _wait_for_translate_button_enabled(
    translate_button: object,
    *,
    timeout_s: float,
    local_status: object | None = None,
    text_input: object | None = None,
    app_log_path: Path | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    start = monotonic()
    deadline = start + max(timeout_s, 0.0)
    while monotonic() < deadline:
        is_enabled = getattr(translate_button, "is_enabled", None)
        if callable(is_enabled) and bool(is_enabled()):
            return
        get_attribute = getattr(translate_button, "get_attribute", None)
        if callable(get_attribute) and get_attribute("disabled") is None:
            return
        sleep(0.05)

    translate_enabled = False
    disabled_attr = None
    is_enabled = getattr(translate_button, "is_enabled", None)
    if callable(is_enabled):
        try:
            translate_enabled = bool(is_enabled())
        except Exception:
            translate_enabled = False
    get_attribute = getattr(translate_button, "get_attribute", None)
    if callable(get_attribute):
        try:
            disabled_attr = get_attribute("disabled")
        except Exception:
            disabled_attr = None

    text_value = ""
    if text_input is not None:
        input_value = getattr(text_input, "input_value", None)
        if callable(input_value):
            try:
                text_value = str(input_value())
            except Exception:
                text_value = ""

    local_ai_state = None
    if local_status is not None:
        get_attribute = getattr(local_status, "get_attribute", None)
        if callable(get_attribute):
            try:
                local_ai_state = get_attribute("data-state")
            except Exception:
                local_ai_state = None
        if not local_ai_state:
            inner_text = getattr(local_status, "inner_text", None)
            if callable(inner_text):
                try:
                    local_ai_state = str(inner_text()).strip()
                except Exception:
                    local_ai_state = None

    log_tail = ""
    if app_log_path is not None:
        try:
            if app_log_path.exists():
                log_tail = app_log_path.read_text(encoding="utf-8")[-2000:]
        except Exception:
            log_tail = ""

    raise TimeoutError(
        "Timeout waiting for translate button. "
        f"translate_enabled={translate_enabled} "
        f"translate_disabled_attr={disabled_attr} "
        f"text_input_len={len(text_value)} "
        f"local_ai_state={local_ai_state}\n"
        f"app_log_tail:\n{log_tail}"
    )
