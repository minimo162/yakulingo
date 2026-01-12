from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _apply_overrides(settings: Any, args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}

    def _set(name: str, value: Any) -> None:
        if value is None:
            return
        setattr(settings, name, value)
        overrides[name] = value

    if args.max_tokens is not None:
        if args.max_tokens <= 0:
            _set("local_ai_max_tokens", None)
        else:
            _set("local_ai_max_tokens", int(args.max_tokens))

    if args.ctx_size is not None:
        _set("local_ai_ctx_size", int(args.ctx_size))
    if args.threads is not None:
        _set("local_ai_threads", int(args.threads))
    if args.batch_size is not None:
        _set(
            "local_ai_batch_size",
            None if args.batch_size <= 0 else int(args.batch_size),
        )
    if args.ubatch_size is not None:
        _set(
            "local_ai_ubatch_size",
            None if args.ubatch_size <= 0 else int(args.ubatch_size),
        )
    if args.max_chars_per_batch is not None:
        _set("local_ai_max_chars_per_batch", int(args.max_chars_per_batch))
    if args.max_chars_per_batch_file is not None:
        _set("local_ai_max_chars_per_batch_file", int(args.max_chars_per_batch_file))
    if args.model_path is not None:
        _set("local_ai_model_path", str(args.model_path))
    if args.server_dir is not None:
        _set("local_ai_server_dir", str(args.server_dir))
    if args.host is not None:
        _set("local_ai_host", str(args.host))
    if args.port_base is not None:
        _set("local_ai_port_base", int(args.port_base))
    if args.port_max is not None:
        _set("local_ai_port_max", int(args.port_max))
    if args.temperature is not None:
        _set("local_ai_temperature", float(args.temperature))
    if args.device is not None:
        _set("local_ai_device", str(args.device))
    if args.n_gpu_layers is not None:
        _set("local_ai_n_gpu_layers", str(args.n_gpu_layers))
    if args.flash_attn is not None:
        _set("local_ai_flash_attn", str(args.flash_attn))
    if args.no_warmup:
        _set("local_ai_no_warmup", True)
    if args.vk_force_max_allocation_size is not None:
        if args.vk_force_max_allocation_size <= 0:
            _set("local_ai_vk_force_max_allocation_size", None)
        else:
            _set(
                "local_ai_vk_force_max_allocation_size",
                int(args.vk_force_max_allocation_size),
            )
    if args.vk_disable_f16:
        _set("local_ai_vk_disable_f16", True)

    if hasattr(settings, "_validate"):
        settings._validate()

    return overrides


def _emit_json(payload: dict[str, Any], *, to_stdout: bool, out_path: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if out_path is not None:
        out_path.write_text(text, encoding="utf-8")
        print(f"json_out: {out_path}")
    if to_stdout:
        print(text)


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
    parser.add_argument("--ctx-size", type=int, default=None)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--ubatch-size", type=int, default=None)
    parser.add_argument("--max-chars-per-batch", type=int, default=None)
    parser.add_argument("--max-chars-per-batch-file", type=int, default=None)
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--server-dir", type=Path, default=None)
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port-base", type=int, default=None)
    parser.add_argument("--port-max", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument(
        "--device", type=str, default=None, help="Override local_ai_device (e.g. Vulkan0)"
    )
    parser.add_argument(
        "--n-gpu-layers",
        type=str,
        default=None,
        help="Override local_ai_n_gpu_layers (int/auto/all)",
    )
    parser.add_argument(
        "--flash-attn",
        type=str,
        default=None,
        help="Override local_ai_flash_attn (auto/0/1)",
    )
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--vk-force-max-allocation-size", type=int, default=None)
    parser.add_argument("--vk-disable-f16", action="store_true")
    parser.add_argument(
        "--restart-server",
        action="store_true",
        help="Restart local AI server before benchmarking (ensures overrides apply).",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--out", type=Path, default=None, help="Write JSON to file")

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
    overrides = _apply_overrides(settings, args)
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
        server_restarted = False
        restart_reason = None
        if args.restart_server:
            get_local_llama_server_manager().stop()
            server_restarted = True
            restart_reason = "restart_server"
        if not server_restarted:
            get_local_llama_server_manager().stop()
            server_restarted = True
            restart_reason = "mode_cold"
        warmup_runs = 0
    else:
        server_restarted = False
        restart_reason = None
        if args.restart_server:
            get_local_llama_server_manager().stop()
            server_restarted = True
            restart_reason = "restart_server"
        warmup_runs = max(0, int(args.warmup_runs))

    warmup_seconds: list[float] = []

    started_at = _utc_now_iso()
    print("benchmark: local-ai")
    print(f"mode: {args.mode}")
    print(f"started_at: {started_at}")
    print(f"input_chars: {len(text)}")
    print(f"style: {args.style}")
    print(f"compare: {bool(args.compare)}")
    print(f"with_glossary: {bool(args.with_glossary)}")
    print(f"reference_files: {len(reference_files)}")
    print(f"effective_local_ai_ctx_size: {settings.local_ai_ctx_size}")
    print(f"effective_local_ai_threads: {settings.local_ai_threads}")
    print(f"effective_local_ai_batch_size: {settings.local_ai_batch_size}")
    print(f"effective_local_ai_ubatch_size: {settings.local_ai_ubatch_size}")
    print(f"effective_local_ai_max_chars_per_batch: {settings.local_ai_max_chars_per_batch}")
    print(
        "effective_local_ai_max_chars_per_batch_file: "
        f"{settings.local_ai_max_chars_per_batch_file}"
    )
    print(f"effective_local_ai_max_tokens: {settings.local_ai_max_tokens}")
    print(f"effective_local_ai_device: {settings.local_ai_device}")
    print(f"effective_local_ai_n_gpu_layers: {settings.local_ai_n_gpu_layers}")
    print(f"effective_local_ai_flash_attn: {settings.local_ai_flash_attn}")
    print(f"effective_local_ai_no_warmup: {settings.local_ai_no_warmup}")
    print(
        "effective_local_ai_vk_force_max_allocation_size: "
        f"{settings.local_ai_vk_force_max_allocation_size}"
    )
    print(f"effective_local_ai_vk_disable_f16: {settings.local_ai_vk_disable_f16}")
    if not args.compare:
        print(f"prompt_chars: {prompt_chars}")
        print(f"prompt_build_seconds: {prompt_build_seconds:.2f}")

    for i in range(warmup_runs):
        if args.compare:
            _, warmup_elapsed = _translate_compare(service, text, reference_files)
        else:
            _, warmup_elapsed = _translate_once(client, text, prompt)
        warmup_seconds.append(warmup_elapsed)
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
        payload = {
            "benchmark": "local-ai",
            "mode": args.mode,
            "compare": True,
            "style": args.style,
            "started_at": started_at,
            "input_path": str(input_path),
            "input_chars": len(text),
            "with_glossary": bool(args.with_glossary),
            "reference_files": [str(p) for p in reference_files],
            "server_restarted": server_restarted,
            "restart_reason": restart_reason,
            "overrides": overrides,
            "settings": {
                "local_ai_model_path": settings.local_ai_model_path,
                "local_ai_server_dir": settings.local_ai_server_dir,
                "local_ai_host": settings.local_ai_host,
                "local_ai_port_base": settings.local_ai_port_base,
                "local_ai_port_max": settings.local_ai_port_max,
                "local_ai_ctx_size": settings.local_ai_ctx_size,
                "local_ai_threads": settings.local_ai_threads,
                "local_ai_temperature": settings.local_ai_temperature,
                "local_ai_max_tokens": settings.local_ai_max_tokens,
                "local_ai_batch_size": settings.local_ai_batch_size,
                "local_ai_ubatch_size": settings.local_ai_ubatch_size,
                "local_ai_max_chars_per_batch": settings.local_ai_max_chars_per_batch,
                "local_ai_max_chars_per_batch_file": settings.local_ai_max_chars_per_batch_file,
                "local_ai_device": settings.local_ai_device,
                "local_ai_n_gpu_layers": settings.local_ai_n_gpu_layers,
                "local_ai_flash_attn": settings.local_ai_flash_attn,
                "local_ai_no_warmup": settings.local_ai_no_warmup,
                "local_ai_vk_force_max_allocation_size": (
                    settings.local_ai_vk_force_max_allocation_size
                ),
                "local_ai_vk_disable_f16": settings.local_ai_vk_disable_f16,
            },
            "warmup_seconds": warmup_seconds,
            "translation_seconds": elapsed,
            "options": len(options),
            "output_chars": output_chars,
            "error": error,
        }
    else:
        output, elapsed = _translate_once(client, text, prompt)
        if not output.strip():
            print("WARNING: empty translation result", file=sys.stderr)

        total_seconds = prompt_build_seconds + elapsed
        print(f"translation_seconds: {elapsed:.2f}")
        print(f"total_seconds: {total_seconds:.2f}")
        print(f"output_chars: {len(output)}")
        payload = {
            "benchmark": "local-ai",
            "mode": args.mode,
            "compare": False,
            "style": args.style,
            "started_at": started_at,
            "input_path": str(input_path),
            "input_chars": len(text),
            "with_glossary": bool(args.with_glossary),
            "reference_files": [str(p) for p in reference_files],
            "server_restarted": server_restarted,
            "restart_reason": restart_reason,
            "overrides": overrides,
            "settings": {
                "local_ai_model_path": settings.local_ai_model_path,
                "local_ai_server_dir": settings.local_ai_server_dir,
                "local_ai_host": settings.local_ai_host,
                "local_ai_port_base": settings.local_ai_port_base,
                "local_ai_port_max": settings.local_ai_port_max,
                "local_ai_ctx_size": settings.local_ai_ctx_size,
                "local_ai_threads": settings.local_ai_threads,
                "local_ai_temperature": settings.local_ai_temperature,
                "local_ai_max_tokens": settings.local_ai_max_tokens,
                "local_ai_batch_size": settings.local_ai_batch_size,
                "local_ai_ubatch_size": settings.local_ai_ubatch_size,
                "local_ai_max_chars_per_batch": settings.local_ai_max_chars_per_batch,
                "local_ai_max_chars_per_batch_file": settings.local_ai_max_chars_per_batch_file,
                "local_ai_device": settings.local_ai_device,
                "local_ai_n_gpu_layers": settings.local_ai_n_gpu_layers,
                "local_ai_flash_attn": settings.local_ai_flash_attn,
                "local_ai_no_warmup": settings.local_ai_no_warmup,
                "local_ai_vk_force_max_allocation_size": (
                    settings.local_ai_vk_force_max_allocation_size
                ),
                "local_ai_vk_disable_f16": settings.local_ai_vk_disable_f16,
            },
            "prompt_chars": prompt_chars,
            "prompt_build_seconds": prompt_build_seconds,
            "warmup_seconds": warmup_seconds,
            "translation_seconds": elapsed,
            "total_seconds": total_seconds,
            "output_chars": len(output),
        }

    if args.json or args.out:
        _emit_json(payload, to_stdout=bool(args.json), out_path=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
