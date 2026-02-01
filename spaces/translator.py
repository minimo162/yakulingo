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
_RE_GEMMA_TURN = re.compile(r"<(?:start|end)_of_turn>\s*", re.IGNORECASE)


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


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _cuda_visible() -> bool:
    value = (os.environ.get("CUDA_VISIBLE_DEVICES") or "").strip()
    if not value or value in ("-1", "none"):
        return False
    return True


@dataclass(frozen=True)
class TranslationConfig:
    gguf_repo_id: str
    gguf_filename: str
    max_new_tokens: int
    n_ctx: int
    n_gpu_layers: int
    temperature: float
    allow_cpu: bool


def default_config() -> TranslationConfig:
    return TranslationConfig(
        gguf_repo_id=os.environ.get(
            "YAKULINGO_SPACES_GGUF_REPO_ID",
            "mradermacher/translategemma-27b-it-i1-GGUF",
        ),
        gguf_filename=os.environ.get(
            "YAKULINGO_SPACES_GGUF_FILENAME", "translategemma-27b-it.i1-Q4_K_M.gguf"
        ),
        max_new_tokens=_env_int("YAKULINGO_SPACES_MAX_NEW_TOKENS", 256),
        n_ctx=_env_int("YAKULINGO_SPACES_N_CTX", 4096),
        n_gpu_layers=_env_int("YAKULINGO_SPACES_N_GPU_LAYERS", -1),
        temperature=_env_float("YAKULINGO_SPACES_TEMPERATURE", 0.0),
        allow_cpu=_env_bool("YAKULINGO_SPACES_ALLOW_CPU", False),
    )


class GGUFTranslator:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self._config = config or default_config()
        self._lock = threading.Lock()
        self._llm: object | None = None
        self._device: str | None = None

    def runtime_device(self) -> str:
        if self._device:
            return self._device
        if _cuda_visible() and self._config.n_gpu_layers != 0:
            return "cuda"
        return "cpu"

    def translate(self, text: str, *, output_language: OutputLanguage) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        max_new_tokens = max(1, int(self._config.max_new_tokens))
        prompt = _build_prompt(cleaned, output_language=output_language)
        llm = self._get_llm()

        try:
            result = llm(  # type: ignore[operator]
                prompt,
                max_tokens=max_new_tokens,
                temperature=float(self._config.temperature),
                top_p=1.0,
                stop=["<end_of_turn>"],
            )
        except Exception as e:
            raise RuntimeError(
                f"翻訳に失敗しました（backend=gguf/llama.cpp, device={self.runtime_device()}）: {e}"
            ) from e

        generated = _extract_llama_text(result)
        return _clean_translation_output(generated)

    def _get_llm(self) -> object:
        if self._llm is not None:
            return self._llm

        with self._lock:
            if self._llm is not None:
                return self._llm

            hf_token = _hf_token()

            try:
                from huggingface_hub import (  # type: ignore[import-not-found]
                    hf_hub_download,
                )
                from llama_cpp import Llama  # type: ignore[import-not-found]
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "Spaces 用の依存関係が不足しています。"
                    "（例: pip install -r spaces/requirements.txt）"
                ) from e

            use_cuda = _cuda_visible()
            if not use_cuda and not self._config.allow_cpu:
                raise RuntimeError(
                    "GPU が利用できません（ZeroGPU が割り当てられていない可能性があります）。"
                    "Space の Hardware を ZeroGPU に設定してください。"
                    "（デバッグ用途で CPU を許可する場合は YAKULINGO_SPACES_ALLOW_CPU=1）"
                )

            gguf_path = hf_hub_download(
                repo_id=self._config.gguf_repo_id,
                filename=self._config.gguf_filename,
                token=hf_token,
            )

            n_gpu_layers = int(self._config.n_gpu_layers)
            if not use_cuda:
                n_gpu_layers = 0

            llm = Llama(
                model_path=gguf_path,
                n_ctx=max(256, int(self._config.n_ctx)),
                n_gpu_layers=n_gpu_layers,
                verbose=False,
            )

            self._device = "cuda" if use_cuda and n_gpu_layers != 0 else "cpu"
            self._llm = llm
            return llm


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


def _extract_llama_text(result: object) -> str:
    if isinstance(result, dict):
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                value = first.get("text") or ""
                return str(value)
    return str(result or "")


def _clean_translation_output(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = _RE_GEMMA_TURN.sub("", cleaned).strip()
    cleaned = _RE_CODE_FENCE_LINE.sub("", cleaned).strip()
    cleaned = _RE_LEADING_LABEL.sub("", cleaned).strip()
    return cleaned


_default_translator = GGUFTranslator()


def get_translator() -> GGUFTranslator:
    return _default_translator


def _hf_token() -> str | None:
    token = (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or ""
    ).strip()
    return token or None
