#!/usr/bin/env python3
"""Run Step 8 API gate checks for chat/responses and write artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib import error, request

MODEL_ID = "gpt-oss-swallow-120b-iq4xs"
HTTP_CODE_RE = re.compile(r"HTTP_CODE=(\d{3})")


@dataclass
class HttpResult:
    status: int
    body: dict


def post_json(url: str, api_key: str, payload: dict, timeout: float) -> HttpResult:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw) if raw else {}
            return HttpResult(status=int(resp.status), body=parsed if isinstance(parsed, dict) else {"data": parsed})
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"_raw": raw[:2000]}
        return HttpResult(status=int(exc.code), body=parsed if isinstance(parsed, dict) else {"data": parsed})
    except Exception as exc:
        return HttpResult(status=0, body={"_error": str(exc)})


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_chat_text(body: dict) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return str(msg.get("content") or "").strip()


def run_chat_gate(base_url: str, api_key: str, model_id: str, timeout: float, out_dir: Path) -> dict:
    oneshot_payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "3行で自己紹介してください。"}],
        "max_tokens": 128,
    }
    multi_payload = {
        "model": model_id,
        "messages": [
            {"role": "user", "content": "Pythonの辞書内包表記を1文で説明して。"},
            {
                "role": "assistant",
                "content": "辞書内包表記は、反復処理からキーと値を同時に作って辞書を簡潔に生成する書き方です。",
            },
            {"role": "user", "content": "では簡単な例を1つ。"},
        ],
        "max_tokens": 128,
    }

    oneshot = post_json(f"{base_url.rstrip('/')}/v1/chat/completions", api_key, oneshot_payload, timeout)
    multi = post_json(f"{base_url.rstrip('/')}/v1/chat/completions", api_key, multi_payload, timeout)

    write_json(out_dir / "chat_gate_oneshot.json", oneshot.body)
    write_json(out_dir / "chat_gate_multi.json", multi.body)

    return {
        "oneshot_http": oneshot.status,
        "multi_http": multi.status,
        "oneshot_has_text": int(bool(extract_chat_text(oneshot.body))),
        "multi_has_text": int(bool(extract_chat_text(multi.body))),
        "passed": int(200 <= oneshot.status < 300 and 200 <= multi.status < 300),
    }


def run_responses_non_stream(base_url: str, api_key: str, model_id: str, timeout: float, out_dir: Path) -> dict:
    payload = {
        "model": model_id,
        "input": "疎通確認です。OKだけ返してください。",
        "stream": False,
        "max_output_tokens": 32,
    }
    result = post_json(f"{base_url.rstrip('/')}/v1/responses", api_key, payload, timeout)
    write_json(out_dir / "resp_gate_non_stream.json", result.body)
    return {
        "http": result.status,
        "has_output_text": int(bool(str(result.body.get("output_text") or "").strip())),
        "passed": int(200 <= result.status < 300),
    }


def run_responses_stream(
    base_url: str,
    api_key: str,
    model_id: str,
    connect_timeout: float,
    max_time: float,
    out_dir: Path,
) -> dict:
    stream_path = out_dir / "resp_gate_stream.txt"
    payload = {
        "model": model_id,
        "input": "stream疎通確認です。短く答えてください。",
        "stream": True,
        "max_output_tokens": 32,
    }

    cmd = [
        "curl",
        "-sS",
        "-N",
        "--connect-timeout",
        str(connect_timeout),
        "--max-time",
        str(max_time),
        f"{base_url.rstrip('/')}/v1/responses",
        "-H",
        "Content-Type: application/json",
        "-H",
        "Accept: text/event-stream",
        "-H",
        f"x-api-key: {api_key}",
        "-d",
        json.dumps(payload, ensure_ascii=False),
        "-o",
        str(stream_path),
        "-w",
        "HTTP_CODE=%{http_code}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    m = HTTP_CODE_RE.search((proc.stdout or "").strip())
    http_code = int(m.group(1)) if m else 0

    text = stream_path.read_text(encoding="utf-8", errors="ignore") if stream_path.exists() else ""
    completed_ok = ("response.completed" in text) or ("[DONE]" in text)
    delta_ok = ("response.output_text.delta" in text) or ("response.output_text.done" in text) or ('"delta"' in text)
    event_ok = int(completed_ok and delta_ok)
    passed = int(200 <= http_code < 300 and event_ok == 1)

    if proc.stderr.strip():
        err_path = out_dir / "resp_gate_stream.stderr.txt"
        err_path.write_text(proc.stderr.strip() + "\n", encoding="utf-8")

    return {
        "http": http_code,
        "event_ok": event_ok,
        "passed": passed,
    }


def recommend_action(chat: dict, non_stream: dict, stream: dict) -> str:
    chat_ok = bool(chat["passed"])
    resp_ok = bool(non_stream["passed"] and stream["passed"])
    all_codes = [
        int(chat["oneshot_http"]),
        int(chat["multi_http"]),
        int(non_stream["http"]),
        int(stream["http"]),
    ]

    if any(code in {401, 403} for code in all_codes):
        return "認証またはallowlistを見直してください（Step 6を再確認）。"
    if any(code in {400, 404, 405, 501} for code in (int(non_stream["http"]), int(stream["http"]))):
        return "responses互換不足の可能性が高いです。Step 8-3（responses->chat変換）を実施してください。"
    if chat_ok and resp_ok:
        return "Step 9-0 / Step 9 へ進んでください。"
    if chat_ok and not resp_ok:
        return "Step 8-3を適用してresponsesゲートを再実行してください。"
    if not chat_ok:
        return "Step 6/7（認証・起動）を再点検してから再実行してください。"
    return "ログを確認し、Step 8ゲートを再実行してください。"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 8 gate checker (chat + responses)")
    parser.add_argument("--base-url", required=True, help="e.g. https://<pod-id>-11434.proxy.runpod.net")
    parser.add_argument("--api-key", default="", help="x-api-key value. If empty, SWALLOW_API_KEY is used.")
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--output-dir", default="/workspace/logs")
    parser.add_argument("--timeout", type=float, default=120.0, help="non-stream request timeout seconds")
    parser.add_argument("--connect-timeout", type=float, default=10.0, help="stream connect timeout seconds")
    parser.add_argument("--max-time", type=float, default=120.0, help="stream max time seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = args.api_key or os.getenv("SWALLOW_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ERROR: --api-key か SWALLOW_API_KEY が必要です。")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chat = run_chat_gate(args.base_url, api_key, args.model_id, args.timeout, out_dir)
    non_stream = run_responses_non_stream(args.base_url, api_key, args.model_id, args.timeout, out_dir)
    stream = run_responses_stream(
        args.base_url,
        api_key,
        args.model_id,
        connect_timeout=args.connect_timeout,
        max_time=args.max_time,
        out_dir=out_dir,
    )

    recommendation = recommend_action(chat=chat, non_stream=non_stream, stream=stream)
    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "model_id": args.model_id,
        "chat_gate": chat,
        "responses_non_stream_gate": non_stream,
        "responses_stream_gate": stream,
        "step8_1_passed": int(bool(chat["passed"])),
        "step8_2_passed": int(bool(non_stream["passed"] and stream["passed"])),
        "recommendation": recommendation,
    }

    summary_json = out_dir / "step8_gate_summary.json"
    write_json(summary_json, summary)

    summary_lines = [
        f"# step8_gate_summary {summary['timestamp']}",
        f"base_url={args.base_url}",
        f"chat_oneshot_http={chat['oneshot_http']} chat_multi_http={chat['multi_http']} step8_1_passed={summary['step8_1_passed']}",
        f"responses_non_stream_http={non_stream['http']} responses_stream_http={stream['http']} stream_event_ok={stream['event_ok']} step8_2_passed={summary['step8_2_passed']}",
        f"recommendation={recommendation}",
        f"summary_json={summary_json}",
    ]
    summary_txt = out_dir / "step8_gate_summary.txt"
    summary_txt.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))


if __name__ == "__main__":
    main()
