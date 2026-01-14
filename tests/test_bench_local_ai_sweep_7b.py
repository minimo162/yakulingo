from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import bench_local_ai_sweep_7b as sweep


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
