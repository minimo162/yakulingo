from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Literal

OutputLanguage = Literal["en", "ja"]


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
    model_ja_en: str
    model_en_ja: str
    max_new_tokens: int
    num_beams: int


def default_config() -> TranslationConfig:
    return TranslationConfig(
        model_ja_en=os.environ.get(
            "YAKULINGO_SPACES_MODEL_JA_EN", "Helsinki-NLP/opus-mt-ja-en"
        ),
        model_en_ja=os.environ.get(
            "YAKULINGO_SPACES_MODEL_EN_JA", "Helsinki-NLP/opus-tatoeba-en-ja"
        ),
        max_new_tokens=_env_int("YAKULINGO_SPACES_MAX_NEW_TOKENS", 256),
        num_beams=_env_int("YAKULINGO_SPACES_NUM_BEAMS", 4),
    )


class TransformersTranslator:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self._config = config or default_config()
        self._lock = threading.Lock()
        self._pipelines: dict[OutputLanguage, object] = {}
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

        pipeline_obj = self._get_pipeline(output_language)

        max_new_tokens = max(1, int(self._config.max_new_tokens))
        num_beams = max(1, int(self._config.num_beams))

        try:
            result = pipeline_obj(  # type: ignore[operator]
                cleaned,
                max_new_tokens=max_new_tokens,
                num_beams=num_beams,
            )
        except Exception as e:
            raise RuntimeError(
                f"翻訳に失敗しました（backend=transformers, device={self.runtime_device()}）: {e}"
            ) from e

        if not result:
            return ""

        first = result[0]
        translated = str(first.get("translation_text", "")).strip()
        return translated

    def _get_pipeline(self, output_language: OutputLanguage) -> object:
        cached = self._pipelines.get(output_language)
        if cached is not None:
            return cached

        with self._lock:
            cached = self._pipelines.get(output_language)
            if cached is not None:
                return cached

            model_id = (
                self._config.model_ja_en
                if output_language == "en"
                else self._config.model_en_ja
            )

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
                "translation",
                model=model_id,
                device=device_index,
                model_kwargs=model_kwargs or None,
            )

            self._device = "cuda" if use_cuda else "cpu"
            self._pipelines[output_language] = pipeline_obj
            return pipeline_obj


_default_translator = TransformersTranslator()


def get_translator() -> TransformersTranslator:
    return _default_translator
