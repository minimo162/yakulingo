import sys
import types

import pytest

from spaces.translator import GGUFTranslator, TranslationConfig, default_config


def _install_fake_llama_stack(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []

    def hf_hub_download(  # type: ignore[no-untyped-def]
        *, repo_id: str, filename: str, token: str | None = None
    ) -> str:
        calls.append(
            {"fn": "hf_hub_download", "repo_id": repo_id, "filename": filename, "token": token}
        )
        return "MODEL.gguf"

    class Llama:  # type: ignore[no-redef]
        def __init__(  # type: ignore[no-untyped-def]
            self,
            *,
            model_path: str,
            n_ctx: int,
            n_gpu_layers: int,
            verbose: bool = False,
        ) -> None:
            calls.append(
                {
                    "fn": "Llama.__init__",
                    "model_path": model_path,
                    "n_ctx": n_ctx,
                    "n_gpu_layers": n_gpu_layers,
                    "verbose": verbose,
                }
            )

        def __call__(self, prompt: str, **kwargs):  # type: ignore[no-untyped-def]
            calls.append({"fn": "Llama.__call__", "prompt": prompt, **kwargs})
            return {"choices": [{"text": "OUTPUT"}]}

    fake_hf = types.ModuleType("huggingface_hub")
    fake_hf.hf_hub_download = hf_hub_download  # type: ignore[attr-defined]
    fake_llama_cpp = types.ModuleType("llama_cpp")
    fake_llama_cpp.Llama = Llama  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_cpp)

    return calls


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
    calls = _install_fake_llama_stack(monkeypatch)
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
) -> None:
    calls = _install_fake_llama_stack(monkeypatch)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

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

    init_call = next(c for c in calls if c["fn"] == "Llama.__init__")
    assert init_call["n_gpu_layers"] == 0


def test_translator_uses_gpu_layers_when_cuda_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_llama_stack(monkeypatch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

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
    init_call = next(c for c in calls if c["fn"] == "Llama.__init__")
    assert init_call["n_gpu_layers"] == 123


def test_translator_caches_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_llama_stack(monkeypatch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

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

    download_calls = [c for c in calls if c["fn"] == "hf_hub_download"]
    init_calls = [c for c in calls if c["fn"] == "Llama.__init__"]
    run_calls = [c for c in calls if c["fn"] == "Llama.__call__"]

    assert len(download_calls) == 1
    assert len(init_calls) == 1
    assert len(run_calls) == 2
