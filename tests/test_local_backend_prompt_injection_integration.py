from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_backend_prompt_includes_rules_and_bundled_glossary() -> None:
    root = Path(__file__).resolve().parent.parent
    prompts_dir = root / "prompts"

    settings = AppSettings(translation_backend="local", use_bundled_glossary=True)
    service = TranslationService(
        copilot=Mock(),
        config=settings,
        prompts_dir=prompts_dir,
    )

    captured: dict[str, str] = {}

    def fake_translate_single(
        self,
        text: str,
        prompt: str,
        reference_files=None,
        on_chunk=None,
    ) -> str:
        _ = self, text, reference_files, on_chunk
        captured["prompt"] = prompt
        return '{"translation":"First-half results.","explanation":""}'

    with patch(
        "yakulingo.services.local_ai_client.LocalAIClient.translate_single",
        new=fake_translate_single,
    ):
        result = service.translate_text_with_style_comparison(
            "上期の実績",
            pre_detected_language="日本語",
        )

    assert result.output_language == "en"
    assert captured.get("prompt")
    prompt = captured["prompt"]
    assert "billion/trillion には変換しない" in prompt
    assert "[REFERENCE:file=glossary.csv]" in prompt
