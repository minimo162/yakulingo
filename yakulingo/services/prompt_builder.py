# yakulingo/services/prompt_builder.py
"""
Builds translation prompts for YakuLingo.

Prompt file structure:
- translate_to_en.txt: File translation → English
- translate_to_jp.txt: File translation → Japanese
- text_translate_to_en.txt: Text translation → English (with 3 options)
- text_translate_to_jp.txt: Text translation → Japanese (with explanation)
- adjust_*.txt: Adjustment prompts (shorter, longer, custom)

Glossary content is embedded directly in prompts for reliable translation.
"""

import re
from pathlib import Path
from typing import Optional, List


def load_glossary_content(reference_files: Optional[List[Path]]) -> str:
    """
    Load glossary content from reference files.

    Args:
        reference_files: List of reference file paths (CSV format expected)

    Returns:
        Formatted glossary content string, or empty string if no files
    """
    if not reference_files:
        return ""

    glossary_entries = []
    for file_path in reference_files:
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding='utf-8')
            for line in content.strip().split('\n'):
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Parse CSV format: source,target
                if ',' in line:
                    parts = line.split(',', 1)
                    if len(parts) == 2:
                        source = parts[0].strip()
                        target = parts[1].strip()
                        if source and target:
                            glossary_entries.append(f"- {source} → {target}")
        except Exception:
            continue

    if not glossary_entries:
        return ""

    return glossary_entries


def build_reference_section(glossary_entries: List[str]) -> str:
    """
    Build reference section with glossary content.

    Args:
        glossary_entries: List of glossary entries

    Returns:
        Formatted reference section string
    """
    if not glossary_entries:
        return ""

    return f"""Glossary (用語集)
以下の用語集に記載されている用語は、必ず指定された訳語を使用してください。

{chr(10).join(glossary_entries)}
"""


# Legacy constant for backwards compatibility
REFERENCE_INSTRUCTION = """
Glossary (用語集)
以下の用語集を参照し、記載されている用語は必ず指定された訳語を使用してください。
"""

# Fallback template for → English (used when translate_to_en.txt doesn't exist)
DEFAULT_TO_EN_TEMPLATE = """Role Definition
あなたは英語への翻訳を行う、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Translation Rule
- すべてのテキストを英語に翻訳
- 既に英語のテキスト → そのまま出力

Critical Rules (優先順位順)

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

2. 自然な翻訳
   - 読みやすく自然な英語に翻訳
   - 過度な省略は避ける

3. 数値表記（必須ルール）
   - 億 → oku (例: 4,500億円 → 4,500 oku yen)
   - 千単位 → k (例: 12,000 → 12k)
   - 負数 → () (例: ▲50 → (50))

4. 体裁の維持とコンパクトな翻訳
   - 原文の改行・段落構造をそのまま維持する
   - 冗長な表現を避け、簡潔な翻訳を心がける
   - 意味を損なわない範囲で、より短い表現を選択する
   - 同じ意味なら文字数の少ない単語・表現を優先する

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

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

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


class PromptBuilder:
    """
    Builds translation prompts for file translation.
    Glossary content is embedded directly in prompts.
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir
        self._to_en_template: str = ""
        self._to_jp_template: str = ""
        self._load_templates()

    def _load_templates(self) -> None:
        """Load prompt templates from files or use defaults"""
        if self.prompts_dir:
            # To English template (translate_to_en.txt)
            to_en_prompt = self.prompts_dir / "translate_to_en.txt"
            if to_en_prompt.exists():
                self._to_en_template = to_en_prompt.read_text(encoding='utf-8')
            else:
                self._to_en_template = DEFAULT_TO_EN_TEMPLATE

            # To Japanese template (translate_to_jp.txt)
            to_jp_prompt = self.prompts_dir / "translate_to_jp.txt"
            if to_jp_prompt.exists():
                self._to_jp_template = to_jp_prompt.read_text(encoding='utf-8')
            else:
                self._to_jp_template = DEFAULT_TO_JP_TEMPLATE
        else:
            self._to_en_template = DEFAULT_TO_EN_TEMPLATE
            self._to_jp_template = DEFAULT_TO_JP_TEMPLATE

    def _get_template(self, output_language: str = "en") -> str:
        """Get appropriate template based on output language."""
        if output_language == "jp":
            return self._to_jp_template
        else:
            return self._to_en_template

    def build(
        self,
        input_text: str,
        glossary_content: str = "",
        output_language: str = "en",
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            input_text: Text or batch to translate
            glossary_content: Formatted glossary content to embed in prompt
            output_language: "en" or "jp" (default: "en")

        Returns:
            Complete prompt string
        """
        # Get appropriate template
        template = self._get_template(output_language)

        # Replace placeholders
        prompt = template.replace("{reference_section}", glossary_content)
        prompt = prompt.replace("{input_text}", input_text)

        return prompt

    def build_batch(
        self,
        texts: list[str],
        glossary_content: str = "",
        output_language: str = "en",
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            texts: List of texts to translate
            glossary_content: Formatted glossary content to embed in prompt
            output_language: "en" or "jp" (default: "en")

        Returns:
            Complete prompt with numbered input
        """
        # Format as numbered list
        numbered_input = "\n".join(
            f"{i+1}. {text}" for i, text in enumerate(texts)
        )

        return self.build(numbered_input, glossary_content, output_language)

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
            match = re.match(r'^\d+\.\s*(.+)$', line)
            if match:
                translations.append(match.group(1))
            else:
                translations.append(line)

        # Pad with empty strings if needed
        while len(translations) < expected_count:
            translations.append("")

        return translations[:expected_count]
