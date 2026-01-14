#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _slugify_token(value: str) -> str:
    cleaned = []
    for ch in str(value):
        if ch.isalnum() or ch in ("-", "_"):
            cleaned.append(ch)
        elif ch.isspace():
            cleaned.append("-")
        else:
            cleaned.append("-")
    token = "".join(cleaned)
    while "--" in token:
        token = token.replace("--", "-")
    return token.strip("-") or "run"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _find_physical_logical_cores() -> tuple[int | None, int | None]:
    try:
        import psutil

        physical = psutil.cpu_count(logical=False)
        logical = psutil.cpu_count(logical=True)
        return (
            int(physical) if physical is not None else None,
            int(logical) if logical is not None else None,
        )
    except Exception:
        logical = os.cpu_count()
        return None, int(logical) if logical is not None else None


@dataclass(frozen=True)
class RunSpec:
    tag: str
    args: list[str]


def _build_run_specs(
    *,
    preset: str,
    model_path: Path,
    cpu_server_dir: Path,
    gpu_server_dir: Path,
    gpu_device: str,
    ngl_main: str,
    ngl_full: str,
    vk_force_max_allocation_size: int | None,
    vk_disable_f16: bool,
    warmup_runs: int,
    compare: bool,
    physical_cores: int | None,
    logical_cores: int | None,
) -> list[RunSpec]:
    common: list[str] = [
        "--mode",
        "warm",
        "--restart-server",
        "--warmup-runs",
        str(max(0, int(warmup_runs))),
        "--model-path",
        str(model_path),
    ]
    if compare:
        common.append("--compare")

    vk_common: list[str] = []
    if vk_force_max_allocation_size is not None:
        vk_common += [
            "--vk-force-max-allocation-size",
            str(int(vk_force_max_allocation_size)),
        ]
    if vk_disable_f16:
        vk_common.append("--vk-disable-f16")

    tag_full = f"vk_ngl_{ngl_full}"
    tag_main = f"vk_ngl_{ngl_main}"

    specs: list[RunSpec] = []
    specs.append(
        RunSpec(
            tag="cpu_base",
            args=[
                *common,
                "--server-dir",
                str(cpu_server_dir),
                "--device",
                "none",
                "--n-gpu-layers",
                "0",
            ],
        )
    )

    specs.append(
        RunSpec(
            tag=tag_full,
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                str(ngl_full),
                "--flash-attn",
                "auto",
            ],
        )
    )

    specs.append(
        RunSpec(
            tag=tag_main,
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                str(ngl_main),
                "--flash-attn",
                "auto",
            ],
        )
    )

    if physical_cores and logical_cores and logical_cores > physical_cores:
        specs.append(
            RunSpec(
                tag=f"{tag_main}_tb_logical",
                args=[
                    *common,
                    *vk_common,
                    "--server-dir",
                    str(gpu_server_dir),
                    "--device",
                    str(gpu_device),
                    "--n-gpu-layers",
                    str(ngl_main),
                    "--threads",
                    str(physical_cores),
                    "--threads-batch",
                    str(logical_cores),
                ],
            )
        )

    if preset != "full":
        return specs

    specs.insert(
        2,
        RunSpec(
            tag="vk_ngl_32",
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                "32",
                "--flash-attn",
                "auto",
            ],
        ),
    )

    specs.append(
        RunSpec(
            tag=f"{tag_main}_b1024_ub256",
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                str(ngl_main),
                "--batch-size",
                "1024",
                "--ubatch-size",
                "256",
            ],
        )
    )

    specs.append(
        RunSpec(
            tag=f"{tag_main}_ctx4096",
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                str(ngl_main),
                "--ctx-size",
                "4096",
            ],
        )
    )

    specs.append(
        RunSpec(
            tag=f"{tag_main}_ct_q4_0",
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                str(ngl_main),
                "--cache-type-k",
                "q4_0",
                "--cache-type-v",
                "q4_0",
            ],
        )
    )

    specs.append(
        RunSpec(
            tag=f"{tag_main}_fa_0",
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                str(ngl_main),
                "--flash-attn",
                "0",
            ],
        )
    )

    specs.append(
        RunSpec(
            tag=f"{tag_main}_mlock_no_mmap",
            args=[
                *common,
                *vk_common,
                "--server-dir",
                str(gpu_server_dir),
                "--device",
                str(gpu_device),
                "--n-gpu-layers",
                str(ngl_main),
                "--mlock",
                "--no-mmap",
            ],
        )
    )

    return specs


def _run(
    python_exe: str,
    bench_script: Path,
    *,
    spec: RunSpec,
    out_path: Path,
    log_path: Path,
    timeout_s: float | None,
) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        python_exe,
        str(bench_script),
        *spec.args,
        "--tag",
        spec.tag,
        "--out",
        str(out_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
        combined = (completed.stdout or "") + ("\n" if completed.stdout else "") + (
            completed.stderr or ""
        )
        _write_text(log_path, combined)
    except subprocess.TimeoutExpired as exc:
        out_text = exc.stdout or ""
        err_text = exc.stderr or ""
        combined = (
            (out_text or "")
            + ("\n" if out_text else "")
            + (err_text or "")
            + ("\n" if err_text else "")
            + f"[sweep] timeout after {timeout_s} seconds"
        )
        _write_text(log_path, combined.strip() + "\n")
        payload = {
            "benchmark": "local-ai",
            "tag": spec.tag,
            "error": "timeout",
            "returncode": 124,
            "command": " ".join(cmd),
            "log_path": str(log_path),
            "timeout_seconds": timeout_s,
        }
        _write_json(out_path, payload)
        return {
            "tag": spec.tag,
            "out_path": str(out_path),
            "log_path": str(log_path),
            "returncode": 124,
        }

    payload = _read_json(out_path)
    if payload is None:
        payload = {
            "benchmark": "local-ai",
            "tag": spec.tag,
            "error": "bench did not produce JSON output",
            "returncode": completed.returncode,
            "command": " ".join(cmd),
            "log_path": str(log_path),
        }
        _write_json(out_path, payload)

    return {
        "tag": spec.tag,
        "out_path": str(out_path),
        "log_path": str(log_path),
        "returncode": completed.returncode,
    }


def _build_summary_rows(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        out_path = Path(item["out_path"])
        payload = _read_json(out_path) or {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        rows.append(
            {
                "tag": str(payload.get("tag") or item.get("tag") or ""),
                "returncode": item.get("returncode"),
                "mode": payload.get("mode"),
                "compare": payload.get("compare"),
                "translation_seconds": _safe_float(payload.get("translation_seconds")),
                "output_chars": _safe_int(payload.get("output_chars")),
                "device": settings.get("local_ai_device"),
                "n_gpu_layers": settings.get("local_ai_n_gpu_layers"),
                "threads": settings.get("local_ai_threads"),
                "threads_batch": settings.get("local_ai_threads_batch"),
                "batch_size": settings.get("local_ai_batch_size"),
                "ubatch_size": settings.get("local_ai_ubatch_size"),
                "ctx_size": settings.get("local_ai_ctx_size"),
                "flash_attn": settings.get("local_ai_flash_attn"),
                "cache_type_k": settings.get("local_ai_cache_type_k"),
                "cache_type_v": settings.get("local_ai_cache_type_v"),
                "mlock": settings.get("local_ai_mlock"),
                "no_mmap": settings.get("local_ai_no_mmap"),
                "json_path": str(out_path),
                "log_path": str(item.get("log_path") or ""),
                "error": payload.get("error"),
                "reused": bool(item.get("reused")),
            }
        )
    return rows


def _write_summary_markdown(path: Path, *, meta: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("# Local AI sweep (7B)")
    lines.append("")
    lines.append(f"- created_at: {meta.get('created_at')}")
    lines.append(f"- preset: {meta.get('preset')}")
    lines.append(f"- out_dir: {meta.get('out_dir')}")
    lines.append(f"- repo_commit: {meta.get('repo_commit')}")
    if meta.get("resume"):
        lines.append("- resume: true")
    if meta.get("run_timeout_seconds") is not None:
        lines.append(f"- run_timeout_seconds: {meta.get('run_timeout_seconds')}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append(
        "| tag | rc | t(s) | out_chars | device | ngl | t | tb | b | ub | ctx | fa | ctk | ctv | mlock | no_mmap | json | log |"
    )
    lines.append(
        "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for row in rows:
        lines.append(
            "| {tag} | {rc} | {t} | {out_chars} | {device} | {ngl} | {threads} | {tb} | {b} | {ub} | {ctx} | {fa} | {ctk} | {ctv} | {mlock} | {no_mmap} | {json_path} | {log_path} |".format(
                tag=row.get("tag") or "",
                rc=row.get("returncode"),
                t="" if row.get("translation_seconds") is None else f"{row['translation_seconds']:.2f}",
                out_chars=row.get("output_chars") or "",
                device=row.get("device") or "",
                ngl=row.get("n_gpu_layers") or "",
                threads=row.get("threads") or "",
                tb=row.get("threads_batch") if row.get("threads_batch") is not None else "",
                b=row.get("batch_size") or "",
                ub=row.get("ubatch_size") or "",
                ctx=row.get("ctx_size") or "",
                fa=row.get("flash_attn") or "",
                ctk=row.get("cache_type_k") if row.get("cache_type_k") is not None else "",
                ctv=row.get("cache_type_v") if row.get("cache_type_v") is not None else "",
                mlock=row.get("mlock"),
                no_mmap=row.get("no_mmap"),
                json_path=row.get("json_path") or "",
                log_path=row.get("log_path") or "",
            )
        )

    errors = [row for row in rows if row.get("error")]
    if errors:
        lines.append("")
        lines.append("## Errors")
        lines.append("")
        for row in errors:
            lines.append(f"- {row.get('tag')}: {row.get('error')}")
            if row.get("log_path"):
                lines.append(f"  - log: {row.get('log_path')}")

    _write_text(path, "\n".join(lines).rstrip() + "\n")


def _git_head_short(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
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
        return (completed.stdout or "").strip() or None
    except Exception:
        return None


def _write_summaries(out_dir: Path, *, meta: dict[str, Any], results: list[dict[str, Any]]) -> None:
    rows = _build_summary_rows(results)
    _write_json(out_dir / "summary.json", {"meta": meta, "rows": rows})
    _write_summary_markdown(out_dir / "summary.md", meta=meta, rows=rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a short sweep of tools/bench_local_ai.py for 7B/Q4_K_M."
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--preset", choices=("quick", "full"), default="quick")
    parser.add_argument("--device", type=str, default="Vulkan0")
    parser.add_argument("--ngl-main", type=str, default="16")
    parser.add_argument("--ngl-full", type=str, default="99")
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--cpu-server-dir", type=Path, default=None)
    parser.add_argument("--gpu-server-dir", type=Path, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-timeout-seconds", type=int, default=None)
    parser.add_argument("--vk-force-max-allocation-size", type=int, default=None)
    parser.add_argument("--vk-disable-f16", action="store_true")

    args = parser.parse_args()

    repo_root = _repo_root()
    bench_script = repo_root / "tools" / "bench_local_ai.py"

    out_dir = args.out_dir or (repo_root / ".tmp" / f"sweep-7b-{_timestamp_compact()}")
    out_dir.mkdir(parents=True, exist_ok=True)

    default_model = repo_root / "local_ai" / "models" / "HY-MT1.5-7B-Q4_K_M.gguf"
    model_path = args.model_path or default_model

    cpu_dir = args.cpu_server_dir or (repo_root / "local_ai" / "llama_cpp" / "avx2")
    gpu_dir = args.gpu_server_dir or (repo_root / "local_ai" / "llama_cpp" / "vulkan")

    physical_cores, logical_cores = _find_physical_logical_cores()

    specs = _build_run_specs(
        preset=args.preset,
        model_path=model_path,
        cpu_server_dir=cpu_dir,
        gpu_server_dir=gpu_dir,
        gpu_device=args.device,
        ngl_main=args.ngl_main,
        ngl_full=args.ngl_full,
        vk_force_max_allocation_size=args.vk_force_max_allocation_size,
        vk_disable_f16=bool(args.vk_disable_f16),
        warmup_runs=args.warmup_runs,
        compare=bool(args.compare),
        physical_cores=physical_cores,
        logical_cores=logical_cores,
    )

    python_exe = sys.executable

    results: list[dict[str, Any]] = []

    meta = {
        "created_at": _utc_now_iso(),
        "preset": args.preset,
        "out_dir": str(out_dir),
        "repo_commit": _git_head_short(repo_root),
        "python": sys.version.split()[0],
        "physical_cores": physical_cores,
        "logical_cores": logical_cores,
        "compare": bool(args.compare),
        "warmup_runs": int(args.warmup_runs),
        "model_path": str(model_path),
        "cpu_server_dir": str(cpu_dir),
        "gpu_server_dir": str(gpu_dir),
        "device": str(args.device),
        "ngl_main": str(args.ngl_main),
        "ngl_full": str(args.ngl_full),
        "resume": bool(args.resume),
        "run_timeout_seconds": args.run_timeout_seconds,
        "vk_force_max_allocation_size": args.vk_force_max_allocation_size,
        "vk_disable_f16": bool(args.vk_disable_f16),
    }
    timeout_s = float(args.run_timeout_seconds) if args.run_timeout_seconds else None

    for spec in specs:
        tag = _slugify_token(spec.tag)
        out_path = out_dir / f"{tag}.json"
        log_path = out_dir / f"{tag}.log.txt"
        if args.resume:
            payload = _read_json(out_path)
            if payload is not None:
                returncode = payload.get("returncode")
                if not isinstance(returncode, int):
                    returncode = 0
                results.append(
                    {
                        "tag": spec.tag,
                        "out_path": str(out_path),
                        "log_path": str(log_path) if log_path.is_file() else "",
                        "returncode": returncode,
                        "reused": True,
                    }
                )
                _write_summaries(out_dir, meta=meta, results=results)
                continue
        print(f"[sweep] {spec.tag} -> {out_path}")
        results.append(
            _run(
                python_exe,
                bench_script,
                spec=spec,
                out_path=out_path,
                log_path=log_path,
                timeout_s=timeout_s,
            )
        )
        _write_summaries(out_dir, meta=meta, results=results)

    print(f"[sweep] summary: {out_dir / 'summary.md'}")

    rows = _build_summary_rows(results)
    failed = [row for row in rows if (row.get("returncode") or 0) != 0]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
