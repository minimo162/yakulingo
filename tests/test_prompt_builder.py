# tests/test_prompt_builder.py
"""Tests for ecm_translate.services.prompt_builder"""

import sys
import tempfile
from pathlib import Path

# Add project root to path for direct imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import prompt_builder directly (not through services __init__)
from ecm_translate.services.prompt_builder import (
    PromptBuilder,
    REFERENCE_INSTRUCTION,
    DEFAULT_UNIFIED_TEMPLATE,
)


class TestPromptBuilder:
    """Tests for PromptBuilder class - unified bidirectional translation"""

    def test_default_template_used_when_no_dir(self):
        builder = PromptBuilder(prompts_dir=None)
        prompt = builder.build("テスト")

        assert "テスト" in prompt
        assert "Role Definition" in prompt

    def test_build_includes_input_text(self):
        builder = PromptBuilder()
        prompt = builder.build("こんにちは")

        assert "こんにちは" in prompt
        assert "Input" in prompt

    def test_build_contains_language_detection_rule(self):
        builder = PromptBuilder()
        prompt = builder.build("Test text")

        # Unified prompt has auto language detection
        assert "Language Detection Rule" in prompt
        assert "日本語の場合 → 英語に翻訳" in prompt
        assert "日本語以外の場合 → 日本語に翻訳" in prompt

    def test_build_without_reference(self):
        builder = PromptBuilder()
        prompt = builder.build(
            "テスト",
            has_reference_files=False
        )

        assert "添付の参考ファイル" not in prompt

    def test_build_with_reference(self):
        builder = PromptBuilder()
        prompt = builder.build(
            "テスト",
            has_reference_files=True
        )

        assert "添付の参考ファイル" in prompt
        assert "用語集がある場合" in prompt

    def test_build_batch(self):
        builder = PromptBuilder()
        texts = ["こんにちは", "さようなら", "ありがとう"]
        prompt = builder.build_batch(texts)

        assert "1. こんにちは" in prompt
        assert "2. さようなら" in prompt
        assert "3. ありがとう" in prompt

    def test_parse_batch_result_numbered(self):
        builder = PromptBuilder()
        result = """1. Hello
2. Goodbye
3. Thank you"""
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == "Goodbye"
        assert parsed[2] == "Thank you"

    def test_parse_batch_result_without_numbers(self):
        builder = PromptBuilder()
        result = """Hello
Goodbye
Thank you"""
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == "Goodbye"
        assert parsed[2] == "Thank you"

    def test_parse_batch_result_fewer_results(self):
        builder = PromptBuilder()
        result = "1. Hello"
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == ""
        assert parsed[2] == ""

    def test_parse_batch_result_more_results(self):
        builder = PromptBuilder()
        result = """1. One
2. Two
3. Three
4. Four"""
        parsed = builder.parse_batch_result(result, expected_count=2)

        assert len(parsed) == 2
        assert parsed[0] == "One"
        assert parsed[1] == "Two"

    def test_parse_batch_result_empty_lines(self):
        builder = PromptBuilder()
        result = """1. Hello

2. World

"""
        parsed = builder.parse_batch_result(result, expected_count=2)

        assert len(parsed) == 2
        assert parsed[0] == "Hello"
        assert parsed[1] == "World"

    def test_load_template_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)

            # Create custom unified template file
            translate_file = prompts_dir / "translate.txt"
            translate_file.write_text("Custom bidirectional: {input_text}\n{reference_section}")

            builder = PromptBuilder(prompts_dir=prompts_dir)

            prompt = builder.build("test")
            assert "Custom bidirectional: test" in prompt

    def test_fallback_to_default_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)
            # Don't create any files

            builder = PromptBuilder(prompts_dir=prompts_dir)
            prompt = builder.build("test")

            # Should use default template
            assert "Role Definition" in prompt


class TestDefaultTemplates:
    """Tests for default prompt templates"""

    def test_unified_template_has_placeholders(self):
        assert "{input_text}" in DEFAULT_UNIFIED_TEMPLATE
        assert "{reference_section}" in DEFAULT_UNIFIED_TEMPLATE

    def test_unified_template_contains_rules(self):
        assert "出力形式厳守" in DEFAULT_UNIFIED_TEMPLATE
        assert "自然な翻訳" in DEFAULT_UNIFIED_TEMPLATE
        assert "数値表記" in DEFAULT_UNIFIED_TEMPLATE
        assert "体裁の維持とコンパクトな翻訳" in DEFAULT_UNIFIED_TEMPLATE

    def test_unified_template_has_language_detection(self):
        assert "Language Detection Rule" in DEFAULT_UNIFIED_TEMPLATE
        assert "日本語の場合 → 英語に翻訳" in DEFAULT_UNIFIED_TEMPLATE
        assert "日本語以外の場合 → 日本語に翻訳" in DEFAULT_UNIFIED_TEMPLATE

    def test_reference_instruction_content(self):
        assert "添付の参考ファイル" in REFERENCE_INSTRUCTION
        assert "用語集" in REFERENCE_INSTRUCTION
