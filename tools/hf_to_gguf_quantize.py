from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _norm_nl(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _safe_slug(text: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-") or "model"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _download_file(url: str, out_path: Path) -> None:
    _ensure_dir(out_path.parent)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "YakuLingo-Tools"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Download failed: HTTP {resp.status} {url}")
        data = resp.read()
    out_path.write_bytes(data)


def _download_hf_raw_text(
    *, repo_id: str, revision: str, filename: str, token: str | None
) -> str | None:
    url = f"https://huggingface.co/{repo_id}/raw/{revision}/{filename}"
    headers = {"User-Agent": "YakuLingo-Tools"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def _extract_registered_architectures(convert_script: Path) -> set[str]:
    try:
        content = convert_script.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()

    registered: set[str] = set()
    for match in re.finditer(
        r"@ModelBase\.register\((?P<args>[^)]*)\)", content, flags=re.DOTALL
    ):
        args = match.group("args")
        for name in re.findall(r"""["']([^"']+)["']""", args):
            stripped = name.strip()
            if stripped:
                registered.add(stripped)
    return registered


def _read_model_architectures(model_dir: Path) -> list[str]:
    cfg = _read_json(model_dir / "config.json") or {}
    architectures = cfg.get("architectures")
    if isinstance(architectures, str) and architectures.strip():
        return [architectures.strip()]
    if isinstance(architectures, list):
        return [str(x).strip() for x in architectures if str(x).strip()]
    return []


def _format_unsupported_arch_message(
    *,
    model_arch: str,
    hf_repo: str | None,
    revision: str,
    llama_tag: str,
    convert_script: Path,
    registered_count: int,
) -> str:
    repo_label = hf_repo or "<local-model-dir>"
    return _norm_nl(
        f"""
        Unsupported HF->GGUF conversion target detected.

        - hf_repo     : {repo_label}
        - revision    : {revision}
        - llama.cpp   : {llama_tag}
        - architecture: {model_arch}
        - convert     : {convert_script}
        - registered  : {registered_count} architectures

        This model architecture is not supported by the current llama.cpp conversion script.

        Recovery:
          - Use a prebuilt GGUF model (.gguf) instead of HF conversion.
          - Download the .gguf from Hugging Face and place it under local_ai/models/.
          - Note: YakuLingo runtime uses a fixed model file name; see README.

        Note: Some HF models require custom code (trust_remote_code). This tool runs conversion
        without executing remote code for safety; even with trust_remote_code, an unregistered
        architecture will still fail.
        """
    ).strip()


def _extract_single_root_dir(zip_path: Path, out_dir: Path) -> Path:
    _ensure_dir(out_dir)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
    roots = [p for p in out_dir.iterdir() if p.is_dir()]
    if len(roots) == 1:
        return roots[0]
    for candidate in roots:
        if candidate.name.startswith("llama.cpp-"):
            return candidate
    raise RuntimeError(f"Unexpected ZIP layout: {zip_path}")


def _get_llama_cpp_tag_from_manifest(repo_root: Path) -> str | None:
    manifest = _read_json(repo_root / "local_ai" / "manifest.json")
    if not manifest:
        return None
    llama_cpp = manifest.get("llama_cpp")
    if not isinstance(llama_cpp, dict):
        return None
    tag = llama_cpp.get("release_tag")
    return tag if isinstance(tag, str) and tag.strip() else None


def _llama_cpp_zip_urls(ref: str) -> list[str]:
    normalized = ref.strip() or "master"
    base = "https://github.com/ggerganov/llama.cpp/archive/refs"
    heads_url = f"{base}/heads/{normalized}.zip"
    tags_url = f"{base}/tags/{normalized}.zip"
    if normalized in {"master", "main"}:
        return [heads_url, tags_url]
    return [tags_url, heads_url]


def _resolve_llama_cpp_source(repo_root: Path, *, tag: str) -> Path:
    tag = tag.strip() or "master"
    cache_dir = repo_root / ".tmp" / "llama_cpp_src" / tag
    root_marker = cache_dir / ".extracted.ok"
    if root_marker.exists():
        roots = [
            p for p in cache_dir.iterdir() if p.is_dir() and p.name != "__pycache__"
        ]
        for p in roots:
            if (p / "LICENSE").exists():
                return p
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    _ensure_dir(cache_dir)

    zip_path = repo_root / ".tmp" / "downloads" / f"llama.cpp-{tag}.zip"
    attempted_urls: list[str] = []
    last_error: BaseException | None = None
    for zip_url in _llama_cpp_zip_urls(tag):
        attempted_urls.append(zip_url)
        print(
            f"[INFO] Downloading llama.cpp source: {zip_url}",
            file=sys.stderr,
            flush=True,
        )
        try:
            _download_file(zip_url, zip_path)
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                print(
                    f"[WARN] llama.cpp source not found (HTTP 404): {zip_url}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            raise RuntimeError(
                "Failed to download llama.cpp source.\n"
                + "Tried:\n"
                + "\n".join(f"- {u}" for u in attempted_urls)
            ) from exc
        except Exception as exc:
            last_error = exc
            raise RuntimeError(
                "Failed to download llama.cpp source.\n"
                + "Tried:\n"
                + "\n".join(f"- {u}" for u in attempted_urls)
            ) from exc
    else:
        raise RuntimeError(
            "Failed to download llama.cpp source (all candidates returned HTTP 404).\n"
            + "Tried:\n"
            + "\n".join(f"- {u}" for u in attempted_urls)
        ) from last_error

    extracted_root = _extract_single_root_dir(zip_path, cache_dir)
    root_marker.write_text("ok\n", encoding="utf-8")
    return extracted_root


def _find_convert_script(llama_src: Path) -> Path:
    candidates = [
        llama_src / "convert_hf_to_gguf.py",
        llama_src / "convert-hf-to-gguf.py",
    ]
    for c in candidates:
        if c.is_file():
            return c

    matches = list(llama_src.rglob("convert_hf_to_gguf.py")) + list(
        llama_src.rglob("convert-hf-to-gguf.py")
    )
    for m in matches:
        if m.is_file():
            return m
    raise FileNotFoundError("convert_hf_to_gguf.py not found in llama.cpp source")


def _resolve_python() -> str:
    return sys.executable or "python"


def _run_checked(args: list[str], *, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(args)
            + "\n\nOutput:\n"
            + (completed.stdout or "")
        )


def _get_help_text(script_path: Path) -> str:
    python = _resolve_python()
    completed = subprocess.run(
        [python, str(script_path), "-h"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.stdout or ""


def _resolve_llama_quantize_exe(repo_root: Path) -> Path:
    base = repo_root / "local_ai" / "llama_cpp"
    candidates: list[Path] = []
    for variant in ("avx2", "vulkan", "generic"):
        candidates += [
            base / variant / "llama-quantize.exe",
            base / variant / "llama-quantize",
        ]
    candidates += [base / "llama-quantize.exe", base / "llama-quantize"]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "llama-quantize executable not found under local_ai/llama_cpp"
    )


@dataclass(frozen=True)
class ResolvedOutputs:
    f16_gguf_path: Path
    quant_gguf_path: Path


def _resolve_outputs(
    repo_root: Path,
    *,
    base_name: str,
    quant: str,
    out_dir: Path | None,
) -> ResolvedOutputs:
    out_dir_resolved = out_dir or (repo_root / "local_ai" / "models")
    out_dir_resolved = (
        out_dir_resolved
        if out_dir_resolved.is_absolute()
        else repo_root / out_dir_resolved
    )
    _ensure_dir(out_dir_resolved)

    base = base_name.strip() or "model"
    quant_token = quant.strip() or "Q4_K_M"
    f16_path = out_dir_resolved / f"{base}.f16.gguf"
    q_path = out_dir_resolved / f"{base}.{quant_token}.gguf"
    return ResolvedOutputs(f16_gguf_path=f16_path, quant_gguf_path=q_path)


def _resolve_model_dir(
    repo_root: Path,
    *,
    hf_repo: str | None,
    revision: str,
    model_dir: Path | None,
) -> Path:
    if model_dir is not None:
        resolved = model_dir if model_dir.is_absolute() else repo_root / model_dir
        if not resolved.is_dir():
            raise FileNotFoundError(f"Model directory not found: {resolved}")
        return resolved

    if not hf_repo:
        raise ValueError("Either --model-dir or --hf-repo is required")

    # Best-effort auto download via huggingface_hub (optional dependency).
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            _norm_nl(
                f"""
                huggingface_hub is required when using --hf-repo.

                Install (example):
                  uv pip install huggingface_hub

                Alternatively, download the model locally and pass:
                  --model-dir <path>

                Original import error: {exc}
                """
            ).strip()
        ) from exc

    cache_dir = (
        repo_root / ".tmp" / "hf_models" / _safe_slug(hf_repo) / _safe_slug(revision)
    )
    _ensure_dir(cache_dir)

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    local_dir = cache_dir / "snapshot"
    if local_dir.is_dir() and any(local_dir.iterdir()):
        return local_dir

    snapshot_download(
        repo_id=hf_repo,
        revision=revision,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
        token=token,
    )
    return local_dir


def main(argv: list[str] | None = None) -> int:
    exit_unsupported_arch = 42
    parser = argparse.ArgumentParser(
        description="HFモデルをGGUFへ変換し、llama-quantizeで4bit量子化します（メンテナ向け）。",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--hf-repo",
        default=None,
        help="Hugging Face repo id (例: openbmb/AgentCPM-Explore)。--model-dir と排他。",
    )
    parser.add_argument(
        "--revision",
        default="main",
        help="Hugging Face revision (branch/tag/commit SHA)。既定: main",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="事前に取得済みのHFモデルディレクトリ（推奨）。--hf-repo と排他。",
    )
    parser.add_argument(
        "--base-name",
        default="AgentCPM-Explore",
        help="出力ファイルのベース名（既定: AgentCPM-Explore）。",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="出力ディレクトリ（既定: local_ai/models）。",
    )
    parser.add_argument(
        "--quant",
        default="Q4_K_M",
        help="量子化タイプ（例: Q4_K_M）。既定: Q4_K_M",
    )
    parser.add_argument(
        "--llama-tag",
        default=None,
        help="llama.cpp ソース取得のタグ（既定: local_ai/manifest.json の release_tag、無ければ master）。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="既存出力があっても再生成します。",
    )

    args = parser.parse_args(argv)

    if args.hf_repo and args.model_dir is not None:
        raise SystemExit("--hf-repo and --model-dir are mutually exclusive")

    repo_root = _repo_root()

    outputs = _resolve_outputs(
        repo_root,
        base_name=args.base_name,
        quant=args.quant,
        out_dir=args.out_dir,
    )

    quant_exe = _resolve_llama_quantize_exe(repo_root)

    tag = (
        str(args.llama_tag).strip()
        if args.llama_tag is not None
        else (_get_llama_cpp_tag_from_manifest(repo_root) or "master")
    )
    llama_src = _resolve_llama_cpp_source(repo_root, tag=tag)
    convert_script = _find_convert_script(llama_src)
    registered_arch = _extract_registered_architectures(convert_script)

    gguf_py = llama_src / "gguf-py"
    if not gguf_py.is_dir():
        raise FileNotFoundError(f"gguf-py not found in llama.cpp source: {gguf_py}")

    # Early guard: avoid downloading full HF snapshots when conversion is known to be unsupported.
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    precheck_architectures: list[str] = []
    if args.model_dir is not None:
        resolved_dir = (
            args.model_dir
            if args.model_dir.is_absolute()
            else repo_root / args.model_dir
        )
        if resolved_dir.is_dir():
            precheck_architectures = _read_model_architectures(resolved_dir)
    elif args.hf_repo:
        raw = _download_hf_raw_text(
            repo_id=args.hf_repo,
            revision=args.revision,
            filename="config.json",
            token=token,
        )
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    architectures = payload.get("architectures")
                    if isinstance(architectures, str) and architectures.strip():
                        precheck_architectures = [architectures.strip()]
                    elif isinstance(architectures, list):
                        precheck_architectures = [
                            str(x).strip() for x in architectures if str(x).strip()
                        ]
            except Exception:
                precheck_architectures = []

    if registered_arch and precheck_architectures:
        model_arch = precheck_architectures[0]
        if model_arch not in registered_arch:
            print(
                _format_unsupported_arch_message(
                    model_arch=model_arch,
                    hf_repo=args.hf_repo,
                    revision=args.revision,
                    llama_tag=tag,
                    convert_script=convert_script,
                    registered_count=len(registered_arch),
                ),
                file=sys.stderr,
            )
            return exit_unsupported_arch

    if (
        outputs.quant_gguf_path.exists()
        and outputs.quant_gguf_path.stat().st_size > 0
        and not args.force
    ):
        print(f"[SKIP] Quantized GGUF already exists: {outputs.quant_gguf_path}")
        return 0

    model_dir = _resolve_model_dir(
        repo_root,
        hf_repo=args.hf_repo,
        revision=args.revision,
        model_dir=args.model_dir,
    )

    # Post-download guard: still check local config.json if available.
    if registered_arch:
        arches = _read_model_architectures(model_dir)
        if arches:
            model_arch = arches[0]
            if model_arch not in registered_arch:
                print(
                    _format_unsupported_arch_message(
                        model_arch=model_arch,
                        hf_repo=args.hf_repo,
                        revision=args.revision,
                        llama_tag=tag,
                        convert_script=convert_script,
                        registered_count=len(registered_arch),
                    ),
                    file=sys.stderr,
                )
                return exit_unsupported_arch

    python = _resolve_python()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(gguf_py) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )

    if (
        not outputs.f16_gguf_path.exists() or outputs.f16_gguf_path.stat().st_size == 0
    ) or args.force:
        help_text = _get_help_text(convert_script)
        if "--outfile" not in help_text:
            raise RuntimeError(
                "Unsupported convert script (missing --outfile). "
                "Please update llama.cpp tag or adjust the tool."
            )
        convert_args = [
            python,
            str(convert_script),
            str(model_dir),
            "--outfile",
            str(outputs.f16_gguf_path),
        ]
        if "--outtype" in help_text:
            convert_args += ["--outtype", "f16"]

        print("[INFO] Converting HF -> GGUF (f16)")
        print("       " + " ".join(convert_args))
        _run_checked(convert_args, env=env)
    else:
        print(f"[SKIP] F16 GGUF already exists: {outputs.f16_gguf_path}")

    if not outputs.f16_gguf_path.exists() or outputs.f16_gguf_path.stat().st_size == 0:
        raise RuntimeError(
            f"F16 GGUF output is missing or empty: {outputs.f16_gguf_path}"
        )

    print("[INFO] Quantizing GGUF -> 4bit")
    quant_args = [
        str(quant_exe),
        str(outputs.f16_gguf_path),
        str(outputs.quant_gguf_path),
        str(args.quant),
    ]
    print("       " + " ".join(quant_args))
    _run_checked(quant_args, env=None)

    if (
        not outputs.quant_gguf_path.exists()
        or outputs.quant_gguf_path.stat().st_size == 0
    ):
        raise RuntimeError(
            f"Quantized GGUF output is missing or empty: {outputs.quant_gguf_path}"
        )

    print("[DONE] Outputs:")
    print(f"  f16 : {outputs.f16_gguf_path}")
    print(f"  q4  : {outputs.quant_gguf_path}")
    print("")
    print("[HINT] Example usage (bench):")
    print(
        f"  uv run python tools/bench_local_ai.py --mode warm --model-path {outputs.quant_gguf_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
