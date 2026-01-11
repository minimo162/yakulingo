from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise SystemExit(f"Input file not found: {path}") from exc


def _build_prompt(
    builder: Any,
    text: str,
    reference_files: list[Path],
    style: str,
) -> str:
    return builder.build_text_to_en_single(
        text,
        style=style,
        reference_files=reference_files,
        detected_language="Japanese",
    )


def _translate_once(
    client: Any,
    text: str,
    prompt: str,
) -> tuple[str, float]:
    start = time.perf_counter()
    result = client.translate_single(text, prompt, reference_files=None, on_chunk=None)
    elapsed = time.perf_counter() - start
    return result, elapsed


def _translate_compare(
    service: Any,
    text: str,
    reference_files: list[Path],
) -> tuple[Any, float]:
    start = time.perf_counter()
    result = service.translate_text_with_style_comparison(
        text,
        reference_files=reference_files,
        styles=None,
        pre_detected_language=None,
        on_chunk=None,
    )
    elapsed = time.perf_counter() - start
    return result, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local AI benchmark (single or style-compare)"
    )
    parser.add_argument("--input", type=Path, default=None, help="Path to input text")
    parser.add_argument("--mode", choices=("warm", "cold"), default="warm")
    parser.add_argument(
        "--style", choices=("standard", "concise", "minimal"), default="concise"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Use TranslationService style comparison (combined + fallback).",
    )
    parser.add_argument("--with-glossary", action="store_true")
    parser.add_argument("--reference", action="append", type=Path, default=[])
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=None)

    args = parser.parse_args()

    repo_root = _repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from yakulingo.config.settings import AppSettings
    from yakulingo.services.local_llama_server import get_local_llama_server_manager
    from yakulingo.services.prompt_builder import PromptBuilder

    default_input = repo_root / "tools" / "bench_local_ai_input.txt"
    compare_input = repo_root / "tools" / "bench_local_ai_input_short.txt"
    if args.input:
        input_path = args.input
    elif args.compare:
        input_path = compare_input
    else:
        input_path = default_input
    text = _load_text(input_path)

    if args.compare:
        if len(text) > 800:
            print(
                f"WARNING: compare input is long ({len(text)} chars); JSON may truncate.",
                file=sys.stderr,
            )
            print(
                "HINT: use --input tools/bench_local_ai_input_short.txt or adjust "
                "--max-tokens (e.g. --max-tokens 1024 / --max-tokens 0).",
                file=sys.stderr,
            )
    else:
        if len(text) < 400 or len(text) > 800:
            print(
                "WARNING: input text length is outside 400-800 chars",
                file=sys.stderr,
            )

    reference_files: list[Path] = []
    if args.with_glossary:
        reference_files.append(repo_root / "glossary.csv")
    if args.reference:
        reference_files.extend(args.reference)

    settings = AppSettings()
    settings.translation_backend = "local"
    if args.max_tokens is not None:
        if args.max_tokens <= 0:
            settings.local_ai_max_tokens = None
        else:
            settings.local_ai_max_tokens = int(args.max_tokens)
    prompts_dir = repo_root / "prompts"
    if args.compare:
        from yakulingo.services.copilot_handler import CopilotHandler
        from yakulingo.services.translation_service import TranslationService

        service = TranslationService(
            CopilotHandler(),
            settings,
            prompts_dir=prompts_dir,
        )
        client = None
        prompt = None
    else:
        from yakulingo.services.local_ai_client import LocalAIClient
        from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder

        base_builder = PromptBuilder(prompts_dir)
        local_builder = LocalPromptBuilder(
            prompts_dir,
            base_prompt_builder=base_builder,
            settings=settings,
        )
        client = LocalAIClient(settings)
        prompt_start = time.perf_counter()
        prompt = _build_prompt(local_builder, text, reference_files, args.style)
        prompt_build_seconds = time.perf_counter() - prompt_start
        prompt_chars = len(prompt or "")

    if args.mode == "cold":
        # Stop existing local AI server (if safe) before measuring cold start.
        get_local_llama_server_manager().stop()
        warmup_runs = 0
    else:
        warmup_runs = max(0, int(args.warmup_runs))

    print("benchmark: local-ai")
    print(f"mode: {args.mode}")
    print(f"input_chars: {len(text)}")
    print(f"style: {args.style}")
    print(f"compare: {bool(args.compare)}")
    print(f"with_glossary: {bool(args.with_glossary)}")
    print(f"reference_files: {len(reference_files)}")
    print(f"effective_local_ai_ctx_size: {settings.local_ai_ctx_size}")
    print(f"effective_local_ai_max_tokens: {settings.local_ai_max_tokens}")
    if not args.compare:
        print(f"prompt_chars: {prompt_chars}")
        print(f"prompt_build_seconds: {prompt_build_seconds:.2f}")

    for i in range(warmup_runs):
        if args.compare:
            _, warmup_elapsed = _translate_compare(service, text, reference_files)
        else:
            _, warmup_elapsed = _translate_once(client, text, prompt)
        print(f"warmup_seconds[{i + 1}]: {warmup_elapsed:.2f}")

    if args.compare:
        result, elapsed = _translate_compare(service, text, reference_files)
        error = getattr(result, "error_message", None)
        options = getattr(result, "options", None) or []
        if error:
            print(f"error: {error}", file=sys.stderr)
        if not options:
            print("WARNING: empty style options", file=sys.stderr)
        output_chars = sum(
            len(getattr(opt, "text", "") or "")
            + len(getattr(opt, "explanation", "") or "")
            for opt in options
        )
        print(f"translation_seconds: {elapsed:.2f}")
        print(f"options: {len(options)}")
        print(f"output_chars: {output_chars}")
    else:
        output, elapsed = _translate_once(client, text, prompt)
        if not output.strip():
            print("WARNING: empty translation result", file=sys.stderr)

        total_seconds = prompt_build_seconds + elapsed
        print(f"translation_seconds: {elapsed:.2f}")
        print(f"total_seconds: {total_seconds:.2f}")
        print(f"output_chars: {len(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
