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


@dataclass(frozen=True)
class TranslationConfig:
    model_id: str
    max_new_tokens: int


def default_config() -> TranslationConfig:
    return TranslationConfig(
        model_id=os.environ.get(
            "YAKULINGO_SPACES_MODEL_ID", "google/translategemma-27b-it"
        ),
        max_new_tokens=_env_int("YAKULINGO_SPACES_MAX_NEW_TOKENS", 256),
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
                from transformers import pipeline  # type: ignore[import-not-found]
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "Spaces 用の依存関係が不足しています。"
                    "（例: pip install -r spaces/requirements.txt）"
                ) from e

            use_cuda = bool(torch.cuda.is_available())
            device_index = 0 if use_cuda else -1
            model_kwargs: dict[str, object] = {}
            if use_cuda:
                model_kwargs["torch_dtype"] = torch.float16

            pipeline_obj = pipeline(
                "text-generation",
                model=model_id,
                device=device_index,
                model_kwargs=model_kwargs or None,
            )

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
