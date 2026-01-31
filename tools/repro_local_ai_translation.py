from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


Mode = Literal[
    "jp-to-en", "jp-to-en-3style", "en-to-jp", "batch-jp-to-en", "batch-en-to-jp"
]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _read_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def _write_optional(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Repro helper for YakuLingo local AI translation (HY-MT etc). "
            "Dumps prompt/raw output to files for debugging."
        )
    )
    parser.add_argument("--input", type=Path, required=True, help="UTF-8 text file")
    parser.add_argument(
        "--mode",
        type=str,
        default="jp-to-en",
        choices=(
            "jp-to-en",
            "jp-to-en-3style",
            "en-to-jp",
            "batch-jp-to-en",
            "batch-en-to-jp",
        ),
        help="Translation mode",
    )
    parser.add_argument(
        "--style",
        choices=("standard", "concise", "minimal"),
        default="minimal",
        help="JP->EN style (single/batch)",
    )
    parser.add_argument(
        "--restart-server",
        action="store_true",
        help="Stop existing local AI server before running",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Request timeout (s)")
    parser.add_argument("--dump-prompt", type=Path, default=None, help="Write prompt")
    parser.add_argument("--dump-raw", type=Path, default=None, help="Write raw output")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON (includes runtime metadata)",
    )

    args = parser.parse_args()
    mode: Mode = args.mode  # type: ignore[assignment]
    repo_root = _repo_root()
    prompts_dir = repo_root / "prompts"

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from yakulingo.config.settings import AppSettings, invalidate_settings_cache
    from yakulingo.services.local_ai_client import (
        LocalAIClient,
        parse_batch_translations,
        parse_text_single_translation,
        parse_text_to_en_3style,
    )
    from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
    from yakulingo.services.local_llama_server import (
        ensure_no_proxy_for_localhost,
        get_local_llama_server_manager,
    )
    from yakulingo.services.prompt_builder import PromptBuilder

    ensure_no_proxy_for_localhost()

    invalidate_settings_cache()
    settings = AppSettings.load(repo_root / "config" / "settings.json", use_cache=False)
    settings.translation_backend = "local"
    settings.copilot_enabled = False

    server_manager = get_local_llama_server_manager()
    if args.restart_server:
        server_manager.stop()

    builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=settings,
    )
    client = LocalAIClient(settings)
    runtime = client.ensure_ready()

    prompt = ""
    raw = ""
    parsed: object = None

    if mode == "jp-to-en":
        text = _read_text(args.input)
        prompt = builder.build_text_to_en_single(
            text,
            style=args.style,
            reference_files=None,
            detected_language="Japanese",
        )
        raw = client.translate_single(text, prompt, timeout=args.timeout)
        translation, explanation = parse_text_single_translation(raw)
        parsed = {"translation": translation or "", "explanation": explanation or ""}
    elif mode == "jp-to-en-3style":
        text = _read_text(args.input)
        prompt = builder.build_text_to_en_3style(
            text,
            reference_files=None,
            detected_language="Japanese",
        )
        raw = client.translate_single(text, prompt, timeout=args.timeout)
        parsed = {k: v[0] for k, v in parse_text_to_en_3style(raw).items()}
    elif mode == "en-to-jp":
        text = _read_text(args.input)
        prompt = builder.build_text_to_jp(
            text,
            reference_files=None,
            detected_language="English",
        )
        raw = client.translate_single(text, prompt, timeout=args.timeout)
        translation, explanation = parse_text_single_translation(raw)
        parsed = {"translation": translation or "", "explanation": explanation or ""}
    elif mode == "batch-jp-to-en":
        texts = _read_lines(args.input)
        prompt = builder.build_batch(
            texts,
            output_language="en",
            translation_style=args.style,
            include_item_ids=False,
            reference_files=None,
        )
        result = client._chat_completions(runtime, prompt, timeout=args.timeout)
        raw = result.content
        parsed = parse_batch_translations(
            raw, expected_count=len(texts), parsed_json=result.parsed_json
        )
    elif mode == "batch-en-to-jp":
        texts = _read_lines(args.input)
        prompt = builder.build_batch(
            texts,
            output_language="jp",
            translation_style=args.style,
            include_item_ids=False,
            reference_files=None,
        )
        result = client._chat_completions(runtime, prompt, timeout=args.timeout)
        raw = result.content
        parsed = parse_batch_translations(
            raw, expected_count=len(texts), parsed_json=result.parsed_json
        )
    else:
        raise SystemExit(f"Unknown mode: {mode}")

    _write_optional(args.dump_prompt, prompt)
    _write_optional(args.dump_raw, raw)

    payload = {
        "mode": mode,
        "input": str(args.input),
        "style": args.style,
        "runtime": {
            "host": runtime.host,
            "port": runtime.port,
            "model_id": runtime.model_id,
            "model_path": str(runtime.model_path),
            "server_variant": runtime.server_variant,
        },
        "prompt_chars": len(prompt),
        "raw_chars": len(raw),
        "parsed": parsed,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"mode: {mode}")
    print(
        f"model: {runtime.model_id or runtime.model_path.name} ({runtime.server_variant})"
    )
    print(f"prompt_chars: {len(prompt)}")
    print(f"raw_chars: {len(raw)}")
    print("--- parsed ---")
    print(payload["parsed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
