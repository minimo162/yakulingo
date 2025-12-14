# yakulingo/services/prompt_builder.py
"""
Builds translation prompts for YakuLingo.

Prompt file structure (style-specific for English output):
- file_translate_to_en_{style}.txt: File translation → English (standard/concise/minimal)
- file_translate_to_jp.txt: File translation → Japanese
- text_translate_to_en_{style}.txt: Text translation → English (standard/concise/minimal)
- text_translate_to_jp.txt: Text translation → Japanese (with explanation)
- adjust_*.txt: Adjustment prompts (shorter, longer, custom)

Reference files are attached to Copilot, not embedded in prompt.
"""

import re
from pathlib import Path
from typing import Optional, Sequence


# 参考ファイル参照の指示文（ファイル添付時のみ挿入）
REFERENCE_INSTRUCTION = """
Reference Files
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
"""

# Item delimiter marker to prevent Copilot from merging consecutive items
# This marker is added to each item in batch translation and removed from the response.
# Without this marker, Copilot may merge items that appear to be parts of the same sentence.
ITEM_END_MARKER = " [END]"

# Fallback template for → English (used when translate_to_en.txt doesn't exist)
DEFAULT_TO_EN_TEMPLATE = """Role Definition
あなたは英語への翻訳を行う、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Translation Rule
- すべてのテキストを英語に翻訳
- 既に英語のテキスト → そのまま出力

Critical Rules (優先順位順)

1. 出力形式厳守 (CRITICAL)
   - 入力は番号付きリスト（1., 2., 3., ...）形式
   - 出力も必ず同じ番号付きリスト形式で出力すること
   - 各翻訳項目は必ず番号で始める（例: "1. Hello"）
   - 番号を飛ばしたり統合したりしないこと
   - 翻訳結果のみを出力。Markdownの枠や解説は不要

2. 自然な翻訳
   - 読みやすく自然な英語に翻訳
   - 簡潔さを維持

3. 数値表記（必須ルール）
   - 億 → oku (例: 4,500億円 → 4,500 oku yen)
   - 千単位 → k (例: 12,000 → 12k)
   - 負数 → () (例: ▲50 → (50))

4. 体裁の維持
   - 原文の改行・段落構造をそのまま維持する

{reference_section}

Input
{input_text}
"""

# Fallback template for → Japanese (used when translate_to_jp.txt doesn't exist)
DEFAULT_TO_JP_TEMPLATE = """Role Definition
あなたは日本語への翻訳を行う、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Translation Rule
- すべてのテキストを日本語に翻訳
- 既に日本語のテキスト → そのまま出力

Critical Rules (優先順位順)

1. 出力形式厳守 (CRITICAL)
   - 入力は番号付きリスト（1., 2., 3., ...）形式
   - 出力も必ず同じ番号付きリスト形式で出力すること
   - 各翻訳項目は必ず番号で始める（例: "1. こんにちは"）
   - 番号を飛ばしたり統合したりしないこと
   - 翻訳結果のみを出力。Markdownの枠や解説は不要

2. 自然な翻訳
   - 読みやすく自然な日本語に翻訳
   - 文脈に応じた適切な表現を使用

3. 数値表記（必須ルール）
   - oku → 億 (例: 4,500 oku → 4,500億)
   - k → 千または000 (例: 12k → 12,000 または 1.2万)
   - () → ▲ (例: (50) → ▲50)

4. 体裁の維持とコンパクトな翻訳
   - 原文の改行・段落構造をそのまま維持する
   - 冗長な表現を避け、簡潔な翻訳を心がける
   - 意味を損なわない範囲で、より短い表現を選択する
   - 同じ意味なら文字数の少ない単語・表現を優先する

{reference_section}

Input
{input_text}
"""

# Fallback templates for text translation (used when text_translate_*.txt don't exist)
DEFAULT_TEXT_TO_EN_TEMPLATE = """## Translation Request

Please translate the following Japanese text into English.

### Guidelines
- Style: {style}
- If the input is already English, output it as-is
- Keep the translation concise and natural

### Output Format
Please provide your response in the following format:

訳文: (English translation)

解説:
- (Key grammar/word choice point - 1 line)
- (Important terms - 1 line)
- (Usage context or nuance - 1 line)

解説は日本語で書いてください。

{reference_section}

---

以下のテキストを翻訳してください:
{input_text}
"""

DEFAULT_TEXT_TO_JP_TEMPLATE = """## Translation Request

Please translate the following text into Japanese.

### Guidelines
- If the input is already Japanese, output it as-is
- Keep original line breaks and tabs intact
- Use concise, natural Japanese
- oku → 億, k → 千/000, () → ▲

### Output Format
Please provide your response in the following format:

訳文: (Japanese translation)

解説:
- (Grammar/syntax key point - 1 line)
- (Important words/phrases - 1 line)
- (Usage context or nuances - 1 line)

{reference_section}

---

以下のテキストを翻訳してください:
{input_text}
"""


class PromptBuilder:
    """
    Builds translation prompts for file translation.
    Reference files are attached to Copilot, not embedded in prompt.

    Supports style-specific prompts for English output (standard/concise/minimal).
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir
        # Templates cache: {(lang, style): template_str}
        self._templates: dict[tuple[str, str], str] = {}
        # Text translation templates cache: {(lang, style): template_str}
        self._text_templates: dict[tuple[str, str], str] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Load prompt templates from files or use defaults"""
        styles = ["standard", "concise", "minimal"]

        if self.prompts_dir:
            # Load style-specific English templates
            for style in styles:
                # File translation to English
                to_en_prompt = self.prompts_dir / f"file_translate_to_en_{style}.txt"
                if to_en_prompt.exists():
                    self._templates[("en", style)] = to_en_prompt.read_text(encoding='utf-8')
                else:
                    # Fallback to old single file if exists
                    old_prompt = self.prompts_dir / "file_translate_to_en.txt"
                    if old_prompt.exists():
                        self._templates[("en", style)] = old_prompt.read_text(encoding='utf-8')
                    else:
                        self._templates[("en", style)] = DEFAULT_TO_EN_TEMPLATE

            # Japanese template (no style variations)
            to_jp_prompt = self.prompts_dir / "file_translate_to_jp.txt"
            if to_jp_prompt.exists():
                jp_template = to_jp_prompt.read_text(encoding='utf-8')
            else:
                jp_template = DEFAULT_TO_JP_TEMPLATE

            # Use same JP template for all styles
            for style in styles:
                self._templates[("jp", style)] = jp_template

            # Load text translation templates (text_translate_to_*)
            for style in styles:
                # Text translation to English
                text_to_en = self.prompts_dir / f"text_translate_to_en_{style}.txt"
                if text_to_en.exists():
                    self._text_templates[("en", style)] = text_to_en.read_text(encoding='utf-8')
                else:
                    # Fallback to old single file
                    old_text_en = self.prompts_dir / "text_translate_to_en.txt"
                    if old_text_en.exists():
                        self._text_templates[("en", style)] = old_text_en.read_text(encoding='utf-8')

            # Text translation to Japanese (no style variations)
            text_to_jp = self.prompts_dir / "text_translate_to_jp.txt"
            if text_to_jp.exists():
                jp_text_template = text_to_jp.read_text(encoding='utf-8')
            else:
                jp_text_template = DEFAULT_TEXT_TO_JP_TEMPLATE

            for style in styles:
                self._text_templates.setdefault(("jp", style), jp_text_template)
                self._text_templates.setdefault(("en", style), DEFAULT_TEXT_TO_EN_TEMPLATE)
        else:
            # Use defaults
            for style in styles:
                self._templates[("en", style)] = DEFAULT_TO_EN_TEMPLATE
                self._templates[("jp", style)] = DEFAULT_TO_JP_TEMPLATE
                self._text_templates[("en", style)] = DEFAULT_TEXT_TO_EN_TEMPLATE
                self._text_templates[("jp", style)] = DEFAULT_TEXT_TO_JP_TEMPLATE

    def _get_template(self, output_language: str = "en", translation_style: str = "concise") -> str:
        """Get appropriate template based on output language and style."""
        key = (output_language, translation_style)
        if key in self._templates:
            return self._templates[key]

        # Fallback to concise if style not found
        fallback_key = (output_language, "concise")
        if fallback_key in self._templates:
            return self._templates[fallback_key]

        # Ultimate fallback
        return DEFAULT_TO_EN_TEMPLATE if output_language == "en" else DEFAULT_TO_JP_TEMPLATE

    def get_text_template(self, output_language: str = "en", translation_style: str = "concise") -> Optional[str]:
        """Get cached text translation template.

        Args:
            output_language: "en" or "jp"
            translation_style: "standard", "concise", or "minimal"

        Returns:
            Cached template string, or None if not found
        """
        key = (output_language, translation_style)
        if key in self._text_templates:
            return self._text_templates[key]

        # Fallback to concise if style not found
        fallback_key = (output_language, "concise")
        if fallback_key in self._text_templates:
            return self._text_templates[fallback_key]

        return None

    def build(
        self,
        input_text: str,
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            input_text: Text or batch to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output

        Returns:
            Complete prompt string
        """
        # Add reference instruction only if files are attached
        reference_section = REFERENCE_INSTRUCTION if has_reference_files else ""

        # Get appropriate template based on language and style
        template = self._get_template(output_language, translation_style)

        # Replace placeholders
        prompt = template.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", input_text)
        # Remove old style placeholder if present (for backwards compatibility)
        prompt = prompt.replace("{translation_style}", translation_style)

        return prompt

    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            texts: List of texts to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output

        Returns:
            Complete prompt with numbered input

        Note:
            Each item is appended with ITEM_END_MARKER to prevent Copilot from
            merging consecutive items that appear to be parts of the same sentence.
            The marker is removed in parse_batch_result().
        """
        # Format as numbered list with end markers to prevent item merging
        # Without markers, Copilot may merge items like "一定の前提に基づいており、"
        # and "その達成を..." into a single translated item.
        numbered_input = "\n".join(
            f"{i+1}. {text}{ITEM_END_MARKER}" for i, text in enumerate(texts)
        )

        return self.build(numbered_input, has_reference_files, output_language, translation_style)

    def build_reference_section(self, reference_files: Optional[Sequence[Path]]) -> str:
        """Return reference section text when reference files are provided."""

        has_reference_files = bool(reference_files)
        return REFERENCE_INSTRUCTION if has_reference_files else ""

    def parse_batch_result(self, result: str, expected_count: int) -> list[str]:
        """
        Parse batch translation result back to list.

        Args:
            result: Raw result string from Copilot
            expected_count: Expected number of translations

        Returns:
            List of translated texts

        Note:
            Removes ITEM_END_MARKER from each translation if present.
            The marker is added in build_batch() to prevent Copilot from merging items.
        """
        lines = result.strip().split('\n')
        translations = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Remove numbering prefix (e.g., "1. ", "2. ")
            match = re.match(r'^\d+\.\s*(.+)$', line)
            if match:
                text = match.group(1)
            else:
                text = line

            # Remove end marker if present (added in build_batch to prevent merging)
            if text.endswith(ITEM_END_MARKER.strip()):
                text = text[:-len(ITEM_END_MARKER.strip())].rstrip()

            translations.append(text)

        # Pad with empty strings if needed
        while len(translations) < expected_count:
            translations.append("")

        return translations[:expected_count]
