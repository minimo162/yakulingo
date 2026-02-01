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

    class BitsAndBytesConfig:  # type: ignore[no-redef]
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            self.kwargs = dict(kwargs)

    class AutoTokenizer:  # type: ignore[no-redef]
        @classmethod
        def from_pretrained(cls, model_id: str):  # type: ignore[no-untyped-def]
            calls.append({"fn": "AutoTokenizer.from_pretrained", "model_id": model_id})
            return object()

    class AutoModelForCausalLM:  # type: ignore[no-redef]
        @classmethod
        def from_pretrained(  # type: ignore[no-untyped-def]
            cls,
            model_id: str,
            device_map: object | None = None,
            torch_dtype: object | None = None,
            quantization_config: object | None = None,
        ):
            calls.append(
                {
                    "fn": "AutoModelForCausalLM.from_pretrained",
                    "model_id": model_id,
                    "device_map": device_map,
                    "torch_dtype": torch_dtype,
                    "quantization_config": quantization_config,
                }
            )
            return object()

    def pipeline(task: str, *, model: object, tokenizer: object):  # type: ignore[no-untyped-def]
        calls.append(
            {"fn": "pipeline", "task": task, "model": model, "tokenizer": tokenizer}
        )

        def run(text: str, **kwargs):  # type: ignore[no-untyped-def]
            return [{"generated_text": f"{text}OUTPUT"}]

        return run

    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=AutoTokenizer,
        AutoModelForCausalLM=AutoModelForCausalLM,
        BitsAndBytesConfig=BitsAndBytesConfig,
        pipeline=pipeline,
    )

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    return calls, float16_sentinel


def test_default_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKULINGO_SPACES_MODEL_ID", "model-id")
    monkeypatch.setenv("YAKULINGO_SPACES_MAX_NEW_TOKENS", "123")
    monkeypatch.setenv("YAKULINGO_SPACES_QUANT", "8bit")
    monkeypatch.setenv("YAKULINGO_SPACES_ALLOW_CPU", "1")

    cfg = default_config()
    assert cfg.model_id == "model-id"
    assert cfg.max_new_tokens == 123
    assert cfg.quant == "8bit"
    assert cfg.allow_cpu is True


def test_default_config_invalid_int_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKULINGO_SPACES_MAX_NEW_TOKENS", "not-an-int")
    cfg = default_config()
    assert cfg.max_new_tokens == 256


def test_translator_fails_when_cuda_unavailable_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _install_fake_transformers(monkeypatch, cuda_available=False)

    translator = TransformersTranslator(
        TranslationConfig(
            model_id="model-id",
            max_new_tokens=10,
            quant="4bit",
            allow_cpu=False,
        )
    )

    with pytest.raises(RuntimeError):
        translator.translate("hello", output_language="ja")
    assert calls == []


def test_translator_uses_cpu_when_cuda_unavailable_and_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _install_fake_transformers(monkeypatch, cuda_available=False)

    translator = TransformersTranslator(
        TranslationConfig(
            model_id="model-id",
            max_new_tokens=10,
            quant="4bit",
            allow_cpu=True,
        )
    )

    out = translator.translate("x", output_language="en")
    assert out == "OUTPUT"

    model_call = next(
        c for c in calls if c["fn"] == "AutoModelForCausalLM.from_pretrained"
    )
    assert model_call["device_map"] is None
    assert model_call["torch_dtype"] is None


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
            quant="4bit",
            allow_cpu=False,
        )
    )

    _ = translator.translate("x", output_language="en")
    model_call = next(
        c for c in calls if c["fn"] == "AutoModelForCausalLM.from_pretrained"
    )
    assert model_call["device_map"] == "auto"
    assert model_call["torch_dtype"] is float16_sentinel

    bnb_cfg = model_call["quantization_config"]
    assert hasattr(bnb_cfg, "kwargs")
    assert bnb_cfg.kwargs.get("load_in_4bit") is True


def test_translator_caches_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, _ = _install_fake_transformers(monkeypatch, cuda_available=False)

    translator = TransformersTranslator(
        TranslationConfig(
            model_id="model-id",
            max_new_tokens=10,
            quant="4bit",
            allow_cpu=True,
        )
    )

    assert translator.translate("a", output_language="en") == "OUTPUT"
    assert translator.translate("b", output_language="en") == "OUTPUT"

    tokenizer_calls = [c for c in calls if c["fn"] == "AutoTokenizer.from_pretrained"]
    pipeline_calls = [c for c in calls if c["fn"] == "pipeline"]
    assert len(tokenizer_calls) == 1
    assert len(pipeline_calls) == 1
