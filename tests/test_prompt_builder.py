# tests/test_prompt_builder.py
"""Tests for yakulingo.services.prompt_builder"""

import tempfile
from pathlib import Path

from yakulingo.services.prompt_builder import (
    PromptBuilder,
    REFERENCE_INSTRUCTION,
    DEFAULT_TO_EN_TEMPLATE,
    DEFAULT_TO_JP_TEMPLATE,
)


class TestPromptBuilder:
    """Tests for PromptBuilder class"""

    def test_default_templates_used_when_no_dir(self):
        """Default templates used when prompts_dir is None"""
        builder = PromptBuilder(prompts_dir=None)

        # Check internal templates are loaded
        assert builder._to_en_template == DEFAULT_TO_EN_TEMPLATE
        assert builder._to_jp_template == DEFAULT_TO_JP_TEMPLATE

    def test_build_includes_input_text(self):
        """Build includes input text in prompt"""
        builder = PromptBuilder()
        prompt = builder.build("こんにちは")

        assert "こんにちは" in prompt
        assert "Input" in prompt

    def test_build_for_english_output(self):
        """Build prompt for English output (JP→EN)"""
        builder = PromptBuilder()
        prompt = builder.build("テスト", output_language="en")

        assert "テスト" in prompt
        assert "英語" in prompt or "English" in prompt.lower()

    def test_build_for_japanese_output(self):
        """Build prompt for Japanese output (EN→JP)"""
        builder = PromptBuilder()
        prompt = builder.build("Test", output_language="jp")

        assert "Test" in prompt
        assert "日本語" in prompt

    def test_build_without_reference(self):
        """Build without reference files"""
        builder = PromptBuilder()
        prompt = builder.build("テスト", has_reference_files=False)

        assert "添付の参考ファイル" not in prompt
        assert REFERENCE_INSTRUCTION.strip() not in prompt

    def test_build_with_reference(self):
        """Build with reference files"""
        builder = PromptBuilder()
        prompt = builder.build("テスト", has_reference_files=True)

        assert "添付の参考ファイル" in prompt
        assert "用語集" in prompt

    def test_build_batch_numbered_format(self):
        """Build batch creates numbered format"""
        builder = PromptBuilder()
        texts = ["こんにちは", "さようなら", "ありがとう"]
        prompt = builder.build_batch(texts)

        assert "1. こんにちは" in prompt
        assert "2. さようなら" in prompt
        assert "3. ありがとう" in prompt

    def test_build_batch_with_reference(self):
        """Build batch with reference files"""
        builder = PromptBuilder()
        texts = ["Text1", "Text2"]
        prompt = builder.build_batch(texts, has_reference_files=True)

        assert "1. Text1" in prompt
        assert "2. Text2" in prompt
        assert "添付の参考ファイル" in prompt

    def test_build_batch_for_japanese_output(self):
        """Build batch for Japanese output"""
        builder = PromptBuilder()
        texts = ["Hello", "World"]
        prompt = builder.build_batch(texts, output_language="jp")

        assert "1. Hello" in prompt
        assert "2. World" in prompt
        assert "日本語" in prompt


class TestPromptBuilderParseBatchResult:
    """Tests for PromptBuilder.parse_batch_result()"""

    def test_parse_numbered_results(self):
        """Parse results with numbered format"""
        builder = PromptBuilder()
        result = """1. Hello
2. Goodbye
3. Thank you"""
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == "Goodbye"
        assert parsed[2] == "Thank you"

    def test_parse_without_numbers(self):
        """Parse results without numbered format"""
        builder = PromptBuilder()
        result = """Hello
Goodbye
Thank you"""
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == "Goodbye"
        assert parsed[2] == "Thank you"

    def test_parse_fewer_results_pads_empty(self):
        """Parse fewer results than expected pads with empty strings"""
        builder = PromptBuilder()
        result = "1. Hello"
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == ""
        assert parsed[2] == ""

    def test_parse_more_results_truncates(self):
        """Parse more results than expected truncates"""
        builder = PromptBuilder()
        result = """1. One
2. Two
3. Three
4. Four"""
        parsed = builder.parse_batch_result(result, expected_count=2)

        assert len(parsed) == 2
        assert parsed[0] == "One"
        assert parsed[1] == "Two"

    def test_parse_skips_empty_lines(self):
        """Parse skips empty lines"""
        builder = PromptBuilder()
        result = """1. Hello

2. World

"""
        parsed = builder.parse_batch_result(result, expected_count=2)

        assert len(parsed) == 2
        assert parsed[0] == "Hello"
        assert parsed[1] == "World"

    def test_parse_handles_whitespace(self):
        """Parse handles leading/trailing whitespace"""
        builder = PromptBuilder()
        result = """  1. Hello
  2.   World   """
        parsed = builder.parse_batch_result(result, expected_count=2)

        assert parsed[0] == "Hello"
        assert parsed[1] == "World"

    def test_parse_empty_result(self):
        """Parse empty result returns empty strings"""
        builder = PromptBuilder()
        result = ""
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert all(p == "" for p in parsed)

    def test_parse_mixed_numbered_and_unnumbered(self):
        """Parse handles mixed numbered and unnumbered lines"""
        builder = PromptBuilder()
        result = """1. First
Second line
3. Third"""
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "First"
        assert parsed[1] == "Second line"
        assert parsed[2] == "Third"

    def test_parse_large_batch(self):
        """Parse large batch result"""
        builder = PromptBuilder()
        lines = [f"{i+1}. Translation {i+1}" for i in range(100)]
        result = "\n".join(lines)
        parsed = builder.parse_batch_result(result, expected_count=100)

        assert len(parsed) == 100
        assert parsed[0] == "Translation 1"
        assert parsed[99] == "Translation 100"

    def test_parse_with_special_characters(self):
        """Parse results with special characters"""
        builder = PromptBuilder()
        result = """1. Hello! @#$%
2. 日本語テスト
3. Mixed: 英語と日本語"""
        parsed = builder.parse_batch_result(result, expected_count=3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello! @#$%"
        assert parsed[1] == "日本語テスト"
        assert parsed[2] == "Mixed: 英語と日本語"

    def test_parse_multiline_entries(self):
        """Parse may not handle multiline entries (single line per entry)"""
        builder = PromptBuilder()
        # This tests current behavior - each line is a separate result
        result = """1. First line
continuation of first
2. Second"""
        parsed = builder.parse_batch_result(result, expected_count=3)

        # Current implementation treats each non-empty line as result
        assert len(parsed) == 3
        assert parsed[0] == "First line"


class TestPromptBuilderTemplateLoading:
    """Tests for template loading from files"""

    def test_load_to_en_template_from_file(self):
        """Load JP→EN template from file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)

            # Create custom to_en template
            to_en_file = prompts_dir / "translate_to_en.txt"
            to_en_file.write_text("Custom EN template: {input_text}\n{reference_section}")

            builder = PromptBuilder(prompts_dir=prompts_dir)
            prompt = builder.build("test", output_language="en")

            assert "Custom EN template: test" in prompt

    def test_load_to_jp_template_from_file(self):
        """Load EN→JP template from file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)

            # Create custom to_jp template
            to_jp_file = prompts_dir / "translate_to_jp.txt"
            to_jp_file.write_text("Custom JP template: {input_text}\n{reference_section}")

            builder = PromptBuilder(prompts_dir=prompts_dir)
            prompt = builder.build("test", output_language="jp")

            assert "Custom JP template: test" in prompt

    def test_fallback_to_default_when_to_en_missing(self):
        """Fallback to default when translate_to_en.txt missing"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)
            # Don't create translate_to_en.txt

            builder = PromptBuilder(prompts_dir=prompts_dir)
            prompt = builder.build("test", output_language="en")

            # Should use default template
            assert "Role Definition" in prompt
            assert "英語" in prompt

    def test_fallback_to_default_when_to_jp_missing(self):
        """Fallback to default when translate_to_jp.txt missing"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)
            # Don't create translate_to_jp.txt

            builder = PromptBuilder(prompts_dir=prompts_dir)
            prompt = builder.build("test", output_language="jp")

            # Should use default template
            assert "Role Definition" in prompt
            assert "日本語" in prompt

    def test_mixed_custom_and_default_templates(self):
        """Load one custom template, use default for other"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_dir = Path(tmpdir)

            # Only create to_en template
            to_en_file = prompts_dir / "translate_to_en.txt"
            to_en_file.write_text("Custom EN: {input_text}\n{reference_section}")

            builder = PromptBuilder(prompts_dir=prompts_dir)

            # EN output uses custom
            prompt_en = builder.build("test", output_language="en")
            assert "Custom EN: test" in prompt_en

            # JP output uses default
            prompt_jp = builder.build("test", output_language="jp")
            assert "Role Definition" in prompt_jp
            assert "日本語" in prompt_jp


class TestDefaultTemplates:
    """Tests for default prompt template content"""

    def test_to_en_template_has_placeholders(self):
        """TO_EN template has required placeholders"""
        assert "{input_text}" in DEFAULT_TO_EN_TEMPLATE
        assert "{reference_section}" in DEFAULT_TO_EN_TEMPLATE

    def test_to_jp_template_has_placeholders(self):
        """TO_JP template has required placeholders"""
        assert "{input_text}" in DEFAULT_TO_JP_TEMPLATE
        assert "{reference_section}" in DEFAULT_TO_JP_TEMPLATE

    def test_to_en_template_contains_rules(self):
        """TO_EN template contains translation rules"""
        assert "出力形式厳守" in DEFAULT_TO_EN_TEMPLATE
        assert "自然な翻訳" in DEFAULT_TO_EN_TEMPLATE
        assert "数値表記" in DEFAULT_TO_EN_TEMPLATE
        assert "oku" in DEFAULT_TO_EN_TEMPLATE  # Number notation rule

    def test_to_jp_template_contains_rules(self):
        """TO_JP template contains translation rules"""
        assert "出力形式厳守" in DEFAULT_TO_JP_TEMPLATE
        assert "自然な翻訳" in DEFAULT_TO_JP_TEMPLATE
        assert "数値表記" in DEFAULT_TO_JP_TEMPLATE
        assert "億" in DEFAULT_TO_JP_TEMPLATE  # Number notation rule

    def test_to_en_template_targets_english(self):
        """TO_EN template targets English output"""
        assert "英語" in DEFAULT_TO_EN_TEMPLATE

    def test_to_jp_template_targets_japanese(self):
        """TO_JP template targets Japanese output"""
        assert "日本語" in DEFAULT_TO_JP_TEMPLATE

    def test_reference_instruction_content(self):
        """REFERENCE_INSTRUCTION has correct content"""
        assert "添付の参考ファイル" in REFERENCE_INSTRUCTION
        assert "用語集" in REFERENCE_INSTRUCTION
        assert "訳語" in REFERENCE_INSTRUCTION


class TestPromptBuilderEdgeCases:
    """Edge case tests for PromptBuilder"""

    def test_empty_input_text(self):
        """Handle empty input text"""
        builder = PromptBuilder()
        prompt = builder.build("")

        assert "Input" in prompt
        # Empty input should still produce valid prompt structure

    def test_very_long_input_text(self):
        """Handle very long input text"""
        builder = PromptBuilder()
        long_text = "あ" * 10000
        prompt = builder.build(long_text)

        assert long_text in prompt

    def test_special_characters_in_input(self):
        """Handle special characters in input"""
        builder = PromptBuilder()
        special_text = "Test {with} [brackets] and $pecial ch@rs!"
        prompt = builder.build(special_text)

        assert special_text in prompt

    def test_build_batch_empty_list(self):
        """Handle empty text list"""
        builder = PromptBuilder()
        prompt = builder.build_batch([])

        # Should produce valid prompt with empty input section
        assert "Input" in prompt

    def test_build_batch_single_item(self):
        """Handle single item in batch"""
        builder = PromptBuilder()
        prompt = builder.build_batch(["Single"])

        assert "1. Single" in prompt

    def test_get_template_defaults_to_en(self):
        """_get_template defaults to English output"""
        builder = PromptBuilder()

        # Default behavior
        template = builder._get_template()
        assert template == builder._to_en_template

        # Explicit en
        template_en = builder._get_template("en")
        assert template_en == builder._to_en_template

    def test_get_template_for_jp(self):
        """_get_template returns JP template for jp language"""
        builder = PromptBuilder()
        template = builder._get_template("jp")
        assert template == builder._to_jp_template

    def test_get_template_unknown_language_defaults_to_en(self):
        """_get_template defaults to EN for unknown language"""
        builder = PromptBuilder()
        template = builder._get_template("unknown")
        assert template == builder._to_en_template
