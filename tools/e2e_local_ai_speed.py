from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect, sync_playwright

DEFAULT_URL = "http://127.0.0.1:8765/"
DEFAULT_TIMEOUT_S = 300
DEFAULT_INPUT_TEXT = "This is a local AI speed test."


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _wait_for_http(url: str, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Server did not respond within {timeout_s}s: {url}")


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


def _start_app(repo_root: Path, env: dict[str, str]) -> subprocess.Popen:
    cmd = [sys.executable, "-u", "app.py"]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
    cleaned = text.strip().replace("秒", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _run_e2e(
    *,
    url: str,
    input_text: str,
    timeout_s: int,
    headless: bool,
) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(
                '[data-testid="text-input"]', timeout=timeout_s * 1000
            )

            backend_toggle = page.locator('[data-testid="backend-toggle"]')
            local_status = page.locator('[data-testid="local-ai-status"]')
            if local_status.count() == 0:
                if backend_toggle.count() == 0:
                    raise RuntimeError(
                        "Backend toggle not found; cannot switch to Local AI"
                    )
                backend_toggle.first.click()

            local_status.wait_for(timeout=timeout_s * 1000)
            try:
                ready_status = page.locator(
                    '[data-testid="local-ai-status"][data-state="ready"]'
                )
                ready_status.wait_for(timeout=timeout_s * 1000)
            except PlaywrightTimeoutError as exc:
                status_state = (
                    local_status.get_attribute("data-state") if local_status.count() else ""
                )
                raise RuntimeError(f"Local AI not ready (state={status_state})") from exc

            page.get_by_test_id("text-input").fill(input_text)
            t_translate_start = time.perf_counter()
            page.get_by_test_id("translate-button").click()
            status = page.locator(
                '[data-testid="translation-status"][data-state="done"]'
            )
            status.wait_for(timeout=timeout_s * 1000)
            t_translate_done = time.perf_counter()

            elapsed_badge = None
            badge = page.locator(
                '[data-testid="translation-status"] .elapsed-time-badge'
            )
            if badge.count():
                elapsed_badge = _extract_elapsed_seconds(badge.first.inner_text())
        finally:
            browser.close()

    return {
        "translation_seconds": t_translate_done - t_translate_start,
        "elapsed_badge_seconds": elapsed_badge,
    }


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
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env.setdefault("YAKULINGO_NO_AUTO_OPEN", "1")
    env.setdefault("YAKULINGO_RESIDENT_UI_MODE", "browser")
    env.setdefault("YAKULINGO_LAUNCH_SOURCE", "e2e_local_ai_speed")

    input_text = args.text if args.text is not None else _load_default_text(repo_root)

    t0 = time.perf_counter()
    proc: subprocess.Popen | None = None
    result: dict[str, Any] = {"ok": False}
    try:
        _log("Starting app...")
        proc = _start_app(repo_root, env)
        _wait_for_http(args.url, args.timeout)
        t_ready = time.perf_counter()
        metrics = _run_e2e(
            url=args.url,
            input_text=input_text,
            timeout_s=args.timeout,
            headless=not args.headed,
        )
        t_done = time.perf_counter()
        result = {
            "ok": True,
            "url": args.url,
            "app_start_seconds": t_ready - t0,
            "total_seconds": t_done - t0,
            **metrics,
        }
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        _log(f"E2E failed: {exc}")
        return_code = 1
    else:
        return_code = 0
    finally:
        if proc is not None:
            _stop_app(proc)

    output = json.dumps(result, ensure_ascii=False)
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(output, encoding="utf-8")
    print(output)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
