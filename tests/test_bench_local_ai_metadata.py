from __future__ import annotations

import json
from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_llama_server import LocalAIServerRuntime

from tools import bench_local_ai


class DummyServerManager:
    def __init__(self, state_path: Path, runtime: LocalAIServerRuntime | None) -> None:
        self._state_path = state_path
        self._runtime = runtime

    def get_state_path(self) -> Path:
        return self._state_path

    def get_runtime(self) -> LocalAIServerRuntime | None:
        return self._runtime


def test_collect_server_metadata_resolves_paths_and_runtime(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    state_path = tmp_path / "state.json"
    state_data = {
        "server_exe_path_resolved": str(tmp_path / "bin" / "llama-server.exe")
    }
    state_path.write_text(json.dumps(state_data), encoding="utf-8")

    runtime = LocalAIServerRuntime(
        host="127.0.0.1",
        port=8000,
        base_url="http://127.0.0.1:8000",
        model_id="model",
        server_exe_path=tmp_path / "runtime" / "llama-server.exe",
        server_variant="vulkan",
        model_path=tmp_path / "models" / "model.gguf",
    )

    settings = AppSettings(
        local_ai_server_dir="local_ai/llama_cpp",
        local_ai_model_path="models/model.gguf",
    )
    settings._validate()

    manager = DummyServerManager(state_path, runtime)

    metadata = bench_local_ai._collect_server_metadata(settings, repo_root, manager)

    assert metadata["server_dir_config"] == "local_ai/llama_cpp"
    assert metadata["server_dir_resolved"] == str(repo_root / "local_ai" / "llama_cpp")
    assert metadata["model_path_config"] == "models/model.gguf"
    assert metadata["model_path_resolved"] == str(repo_root / "models" / "model.gguf")
    assert metadata["server_state_path"] == str(state_path)
    assert metadata["server_state"] == state_data
    assert metadata["runtime"] == {
        "host": "127.0.0.1",
        "port": 8000,
        "base_url": "http://127.0.0.1:8000",
        "model_id": "model",
        "server_exe_path": str(tmp_path / "runtime" / "llama-server.exe"),
        "server_variant": "vulkan",
        "model_path": str(tmp_path / "models" / "model.gguf"),
    }
    assert metadata["llama_server_path"] == str(
        tmp_path / "runtime" / "llama-server.exe"
    )
    assert metadata["llama_server_version"] is None
    assert metadata["llama_cli_path"] is None
    assert metadata["llama_cli_version"] is None


def test_collect_git_metadata_includes_commit_and_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    class DummyCompleted:
        def __init__(self, *, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(*args, **kwargs):
        cmd = kwargs.get("args") or args[0]
        if cmd == ["git", "rev-parse", "HEAD"]:
            return DummyCompleted(
                returncode=0, stdout="0123456789abcdef0123456789abcdef01234567\n"
            )
        if cmd == ["git", "rev-parse", "--short", "HEAD"]:
            return DummyCompleted(returncode=0, stdout="0123456\n")
        if cmd == ["git", "status", "--porcelain"]:
            return DummyCompleted(returncode=0, stdout="")
        raise AssertionError(f"unexpected git command: {cmd}")

    monkeypatch.setattr(bench_local_ai.subprocess, "run", fake_run)

    metadata = bench_local_ai._collect_git_metadata(repo_root)

    assert metadata["commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert metadata["commit_short"] == "0123456"
    assert metadata["dirty"] is False


def test_collect_runtime_metadata_includes_cpu_counts() -> None:
    metadata = bench_local_ai._collect_runtime_metadata()

    assert "platform" in metadata
    assert "python" in metadata
    assert "cpu_physical_cores" in metadata
    assert "cpu_logical_cores" in metadata
