#!/usr/bin/env python3
import argparse
import csv
import json
import math
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

JA_PROMPT = "次の要件を満たすPythonのCSVパーサー用ユニットテストを作成してください。境界値、空行、引用符、文字コード混在を含める。"
EN_PROMPT = "Write Python unit tests for a CSV parser, covering edge cases, quotes, empty rows, and encoding issues."
MODEL_ID = "gpt-oss-swallow-120b-iq4xs"
METRICS_RE = re.compile(r"HTTP=(\d+) TOTAL=([0-9.]+) TTFB=([0-9.]+)")


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, math.ceil(len(ordered) * pct / 100) - 1)
    return ordered[idx]


def make_payload(tokens: int, rid: int) -> dict:
    prompt = JA_PROMPT if rid % 2 == 0 else EN_PROMPT
    return {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": tokens,
    }


def run_one(
    base_url: str,
    api_key: str,
    parallel: int,
    tokens: int,
    rid: int,
    connect_timeout: float,
    max_time: float,
) -> dict:
    payload = make_payload(tokens=tokens, rid=rid)
    with tempfile.NamedTemporaryFile(prefix=f"step9_{parallel}_{tokens}_{rid}_", suffix=".json", delete=False) as tf:
        resp_path = Path(tf.name)
    curl_cfg_path: Path | None = None
    # APIキーをプロセス引数に露出させないため、curl --config を使う
    with tempfile.NamedTemporaryFile(prefix="step9_curl_", suffix=".cfg", delete=False, mode="w", encoding="utf-8") as cf:
        curl_cfg_path = Path(cf.name)
        cf.write('header = "Content-Type: application/json"\n')
        cf.write(f'header = "x-api-key: {api_key}"\n')

    cmd = [
        "curl",
        "-sS",
        "--connect-timeout",
        str(connect_timeout),
        "--max-time",
        str(max_time),
        "--config",
        str(curl_cfg_path),
        f"{base_url}/v1/chat/completions",
    ]
    cmd.extend(
        [
            "-d",
            json.dumps(payload, ensure_ascii=False),
            "-o",
            str(resp_path),
            "-w",
            "HTTP=%{http_code} TOTAL=%{time_total} TTFB=%{time_starttransfer}",
        ]
    )

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    metrics_line = proc.stdout.strip()
    m = METRICS_RE.search(metrics_line)

    http_code = 0
    total = 0.0
    ttfb = 0.0
    if m:
        http_code = int(m.group(1))
        total = float(m.group(2))
        ttfb = float(m.group(3))

    completion_tokens = 0
    try:
        body = json.loads(resp_path.read_text(encoding="utf-8", errors="ignore"))
        completion_tokens = int((body.get("usage") or {}).get("completion_tokens") or 0)
    except Exception:
        completion_tokens = 0
    finally:
        resp_path.unlink(missing_ok=True)
        if curl_cfg_path is not None:
            curl_cfg_path.unlink(missing_ok=True)

    decode_window = max(total - ttfb, 0.0)
    tok_per_sec = (completion_tokens / decode_window) if (completion_tokens > 0 and decode_window > 0) else 0.0

    return {
        "parallel": parallel,
        "tokens": tokens,
        "req_id": rid,
        "http": http_code,
        "total": total,
        "ttfb": ttfb,
        "completion_tokens": completion_tokens,
        "tok_per_sec": tok_per_sec,
        "stderr": proc.stderr.strip(),
    }


def warmup(base_url: str, api_key: str, connect_timeout: float, max_time: float, n: int = 10) -> None:
    for rid in range(1, n + 1):
        _ = run_one(
            base_url,
            api_key,
            parallel=1,
            tokens=128,
            rid=rid,
            connect_timeout=connect_timeout,
            max_time=max_time,
        )


def run_case(
    base_url: str,
    api_key: str,
    parallel: int,
    tokens: int,
    reqs: int,
    connect_timeout: float,
    max_time: float,
) -> list[dict]:
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futures = [
            ex.submit(
                run_one,
                base_url,
                api_key,
                parallel,
                tokens,
                rid,
                connect_timeout,
                max_time,
            )
            for rid in range(1, reqs + 1)
        ]
        for f in as_completed(futures):
            rows.append(f.result())
    rows.sort(key=lambda x: x["req_id"])
    return rows


def summarize(rows: list[dict], parallel: int, tokens: int, reqs: int) -> str:
    target = [r for r in rows if r["parallel"] == parallel and r["tokens"] == tokens]
    ok = [r for r in target if 200 <= r["http"] < 300]
    success_rate = (len(ok) / len(target) * 100) if target else 0.0
    p95_ttfb = percentile([r["ttfb"] for r in ok], 95)
    p95_total = percentile([r["total"] for r in ok], 95)
    tokps_median = percentile([r["tok_per_sec"] for r in ok], 50)
    fail_count = len(target) - len(ok)
    return (
        f"parallel={parallel} tokens={tokens} reqs={reqs} "
        f"success_rate={success_rate:.2f}% ok={len(ok)} fail={fail_count} "
        f"p95_ttfb={(p95_ttfb if p95_ttfb is not None else float('nan')):.3f}s "
        f"p95_total={(p95_total if p95_total is not None else float('nan')):.3f}s "
        f"tokps_median={(tokps_median if tokps_median is not None else float('nan')):.3f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--csv-log", required=True)
    parser.add_argument("--summary-log", required=True)
    parser.add_argument("--short-tokens", type=int, default=256)
    parser.add_argument("--short-reqs", type=int, default=30)
    parser.add_argument("--long-tokens", type=int, default=1024)
    parser.add_argument("--long-reqs", type=int, default=10)
    parser.add_argument("--parallels", default="1,2,3")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--max-time", type=float, default=180.0)
    parser.add_argument("--warmup-reqs", type=int, default=10)
    parser.add_argument("--short-only", action="store_true")
    args = parser.parse_args()

    parallels = [int(x.strip()) for x in args.parallels.split(",") if x.strip()]
    rows: list[dict] = []

    warmup(
        args.base_url,
        args.api_key,
        connect_timeout=args.connect_timeout,
        max_time=args.max_time,
        n=args.warmup_reqs,
    )

    for par in parallels:
        rows.extend(
            run_case(
                args.base_url,
                args.api_key,
                par,
                args.short_tokens,
                args.short_reqs,
                connect_timeout=args.connect_timeout,
                max_time=args.max_time,
            )
        )

    if not args.short_only:
        for par in parallels:
            rows.extend(
                run_case(
                    args.base_url,
                    args.api_key,
                    par,
                    args.long_tokens,
                    args.long_reqs,
                    connect_timeout=args.connect_timeout,
                    max_time=args.max_time,
                )
            )

    csv_path = Path(args.csv_log)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["parallel", "tokens", "req_id", "http", "total", "ttfb", "completion_tokens", "tok_per_sec"])
        for r in rows:
            writer.writerow([
                r["parallel"],
                r["tokens"],
                r["req_id"],
                r["http"],
                f"{r['total']:.6f}",
                f"{r['ttfb']:.6f}",
                r["completion_tokens"],
                f"{r['tok_per_sec']:.6f}",
            ])

    summary_lines = [f"# summary: {datetime.now().isoformat(timespec='seconds')} base_url={args.base_url}"]
    for par in parallels:
        summary_lines.append(summarize(rows, par, args.short_tokens, args.short_reqs))
    if not args.short_only:
        for par in parallels:
            summary_lines.append(summarize(rows, par, args.long_tokens, args.long_reqs))

    summary_path = Path(args.summary_log)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))
    print(f"raw_csv: {csv_path}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
