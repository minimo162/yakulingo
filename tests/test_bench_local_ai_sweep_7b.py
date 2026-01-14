from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import bench_local_ai_sweep_7b as sweep


def _build_specs(tmp_path: Path, *, preset: str) -> list[sweep.RunSpec]:
    model = tmp_path / "model.gguf"
    model.write_text("x", encoding="utf-8")
    cpu_dir = tmp_path / "cpu"
    cpu_dir.mkdir()
    gpu_dir = tmp_path / "gpu"
    gpu_dir.mkdir()

    return sweep._build_run_specs(
        preset=preset,
        model_path=model,
        cpu_server_dir=cpu_dir,
        gpu_server_dir=gpu_dir,
        gpu_device="Vulkan0",
        ngl_main="16",
        ngl_full="99",
        vk_force_max_allocation_size=None,
        vk_disable_f16=False,
        warmup_runs=0,
        compare=False,
        physical_cores=4,
        logical_cores=8,
    )


def test_run_timeout_creates_error_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = sweep.RunSpec(tag="timeout", args=["--mode", "warm"])
    out_path = tmp_path / "out.json"
    log_path = tmp_path / "out.log"

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", args[0]), timeout=1)

    monkeypatch.setattr(sweep.subprocess, "run", fake_run)

    result = sweep._run(
        "python",
        tmp_path / "bench.py",
        spec=spec,
        out_path=out_path,
        log_path=log_path,
        timeout_s=1.0,
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["error"] == "timeout"
    assert payload["returncode"] == 124
    assert result["returncode"] == 124
    assert "timeout" in log_path.read_text(encoding="utf-8").lower()


def test_resume_skips_existing_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    specs = [
        sweep.RunSpec(tag="cpu_base", args=[]),
        sweep.RunSpec(tag="vk_ngl_99", args=[]),
    ]
    for spec in specs:
        out_path = out_dir / f"{spec.tag}.json"
        out_path.write_text(
            json.dumps({"tag": spec.tag, "returncode": 0, "settings": {}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(sweep, "_build_run_specs", lambda **kwargs: specs)
    monkeypatch.setattr(sweep, "_git_head_short", lambda _: "deadbee")
    monkeypatch.setattr(sweep, "_find_physical_logical_cores", lambda: (1, 2))

    def fail_run(*args, **kwargs):
        raise AssertionError("resume should skip subprocess runs")

    monkeypatch.setattr(sweep, "_run", fail_run)

    model = tmp_path / "model.gguf"
    model.write_text("x", encoding="utf-8")
    cpu_dir = tmp_path / "cpu"
    cpu_dir.mkdir()
    gpu_dir = tmp_path / "gpu"
    gpu_dir.mkdir()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--resume",
            "--out-dir",
            str(out_dir),
            "--model-path",
            str(model),
            "--cpu-server-dir",
            str(cpu_dir),
            "--gpu-server-dir",
            str(gpu_dir),
        ],
    )

    assert sweep.main() == 0

    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    rows = summary.get("rows", [])
    assert len(rows) == 2
    assert any(row.get("reused") for row in rows)


def test_quick_preset_excludes_risky_tags(tmp_path: Path) -> None:
    tags = [spec.tag for spec in _build_specs(tmp_path, preset="quick")]

    assert "cpu_base" in tags
    assert "vk_ngl_99" in tags
    assert "vk_ngl_16" in tags
    assert "vk_ngl_16_tb_logical" in tags

    assert "vk_ngl_32" not in tags
    assert not any(tag.endswith("_b1024_ub256") for tag in tags)
    assert not any(tag.endswith("_ctx4096") for tag in tags)
    assert not any(tag.endswith("_ct_q4_0") for tag in tags)
    assert not any(tag.endswith("_fa_0") for tag in tags)
    assert not any(tag.endswith("_mlock_no_mmap") for tag in tags)


def test_full_preset_includes_risky_tags(tmp_path: Path) -> None:
    tags = [spec.tag for spec in _build_specs(tmp_path, preset="full")]

    assert "vk_ngl_32" in tags
    assert any(tag.endswith("_b1024_ub256") for tag in tags)
    assert any(tag.endswith("_ctx4096") for tag in tags)
    assert any(tag.endswith("_ct_q4_0") for tag in tags)
    assert any(tag.endswith("_fa_0") for tag in tags)
    assert any(tag.endswith("_mlock_no_mmap") for tag in tags)


def test_cpu_preset_is_cpu_only_and_uses_short_input(tmp_path: Path) -> None:
    specs = _build_specs(tmp_path, preset="cpu")
    tags = [spec.tag for spec in specs]

    assert "cpu_base" in tags
    assert "cpu_ctx4096" in tags
    assert "cpu_b256_ub64" in tags
    assert "cpu_b1024_ub256" in tags
    assert any(tag.startswith("cpu_t") for tag in tags)
    assert not any(tag.startswith("vk_ngl_") for tag in tags)

    cpu_dir = str(tmp_path / "cpu")
    for spec in specs:
        assert spec.args[spec.args.index("--server-dir") + 1] == cpu_dir
        assert spec.args[spec.args.index("--device") + 1] == "none"
        assert spec.args[spec.args.index("--n-gpu-layers") + 1] == "0"
        input_path = Path(spec.args[spec.args.index("--input") + 1])
        assert input_path.name == "bench_local_ai_input_short.txt"


def test_vulkan_preset_is_vulkan_only_and_includes_safe_grid(tmp_path: Path) -> None:
    specs = _build_specs(tmp_path, preset="vulkan")
    tags = [spec.tag for spec in specs]

    assert "vk_ngl_99" in tags
    assert "vk_ngl_16" in tags
    assert "vk_ngl_16_fa_0" in tags
    assert "vk_ngl_16_ct_q4_0" in tags
    assert "vk_ngl_16_alloc256m" in tags
    assert "vk_ngl_16_no_f16" in tags
    assert not any(tag.startswith("cpu_") for tag in tags)

    gpu_dir = str(tmp_path / "gpu")
    for spec in specs:
        assert spec.args[spec.args.index("--server-dir") + 1] == gpu_dir
        assert spec.args[spec.args.index("--device") + 1] == "Vulkan0"
        input_path = Path(spec.args[spec.args.index("--input") + 1])
        assert input_path.name == "bench_local_ai_input_short.txt"

    alloc_spec = next(spec for spec in specs if spec.tag.endswith("_alloc256m"))
    assert (
        alloc_spec.args[alloc_spec.args.index("--vk-force-max-allocation-size") + 1]
        == "268435456"
    )

    no_f16_spec = next(spec for spec in specs if spec.tag.endswith("_no_f16"))
    assert "--vk-disable-f16" in no_f16_spec.args

    ct_spec = next(spec for spec in specs if spec.tag.endswith("_ct_q4_0"))
    assert ct_spec.args[ct_spec.args.index("--cache-type-k") + 1] == "q4_0"
    assert ct_spec.args[ct_spec.args.index("--cache-type-v") + 1] == "q4_0"

    fa0_spec = next(spec for spec in specs if spec.tag.endswith("_fa_0"))
    assert fa0_spec.args[fa0_spec.args.index("--flash-attn") + 1] == "0"
