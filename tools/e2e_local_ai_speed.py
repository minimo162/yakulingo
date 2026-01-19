from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

DEFAULT_URL = "http://127.0.0.1:8765/"
DEFAULT_TIMEOUT_S = 300
DEFAULT_TRANSLATE_BUTTON_READY_TIMEOUT_S = 30
DEFAULT_LOG_DIR_NAME = ".tmp"
DEFAULT_INPUT_TEXT = "This is a local AI speed test."
_RE_TRANSLATION_COMPLETED = re.compile(
    r"Translation \[[^\]]+\] completed in ([0-9.]+)s"
)
_RE_TRANSLATION_ELAPSED = re.compile(
    r"Translation \[[^\]]+\] end_time: .*?elapsed_time: ([0-9.]+)s"
)
_RE_TRANSLATION_PREP = re.compile(r"prep_time: ([0-9.]+)s since button click")
_RE_LOCAL_AI_WARMUP_FINISHED = re.compile(r"LocalAI warmup finished: ([0-9.]+)s")


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _commit_text_input(text_input) -> None:
    text_input.blur()
    text_input.dispatch_event("change")


def _wait_for_translate_button_enabled(
    translate_button,
    *,
    timeout_s: float,
    local_status=None,
    text_input=None,
    app_log_path: Optional[Path] = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    deadline = monotonic() + timeout_s
    while monotonic() < deadline:
        if translate_button.is_enabled():
            return
        sleep(0.1)

    details: list[str] = []
    try:
        details.append(f"translate_enabled={translate_button.is_enabled()}")
    except Exception as exc:
        details.append(f"translate_enabled=<error:{exc}>")
    try:
        details.append(
            f"translate_disabled_attr={translate_button.get_attribute('disabled')}"
        )
    except Exception as exc:
        details.append(f"translate_disabled_attr=<error:{exc}>")

    if text_input is not None:
        try:
            value = text_input.input_value()
            details.append(f"text_input_len={len(value)}")
        except Exception as exc:
            details.append(f"text_input_len=<error:{exc}>")

    if local_status is not None:
        try:
            details.append(f"local_ai_state={local_status.get_attribute('data-state')}")
        except Exception as exc:
            details.append(f"local_ai_state=<error:{exc}>")
        try:
            details.append(f"local_ai_text={local_status.inner_text()}")
        except Exception:
            pass

    if app_log_path is not None:
        tail = _read_log_tail(app_log_path)
        if tail:
            details.append("app_log_tail:")
            details.append(tail)

    message = (
        f"Translate button did not become enabled within {timeout_s}s.\n"
        + "\n".join(details)
    ).strip()
    raise TimeoutError(message)


_NO_PROXY_OPENER: Optional[urllib.request.OpenerDirector] = None


def _is_local_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    return host in ("127.0.0.1", "localhost", "::1")


def _get_no_proxy_opener() -> urllib.request.OpenerDirector:
    global _NO_PROXY_OPENER
    opener = _NO_PROXY_OPENER
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        _NO_PROXY_OPENER = opener
    return opener


def _proxy_env_summary() -> str:
    def _is_set(*keys: str) -> bool:
        return any(bool(os.environ.get(key)) for key in keys)

    parts = [
        f"http_proxy={'set' if _is_set('HTTP_PROXY', 'http_proxy') else 'unset'}",
        f"https_proxy={'set' if _is_set('HTTPS_PROXY', 'https_proxy') else 'unset'}",
        f"all_proxy={'set' if _is_set('ALL_PROXY', 'all_proxy') else 'unset'}",
        f"no_proxy={'set' if _is_set('NO_PROXY', 'no_proxy') else 'unset'}",
    ]
    return "proxy_env(" + ", ".join(parts) + ")"


def _open_url(url: str, *, timeout_s: float):
    if _is_local_url(url):
        return _get_no_proxy_opener().open(url, timeout=timeout_s)
    return urllib.request.urlopen(url, timeout=timeout_s)


def _is_http_ready(url: str, timeout_s: float = 1.0) -> bool:
    try:
        with _open_url(url, timeout_s=timeout_s) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return int(getattr(exc, "code", 0) or 0) < 500
    except urllib.error.URLError:
        return False


def _wait_for_http(
    url: str,
    timeout_s: int,
    *,
    proc: Optional[subprocess.Popen] = None,
    log_path: Optional[Path] = None,
) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Optional[str] = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            tail = _read_log_tail(log_path) if log_path else ""
            last = (
                f"Last HTTP error: {last_error}"
                if last_error
                else "Last HTTP error: <none>"
            )
            raise RuntimeError(
                f"App exited before HTTP was ready (code={proc.returncode}).\n"
                f"{_proxy_env_summary()}\n{last}\n{tail}"
            )
        try:
            with _open_url(url, timeout_s=2.0) as response:
                if response.status < 500:
                    return
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            last_error = f"HTTPError(code={code}): {exc}"
            if code < 500:
                return
        except urllib.error.URLError as exc:
            last_error = f"URLError: {exc}"
        time.sleep(0.5)
    tail = _read_log_tail(log_path) if log_path else ""
    last = f"Last HTTP error: {last_error}" if last_error else "Last HTTP error: <none>"
    raise TimeoutError(
        f"Server did not respond within {timeout_s}s: {url}\n"
        f"{_proxy_env_summary()}\n{last}\n{tail}"
    )


def _load_default_text(repo_root: Path) -> str:
    input_path = repo_root / "tools" / "bench_local_ai_input.txt"
    if input_path.exists():
        try:
            content = input_path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception as exc:
            _log(f"Failed to read {input_path}: {exc}")
    return DEFAULT_INPUT_TEXT


def _start_app(
    repo_root: Path,
    env: dict[str, str],
    *,
    stdout,
    stderr,
) -> subprocess.Popen:
    cmd = [sys.executable, "-u", "app.py"]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        env=env,
        stdout=stdout,
        stderr=stderr,
        creationflags=creationflags,
    )


def _stop_app(proc: subprocess.Popen, timeout_s: int = 15) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()


def _extract_elapsed_seconds(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _default_log_path(repo_root: Path) -> Path:
    log_dir = repo_root / DEFAULT_LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return log_dir / f"e2e_local_ai_app_{stamp}.log"


def _read_log_tail(
    path: Optional[Path], max_bytes: int = 8192, max_lines: int = 80
) -> str:
    if path is None:
        return ""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return ""
    if not data:
        return ""
    tail = data[-max_bytes:]
    text = tail.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return _sanitize_text_for_console("\n".join(lines).strip())


def _sanitize_text_for_console(text: str) -> str:
    try:
        text.encode("cp932")
        return text
    except UnicodeEncodeError:
        return text.encode("cp932", errors="replace").decode("cp932")


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace") + b"\n")


def _parse_translation_elapsed_from_log(path: Optional[Path]) -> Optional[float]:
    text = _read_log_tail(path)
    if not text:
        return None
    matches = _RE_TRANSLATION_COMPLETED.findall(text)
    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            return None
    matches = _RE_TRANSLATION_ELAPSED.findall(text)
    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            return None
    return None


def _parse_translation_prep_from_log(path: Optional[Path]) -> Optional[float]:
    text = _read_log_tail(path)
    if not text:
        return None
    matches = _RE_TRANSLATION_PREP.findall(text)
    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            return None
    return None


def _parse_local_ai_warmup_from_log(path: Optional[Path]) -> Optional[float]:
    text = _read_log_tail(path)
    if not text:
        return None
    matches = _RE_LOCAL_AI_WARMUP_FINISHED.findall(text)
    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            return None
    return None


def _run_e2e(
    *,
    url: str,
    input_text: str,
    startup_timeout_s: int,
    translation_timeout_s: int,
    app_log_path: Optional[Path] = None,
    headless: bool,
) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            t_page_start = time.perf_counter()
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=startup_timeout_s * 1000,
            )
            page.wait_for_selector(
                '[data-testid="text-input"]', timeout=startup_timeout_s * 1000
            )
            t_page_ready = time.perf_counter()
            page_ready_seconds = t_page_ready - t_page_start

            backend_toggle = page.locator('[data-testid="backend-toggle"]')
            local_status = page.locator('[data-testid="local-ai-status"]')
            if local_status.count() == 0:
                if backend_toggle.count() == 0:
                    raise RuntimeError(
                        "Backend toggle not found; cannot switch to Local AI"
                    )
                backend_toggle.first.click()

            local_status.wait_for(timeout=startup_timeout_s * 1000)
            try:
                ready_status = page.locator(
                    '[data-testid="local-ai-status"][data-state="ready"]'
                )
                ready_status.wait_for(timeout=startup_timeout_s * 1000)
                t_local_ready = time.perf_counter()
                local_ai_ready_seconds = t_local_ready - t_page_ready
            except PlaywrightTimeoutError as exc:
                status_state = (
                    local_status.get_attribute("data-state")
                    if local_status.count()
                    else ""
                )
                status_text = local_status.inner_text() if local_status.count() else ""
                raise RuntimeError(
                    f"Local AI not ready (state={status_state} text={status_text})"
                ) from exc

            text_input = page.get_by_test_id("text-input")
            text_input.fill(input_text)
            _commit_text_input(text_input)
            translate_button = page.get_by_test_id("translate-button")
            translate_ready_timeout_s = min(
                float(translation_timeout_s),
                float(startup_timeout_s),
                float(DEFAULT_TRANSLATE_BUTTON_READY_TIMEOUT_S),
            )
            _wait_for_translate_button_enabled(
                translate_button,
                timeout_s=translate_ready_timeout_s,
                local_status=local_status if local_status.count() else None,
                text_input=text_input,
                app_log_path=app_log_path,
            )
            t_translate_start = time.perf_counter()
            translate_button.click()
            status = page.get_by_test_id("translation-status")
            preview_label = page.locator(".streaming-preview .streaming-text")
            preview_first_at: float | None = None
            preview_first_chars: int | None = None
            translation_seconds_source = "ui"
            translation_elapsed_logged = None
            status_state = ""
            deadline = time.monotonic() + translation_timeout_s
            next_log_poll_at = time.monotonic()
            while time.monotonic() < deadline:
                if preview_first_at is None and preview_label.count():
                    try:
                        preview_text = preview_label.first.inner_text().strip()
                    except Exception:
                        preview_text = ""
                    if preview_text:
                        preview_first_at = time.perf_counter()
                        preview_first_chars = len(preview_text)
                if status.count():
                    status_state = status.get_attribute("data-state") or ""
                    if status_state == "done":
                        break
                if time.monotonic() >= next_log_poll_at:
                    translation_elapsed_logged = _parse_translation_elapsed_from_log(
                        app_log_path
                    )
                    if translation_elapsed_logged is not None:
                        translation_seconds_source = "log"
                        break
                    next_log_poll_at = time.monotonic() + 0.5
                time.sleep(0.1)
            else:
                status_text = status.inner_text() if status.count() else ""
                raise RuntimeError(
                    f"Translation did not complete (state={status_state} text={status_text})"
                )
            t_translate_done = time.perf_counter()

            elapsed_badge = None
            badge = page.locator(
                '[data-testid="translation-status"] .elapsed-time-badge'
            )
            if badge.count():
                elapsed_badge = _extract_elapsed_seconds(badge.first.inner_text())
        finally:
            browser.close()

    translation_prep_logged = _parse_translation_prep_from_log(app_log_path)
    local_ai_warmup_logged = _parse_local_ai_warmup_from_log(app_log_path)
    ttlc_seconds = t_translate_done - t_translate_start
    ttft_seconds = (
        preview_first_at - t_translate_start if preview_first_at is not None else None
    )
    result: dict[str, Any] = {
        "page_ready_seconds": page_ready_seconds,
        "local_ai_ready_seconds": local_ai_ready_seconds,
        "local_ai_ready_source": "ui",
        "ttft_seconds": ttft_seconds,
        "ttlc_seconds": ttlc_seconds,
        "translation_seconds": ttlc_seconds,
        "elapsed_badge_seconds": elapsed_badge,
        "translation_seconds_source": translation_seconds_source,
    }
    if preview_first_chars is not None:
        result["ttft_preview_chars"] = preview_first_chars
    if translation_elapsed_logged is not None:
        result["translation_elapsed_logged"] = translation_elapsed_logged
    if translation_prep_logged is not None:
        result["translation_prep_seconds_logged"] = translation_prep_logged
    if local_ai_warmup_logged is not None:
        result["local_ai_warmup_seconds_logged"] = local_ai_warmup_logged
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure Local AI translation speed via browser UI (Playwright)."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="NiceGUI base URL")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help="Timeout seconds for startup and translation",
    )
    parser.add_argument(
        "--startup-timeout",
        type=int,
        default=None,
        help="Timeout seconds for app startup and Local AI readiness",
    )
    parser.add_argument(
        "--translation-timeout",
        type=int,
        default=None,
        help="Timeout seconds for translation completion",
    )
    parser.add_argument(
        "--text",
        default=None,
        help="Input text for translation (default: bench_local_ai_input.txt)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Playwright in headed mode",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write JSON result to file",
    )
    parser.add_argument(
        "--app-log",
        default=None,
        help="Write app stdout/stderr to this log file",
    )
    parser.add_argument(
        "--keep-app",
        action="store_true",
        help="Do not terminate the app process after measurement",
    )
    parser.add_argument(
        "--disable-streaming-preview",
        action="store_true",
        help="Disable Local AI streaming preview updates in the UI.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env.setdefault("YAKULINGO_NO_AUTO_OPEN", "1")
    env.setdefault("YAKULINGO_RESIDENT_UI_MODE", "browser")
    env.setdefault("YAKULINGO_LAUNCH_SOURCE", "e2e_local_ai_speed")
    streaming_preview_disabled = bool(args.disable_streaming_preview)
    if streaming_preview_disabled:
        env["YAKULINGO_DISABLE_LOCAL_STREAMING_PREVIEW"] = "1"

    startup_timeout_s = args.startup_timeout or args.timeout
    translation_timeout_s = args.translation_timeout or args.timeout
    input_text = args.text if args.text is not None else _load_default_text(repo_root)

    t0 = time.perf_counter()
    proc: subprocess.Popen | None = None
    log_fp = None
    log_path = Path(args.app_log) if args.app_log else _default_log_path(repo_root)
    stage = "init"
    result: dict[str, Any] = {
        "ok": False,
        "streaming_preview_disabled": streaming_preview_disabled,
    }
    return_code = 1
    try:
        stage = "precheck"
        if _is_http_ready(args.url):
            raise RuntimeError(f"App already running on {args.url}")
        _log("Starting app...")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fp = open(log_path, "wb")
        stage = "start_app"
        proc = _start_app(repo_root, env, stdout=log_fp, stderr=log_fp)
        stage = "wait_http"
        _wait_for_http(
            args.url,
            startup_timeout_s,
            proc=proc,
            log_path=log_path,
        )
        t_ready = time.perf_counter()
        stage = "run_e2e"
        metrics = _run_e2e(
            url=args.url,
            input_text=input_text,
            startup_timeout_s=startup_timeout_s,
            translation_timeout_s=translation_timeout_s,
            app_log_path=log_path,
            headless=not args.headed,
        )
        t_done = time.perf_counter()
        result = {
            "ok": True,
            "stage": stage,
            "url": args.url,
            "app_log_path": str(log_path),
            "streaming_preview_disabled": streaming_preview_disabled,
            "startup_timeout_s": startup_timeout_s,
            "translation_timeout_s": translation_timeout_s,
            "app_start_seconds": t_ready - t0,
            "total_seconds": t_done - t0,
            **metrics,
        }
    except Exception as exc:
        if log_fp:
            try:
                log_fp.flush()
            except Exception:
                pass
        app_exit_code = proc.returncode if proc else None
        result = {
            "ok": False,
            "stage": stage,
            "error": str(exc),
            "url": args.url,
            "app_log_path": str(log_path),
            "streaming_preview_disabled": streaming_preview_disabled,
            "app_exit_code": app_exit_code,
            "startup_timeout_s": startup_timeout_s,
            "translation_timeout_s": translation_timeout_s,
            "total_seconds": time.perf_counter() - t0,
            "app_log_tail": _read_log_tail(log_path),
        }
        _log(f"E2E failed (stage={stage}): {exc}")
        return_code = 1
    else:
        return_code = 0
    finally:
        if proc is not None and not args.keep_app:
            _stop_app(proc)
        if log_fp is not None:
            try:
                log_fp.flush()
            except Exception:
                pass
            try:
                log_fp.close()
            except Exception:
                pass

    output = json.dumps(result, ensure_ascii=False)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
    _safe_print(output)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
