# ecm_translate/services/prompt_builder.py
"""
Builds translation prompts with unified rules.
Reference files are attached to Copilot, not embedded in prompt.
"""

from pathlib import Path
from typing import Optional

from ecm_translate.models.types import TranslationDirection


# 参考ファイル参照の指示文（ファイル添付時のみ挿入）
REFERENCE_INSTRUCTION = """
Reference Files
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
"""

# Default prompt templates (used if files not found)
DEFAULT_JP_TO_EN_TEMPLATE = """Role Definition
あなたは日本語を英語に翻訳する、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

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

DEFAULT_EN_TO_JP_TEMPLATE = """Role Definition
あなたは英語を日本語に翻訳する、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

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
    Builds translation prompts with compression rules.
    Reference files are attached to Copilot, not embedded in prompt.
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir
        self._templates: dict[TranslationDirection, str] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Load prompt templates from files or use defaults"""
        if self.prompts_dir:
            jp_to_en = self.prompts_dir / "translate_jp_to_en.txt"
            en_to_jp = self.prompts_dir / "translate_en_to_jp.txt"

            if jp_to_en.exists():
                self._templates[TranslationDirection.JP_TO_EN] = jp_to_en.read_text(encoding='utf-8')
            else:
                self._templates[TranslationDirection.JP_TO_EN] = DEFAULT_JP_TO_EN_TEMPLATE

            if en_to_jp.exists():
                self._templates[TranslationDirection.EN_TO_JP] = en_to_jp.read_text(encoding='utf-8')
            else:
                self._templates[TranslationDirection.EN_TO_JP] = DEFAULT_EN_TO_JP_TEMPLATE
        else:
            self._templates[TranslationDirection.JP_TO_EN] = DEFAULT_JP_TO_EN_TEMPLATE
            self._templates[TranslationDirection.EN_TO_JP] = DEFAULT_EN_TO_JP_TEMPLATE

    def build(
        self,
        direction: TranslationDirection,
        input_text: str,
        has_reference_files: bool = False,
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            direction: Translation direction
            input_text: Text or batch to translate
            has_reference_files: Whether reference files are attached

        Returns:
            Complete prompt string
        """
        template = self._templates.get(direction, DEFAULT_JP_TO_EN_TEMPLATE)

        # Add reference instruction only if files are attached
        reference_section = REFERENCE_INSTRUCTION if has_reference_files else ""

        # Replace placeholders
        prompt = template.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", input_text)

        return prompt

    def build_batch(
        self,
        direction: TranslationDirection,
        texts: list[str],
        has_reference_files: bool = False,
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            direction: Translation direction
            texts: List of texts to translate
            has_reference_files: Whether reference files are attached

        Returns:
            Complete prompt with numbered input
        """
        # Format as numbered list
        numbered_input = "\n".join(
            f"{i+1}. {text}" for i, text in enumerate(texts)
        )

        return self.build(direction, numbered_input, has_reference_files)

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
