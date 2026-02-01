from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from typing import Literal

OutputLanguage = Literal["en", "ja"]

_RE_CODE_FENCE_LINE = re.compile(r"^\s*```.*$", re.MULTILINE)
_RE_LEADING_LABEL = re.compile(
    r"^\s*(?:Translation|Translated|訳|訳文|翻訳)\s*[:：]\s*", re.IGNORECASE
)


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class TranslationConfig:
    model_id: str
    max_new_tokens: int
    quant: str
    allow_cpu: bool


def default_config() -> TranslationConfig:
    return TranslationConfig(
        model_id=os.environ.get(
            "YAKULINGO_SPACES_MODEL_ID", "google/translategemma-27b-it"
        ),
        max_new_tokens=_env_int("YAKULINGO_SPACES_MAX_NEW_TOKENS", 256),
        quant=(os.environ.get("YAKULINGO_SPACES_QUANT") or "4bit").strip().lower(),
        allow_cpu=_env_bool("YAKULINGO_SPACES_ALLOW_CPU", False),
    )


class TransformersTranslator:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self._config = config or default_config()
        self._lock = threading.Lock()
        self._pipeline: object | None = None
        self._device: str | None = None

    def runtime_device(self) -> str:
        if self._device:
            return self._device
        try:
            import torch  # type: ignore[import-not-found]

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ModuleNotFoundError:
            return "unknown"

    def translate(self, text: str, *, output_language: OutputLanguage) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        max_new_tokens = max(1, int(self._config.max_new_tokens))
        prompt = _build_prompt(cleaned, output_language=output_language)
        pipeline_obj = self._get_pipeline()

        try:
            result = pipeline_obj(
                prompt, max_new_tokens=max_new_tokens, do_sample=False
            )  # type: ignore[operator]
        except Exception as e:
            raise RuntimeError(
                f"翻訳に失敗しました（backend=transformers, device={self.runtime_device()}）: {e}"
            ) from e

        generated = _extract_generated_text(result)
        if generated.startswith(prompt):
            generated = generated[len(prompt) :]
        return _clean_translation_output(generated)

    def _get_pipeline(self) -> object:
        if self._pipeline is not None:
            return self._pipeline

        with self._lock:
            if self._pipeline is not None:
                return self._pipeline

            model_id = self._config.model_id

            try:
                import torch  # type: ignore[import-not-found]
                from transformers import (  # type: ignore[import-not-found]
                    AutoModelForCausalLM,
                    AutoTokenizer,
                    BitsAndBytesConfig,
                    pipeline,
                )
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "Spaces 用の依存関係が不足しています。"
                    "（例: pip install -r spaces/requirements.txt）"
                ) from e

            use_cuda = bool(torch.cuda.is_available())
            if not use_cuda and not self._config.allow_cpu:
                raise RuntimeError(
                    "GPU が利用できません（ZeroGPU が割り当てられていない可能性があります）。"
                    "Space の Hardware を ZeroGPU に設定してください。"
                    "（デバッグ用途で CPU を許可する場合は YAKULINGO_SPACES_ALLOW_CPU=1）"
                )

            quant = (self._config.quant or "").strip().lower()
            torch_dtype = torch.float16 if use_cuda else None

            quantization_config = None
            if use_cuda:
                if quant in ("4bit", "4-bit", "4"):
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_compute_dtype=torch.float16,
                    )
                elif quant in ("8bit", "8-bit", "8"):
                    quantization_config = BitsAndBytesConfig(load_in_8bit=True)
                elif quant in ("none", "", "fp16", "bf16"):
                    quantization_config = None
                else:
                    raise RuntimeError(
                        f"YAKULINGO_SPACES_QUANT が不正です: {self._config.quant!r}（例: 4bit / 8bit / none）"
                    )

            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                device_map="auto" if use_cuda else None,
                torch_dtype=torch_dtype,
                quantization_config=quantization_config,
            )

            pipeline_obj = pipeline("text-generation", model=model, tokenizer=tokenizer)

            self._device = "cuda" if use_cuda else "cpu"
            self._pipeline = pipeline_obj
            return pipeline_obj


def _build_prompt(text: str, *, output_language: OutputLanguage) -> str:
    if output_language == "en":
        return (
            "Translate the following Japanese text into English.\n"
            "Output the translation only.\n\n"
            f"{text}\n"
        )
    return (
        "Translate the following English text into Japanese.\n"
        "Output the translation only.\n\n"
        f"{text}\n"
    )


def _extract_generated_text(result: object) -> str:
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            for key in ("generated_text", "text", "translation_text"):
                value = first.get(key)
                if value:
                    return str(value)
            return ""
        return str(first)
    return str(result or "")


def _clean_translation_output(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = _RE_CODE_FENCE_LINE.sub("", cleaned).strip()
    cleaned = _RE_LEADING_LABEL.sub("", cleaned).strip()
    return cleaned


_default_translator = TransformersTranslator()


def get_translator() -> TransformersTranslator:
    return _default_translator
