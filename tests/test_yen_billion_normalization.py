from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder
from yakulingo.services.translation_service import TranslationService


class RecordingLocalClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.last_prompt: str | None = None

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk=None,
    ) -> str:
        _ = text, reference_files, on_chunk
        self.last_prompt = prompt
        return self._response


def test_prompt_builder_normalizes_yen_billion_expression_for_jp() -> None:
    normalized = PromptBuilder.normalize_input_text(
        "Revenue was ¥2,238.5billion in FY2024.",
        output_language="jp",
    )
    assert "2兆2,385億円" in normalized
    assert "¥2,238.5billion" not in normalized


def test_prompt_builder_normalizes_yen_bn_expression_for_jp() -> None:
    normalized = PromptBuilder.normalize_input_text(
        "Revenue was ¥1.2bn in FY2024.",
        output_language="jp",
    )
    assert "12億円" in normalized


def test_translate_text_with_options_includes_normalized_amount_in_prompt() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    local = RecordingLocalClient("テスト")
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        config=settings,
        prompts_dir=prompts_dir,
    )
    service._local_client = local
    service._local_prompt_builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=service.prompt_builder,
        settings=settings,
    )
    service._local_batch_translator = object()

    result = service.translate_text_with_options(
        "Revenue was ¥2,238.5billion in FY2024.",
        pre_detected_language="英語",
    )

    assert result.output_language == "jp"
    assert local.last_prompt is not None
    assert "2兆2,385億円" in local.last_prompt

    prompt_input = local.last_prompt.split("<source>", 1)[-1]
    prompt_input = prompt_input.split("</source>", 1)[0]
    assert "2兆2,385億円" in prompt_input
    assert "¥2,238.5billion" not in prompt_input
