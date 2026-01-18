from __future__ import annotations

import argparse
import difflib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_from_app_base(path_value: str, repo_root: Path) -> Path:
    raw = (path_value or "").strip()
    if not raw:
        return repo_root
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return repo_root / candidate


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _compute_similarity(gold_text: str, candidate_text: str) -> float:
    return difflib.SequenceMatcher(None, gold_text, candidate_text).ratio()


def _format_compare_output(options: list[Any]) -> str:
    lines: list[str] = []
    for index, option in enumerate(options, start=1):
        style = getattr(option, "style", None) or f"option-{index}"
        text = getattr(option, "text", "") or ""
        explanation = getattr(option, "explanation", "") or ""
        lines.append(f"[{style}]")
        lines.append(text)
        if explanation:
            lines.append("")
            lines.append("[explanation]")
            lines.append(explanation)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


def _run_version_command(exe_path: Path) -> str | None:
    if not exe_path.is_file():
        return None
    completed = subprocess.run(
        [str(exe_path), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return None
    output = completed.stdout.strip()
    return output or completed.stderr.strip() or None


def _find_llama_server_path(
    resolved_server_dir: Path,
    *,
    runtime_exe_path: Path | None,
    state_exe_path: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if runtime_exe_path is not None:
        candidates.append(runtime_exe_path)
    if state_exe_path is not None:
        candidates.append(state_exe_path)

    for base_dir in (
        resolved_server_dir,
        resolved_server_dir / "vulkan",
        resolved_server_dir / "avx2",
        resolved_server_dir / "generic",
    ):
        for name in ("llama-server.exe", "llama-server"):
            candidates.append(base_dir / name)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue

    if runtime_exe_path is not None:
        return runtime_exe_path
    if state_exe_path is not None:
        return state_exe_path
    return None


def _find_llama_cli_path(
    resolved_server_dir: Path,
    *,
    runtime_exe_path: Path | None,
    state_exe_path: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if runtime_exe_path is not None:
        candidates.append(runtime_exe_path.parent)
    if state_exe_path is not None:
        candidates.append(state_exe_path.parent)
    candidates.append(resolved_server_dir)
    candidates.append(resolved_server_dir / "vulkan")
    candidates.append(resolved_server_dir / "avx2")
    candidates.append(resolved_server_dir / "generic")

    for base_dir in candidates:
        if not base_dir.exists():
            continue
        for name in ("llama-cli.exe", "llama-cli"):
            candidate = base_dir / name
            if candidate.is_file():
                return candidate
    return None


def _collect_server_metadata(
    settings: Any,
    repo_root: Path,
    server_manager: Any,
) -> dict[str, Any]:
    resolved_server_dir = _resolve_from_app_base(
        str(settings.local_ai_server_dir or ""), repo_root
    )
    resolved_model_path = _resolve_from_app_base(
        str(settings.local_ai_model_path or ""), repo_root
    )
    state_path = server_manager.get_state_path()
    state = _read_json(state_path)
    runtime = server_manager.get_runtime()

    runtime_payload = None
    runtime_exe_path = None
    if runtime is not None:
        runtime_exe_path = runtime.server_exe_path
        runtime_payload = {
            "host": runtime.host,
            "port": runtime.port,
            "base_url": runtime.base_url,
            "model_id": runtime.model_id,
            "server_exe_path": str(runtime.server_exe_path),
            "server_variant": runtime.server_variant,
            "model_path": str(runtime.model_path),
        }

    state_exe_path = None
    if state and isinstance(state.get("server_exe_path_resolved"), str):
        state_exe_path = Path(state["server_exe_path_resolved"])

    llama_server_path = _find_llama_server_path(
        resolved_server_dir,
        runtime_exe_path=runtime_exe_path,
        state_exe_path=state_exe_path,
    )
    llama_server_version = (
        _run_version_command(llama_server_path) if llama_server_path else None
    )

    llama_cli_path = _find_llama_cli_path(
        resolved_server_dir,
        runtime_exe_path=runtime_exe_path,
        state_exe_path=state_exe_path,
    )
    llama_cli_version = _run_version_command(llama_cli_path) if llama_cli_path else None

    return {
        "server_dir_config": settings.local_ai_server_dir,
        "server_dir_resolved": str(resolved_server_dir),
        "model_path_config": settings.local_ai_model_path,
        "model_path_resolved": str(resolved_model_path),
        "server_state_path": str(state_path),
        "server_state": state,
        "runtime": runtime_payload,
        "llama_server_path": str(llama_server_path) if llama_server_path else None,
        "llama_server_version": llama_server_version,
        "llama_cli_path": str(llama_cli_path) if llama_cli_path else None,
        "llama_cli_version": llama_cli_version,
    }


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


def _build_settings_payload(settings: Any) -> dict[str, Any]:
    return {
        "local_ai_model_path": settings.local_ai_model_path,
        "local_ai_server_dir": settings.local_ai_server_dir,
        "local_ai_host": settings.local_ai_host,
        "local_ai_port_base": settings.local_ai_port_base,
        "local_ai_port_max": settings.local_ai_port_max,
        "local_ai_ctx_size": settings.local_ai_ctx_size,
        "local_ai_threads": settings.local_ai_threads,
        "local_ai_threads_batch": settings.local_ai_threads_batch,
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
        "local_ai_mlock": settings.local_ai_mlock,
        "local_ai_no_mmap": settings.local_ai_no_mmap,
        "local_ai_vk_force_max_allocation_size": settings.local_ai_vk_force_max_allocation_size,
        "local_ai_vk_disable_f16": settings.local_ai_vk_disable_f16,
        "local_ai_cache_type_k": settings.local_ai_cache_type_k,
        "local_ai_cache_type_v": settings.local_ai_cache_type_v,
    }


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
    if getattr(args, "threads_batch", None) is not None:
        _set("local_ai_threads_batch", int(args.threads_batch))
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
    if getattr(args, "mlock", None) is not None:
        _set("local_ai_mlock", bool(args.mlock))
    if getattr(args, "no_mmap", None) is not None:
        _set("local_ai_no_mmap", bool(args.no_mmap))
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
    if args.cache_type_k is not None:
        _set("local_ai_cache_type_k", str(args.cache_type_k))
    if args.cache_type_v is not None:
        _set("local_ai_cache_type_v", str(args.cache_type_v))

    if hasattr(settings, "_validate"):
        settings._validate()

    return overrides


def _emit_json(
    payload: dict[str, Any], *, to_stdout: bool, out_path: Path | None
) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if out_path is not None:
        out_path.write_text(text, encoding="utf-8")
        print(f"json_out: {out_path}")
    if to_stdout:
        print(text)


def main() -> int:
    def _non_negative_int(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if parsed < 0:
            raise argparse.ArgumentTypeError("must be >= 0")
        return parsed

    parser = argparse.ArgumentParser(
        description="Local AI benchmark (minimal-only; optionally via TranslationService)"
    )
    parser.add_argument("--input", type=Path, default=None, help="Path to input text")
    parser.add_argument("--mode", choices=("warm", "cold"), default="warm")
    parser.add_argument(
        "--style", choices=("standard", "concise", "minimal"), default="minimal"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help=(
            "DEPRECATED: kept for compatibility. Runs the TranslationService text path "
            "(JP→EN is minimal-only; no multi-style compare)."
        ),
    )
    parser.add_argument("--with-glossary", action="store_true")
    parser.add_argument("--reference", action="append", type=Path, default=[])
    parser.add_argument("--tag", type=str, default=None, help="Label for this run")
    parser.add_argument(
        "--save-output",
        type=Path,
        default=None,
        help="Write translation output to file",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=None,
        help="Path to reference translation (plain text)",
    )
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--ctx-size", type=int, default=None)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument(
        "--threads-batch",
        type=_non_negative_int,
        default=None,
        help="Override local_ai_threads_batch (0=auto)",
    )
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
        "--device",
        type=str,
        default=None,
        help="Override local_ai_device (e.g. Vulkan0)",
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
    mlock_group = parser.add_mutually_exclusive_group()
    mlock_group.add_argument(
        "--mlock",
        dest="mlock",
        action="store_const",
        const=True,
        default=None,
        help="Override local_ai_mlock (enable)",
    )
    mlock_group.add_argument(
        "--no-mlock",
        dest="mlock",
        action="store_const",
        const=False,
        default=None,
        help="Override local_ai_mlock (disable)",
    )
    mmap_group = parser.add_mutually_exclusive_group()
    mmap_group.add_argument(
        "--no-mmap",
        dest="no_mmap",
        action="store_const",
        const=True,
        default=None,
        help="Override local_ai_no_mmap (enable)",
    )
    mmap_group.add_argument(
        "--mmap",
        dest="no_mmap",
        action="store_const",
        const=False,
        default=None,
        help="Override local_ai_no_mmap (disable)",
    )
    parser.add_argument("--vk-force-max-allocation-size", type=int, default=None)
    parser.add_argument("--vk-disable-f16", action="store_true")
    parser.add_argument("--cache-type-k", type=str, default=None)
    parser.add_argument("--cache-type-v", type=str, default=None)
    parser.add_argument(
        "--restart-server",
        action="store_true",
        help="Restart local AI server before benchmarking (ensures overrides apply).",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--out", type=Path, default=None, help="Write JSON to file")

    args = parser.parse_args()

    repo_root = _repo_root()
    git_metadata = _collect_git_metadata(repo_root)
    runtime_metadata = _collect_runtime_metadata()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from yakulingo.config.settings import AppSettings
    from yakulingo.services.local_llama_server import (
        ensure_no_proxy_for_localhost,
        get_local_llama_server_manager,
    )
    from yakulingo.services.prompt_builder import PromptBuilder

    ensure_no_proxy_for_localhost()

    default_input = repo_root / "tools" / "bench_local_ai_input.txt"
    if args.input:
        input_path = args.input
    else:
        input_path = default_input
    text = _load_text(input_path)
    gold_text = _load_text(args.gold) if args.gold else None
    gold_chars = len(gold_text) if gold_text is not None else None

    if len(text) < 400 or len(text) > 800:
        print("WARNING: input text length is outside 400-800 chars", file=sys.stderr)

    reference_files: list[Path] = []
    if args.with_glossary:
        reference_files.append(repo_root / "glossary.csv")
    if args.reference:
        reference_files.extend(args.reference)

    settings = AppSettings()
    settings.translation_backend = "local"
    settings.copilot_enabled = False
    overrides = _apply_overrides(settings, args)
    server_manager = get_local_llama_server_manager()
    prompts_dir = repo_root / "prompts"
    local_translate_single_calls_warmup = 0
    local_translate_single_calls_translation = 0

    if args.compare:
        from yakulingo.services.translation_service import TranslationService

        class _NullCopilot:
            def set_cancel_callback(self, _callback) -> None:
                return None

            def translate_sync(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
                raise RuntimeError("copilot is disabled for local-ai benchmarks")

            def translate_single(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
                raise RuntimeError("copilot is disabled for local-ai benchmarks")

        service = TranslationService(
            _NullCopilot(),
            settings,
            prompts_dir=prompts_dir,
        )

        translate_single_calls = 0
        original_translate_single = service._translate_single_with_cancel

        def _counting_translate_single(
            source_text: str,
            prompt: str,
            reference_files: list[Path] | None = None,
            on_chunk=None,
        ) -> str:
            nonlocal translate_single_calls
            translate_single_calls += 1
            return original_translate_single(
                source_text, prompt, reference_files, on_chunk
            )

        service._translate_single_with_cancel = _counting_translate_single
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
    print(f"effective_local_ai_threads_batch: {settings.local_ai_threads_batch}")
    print(f"effective_local_ai_batch_size: {settings.local_ai_batch_size}")
    print(f"effective_local_ai_ubatch_size: {settings.local_ai_ubatch_size}")
    print(
        f"effective_local_ai_max_chars_per_batch: {settings.local_ai_max_chars_per_batch}"
    )
    print(
        "effective_local_ai_max_chars_per_batch_file: "
        f"{settings.local_ai_max_chars_per_batch_file}"
    )
    print(f"effective_local_ai_max_tokens: {settings.local_ai_max_tokens}")
    print(f"effective_local_ai_device: {settings.local_ai_device}")
    print(f"effective_local_ai_n_gpu_layers: {settings.local_ai_n_gpu_layers}")
    print(f"effective_local_ai_flash_attn: {settings.local_ai_flash_attn}")
    print(f"effective_local_ai_no_warmup: {settings.local_ai_no_warmup}")
    print(f"effective_local_ai_mlock: {settings.local_ai_mlock}")
    print(f"effective_local_ai_no_mmap: {settings.local_ai_no_mmap}")
    print(
        "effective_local_ai_vk_force_max_allocation_size: "
        f"{settings.local_ai_vk_force_max_allocation_size}"
    )
    print(f"effective_local_ai_vk_disable_f16: {settings.local_ai_vk_disable_f16}")
    print(f"effective_local_ai_cache_type_k: {settings.local_ai_cache_type_k}")
    print(f"effective_local_ai_cache_type_v: {settings.local_ai_cache_type_v}")
    if not args.compare:
        print(f"prompt_chars: {prompt_chars}")
        print(f"prompt_build_seconds: {prompt_build_seconds:.2f}")

    for i in range(warmup_runs):
        if args.compare:
            translate_single_calls = 0
        if args.compare:
            _, warmup_elapsed = _translate_compare(service, text, reference_files)
        else:
            _, warmup_elapsed = _translate_once(client, text, prompt)
        warmup_seconds.append(warmup_elapsed)
        print(f"warmup_seconds[{i + 1}]: {warmup_elapsed:.2f}")
        if args.compare:
            local_translate_single_calls_warmup += translate_single_calls

    if args.compare:
        translate_single_calls = 0
        result, elapsed = _translate_compare(service, text, reference_files)
        local_translate_single_calls_translation = translate_single_calls
        server_metadata = _collect_server_metadata(settings, repo_root, server_manager)
        versions_metadata = {
            "llama_server": server_metadata.get("llama_server_version"),
            "llama_cli": server_metadata.get("llama_cli_version"),
        }
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
        if args.save_output is not None:
            _write_text(args.save_output, _format_compare_output(options))
        similarity_by_style = None
        best_similarity = None
        if gold_text is not None:
            similarity_by_style = []
            for index, option in enumerate(options, start=1):
                style = getattr(option, "style", None) or f"option-{index}"
                text_value = getattr(option, "text", "") or ""
                similarity_by_style.append(
                    {
                        "style": style,
                        "ratio": _compute_similarity(gold_text, text_value),
                        "text_chars": len(text_value),
                    }
                )
            if similarity_by_style:
                best_similarity = max(item["ratio"] for item in similarity_by_style)
        print(f"translation_seconds: {elapsed:.2f}")
        print(
            "translate_single_calls_translation: "
            f"{local_translate_single_calls_translation}"
        )
        print(f"options: {len(options)}")
        print(f"output_chars: {output_chars}")
        payload = {
            "benchmark": "local-ai",
            "mode": args.mode,
            "compare": True,
            "style": args.style,
            "started_at": started_at,
            "tag": args.tag,
            "git": git_metadata,
            "runtime": runtime_metadata,
            "versions": versions_metadata,
            "input_path": str(input_path),
            "input_chars": len(text),
            "with_glossary": bool(args.with_glossary),
            "reference_files": [str(p) for p in reference_files],
            "save_output_path": str(args.save_output) if args.save_output else None,
            "gold_path": str(args.gold) if args.gold else None,
            "gold_chars": gold_chars,
            "server_restarted": server_restarted,
            "restart_reason": restart_reason,
            "overrides": overrides,
            "server": server_metadata,
            "settings": _build_settings_payload(settings),
            "warmup_seconds": warmup_seconds,
            "translate_single_calls_warmup": local_translate_single_calls_warmup,
            "translate_single_calls_translation": local_translate_single_calls_translation,
            "translate_single_calls_total": local_translate_single_calls_warmup
            + local_translate_single_calls_translation,
            "translation_seconds": elapsed,
            "options": len(options),
            "output_chars": output_chars,
            "similarity_method": "SequenceMatcher",
            "similarity_by_style": similarity_by_style,
            "best_similarity": best_similarity,
            "error": error,
        }
    else:
        output, elapsed = _translate_once(client, text, prompt)
        server_metadata = _collect_server_metadata(settings, repo_root, server_manager)
        versions_metadata = {
            "llama_server": server_metadata.get("llama_server_version"),
            "llama_cli": server_metadata.get("llama_cli_version"),
        }
        if not output.strip():
            print("WARNING: empty translation result", file=sys.stderr)

        total_seconds = prompt_build_seconds + elapsed
        local_translate_single_calls_warmup = warmup_runs
        local_translate_single_calls_translation = 1
        if args.save_output is not None:
            _write_text(args.save_output, output)
        similarity = (
            _compute_similarity(gold_text, output) if gold_text is not None else None
        )
        print(f"translation_seconds: {elapsed:.2f}")
        print(
            "translate_single_calls_translation: "
            f"{local_translate_single_calls_translation}"
        )
        print(f"total_seconds: {total_seconds:.2f}")
        print(f"output_chars: {len(output)}")
        payload = {
            "benchmark": "local-ai",
            "mode": args.mode,
            "compare": False,
            "style": args.style,
            "started_at": started_at,
            "tag": args.tag,
            "git": git_metadata,
            "runtime": runtime_metadata,
            "versions": versions_metadata,
            "input_path": str(input_path),
            "input_chars": len(text),
            "with_glossary": bool(args.with_glossary),
            "reference_files": [str(p) for p in reference_files],
            "save_output_path": str(args.save_output) if args.save_output else None,
            "gold_path": str(args.gold) if args.gold else None,
            "gold_chars": gold_chars,
            "server_restarted": server_restarted,
            "restart_reason": restart_reason,
            "overrides": overrides,
            "server": server_metadata,
            "settings": _build_settings_payload(settings),
            "prompt_chars": prompt_chars,
            "prompt_build_seconds": prompt_build_seconds,
            "warmup_seconds": warmup_seconds,
            "translate_single_calls_warmup": local_translate_single_calls_warmup,
            "translate_single_calls_translation": local_translate_single_calls_translation,
            "translate_single_calls_total": local_translate_single_calls_warmup
            + local_translate_single_calls_translation,
            "translation_seconds": elapsed,
            "total_seconds": total_seconds,
            "output_chars": len(output),
            "similarity_method": "SequenceMatcher",
            "similarity": similarity,
        }

    if args.json or args.out:
        _emit_json(payload, to_stdout=bool(args.json), out_path=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
