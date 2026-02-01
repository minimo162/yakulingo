import sys
import types

import pytest

from spaces.translator import TranslationConfig, TransformersTranslator, default_config


def _install_fake_transformers(
    monkeypatch: pytest.MonkeyPatch, *, cuda_available: bool
):
    calls: list[dict[str, object]] = []

    float16_sentinel = object()

    fake_torch = types.SimpleNamespace()
    fake_torch.float16 = float16_sentinel
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: cuda_available)

    def pipeline(  # type: ignore[no-untyped-def]
        task: str, *, model: str, device: int, model_kwargs: object | None
    ):
        calls.append(
            {
                "task": task,
                "model": model,
                "device": device,
                "model_kwargs": model_kwargs,
            }
        )

        def run(text: str, **kwargs):  # type: ignore[no-untyped-def]
            return [
                {
                    "generated_text": f"{model}|{text}|{kwargs}",
                }
            ]

        return run

    fake_transformers = types.SimpleNamespace(pipeline=pipeline)

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    return calls, float16_sentinel


def test_default_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKULINGO_SPACES_MODEL_ID", "model-id")
    monkeypatch.setenv("YAKULINGO_SPACES_MAX_NEW_TOKENS", "123")

    cfg = default_config()
    assert cfg.model_id == "model-id"
    assert cfg.max_new_tokens == 123


def test_default_config_invalid_int_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKULINGO_SPACES_MAX_NEW_TOKENS", "not-an-int")
    cfg = default_config()
    assert cfg.max_new_tokens == 256


def test_translator_caches_pipeline_per_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _install_fake_transformers(monkeypatch, cuda_available=False)

    translator = TransformersTranslator(
        TranslationConfig(
            model_id="model-id",
            max_new_tokens=10,
        )
    )

    out1 = translator.translate("hello", output_language="ja")
    assert out1.startswith("model-id|")
    assert len(calls) == 1

    out2 = translator.translate("hello2", output_language="ja")
    assert out2.startswith("model-id|")
    assert len(calls) == 1  # cached

    out3 = translator.translate("こんにちは", output_language="en")
    assert out3.startswith("model-id|")
    assert len(calls) == 1


def test_translator_uses_cpu_when_cuda_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _install_fake_transformers(monkeypatch, cuda_available=False)

    translator = TransformersTranslator(
        TranslationConfig(
            model_id="model-id",
            max_new_tokens=10,
        )
    )

    _ = translator.translate("x", output_language="en")
    assert calls[0]["device"] == -1
    assert calls[0]["model_kwargs"] is None


def test_translator_sets_dtype_when_cuda_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, float16_sentinel = _install_fake_transformers(
        monkeypatch, cuda_available=True
    )

    translator = TransformersTranslator(
        TranslationConfig(
            model_id="model-id",
            max_new_tokens=10,
        )
    )

    _ = translator.translate("x", output_language="en")
    assert calls[0]["device"] == 0
    assert isinstance(calls[0]["model_kwargs"], dict)
    assert calls[0]["model_kwargs"]["torch_dtype"] is float16_sentinel
