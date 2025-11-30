# ecm_translate/services/prompt_builder.py
"""
Builds translation prompts with unified bidirectional translation.
Japanese → English, Other languages → Japanese (auto-detected by AI).
Reference files are attached to Copilot, not embedded in prompt.
"""

from pathlib import Path
from typing import Optional


# 参考ファイル参照の指示文（ファイル添付時のみ挿入）
REFERENCE_INSTRUCTION = """
Reference Files
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
"""

# Unified prompt template (auto-detects language direction) - for text translation
DEFAULT_UNIFIED_TEMPLATE = """Role Definition
あなたは双方向翻訳を行う、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Language Detection Rule
- 入力テキストが日本語の場合 → 英語に翻訳
- 入力テキストが日本語以外の場合 → 日本語に翻訳

Critical Rules (優先順位順)

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

2. 自然な翻訳
   - 読みやすく自然な表現に翻訳
   - 文脈に応じた適切な表現を使用
   - 過度な省略は避ける

3. 数値表記（必須ルール）
   日本語→英語の場合:
   - 億 → oku (例: 4,500億円 → 4,500 oku yen)
   - 千単位 → k (例: 12,000 → 12k)
   - 負数 → () (例: ▲50 → (50))

   英語→日本語の場合:
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

# Template for explicit "to English" translation (for file translation)
TO_ENGLISH_TEMPLATE = """Role Definition
あなたは英語への翻訳を行う、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Translation Rule
すべての入力テキストを英語に翻訳してください。
- 日本語 → 英語に翻訳
- 他の言語 → 英語に翻訳
- 既に英語のテキスト → そのまま出力

Critical Rules (優先順位順)

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

2. 自然な翻訳
   - 読みやすく自然な英語に翻訳
   - 文脈に応じた適切な表現を使用
   - 過度な省略は避ける

3. 数値表記（必須ルール）
   - 億 → oku (例: 4,500億円 → 4,500 oku yen)
   - 千単位 → k (例: 12,000 → 12k)
   - 負数 → () (例: ▲50 → (50))

4. 体裁の維持とコンパクトな翻訳
   - 原文の改行・段落構造をそのまま維持する
   - 冗長な表現を避け、簡潔な翻訳を心がける
   - 意味を損なわない範囲で、より短い表現を選択する

{reference_section}

Input
{input_text}
"""

# Template for explicit "to Japanese" translation (for file translation)
TO_JAPANESE_TEMPLATE = """Role Definition
あなたは日本語への翻訳を行う、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Translation Rule
すべての入力テキストを日本語に翻訳してください。
- 英語 → 日本語に翻訳
- 他の言語 → 日本語に翻訳
- 既に日本語のテキスト → そのまま出力

Critical Rules (優先順位順)

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

2. 自然な翻訳
   - 読みやすく自然な日本語に翻訳
   - 文脈に応じた適切な表現を使用
   - 過度な省略は避ける

3. 数値表記（必須ルール）
   - oku → 億 (例: 4,500 oku → 4,500億)
   - k → 千または000 (例: 12k → 12,000 または 1.2万)
   - () → ▲ (例: (50) → ▲50)

4. 体裁の維持とコンパクトな翻訳
   - 原文の改行・段落構造をそのまま維持する
   - 冗長な表現を避け、簡潔な翻訳を心がける
   - 意味を損なわない範囲で、より短い表現を選択する

{reference_section}

Input
{input_text}
"""


class PromptBuilder:
    """
    Builds translation prompts with unified bidirectional translation.
    Reference files are attached to Copilot, not embedded in prompt.
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir
        self._template: str = ""
        self._to_en_template: str = ""
        self._to_jp_template: str = ""
        self._load_templates()

    def _load_templates(self) -> None:
        """Load prompt templates from files or use defaults"""
        # Unified (auto-detect) template
        if self.prompts_dir:
            unified_prompt = self.prompts_dir / "translate.txt"
            if unified_prompt.exists():
                self._template = unified_prompt.read_text(encoding='utf-8')
            else:
                self._template = DEFAULT_UNIFIED_TEMPLATE

            # To English template
            to_en_prompt = self.prompts_dir / "translate_to_en.txt"
            if to_en_prompt.exists():
                self._to_en_template = to_en_prompt.read_text(encoding='utf-8')
            else:
                self._to_en_template = TO_ENGLISH_TEMPLATE

            # To Japanese template
            to_jp_prompt = self.prompts_dir / "translate_to_jp.txt"
            if to_jp_prompt.exists():
                self._to_jp_template = to_jp_prompt.read_text(encoding='utf-8')
            else:
                self._to_jp_template = TO_JAPANESE_TEMPLATE
        else:
            self._template = DEFAULT_UNIFIED_TEMPLATE
            self._to_en_template = TO_ENGLISH_TEMPLATE
            self._to_jp_template = TO_JAPANESE_TEMPLATE

    def _get_template(self, output_language: Optional[str] = None) -> str:
        """Get appropriate template based on output language."""
        if output_language == "en":
            return self._to_en_template
        elif output_language == "jp":
            return self._to_jp_template
        else:
            return self._template

    def build(
        self,
        input_text: str,
        has_reference_files: bool = False,
        output_language: Optional[str] = None,
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            input_text: Text or batch to translate
            has_reference_files: Whether reference files are attached
            output_language: "en", "jp", or None for auto-detect

        Returns:
            Complete prompt string
        """
        # Add reference instruction only if files are attached
        reference_section = REFERENCE_INSTRUCTION if has_reference_files else ""

        # Get appropriate template
        template = self._get_template(output_language)

        # Replace placeholders
        prompt = template.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", input_text)

        return prompt

    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: Optional[str] = None,
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            texts: List of texts to translate
            has_reference_files: Whether reference files are attached
            output_language: "en", "jp", or None for auto-detect

        Returns:
            Complete prompt with numbered input
        """
        # Format as numbered list
        numbered_input = "\n".join(
            f"{i+1}. {text}" for i, text in enumerate(texts)
        )

        return self.build(numbered_input, has_reference_files, output_language)

    def parse_batch_result(self, result: str, expected_count: int) -> list[str]:
        """
        Parse batch translation result back to list.

        Args:
            result: Raw result string from Copilot
            expected_count: Expected number of translations

        Returns:
            List of translated texts
        """
        lines = result.strip().split('\n')
        translations = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Remove numbering prefix (e.g., "1. ", "2. ")
            import re
            match = re.match(r'^\d+\.\s*(.+)$', line)
            if match:
                translations.append(match.group(1))
            else:
                translations.append(line)

        # Pad with empty strings if needed
        while len(translations) < expected_count:
            translations.append("")

        return translations[:expected_count]
