from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def _measure(label: str, fn, *, runs: int) -> list[float]:
    durations: list[float] = []
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        fn()
        durations.append(time.perf_counter() - t0)
    _print_stats(label, durations)
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
    parser = argparse.ArgumentParser(description="LocalPromptBuilder micro-bench (serverless)")
    parser.add_argument("--glossary-rows", type=int, default=20000)
    parser.add_argument("--input-chars", type=int, default=800)
    parser.add_argument("--items", type=int, default=12)
    parser.add_argument("--runs", type=int, default=50)
    args = parser.parse_args()

    repo_root = _repo_root()
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
    input_text = (base_input * ((args.input_chars // len(base_input)) + 1))[: args.input_chars]
    match_terms = ["revenue", "operating", "EBITDA", "guidance", "pipeline", "conversion"]

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
            lambda: builder.build_reference_embed([glossary_path], input_text=input_text),
            runs=1,
        )
        # 2) build_reference_embed: cache-hit
        _measure(
            "build_reference_embed (cache hit)",
            lambda: builder.build_reference_embed([glossary_path], input_text=input_text),
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
