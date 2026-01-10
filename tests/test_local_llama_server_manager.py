from __future__ import annotations

import os
from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services import local_llama_server as lls


def test_resolve_from_app_base_is_not_cwd_dependent(tmp_path: Path) -> None:
    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        resolved = lls._resolve_from_app_base("local_ai/models/foo.gguf")
    finally:
        os.chdir(original_cwd)

    assert resolved == lls._app_base_dir() / "local_ai" / "models" / "foo.gguf"


def test_find_free_port_scans_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = lls.LocalLlamaServerManager()

    seen: list[int] = []

    def fake_is_port_free(host: str, port: int) -> bool:
        seen.append(port)
        return port == 4892

    monkeypatch.setattr(lls, "_is_port_free", fake_is_port_free)

    assert manager._find_free_port("127.0.0.1", 4891, 4893) == 4892
    assert seen == [4891, 4892]


def test_find_free_port_returns_none_when_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = lls.LocalLlamaServerManager()
    monkeypatch.setattr(lls, "_is_port_free", lambda host, port: False)
    assert manager._find_free_port("127.0.0.1", 4891, 4893) is None


def test_ensure_ready_calls_reuse_before_scanning_ports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"dummy")

    server_dir = tmp_path / "llama_cpp"
    generic_dir = server_dir / "generic"
    generic_dir.mkdir(parents=True)
    (generic_dir / "llama-server.exe").write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(model_path),
        local_ai_server_dir=str(server_dir),
        local_ai_port_base=4891,
        local_ai_port_max=4893,
    )

    manager = lls.LocalLlamaServerManager()
    monkeypatch.setattr(lls.LocalLlamaServerManager, "get_state_path", staticmethod(lambda: tmp_path / "state.json"))
    monkeypatch.setattr(lls.LocalLlamaServerManager, "get_log_path", staticmethod(lambda: tmp_path / "local_ai_server.log"))

    calls: list[str] = []

    def fake_try_reuse(state: dict, **kwargs):
        calls.append("reuse")
        return None

    def fake_find_free_port(host: str, port_base: int, port_max: int):
        calls.append("find_port")
        return port_base

    def fake_start_new_server(**kwargs):
        calls.append("start")
        host = kwargs["host"]
        port = kwargs["port"]
        return lls.LocalAIServerRuntime(
            host=host,
            port=port,
            base_url=f"http://{host}:{port}",
            model_id=None,
            server_exe_path=kwargs["server_exe_path"],
            server_variant=str(kwargs["server_variant"]),
            model_path=kwargs["model_path"],
        )

    monkeypatch.setattr(manager, "_try_reuse", fake_try_reuse)
    monkeypatch.setattr(manager, "_find_free_port", fake_find_free_port)
    monkeypatch.setattr(manager, "_start_new_server", fake_start_new_server)

    runtime = manager.ensure_ready(settings)

    assert runtime.host == "127.0.0.1"
    assert runtime.port == 4891
    assert calls == ["reuse", "find_port", "start"]


def test_ensure_ready_does_not_scan_ports_when_reuse_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"dummy")

    server_dir = tmp_path / "llama_cpp"
    generic_dir = server_dir / "generic"
    generic_dir.mkdir(parents=True)
    (generic_dir / "llama-server.exe").write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(model_path),
        local_ai_server_dir=str(server_dir),
        local_ai_port_base=4891,
        local_ai_port_max=4893,
    )

    manager = lls.LocalLlamaServerManager()
    monkeypatch.setattr(lls.LocalLlamaServerManager, "get_state_path", staticmethod(lambda: tmp_path / "state.json"))

    reuse_runtime = lls.LocalAIServerRuntime(
        host="127.0.0.1",
        port=4899,
        base_url="http://127.0.0.1:4899",
        model_id=None,
        server_exe_path=generic_dir / "llama-server.exe",
        server_variant="generic",
        model_path=model_path,
    )

    monkeypatch.setattr(manager, "_try_reuse", lambda state, **kwargs: reuse_runtime)
    monkeypatch.setattr(manager, "_find_free_port", lambda host, port_base, port_max: (_ for _ in ()).throw(AssertionError("port scan should not run")))
    monkeypatch.setattr(manager, "_start_new_server", lambda **kwargs: (_ for _ in ()).throw(AssertionError("start should not run")))

    assert manager.ensure_ready(settings) == reuse_runtime


def test_ensure_ready_falls_back_to_bundled_server_dir_when_custom_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"dummy")

    monkeypatch.setattr(lls, "_app_base_dir", lambda: tmp_path)
    monkeypatch.setattr(lls.LocalLlamaServerManager, "get_state_path", staticmethod(lambda: tmp_path / "state.json"))
    monkeypatch.setattr(lls.LocalLlamaServerManager, "get_log_path", staticmethod(lambda: tmp_path / "local_ai_server.log"))

    bundled_dir = tmp_path / "local_ai" / "llama_cpp"
    exe_path = bundled_dir / "generic" / "llama-server.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(model_path),
        local_ai_server_dir="custom/invalid",
        local_ai_port_base=4891,
        local_ai_port_max=4893,
    )

    manager = lls.LocalLlamaServerManager()

    seen_dirs: list[Path] = []

    def fake_resolve_server_exe(server_dir: Path):
        seen_dirs.append(server_dir)
        if server_dir == tmp_path / "custom" / "invalid":
            return None, "unknown"
        if server_dir == bundled_dir:
            return exe_path, "generic"
        return None, "unknown"

    def fake_start_new_server(**kwargs):
        host = kwargs["host"]
        port = kwargs["port"]
        return lls.LocalAIServerRuntime(
            host=host,
            port=port,
            base_url=f"http://{host}:{port}",
            model_id=None,
            server_exe_path=kwargs["server_exe_path"],
            server_variant=str(kwargs["server_variant"]),
            model_path=kwargs["model_path"],
        )

    monkeypatch.setattr(manager, "_resolve_server_exe", fake_resolve_server_exe)
    monkeypatch.setattr(manager, "_try_reuse", lambda state, **kwargs: None)
    monkeypatch.setattr(manager, "_find_free_port", lambda host, port_base, port_max: port_base)
    monkeypatch.setattr(manager, "_start_new_server", fake_start_new_server)

    runtime = manager.ensure_ready(settings)

    assert runtime.server_exe_path == exe_path
    assert seen_dirs == [tmp_path / "custom" / "invalid", bundled_dir]


def test_build_server_args_adds_batch_flags_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"model")

    help_text = "\n".join(
        [
            "-m, --model",
            "--ctx-size",
            "--threads",
            "--temp",
            "--n-predict",
            "--batch-size",
            "--ubatch-size",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(*args, **kwargs):
        return DummyCompleted(help_text)

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    settings = AppSettings(
        local_ai_batch_size=512,
        local_ai_ubatch_size=128,
    )
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--batch-size" in args
    assert args[args.index("--batch-size") + 1] == "512"
    assert "--ubatch-size" in args
    assert args[args.index("--ubatch-size") + 1] == "128"


def test_build_server_args_skips_batch_flags_without_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"model")

    help_text = "\n".join(
        [
            "-m, --model",
            "--ctx-size",
            "--threads",
            "--temp",
            "--n-predict",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(*args, **kwargs):
        return DummyCompleted(help_text)

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    settings = AppSettings(
        local_ai_batch_size=512,
        local_ai_ubatch_size=128,
    )
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--batch-size" not in args
    assert "-b" not in args
    assert "--ubatch-size" not in args
    assert "-ub" not in args
