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


def test_find_free_port_returns_none_when_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = lls.LocalLlamaServerManager()
    monkeypatch.setattr(lls, "_is_port_free", lambda host, port: False)
    assert manager._find_free_port("127.0.0.1", 4891, 4893) is None


def test_ensure_ready_calls_reuse_before_scanning_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_state_path",
        staticmethod(lambda: tmp_path / "state.json"),
    )
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_log_path",
        staticmethod(lambda: tmp_path / "local_ai_server.log"),
    )

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


def test_ensure_ready_does_not_scan_ports_when_reuse_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_state_path",
        staticmethod(lambda: tmp_path / "state.json"),
    )

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
    monkeypatch.setattr(
        manager,
        "_find_free_port",
        lambda host, port_base, port_max: (_ for _ in ()).throw(
            AssertionError("port scan should not run")
        ),
    )
    monkeypatch.setattr(
        manager,
        "_start_new_server",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("start should not run")),
    )

    assert manager.ensure_ready(settings) == reuse_runtime


def test_ensure_ready_falls_back_to_bundled_server_dir_when_custom_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"dummy")

    monkeypatch.setattr(lls, "_app_base_dir", lambda: tmp_path)
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_state_path",
        staticmethod(lambda: tmp_path / "state.json"),
    )
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_log_path",
        staticmethod(lambda: tmp_path / "local_ai_server.log"),
    )

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
    monkeypatch.setattr(
        manager, "_find_free_port", lambda host, port_base, port_max: port_base
    )
    monkeypatch.setattr(manager, "_start_new_server", fake_start_new_server)

    runtime = manager.ensure_ready(settings)

    assert runtime.server_exe_path == exe_path
    assert seen_dirs == [tmp_path / "custom" / "invalid", bundled_dir]


def test_resolve_server_exe_prefers_vulkan_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = tmp_path / "llama_cpp"
    for variant in ("vulkan", "avx2", "generic"):
        variant_dir = server_dir / variant
        variant_dir.mkdir(parents=True, exist_ok=True)
        (variant_dir / "llama-server.exe").write_bytes(b"exe")

    monkeypatch.setattr(lls, "_probe_executable_supported", lambda path: True)
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_state_path",
        staticmethod(lambda: tmp_path / "state.json"),
    )

    manager = lls.LocalLlamaServerManager()
    exe_path, variant = manager._resolve_server_exe(server_dir)

    assert variant == "vulkan"
    assert exe_path == server_dir / "vulkan" / "llama-server.exe"


def test_ensure_ready_fast_path_uses_running_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"dummy")

    server_dir = tmp_path / "llama_cpp"
    server_dir.mkdir(parents=True)
    exe_path = server_dir / "llama-server.exe"
    exe_path.write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(model_path),
        local_ai_server_dir=str(server_dir),
        local_ai_port_base=4891,
        local_ai_port_max=4893,
    )

    manager = lls.LocalLlamaServerManager()
    manager._runtime = lls.LocalAIServerRuntime(
        host="127.0.0.1",
        port=4891,
        base_url="http://127.0.0.1:4891",
        model_id=None,
        server_exe_path=exe_path,
        server_variant="direct",
        model_path=model_path,
    )

    class DummyProcess:
        pid = 12345

        def poll(self):
            return None

    manager._process = DummyProcess()

    monkeypatch.setattr(
        manager,
        "_try_reuse",
        lambda state, **kwargs: (_ for _ in ()).throw(
            AssertionError("reuse should not run")
        ),
    )
    monkeypatch.setattr(
        manager,
        "_find_free_port",
        lambda host, port_base, port_max: (_ for _ in ()).throw(
            AssertionError("port scan should not run")
        ),
    )
    monkeypatch.setattr(
        manager,
        "_start_new_server",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("start should not run")
        ),
    )

    runtime = manager.ensure_ready(settings)

    assert runtime == manager._runtime


def test_ensure_ready_fast_path_skips_when_model_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "model_old.gguf"
    model_path.write_bytes(b"old")
    new_model_path = tmp_path / "model_new.gguf"
    new_model_path.write_bytes(b"new")

    server_dir = tmp_path / "llama_cpp"
    server_dir.mkdir(parents=True)
    exe_path = server_dir / "llama-server.exe"
    exe_path.write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(new_model_path),
        local_ai_server_dir=str(server_dir),
        local_ai_port_base=4891,
        local_ai_port_max=4893,
    )

    manager = lls.LocalLlamaServerManager()
    manager._runtime = lls.LocalAIServerRuntime(
        host="127.0.0.1",
        port=4891,
        base_url="http://127.0.0.1:4891",
        model_id=None,
        server_exe_path=exe_path,
        server_variant="direct",
        model_path=model_path,
    )

    class DummyProcess:
        pid = 12345

        def poll(self):
            return None

    manager._process = DummyProcess()

    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_state_path",
        staticmethod(lambda: tmp_path / "state.json"),
    )
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_log_path",
        staticmethod(lambda: tmp_path / "local_ai_server.log"),
    )
    monkeypatch.setattr(manager, "_resolve_server_exe", lambda _: (exe_path, "direct"))

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

    assert calls == ["reuse", "find_port", "start"]
    assert runtime.model_path == new_model_path


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


def test_build_server_args_adds_gpu_flags_when_available(
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
            "--device",
            "-ngl, --n-gpu-layers",
            "-fa, --flash-attn",
            "-ctk, --cache-type-k",
            "-ctv, --cache-type-v",
            "--no-warmup",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(*args, **kwargs):
        return DummyCompleted(help_text)

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    settings = AppSettings(
        local_ai_device="Vulkan0",
        local_ai_n_gpu_layers=99,
        local_ai_flash_attn="1",
        local_ai_no_warmup=True,
        local_ai_cache_type_k="q8_0",
        local_ai_cache_type_v="q8_0",
    )
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--device" in args
    assert args[args.index("--device") + 1] == "Vulkan0"
    assert "--n-gpu-layers" in args
    assert args[args.index("--n-gpu-layers") + 1] == "99"
    assert "-fa" in args
    assert args[args.index("-fa") + 1] == "1"
    assert "--cache-type-k" in args
    assert args[args.index("--cache-type-k") + 1] == "q8_0"
    assert "--cache-type-v" in args
    assert args[args.index("--cache-type-v") + 1] == "q8_0"
    assert "--no-warmup" in args


def test_build_server_args_auto_threads_when_zero(
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
    monkeypatch.setattr(lls.psutil, "cpu_count", lambda logical=None: 4)
    monkeypatch.setattr(lls.os, "cpu_count", lambda: 6)

    settings = AppSettings(local_ai_threads=0)
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--threads" in args
    assert args[args.index("--threads") + 1] == "4"


def test_build_server_args_auto_threads_fallbacks_when_physical_missing(
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
    monkeypatch.setattr(lls.psutil, "cpu_count", lambda logical=None: None)
    monkeypatch.setattr(lls.os, "cpu_count", lambda: 6)

    settings = AppSettings(local_ai_threads=0)
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--threads" in args
    assert args[args.index("--threads") + 1] == "6"


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


def test_start_new_server_injects_vk_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"model")

    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_log_path",
        staticmethod(lambda: tmp_path / "local_ai_server.log"),
    )
    monkeypatch.setattr(
        manager,
        "_build_server_args",
        lambda **kwargs: [str(server_exe_path)],
    )
    monkeypatch.setattr(
        manager,
        "_wait_ready",
        lambda *args, **kwargs: (True, None, {}),
    )

    captured = {}

    class DummyProc:
        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return DummyProc()

    monkeypatch.setattr(lls.subprocess, "Popen", fake_popen)

    settings = AppSettings(
        local_ai_vk_force_max_allocation_size=536870912,
        local_ai_vk_disable_f16=True,
    )
    settings._validate()

    runtime = manager._start_new_server(
        server_exe_path=server_exe_path,
        server_variant="direct",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert runtime.model_path == model_path
    assert captured["env"]["GGML_VK_FORCE_MAX_ALLOCATION_SIZE"] == "536870912"
    assert captured["env"]["GGML_VK_DISABLE_F16"] == "1"


def test_build_server_args_uses_cached_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"model")

    help_text = "\n".join(["-m, --model", "--threads"])

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        return DummyCompleted(help_text)

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    with lls._HELP_TEXT_CACHE_LOCK:
        lls._HELP_TEXT_CACHE.clear()

    settings = AppSettings(local_ai_threads=1)
    settings._validate()

    manager._build_server_args(
        server_exe_path=server_exe_path,
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )
    manager._build_server_args(
        server_exe_path=server_exe_path,
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert calls["count"] == 1
