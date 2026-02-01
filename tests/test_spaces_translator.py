import sys
import types

import pytest

import spaces.translator as translator_mod
from spaces.translator import GGUFTranslator, TranslationConfig, default_config


def _install_fake_hf_hub(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []

    def hf_hub_download(  # type: ignore[no-untyped-def]
        *, repo_id: str, filename: str, token: str | None = None
    ) -> str:
        calls.append(
            {
                "fn": "hf_hub_download",
                "repo_id": repo_id,
                "filename": filename,
                "token": token,
            }
        )
        return "MODEL.gguf"

    fake_hf = types.ModuleType("huggingface_hub")
    fake_hf.hf_hub_download = hf_hub_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)
    return calls


class _FakeProcess:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.returncode: int | None = None

    def poll(self):  # type: ignore[no-untyped-def]
        return None

    def terminate(self) -> None:
        self.returncode = -15


def test_default_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKULINGO_SPACES_GGUF_REPO_ID", "repo-id")
    monkeypatch.setenv("YAKULINGO_SPACES_GGUF_FILENAME", "file.gguf")
    monkeypatch.setenv("YAKULINGO_SPACES_MAX_NEW_TOKENS", "123")
    monkeypatch.setenv("YAKULINGO_SPACES_N_CTX", "2048")
    monkeypatch.setenv("YAKULINGO_SPACES_N_GPU_LAYERS", "42")
    monkeypatch.setenv("YAKULINGO_SPACES_TEMPERATURE", "0.25")
    monkeypatch.setenv("YAKULINGO_SPACES_ALLOW_CPU", "1")

    cfg = default_config()
    assert cfg.gguf_repo_id == "repo-id"
    assert cfg.gguf_filename == "file.gguf"
    assert cfg.max_new_tokens == 123
    assert cfg.n_ctx == 2048
    assert cfg.n_gpu_layers == 42
    assert cfg.temperature == 0.25
    assert cfg.allow_cpu is True


def test_default_config_invalid_int_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKULINGO_SPACES_MAX_NEW_TOKENS", "not-an-int")
    cfg = default_config()
    assert cfg.max_new_tokens == 256


def test_translator_fails_when_cuda_unavailable_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_hf_hub(monkeypatch)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    translator = GGUFTranslator(
        TranslationConfig(
            gguf_repo_id="repo-id",
            gguf_filename="file.gguf",
            max_new_tokens=10,
            n_ctx=512,
            n_gpu_layers=-1,
            temperature=0.0,
            allow_cpu=False,
        )
    )

    with pytest.raises(RuntimeError):
        translator.translate("hello", output_language="ja")
    assert calls == []


def test_translator_uses_cpu_when_cuda_unavailable_and_allowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls = _install_fake_hf_hub(monkeypatch)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    popen_calls: list[list[str]] = []

    def fake_popen(args, **kwargs):  # type: ignore[no-untyped-def]
        popen_calls.append([str(x) for x in args])
        return _FakeProcess([str(x) for x in args])

    build_calls: list[dict[str, object]] = []

    def fake_build_args(**kwargs):  # type: ignore[no-untyped-def]
        build_calls.append(dict(kwargs))
        return ["llama-server", "--host", "127.0.0.1", "--port", "8090", "-m", "MODEL.gguf"]

    wait_calls: list[dict[str, object]] = []

    def fake_wait_for_llama_server(**kwargs):  # type: ignore[no-untyped-def]
        wait_calls.append(dict(kwargs))
        return "model-id"

    completion_calls: list[dict[str, object]] = []

    def fake_completions(**kwargs):  # type: ignore[no-untyped-def]
        completion_calls.append(dict(kwargs))
        return "OUTPUT"

    monkeypatch.setattr(translator_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(translator_mod, "_build_llama_server_args", fake_build_args)
    monkeypatch.setattr(translator_mod, "_wait_for_llama_server", fake_wait_for_llama_server)
    monkeypatch.setattr(translator_mod, "_openai_completions", fake_completions)
    monkeypatch.setattr(
        translator_mod,
        "_ensure_llama_server_binary",
        lambda: (translator_mod.Path("llama-server"), "llama-b123-bin-ubuntu-x64.tar.gz"),
    )
    monkeypatch.setattr(translator_mod, "_llama_server_log_path", lambda: tmp_path / "llama.log")

    translator = GGUFTranslator(
        TranslationConfig(
            gguf_repo_id="repo-id",
            gguf_filename="file.gguf",
            max_new_tokens=10,
            n_ctx=512,
            n_gpu_layers=-1,
            temperature=0.0,
            allow_cpu=True,
        )
    )

    out = translator.translate("x", output_language="en")
    assert out == "OUTPUT"

    assert [c["fn"] for c in calls] == ["hf_hub_download"]
    assert len(build_calls) == 1
    assert build_calls[0]["use_cuda"] is False
    assert popen_calls == [["llama-server", "--host", "127.0.0.1", "--port", "8090", "-m", "MODEL.gguf"]]
    assert len(wait_calls) == 1
    assert len(completion_calls) == 1


def test_translator_uses_gpu_layers_when_cuda_visible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls = _install_fake_hf_hub(monkeypatch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

    build_calls: list[dict[str, object]] = []

    def fake_build_args(**kwargs):  # type: ignore[no-untyped-def]
        build_calls.append(dict(kwargs))
        return ["llama-server"]

    monkeypatch.setattr(translator_mod, "_build_llama_server_args", fake_build_args)
    monkeypatch.setattr(translator_mod, "_wait_for_llama_server", lambda **kwargs: "model-id")
    monkeypatch.setattr(translator_mod, "_openai_completions", lambda **kwargs: "OUTPUT")
    monkeypatch.setattr(translator_mod.subprocess, "Popen", lambda args, **kwargs: _FakeProcess([str(x) for x in args]))
    monkeypatch.setattr(
        translator_mod,
        "_ensure_llama_server_binary",
        lambda: (translator_mod.Path("llama-server"), "llama-b123-bin-ubuntu-vulkan-x64.tar.gz"),
    )
    monkeypatch.setattr(translator_mod, "_llama_server_log_path", lambda: tmp_path / "llama.log")

    translator = GGUFTranslator(
        TranslationConfig(
            gguf_repo_id="repo-id",
            gguf_filename="file.gguf",
            max_new_tokens=10,
            n_ctx=512,
            n_gpu_layers=123,
            temperature=0.0,
            allow_cpu=False,
        )
    )

    _ = translator.translate("x", output_language="en")
    assert [c["fn"] for c in calls] == ["hf_hub_download"]
    assert len(build_calls) == 1
    assert build_calls[0]["use_cuda"] is True
    assert build_calls[0]["n_gpu_layers"] == 123
    assert translator.runtime_device() == "cuda"


def test_translator_caches_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls = _install_fake_hf_hub(monkeypatch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

    popen_calls: list[list[str]] = []

    def fake_popen(args, **kwargs):  # type: ignore[no-untyped-def]
        popen_calls.append([str(x) for x in args])
        return _FakeProcess([str(x) for x in args])

    build_calls: list[dict[str, object]] = []

    def fake_build_args(**kwargs):  # type: ignore[no-untyped-def]
        build_calls.append(dict(kwargs))
        return ["llama-server"]

    wait_calls: list[dict[str, object]] = []

    def fake_wait(**kwargs):  # type: ignore[no-untyped-def]
        wait_calls.append(dict(kwargs))
        return "model-id"

    completion_calls: list[dict[str, object]] = []

    def fake_completions(**kwargs):  # type: ignore[no-untyped-def]
        completion_calls.append(dict(kwargs))
        return "OUTPUT"

    monkeypatch.setattr(translator_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(translator_mod, "_build_llama_server_args", fake_build_args)
    monkeypatch.setattr(translator_mod, "_wait_for_llama_server", fake_wait)
    monkeypatch.setattr(translator_mod, "_openai_completions", fake_completions)
    monkeypatch.setattr(
        translator_mod,
        "_ensure_llama_server_binary",
        lambda: (translator_mod.Path("llama-server"), "llama-b123-bin-ubuntu-vulkan-x64.tar.gz"),
    )
    monkeypatch.setattr(translator_mod, "_llama_server_log_path", lambda: tmp_path / "llama.log")

    translator = GGUFTranslator(
        TranslationConfig(
            gguf_repo_id="repo-id",
            gguf_filename="file.gguf",
            max_new_tokens=10,
            n_ctx=512,
            n_gpu_layers=1,
            temperature=0.0,
            allow_cpu=False,
        )
    )

    assert translator.translate("a", output_language="en") == "OUTPUT"
    assert translator.translate("b", output_language="en") == "OUTPUT"

    assert [c["fn"] for c in calls] == ["hf_hub_download"]
    assert len(build_calls) == 1
    assert len(popen_calls) == 1
    assert len(wait_calls) == 1
    assert len(completion_calls) == 2
