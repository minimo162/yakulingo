from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.translation_service import TranslationService


class SequencedLocalClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.translate_single_calls = 0
        self.prompts: list[str] = []

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        _ = text
        _ = reference_files
        self.translate_single_calls += 1
        self.prompts.append(prompt)
        index = min(self.translate_single_calls - 1, len(self._responses) - 1)
        response = self._responses[index]
        if on_chunk is not None:
            on_chunk(response)
        return response


def _make_service(local: SequencedLocalClient) -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
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
    return service


def test_text_style_comparison_retries_when_output_language_mismatched() -> None:
    first = "これは日本語です。"
    second = "This is a test."
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert result.options[0].text == second
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    assert "output_language" in (metadata.get("output_language_retry_reasons") or [])


def test_text_options_ignores_requested_style_and_retries_on_output_language_mismatch() -> (
    None
):
    first = "これは日本語です。"
    second = "This is a test."
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_options(
        "これはテストです。",
        style="standard",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options[0].style == "standard"
    assert result.options[0].text == second
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True


def test_text_style_comparison_retries_when_translation_is_ellipsis_only() -> None:
    first = "..."
    second = "This is a test."
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert result.options[0].text == second
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    assert "ellipsis" in (metadata.get("output_language_retry_reasons") or [])


def test_text_style_comparison_errors_when_translation_stays_ellipsis_only() -> None:
    first = "..."
    second = "..."
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert not result.options
    assert (
        result.error_message
        == "ローカルAIの出力が「...」のみでした。モデル/設定を確認してください。"
    )
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    assert metadata.get("output_language_retry_failed") is True


def test_text_style_comparison_retries_when_translation_is_placeholder_only() -> None:
    first = "<TRANSLATION>"
    second = "This is a test."
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert result.options[0].text == second
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    assert "placeholder" in (metadata.get("output_language_retry_reasons") or [])


def test_text_style_comparison_errors_when_translation_stays_placeholder_only() -> None:
    first = "<TRANSLATION>"
    second = "<TRANSLATION>"
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert not result.options
    assert (
        result.error_message
        == "ローカルAIの出力がプレースホルダーのみでした。モデル/設定を確認してください。"
    )
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    assert metadata.get("output_language_retry_failed") is True


def test_text_options_retries_when_translation_is_placeholder_only_for_jp() -> None:
    first = "<TRANSLATION>"
    second = "これはテストです。"
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_options(
        "This is a test.",
        style="standard",
        pre_detected_language="英語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "jp"
    assert result.options[0].text == second
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True


def test_text_options_retries_when_translation_equals_input_for_jp() -> None:
    first = "Hello"
    second = "こんにちは"
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_options(
        first,
        pre_detected_language="英語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "jp"
    assert result.options
    assert result.options[0].text == second
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    assert "untranslated" in (metadata.get("output_language_retry_reasons") or [])


def test_text_style_comparison_retries_for_oku_numeric_rule_when_auto_fix_not_possible() -> (
    None
):
    input_text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。"
    )
    first = "Net sales were in the billions of yen."
    second = "Net sales were 22,385 oku yen."
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 1
    assert local.prompts
    assert "- JP: 2兆2,385億円 | EN: 22,385 oku yen" not in local.prompts[0]

    metadata = result.metadata or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert result.options[0].text == first
    assert metadata.get("to_en_numeric_rule_retry") is None


def test_text_style_comparison_skips_numeric_retry_when_auto_fixable() -> None:
    input_text = "売上高は2兆2,385億円となりました。"
    expected = "Net sales were ¥2,238.5 billion."
    raw = expected
    local = SequencedLocalClient([raw])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
        styles=["standard"],
    )

    assert local.translate_single_calls == 1
    assert local.prompts
    assert "¥2,238.5 billion" in local.prompts[0]
    assert "2兆2,385億円" not in local.prompts[0]
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["standard"]
    assert result.options[0].text == expected


def test_text_style_comparison_skips_numeric_retry_when_auto_fixable_by_conversion() -> (
    None
):
    input_text = "売上高は2兆2,385億円(前年同期比1,554億円減)となりました。"
    expected = "Revenue was ¥2,238.5 billion, down by ¥155.4 billion year on year."
    raw = expected
    local = SequencedLocalClient([raw])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
        styles=["standard"],
    )

    assert local.translate_single_calls == 1
    assert local.prompts
    assert "¥2,238.5 billion" in local.prompts[0]
    assert "¥155.4 billion" in local.prompts[0]
    assert "2兆2,385億円" not in local.prompts[0]
    assert "1,554億円" not in local.prompts[0]

    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["standard"]
    assert result.options[0].text == expected

    metadata = result.metadata or {}
    assert metadata.get("to_en_numeric_rule_retry") is None


def test_text_style_comparison_does_not_retry_when_output_keeps_jp_numeric_units() -> (
    None
):
    input_text = "売上高は2兆2,385億円となりました。"
    first = "Net sales: 2兆2,385億円."
    local = SequencedLocalClient([first])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
        styles=["standard"],
    )

    assert local.translate_single_calls == 1
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["standard"]
    assert result.options[0].text == first
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is None


def test_user_report_financial_text_retries_when_first_output_echoes_input() -> None:
    input_text = """１．2026年３月期第２四半期（中間期）の連結業績（2025年４月１日～2025年９月30日）
（１）連結経営成績(累計) (％表示は、対前年中間期増減率)
売上高 営業利益 経常利益 親会社株主に帰属
する中間純利益
百万円 ％ 百万円 ％ 百万円 ％ 百万円 ％
2026年３月期中間期 2,238,463 △6.5 △53,879 － △21,294 － △45,284 －
2025年３月期中間期 2,393,919 3.3 103,048 △20.5 83,513 △53.4 35,334 △67.3
(注) 包括利益 2026年３月期中間期 △32,510百万円( －％) 2025年３月期中間期 △2,123百万円( －％)"""
    translated = (
        "Consolidated financial results for Q2 FY2026 (interim) are as follows."
    )
    local = SequencedLocalClient([input_text, translated])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(input_text)

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options
    assert result.options[0].text == translated

    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    reasons = set(metadata.get("output_language_retry_reasons") or [])
    assert {"output_language"} <= reasons


def test_user_report_non_japanese_input_detects_and_outputs_jp() -> None:
    local = SequencedLocalClient(["これはテストです。"])
    service = _make_service(local)

    result = service.translate_text_with_options("This is a test.")

    assert local.translate_single_calls == 1
    assert result.output_language == "jp"
    assert result.options
    assert result.options[0].text == "これはテストです。"
