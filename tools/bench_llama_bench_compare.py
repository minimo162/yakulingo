#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _select_lines(text: str, token: str) -> list[str]:
    pattern = re.compile(rf"\\b{re.escape(token)}\\b", re.IGNORECASE)
    return [line.strip() for line in text.splitlines() if pattern.search(line)]


def _find_bench_exe(server_dir: Path) -> Path:
    candidates = [server_dir / "llama-bench.exe", server_dir / "llama-bench"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"llama-bench not found in: {server_dir}")


def _resolve_variant_dir(base_dir: Path, variant: str) -> Path:
    if (base_dir / variant).is_dir():
        return base_dir / variant
    return base_dir


def _run_bench(
    *,
    bench_exe: Path,
    model_path: Path,
    device: str,
    n_gpu_layers: str,
    pg: str,
    repeat: int,
    extra_args: Iterable[str],
) -> dict:
    cmd = [
        str(bench_exe),
        "-m",
        str(model_path),
        "--device",
        device,
        "-ngl",
        str(n_gpu_layers),
        "-pg",
        pg,
        "-r",
        str(repeat),
        *extra_args,
    ]
    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return {
        "command": " ".join(cmd),
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "pp_lines": _select_lines(stdout, "pp"),
        "tg_lines": _select_lines(stdout, "tg"),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    meta = payload.get("meta", {})
    settings = payload.get("settings", {})
    lines.append("# llama-bench compare")
    lines.append("")
    lines.append(f"- created_at: {meta.get('created_at')}")
    lines.append(f"- model_path: {settings.get('model_path')}")
    lines.append(f"- pg: {settings.get('pg')}")
    lines.append(f"- r: {settings.get('repeat')}")
    lines.append(f"- gpu_device: {settings.get('gpu_device')}")
    lines.append(f"- gpu_n_gpu_layers: {settings.get('gpu_n_gpu_layers')}")
    lines.append("")
    for label in ("cpu", "gpu"):
        result = payload.get(label, {})
        lines.append(f"## {label.upper()}")
        lines.append("")
        lines.append(f"- server_dir: {result.get('server_dir')}")
        lines.append(f"- bench_exe: {result.get('bench_exe')}")
        lines.append(f"- returncode: {result.get('returncode')}")
        lines.append("")
        lines.append("Command:")
        lines.append("```")
        lines.append(result.get("command", ""))
        lines.append("```")
        lines.append("")
        lines.append("pp lines:")
        for line in result.get("pp_lines", []):
            lines.append(f"- {line}")
        if not result.get("pp_lines"):
            lines.append("- (none)")
        lines.append("")
        lines.append("tg lines:")
        for line in result.get("tg_lines", []):
            lines.append(f"- {line}")
        if not result.get("tg_lines"):
            lines.append("- (none)")
        lines.append("")
        lines.append("stdout:")
        lines.append("```")
        lines.append(result.get("stdout", ""))
        lines.append("```")
        lines.append("")
        if result.get("stderr"):
            lines.append("stderr:")
            lines.append("```")
            lines.append(result.get("stderr", ""))
            lines.append("```")
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare llama-bench CPU-only vs Vulkan(iGPU) in one run."
    )
    parser.add_argument("--server-dir", type=Path, default=None)
    parser.add_argument("--cpu-server-dir", type=Path, default=None)
    parser.add_argument("--gpu-server-dir", type=Path, default=None)
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--device", type=str, default="Vulkan0")
    parser.add_argument("--n-gpu-layers", type=str, default="all")
    parser.add_argument("--pg", type=str, default="2048,256")
    parser.add_argument("-r", "--repeat", type=int, default=3)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--extra-args",
        nargs="*",
        default=[],
        help="Extra args passed to both CPU and GPU runs.",
    )

    args = parser.parse_args()

    repo_root = _repo_root()
    default_model = repo_root / "local_ai" / "models" / "HY-MT1.5-1.8B-Q4_K_M.gguf"
    model_path = args.model_path or default_model

    base_server_dir = args.server_dir or (repo_root / "local_ai" / "llama_cpp")
    cpu_dir = args.cpu_server_dir or _resolve_variant_dir(base_server_dir, "avx2")
    gpu_dir = args.gpu_server_dir or _resolve_variant_dir(base_server_dir, "vulkan")

    cpu_bench = _find_bench_exe(cpu_dir)
    gpu_bench = _find_bench_exe(gpu_dir)

    cpu_result = _run_bench(
        bench_exe=cpu_bench,
        model_path=model_path,
        device="none",
        n_gpu_layers="0",
        pg=args.pg,
        repeat=args.repeat,
        extra_args=args.extra_args,
    )
    cpu_result.update({"server_dir": str(cpu_dir), "bench_exe": str(cpu_bench)})

    gpu_result = _run_bench(
        bench_exe=gpu_bench,
        model_path=model_path,
        device=args.device,
        n_gpu_layers=str(args.n_gpu_layers),
        pg=args.pg,
        repeat=args.repeat,
        extra_args=args.extra_args,
    )
    gpu_result.update({"server_dir": str(gpu_dir), "bench_exe": str(gpu_bench)})

    payload = {
        "meta": {"created_at": datetime.now(timezone.utc).isoformat()},
        "settings": {
            "model_path": str(model_path),
            "pg": args.pg,
            "repeat": args.repeat,
            "gpu_device": args.device,
            "gpu_n_gpu_layers": str(args.n_gpu_layers),
        },
        "cpu": cpu_result,
        "gpu": gpu_result,
    }

    if args.out is None:
        suffix = "json" if args.format == "json" else "md"
        out_path = repo_root / ".tmp" / f"llama_bench_compare.{suffix}"
    else:
        out_path = args.out

    if args.format == "json":
        _write_json(out_path, payload)
    else:
        _write_markdown(out_path, payload)

    if cpu_result["returncode"] != 0 or gpu_result["returncode"] != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
