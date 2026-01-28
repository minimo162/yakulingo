from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class _DummyLocalClient:
    def __init__(self) -> None:
        self.runtime = object()
        self.ensure_ready_calls = 0
        self.translate_calls = 0
        self.runtimes: list[object | None] = []

    def set_cancel_callback(self, _callback) -> None:
        return

    def ensure_ready(self):
        self.ensure_ready_calls += 1
        return self.runtime

    def translate_single(
        self,
        _text: str,
        _prompt: str,
        _reference_files=None,
        _on_chunk=None,
        timeout=None,
        runtime=None,
    ) -> str:
        _ = timeout
        self.translate_calls += 1
        self.runtimes.append(runtime)
        if self.translate_calls == 1:
            return "こんにちは"
        return "Hello"


class _DummyLocalPromptBuilder:
    def build_reference_embed(self, _reference_files, *, input_text: str | None = None):
        _ = input_text
        return SimpleNamespace(text="", warnings=[], truncated=False)

    def build_text_to_en_single(
        self,
        _text: str,
        *,
        style: str,
        reference_files,
        detected_language: str,
        extra_instruction: str | None = None,
    ) -> str:
        _ = (style, reference_files, detected_language, extra_instruction)
        return "prompt"


def test_local_text_translation_uses_runtime_once_without_retry() -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        config=settings,
        prompts_dir=Path("prompts"),
    )

    dummy_client = _DummyLocalClient()
    service._local_client = dummy_client
    service._local_prompt_builder = _DummyLocalPromptBuilder()
    service._local_batch_translator = object()

    detected = service.detect_language("こんにちは")
    result = service._translate_text_with_options_local(
        text="こんにちは",
        reference_files=None,
        style="minimal",
        detected_language=detected,
        output_language="en",
        on_chunk=None,
    )

    assert result.options == []
    assert result.error_message is not None
    assert dummy_client.ensure_ready_calls == 1
    assert dummy_client.runtimes == [dummy_client.runtime]
