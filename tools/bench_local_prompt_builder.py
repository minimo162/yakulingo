from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_git_command(repo_root: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            return None
        output = (completed.stdout or "").strip()
        return output or None
    except Exception:
        return None


def _git_is_dirty(repo_root: Path) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            return None
        return bool((completed.stdout or "").strip())
    except Exception:
        return None


def _collect_git_metadata(repo_root: Path) -> dict[str, Any]:
    return {
        "commit": _run_git_command(repo_root, ["rev-parse", "HEAD"]),
        "commit_short": _run_git_command(repo_root, ["rev-parse", "--short", "HEAD"]),
        "dirty": _git_is_dirty(repo_root),
    }


def _collect_runtime_metadata() -> dict[str, Any]:
    cpu_physical = None
    cpu_logical = None
    try:
        import psutil  # type: ignore[import-not-found]

        cpu_physical = psutil.cpu_count(logical=False)
        cpu_logical = psutil.cpu_count(logical=True)
    except Exception:
        cpu_logical = os.cpu_count()

    return {
        "platform": platform.platform(aliased=True, terse=True),
        "python": sys.version.split()[0],
        "cpu_physical_cores": cpu_physical,
        "cpu_logical_cores": cpu_logical,
    }


def _emit_json(
    payload: dict[str, Any], *, to_stdout: bool, out_path: Path | None
) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if out_path is not None:
        out_path.write_text(text, encoding="utf-8")
        print(f"json_out: {out_path}")
    if to_stdout:
        print(text)


_RESULTS: list[dict[str, Any]] | None = None


repo_root = _repo_root()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from yakulingo.config.settings import AppSettings  # noqa: E402
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder  # noqa: E402
from yakulingo.services.prompt_builder import PromptBuilder  # noqa: E402


def _write_glossary(path: Path, *, rows: int, match_terms: list[str]) -> None:
    lines: list[str] = []
    for term in match_terms:
        lines.append(f"{term},{term.upper()}")
    remaining = max(0, int(rows) - len(lines))
    for idx in range(remaining):
        term = f"term{idx:06d}"
        lines.append(f"{term},{term}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stats_ms(durations: list[float]) -> dict[str, Any]:
    if not durations:
        return {"runs": 0, "p50_ms": None, "p95_ms": None}
    ms = [d * 1000.0 for d in durations]
    p50 = statistics.median(ms)
    p95 = statistics.quantiles(ms, n=20)[-1] if len(ms) >= 20 else max(ms)
    return {
        "runs": len(ms),
        "p50_ms": p50,
        "p95_ms": p95,
        "min_ms": min(ms),
        "max_ms": max(ms),
        "mean_ms": statistics.mean(ms),
    }


def _measure(label: str, fn, *, runs: int) -> list[float]:
    durations: list[float] = []
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        fn()
        durations.append(time.perf_counter() - t0)
    _print_stats(label, durations)
    if _RESULTS is not None:
        _RESULTS.append({"label": label, **_stats_ms(durations)})
    return durations


def _print_stats(label: str, durations: list[float]) -> None:
    if not durations:
        print(f"- {label}: (no data)")
        return
    ms = [d * 1000.0 for d in durations]
    p50 = statistics.median(ms)
    p95 = statistics.quantiles(ms, n=20)[-1] if len(ms) >= 20 else max(ms)
    print(f"- {label}: p50={p50:.2f}ms p95={p95:.2f}ms runs={len(ms)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LocalPromptBuilder micro-bench (serverless)"
    )
    parser.add_argument("--glossary-rows", type=int, default=20000)
    parser.add_argument("--input-chars", type=int, default=800)
    parser.add_argument("--items", type=int, default=12)
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--tag", type=str, default=None, help="Label for this run")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--out", type=Path, default=None, help="Write JSON to file")
    args = parser.parse_args()

    repo_root = _repo_root()
    started_at = _utc_now_iso()
    global _RESULTS
    _RESULTS = [] if (args.json or args.out) else None
    prompts_dir = repo_root / "prompts"
    settings = AppSettings()
    settings.use_bundled_glossary = False
    base = PromptBuilder(prompts_dir)
    builder = LocalPromptBuilder(
        prompts_dir, base_prompt_builder=base, settings=settings
    )

    base_input = (
        "売上高 revenue operating profit EBITDA growth YoY QoQ "
        "guidance forecast outlook pipeline conversion rate "
    )
    input_text = (base_input * ((args.input_chars // len(base_input)) + 1))[
        : args.input_chars
    ]
    match_terms = [
        "revenue",
        "operating",
        "EBITDA",
        "guidance",
        "pipeline",
        "conversion",
    ]

    with TemporaryDirectory(prefix="yakulingo_prompt_bench_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        glossary_path = tmp_path / "glossary.csv"
        _write_glossary(glossary_path, rows=args.glossary_rows, match_terms=match_terms)

        print("== LocalPromptBuilder micro-bench (serverless) ==")
        print(f"- glossary_rows={args.glossary_rows}")
        print(f"- input_chars={len(input_text)}")
        print(f"- items={args.items}")
        print(f"- runs={args.runs}")
        print("")

        # 1) build_reference_embed: first call (loads glossary + builds embed)
        _measure(
            "build_reference_embed (cold first)",
            lambda: builder.build_reference_embed(
                [glossary_path], input_text=input_text
            ),
            runs=1,
        )
        # 2) build_reference_embed: cache-hit
        _measure(
            "build_reference_embed (cache hit)",
            lambda: builder.build_reference_embed(
                [glossary_path], input_text=input_text
            ),
            runs=args.runs,
        )
        # 3) build_reference_embed: cache-miss (vary input), glossary cache stays warm
        _measure(
            "build_reference_embed (cache miss, glossary warm)",
            lambda: builder.build_reference_embed(
                [glossary_path], input_text=f"{input_text} #{time.time_ns()}"
            ),
            runs=args.runs,
        )

        texts = [f"{input_text}\n[{i}]" for i in range(max(1, args.items))]
        _measure(
            "build_batch (to_en)",
            lambda: builder.build_batch(
                texts,
                has_reference_files=True,
                output_language="en",
                translation_style="minimal",
                include_item_ids=True,
                reference_files=[glossary_path],
            ),
            runs=args.runs,
        )
        _measure(
            "build_text_to_en_3style",
            lambda: builder.build_text_to_en_3style(
                input_text,
                reference_files=[glossary_path],
                detected_language="日本語",
            ),
            runs=args.runs,
        )

    if args.json or args.out:
        payload = {
            "benchmark": "local-prompt-builder",
            "started_at": started_at,
            "tag": args.tag,
            "git": _collect_git_metadata(repo_root),
            "runtime": _collect_runtime_metadata(),
            "settings": {
                "glossary_rows": int(args.glossary_rows),
                "input_chars": len(input_text),
                "items": int(args.items),
                "runs": int(args.runs),
            },
            "results": _RESULTS or [],
        }
        _emit_json(payload, to_stdout=bool(args.json), out_path=args.out)
        _RESULTS = None

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
