from __future__ import annotations

import os
import logging
from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services import local_llama_server as lls


def _patch_app_base_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lls, "_app_base_dir", lambda: tmp_path)


def test_ensure_ready_raises_install_hint_when_fixed_model_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = AppSettings()
    monkeypatch.setattr(lls, "_app_base_dir", lambda: tmp_path)

    manager = lls.LocalLlamaServerManager()
    with pytest.raises(lls.LocalAINotInstalledError) as excinfo:
        manager.ensure_ready(settings)

    message = str(excinfo.value)
    assert "local_ai_model_path" in message
    assert settings.local_ai_model_path in message


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
    settings_model_path = tmp_path / "settings_model.gguf"
    settings_model_path.write_bytes(b"dummy")

    server_dir = tmp_path / "llama_cpp"
    generic_dir = server_dir / "generic"
    generic_dir.mkdir(parents=True)
    (generic_dir / "llama-server.exe").write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(settings_model_path),
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
    assert runtime.model_path == settings_model_path


def test_ensure_ready_does_not_scan_ports_when_reuse_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_model_path = tmp_path / "settings_model.gguf"
    settings_model_path.write_bytes(b"dummy")

    server_dir = tmp_path / "llama_cpp"
    generic_dir = server_dir / "generic"
    generic_dir.mkdir(parents=True)
    (generic_dir / "llama-server.exe").write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(settings_model_path),
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
        model_path=settings_model_path,
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


def test_try_reuse_skips_psutil_when_state_not_recent_and_port_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"model")

    expected_model_size, expected_model_mtime = lls._file_fingerprint(model_path)
    expected_exe_norm = lls._normalize_path_text(server_exe_path)
    expected_model_norm = lls._normalize_path_text(model_path)

    state = {
        "host": "127.0.0.1",
        "port": 4891,
        "pid": 12345,
        "server_exe_path_resolved": str(server_exe_path),
        "model_path_resolved": str(model_path),
        "model_size": expected_model_size,
        "model_mtime": expected_model_mtime,
        "started_at": "2000-01-01T00:00:00+00:00",
        "last_ok_at": "2000-01-01T00:00:00+00:00",
    }

    monkeypatch.setattr(
        lls, "_probe_openai_models", lambda *args, **kwargs: (None, "nope")
    )
    monkeypatch.setattr(
        lls.psutil,
        "Process",
        lambda _pid: (_ for _ in ()).throw(AssertionError("psutil should not run")),
    )

    assert (
        lls.LocalLlamaServerManager()._try_reuse(
            state,
            expected_host="127.0.0.1",
            expected_exe_norm=expected_exe_norm,
            expected_model_norm=expected_model_norm,
            expected_model_size=expected_model_size,
            expected_model_mtime=expected_model_mtime,
        )
        is None
    )


def test_ensure_ready_falls_back_to_bundled_server_dir_when_custom_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_app_base_dir(tmp_path, monkeypatch)
    settings_model_path = tmp_path / "settings_model.gguf"
    settings_model_path.write_bytes(b"dummy")

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
        local_ai_model_path=str(settings_model_path),
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


def test_ensure_ready_falls_back_to_avx2_when_vulkan_oom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_app_base_dir(tmp_path, monkeypatch)
    settings_model_path = tmp_path / "settings_model.gguf"
    settings_model_path.write_bytes(b"dummy")

    server_dir = tmp_path / "llama_cpp"
    for variant in ("vulkan", "avx2"):
        variant_dir = server_dir / variant
        variant_dir.mkdir(parents=True, exist_ok=True)
        (variant_dir / "llama-server.exe").write_bytes(b"exe")

    log_path = tmp_path / "local_ai_server.log"
    state_path = tmp_path / "state.json"

    monkeypatch.setattr(lls, "_probe_executable_supported", lambda path: True)
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_state_path",
        staticmethod(lambda: state_path),
    )
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_log_path",
        staticmethod(lambda: log_path),
    )

    settings = AppSettings(
        local_ai_model_path=str(settings_model_path),
        local_ai_server_dir="llama_cpp",
        local_ai_port_base=4891,
        local_ai_port_max=4893,
    )

    manager = lls.LocalLlamaServerManager()
    monkeypatch.setattr(manager, "_try_reuse", lambda state, **kwargs: None)
    monkeypatch.setattr(
        manager, "_find_free_port", lambda host, port_base, port_max: port_base
    )

    calls: list[str] = []

    def fake_start_new_server(**kwargs):
        calls.append(str(kwargs["server_variant"]))
        if str(kwargs["server_variant"]) == "vulkan":
            log_path.write_text(
                "ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory\n",
                encoding="utf-8",
            )
            raise lls.LocalAIServerStartError("start failed")

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

    monkeypatch.setattr(manager, "_start_new_server", fake_start_new_server)

    runtime = manager.ensure_ready(settings)

    assert runtime.server_variant == "avx2"
    assert calls == ["vulkan", "avx2"]
    saved_state = lls._safe_read_json(state_path) or {}
    assert saved_state.get("server_variant") == "avx2"
    assert runtime.model_path == settings_model_path


def test_wait_ready_aborts_early_when_vulkan_oom_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    log_path = tmp_path / "local_ai_server.log"
    log_path.write_text("oom", encoding="utf-8")

    monkeypatch.setattr(lls, "_log_indicates_vulkan_oom", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        lls,
        "_probe_openai_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("probe should not run when aborting on vulkan oom")
        ),
    )

    called = {"terminate": 0, "wait": 0, "kill": 0}

    class DummyProc:
        def poll(self):
            return None

        def terminate(self):
            called["terminate"] += 1

        def wait(self, timeout=None):
            _ = timeout
            called["wait"] += 1

        def kill(self):
            called["kill"] += 1

    ready, last_error, models_payload = manager._wait_ready(
        "127.0.0.1",
        4891,
        DummyProc(),
        timeout_s=5.0,
        log_path=log_path,
        abort_on_vulkan_oom=True,
    )

    assert ready is False
    assert last_error == "vulkan_oom"
    assert models_payload is None
    assert called["terminate"] == 1
    assert called["wait"] == 1
    assert called["kill"] == 0


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


def test_resolve_server_exe_direct_variant_uses_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = tmp_path / "llama_cpp" / "vulkan"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "llama-server.exe").write_bytes(b"exe")

    state_path = tmp_path / "state.json"
    lls._atomic_write_json(state_path, {"server_variant": "avx2"})

    monkeypatch.setattr(lls, "_probe_executable_supported", lambda path: True)
    monkeypatch.setattr(
        lls.LocalLlamaServerManager,
        "get_state_path",
        staticmethod(lambda: state_path),
    )

    manager = lls.LocalLlamaServerManager()
    exe_path, variant = manager._resolve_server_exe(server_dir)

    assert variant == "vulkan"
    assert exe_path == server_dir / "llama-server.exe"


def test_ensure_ready_fast_path_uses_running_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_model_path = tmp_path / "settings_model.gguf"
    settings_model_path.write_bytes(b"dummy")

    server_dir = tmp_path / "llama_cpp"
    server_dir.mkdir(parents=True)
    exe_path = server_dir / "llama-server.exe"
    exe_path.write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(settings_model_path),
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
        model_path=settings_model_path,
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
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("start should not run")),
    )

    runtime = manager.ensure_ready(settings)

    assert runtime == manager._runtime


def test_ensure_ready_fast_path_skips_when_model_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_model_path = tmp_path / "model_old.gguf"
    old_model_path.write_bytes(b"old")
    settings_model_path = tmp_path / "settings_model.gguf"
    settings_model_path.write_bytes(b"new")

    server_dir = tmp_path / "llama_cpp"
    server_dir.mkdir(parents=True)
    exe_path = server_dir / "llama-server.exe"
    exe_path.write_bytes(b"exe")

    settings = AppSettings(
        local_ai_model_path=str(settings_model_path),
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
        model_path=old_model_path,
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
    assert runtime.model_path == settings_model_path


def test_resolve_model_path_uses_settings_model_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    settings_model_path = tmp_path / "settings_model.gguf"
    settings_model_path.write_bytes(b"dummy")

    settings = AppSettings(local_ai_model_path=str(settings_model_path))
    resolved = manager._resolve_model_path(settings)

    assert resolved == settings_model_path


def test_resolve_model_path_resolves_relative_from_app_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    _patch_app_base_dir(tmp_path, monkeypatch)
    model_path = tmp_path / "local_ai" / "models" / "settings_model.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"dummy")
    settings = AppSettings(local_ai_model_path="local_ai/models/settings_model.gguf")
    resolved = manager._resolve_model_path(settings)

    assert resolved == model_path


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
            "--threads-batch",
            "--mlock",
            "--no-mmap",
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
        local_ai_threads_batch=12,
        local_ai_mlock=True,
        local_ai_no_mmap=True,
    )
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--batch-size" in args
    assert args[args.index("--batch-size") + 1] == "512"
    assert "--ubatch-size" in args
    assert args[args.index("--ubatch-size") + 1] == "128"
    assert "--threads-batch" in args
    assert args[args.index("--threads-batch") + 1] == "12"
    assert "--mlock" in args
    assert "--no-mmap" in args


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
        server_variant="vulkan",
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


def test_build_server_args_supports_string_ngl_and_skips_flash_attn_auto(
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
        local_ai_n_gpu_layers="all",
        local_ai_flash_attn="auto",
        local_ai_cache_type_k=None,
        local_ai_cache_type_v=None,
    )
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="vulkan",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--device" in args
    assert args[args.index("--device") + 1] == "Vulkan0"
    assert "--n-gpu-layers" in args
    assert args[args.index("--n-gpu-layers") + 1] == "all"
    assert "-fa" not in args
    assert "--flash-attn" not in args
    assert "--flash-attention" not in args
    assert "--cache-type-k" not in args
    assert "-ctk" not in args
    assert "--cache-type-v" not in args
    assert "-ctv" not in args


def test_build_server_args_skips_gpu_flags_without_help(
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
        server_variant="vulkan",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--device" not in args
    assert "--n-gpu-layers" not in args
    assert "-ngl" not in args
    assert "-fa" not in args
    assert "--flash-attn" not in args
    assert "--flash-attention" not in args
    assert "--cache-type-k" not in args
    assert "-ctk" not in args
    assert "--cache-type-v" not in args
    assert "-ctv" not in args
    assert "--no-warmup" not in args


def test_build_server_args_cpu_only_forces_device_and_ngl(
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
            "--n-gpu-layers",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(*args, **kwargs):
        return DummyCompleted(help_text)

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    settings = AppSettings(
        local_ai_device="none",
        local_ai_n_gpu_layers=0,
    )
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="vulkan",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--device" in args
    assert args[args.index("--device") + 1] == "none"
    assert "--n-gpu-layers" in args
    assert args[args.index("--n-gpu-layers") + 1] == "0"


def test_build_server_args_auto_device_resolves_to_first_vulkan_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = lls.LocalLlamaServerManager()
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    (tmp_path / "llama-cli.exe").write_bytes(b"exe")
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
            "--n-gpu-layers",
        ]
    )
    list_devices_text = "\n".join(
        [
            "Available devices:",
            "  Vulkan0: AMD Radeon(TM) Graphics (8330 MiB, 7913 MiB free)",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and cmd and cmd[0] == str(server_exe_path):
            assert "--help" in cmd
            return DummyCompleted(help_text)
        if isinstance(cmd, list) and cmd and cmd[0] == str(tmp_path / "llama-cli.exe"):
            assert "--list-devices" in cmd
            return DummyCompleted(list_devices_text)
        raise AssertionError(f"unexpected subprocess.run: {cmd}")

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    settings = AppSettings(local_ai_device="auto", local_ai_n_gpu_layers=16)
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="vulkan",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--device" in args
    assert args[args.index("--device") + 1] == "Vulkan0"
    assert "--n-gpu-layers" in args
    assert args[args.index("--n-gpu-layers") + 1] == "16"


def test_build_server_args_auto_device_falls_back_to_cpu_only_when_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
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
            "--n-gpu-layers",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and cmd and cmd[0] == str(server_exe_path):
            assert "--help" in cmd
            return DummyCompleted(help_text)
        raise AssertionError(f"unexpected subprocess.run: {cmd}")

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    settings = AppSettings(local_ai_device="auto", local_ai_n_gpu_layers=16)
    settings._validate()

    caplog.set_level(logging.WARNING)
    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="vulkan",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--device" in args
    assert args[args.index("--device") + 1] == "none"
    assert "--n-gpu-layers" in args
    assert args[args.index("--n-gpu-layers") + 1] == "0"
    assert "auto detection failed (llama-cli not found)" in caplog.text


def test_build_server_args_skips_gpu_flags_for_non_vulkan_variant(
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
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--device" not in args
    assert "--n-gpu-layers" not in args
    assert "-ngl" not in args
    assert "-fa" not in args
    assert "--flash-attn" not in args
    assert "--flash-attention" not in args
    assert "--cache-type-k" not in args
    assert "-ctk" not in args
    assert "--cache-type-v" not in args
    assert "-ctv" not in args
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
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--threads" in args
    assert args[args.index("--threads") + 1] == "4"


def test_build_server_args_auto_threads_batch_when_zero(
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
            "--threads-batch",
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

    settings = AppSettings(local_ai_threads=0, local_ai_threads_batch=0)
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--threads" in args
    assert args[args.index("--threads") + 1] == "4"
    assert "--threads-batch" in args
    assert args[args.index("--threads-batch") + 1] == "4"


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
        server_variant="generic",
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
        local_ai_threads_batch=12,
        local_ai_mlock=True,
        local_ai_no_mmap=True,
    )
    settings._validate()

    args = manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert "--batch-size" not in args
    assert "-b" not in args
    assert "--ubatch-size" not in args
    assert "-ub" not in args
    assert "--threads-batch" not in args
    assert "-tb" not in args
    assert "--mlock" not in args
    assert "--no-mmap" not in args


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
        server_variant="vulkan",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert runtime.model_path == model_path
    assert captured["env"]["GGML_VK_FORCE_MAX_ALLOCATION_SIZE"] == "536870912"
    assert captured["env"]["GGML_VK_DISABLE_F16"] == "1"


def test_start_new_server_skips_vk_env_for_non_vulkan(
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
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert runtime.model_path == model_path
    assert "GGML_VK_FORCE_MAX_ALLOCATION_SIZE" not in captured["env"]
    assert "GGML_VK_DISABLE_F16" not in captured["env"]


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
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )
    manager._build_server_args(
        server_exe_path=server_exe_path,
        server_variant="generic",
        model_path=model_path,
        host="127.0.0.1",
        port=4891,
        settings=settings,
    )

    assert calls["count"] == 1


def test_ensure_no_proxy_for_localhost_adds_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("http_proxy", "http://proxy.example")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    lls.ensure_no_proxy_for_localhost()

    for name in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(name, "")
        assert "127.0.0.1" in value
        assert "localhost" in value


def test_ensure_no_proxy_for_localhost_preserves_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_PROXY", "example.com,127.0.0.1")

    lls.ensure_no_proxy_for_localhost()

    assert "example.com" in os.environ["NO_PROXY"]
    assert "127.0.0.1" in os.environ["NO_PROXY"]
    assert "localhost" in os.environ["NO_PROXY"]
    assert "127.0.0.1" in os.environ["no_proxy"]
    assert "localhost" in os.environ["no_proxy"]


def test_parse_llama_cli_vulkan_devices_parses_available_devices_section() -> None:
    text = "\n".join(
        [
            "load_backend: loaded Vulkan backend from ...",
            "Available devices:",
            "  Vulkan0: AMD Radeon(TM) Graphics (8330 MiB, 7913 MiB free)",
            "  Vulkan1 : Dummy GPU (1234 MiB, 1000 MiB free)",
        ]
    )

    assert lls._parse_llama_cli_vulkan_devices(text) == ["Vulkan0", "Vulkan1"]


def test_parse_llama_cli_vulkan_devices_falls_back_without_header() -> None:
    text = "\n".join(
        [
            "ggml_vulkan: Found 1 Vulkan devices:",
            "Vulkan0: AMD Radeon(TM) Graphics (8330 MiB, 7913 MiB free)",
        ]
    )

    assert lls._parse_llama_cli_vulkan_devices(text) == ["Vulkan0"]


def test_resolve_local_ai_device_auto_returns_first_vulkan_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    (tmp_path / "llama-cli.exe").write_bytes(b"exe")

    output = "\n".join(
        [
            "Available devices:",
            "  Vulkan0: AMD Radeon(TM) Graphics (8330 MiB, 7913 MiB free)",
            "  Vulkan1: Dummy GPU (1234 MiB, 1000 MiB free)",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(*args, **kwargs):
        return DummyCompleted(output)

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    device, error = lls._resolve_local_ai_device_auto("auto", server_exe_path)
    assert device == "Vulkan0"
    assert error is None


def test_resolve_local_ai_device_auto_caches_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lls._AUTO_DEVICE_CACHE.clear()

    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    (tmp_path / "llama-cli.exe").write_bytes(b"exe")

    output = "\n".join(
        [
            "Available devices:",
            "  Vulkan0: AMD Radeon(TM) Graphics (8330 MiB, 7913 MiB free)",
        ]
    )

    class DummyCompleted:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        return DummyCompleted(output)

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    device1, error1 = lls._resolve_local_ai_device_auto("auto", server_exe_path)
    device2, error2 = lls._resolve_local_ai_device_auto("auto", server_exe_path)

    assert device1 == "Vulkan0"
    assert error1 is None
    assert device2 == "Vulkan0"
    assert error2 is None
    assert calls["count"] == 1


def test_resolve_local_ai_device_auto_returns_none_when_cli_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")

    called = {"run": False}

    def fake_run(*args, **kwargs):
        called["run"] = True
        raise AssertionError("subprocess.run should not be called when cli is missing")

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    device, error = lls._resolve_local_ai_device_auto("auto", server_exe_path)
    assert device is None
    assert error == "llama-cli not found"
    assert called["run"] is False


def test_resolve_local_ai_device_auto_returns_none_on_run_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_exe_path = tmp_path / "llama-server.exe"
    server_exe_path.write_bytes(b"exe")
    (tmp_path / "llama-cli.exe").write_bytes(b"exe")

    def fake_run(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(lls.subprocess, "run", fake_run)

    device, error = lls._resolve_local_ai_device_auto("auto", server_exe_path)
    assert device is None
    assert error == "llama-cli --list-devices failed"
