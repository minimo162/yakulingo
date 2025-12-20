# yakulingo/services/prompt_builder.py
"""
Builds translation prompts for YakuLingo.

Prompt file structure:
- translation_rules.txt: Common translation rules (numeric notation, symbol conversion)
- file_translate_to_en_{style}.txt: File translation → English (standard/concise/minimal)
- file_translate_to_jp.txt: File translation → Japanese
- text_translate_to_en_{style}.txt: Text translation → English (standard/concise/minimal)
- text_translate_to_en_compare.txt: Text translation -> English (standard/concise/minimal in one response)
- text_translate_to_jp.txt: Text translation → Japanese (with explanation)
- adjust_*.txt: Adjustment prompts (shorter, longer, custom)

Common translation rules are loaded from translation_rules.txt and injected into
each prompt template via the {translation_rules} placeholder.
"""

import re
from pathlib import Path
from typing import Optional, Sequence


# 参考ファイル参照の指示文（ファイル添付時のみ挿入）
REFERENCE_INSTRUCTION = """
参考ファイル (Reference Files)
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
"""

# 用語集埋め込み時の指示文（プロンプト内に用語集を含める場合）
GLOSSARY_EMBEDDED_INSTRUCTION = """
用語集 (Glossary)
以下の用語集に記載されている用語は、必ずその訳語を使用してください。

{glossary_content}
"""

# 共通翻訳ルール（translation_rules.txt が存在しない場合のデフォルト）
DEFAULT_TRANSLATION_RULES = """### 数値表記ルール（日本語 → 英語）

重要: 数字は絶対に変換しない。単位のみを置き換える。

| 日本語 | 英語 | 変換例 |
|--------|------|--------|
| 億 | oku | 4,500億円 → 4,500 oku yen |
| 千 | k | 12,000 → 12k |
| ▲ (マイナス) | () | ▲50 → (50) |
| 前年比 | YoY | 前年比10%増 → 10% YoY increase |
| 前期比 | QoQ | 前期比5%減 → 5% QoQ decrease |
| 年平均成長率 | CAGR | 年平均成長率3% → CAGR 3% |

注意:
- 「4,500億円」は必ず「4,500 oku yen」に翻訳する
- 「450 billion」や「4.5 trillion」には絶対に変換しない
- 数字の桁は絶対に変えない（4,500は4,500のまま）

### 記号変換ルール（英訳時）

以下の記号は英語圏でビジネス文書に不適切です。必ず英語で表現してください。

禁止記号と置き換え:
- ↑ → increased, up, higher（使用禁止）
- ↓ → decreased, down, lower（使用禁止）
- ~ → approximately, about, around（使用禁止）
- → → leads to, results in, becomes（使用禁止）
- > → greater than, more than, exceeds（使用禁止）
- < → less than, below, under（使用禁止）
- = → equals, is, amounts to（使用禁止）
- ※ → Note:, *（使用禁止）

例:
- 「3か月以上」→ "3 months or more"（× > 3 months）
- 「売上↑」→ "Sales increased"（× Sales ↑）
- 「約100万円」→ "approximately 1 million yen"（× ~1 million yen）

許可される記号: & % / + # @
"""

# Fallback template for → English (used when translate_to_en.txt doesn't exist)
DEFAULT_TO_EN_TEMPLATE = """## ファイル翻訳リクエスト

重要: 出力は必ず入力と同じ番号付きリスト形式で出力してください。

### 出力形式（最優先ルール）
- 入力: 番号付きリスト（1., 2., 3., ...）
- 出力: 必ず同じ番号付きリスト形式で出力
- 各行は必ず「番号. 」で始める（例: "1. Hello"）
- 番号を飛ばしたり、統合したりしないこと
- 解説、Markdown、追加テキストは不要
- 番号なしの出力は禁止

### 翻訳スタイル
- 自然で読みやすい英語
- 既に英語の場合はそのまま出力

{translation_rules}

{reference_section}

---

{input_text}
"""

# Fallback template for → Japanese (used when translate_to_jp.txt doesn't exist)
DEFAULT_TO_JP_TEMPLATE = """## ファイル翻訳リクエスト（日本語への翻訳）

重要: 出力は必ず入力と同じ番号付きリスト形式で出力してください。

### 出力形式（最優先ルール）
- 入力: 番号付きリスト（1., 2., 3., ...）
- 出力: 必ず同じ番号付きリスト形式で出力
- 各行は必ず「番号. 」で始める（例: "1. こんにちは"）
- 番号を飛ばしたり、統合したりしないこと
- 解説、Markdown、追加テキストは不要
- 番号なしの出力は禁止

### 翻訳ガイドライン
- 自然で読みやすい日本語
- 簡潔な表現を心がける
- 既に日本語の場合はそのまま出力

### 数値表記ルール
- oku → 億（例: 4,500 oku → 4,500億）
- k → 千または000（例: 12k → 12,000）
- () → ▲（例: (50) → ▲50）

{reference_section}

---

{input_text}
"""

# Fallback templates for text translation (used when text_translate_*.txt don't exist)
DEFAULT_TEXT_TO_EN_TEMPLATE = """## テキスト翻訳リクエスト

日本語を英語に翻訳してください。

### 翻訳ガイドライン
- 自然で読みやすい英語
- 既に英語の場合はそのまま出力
- 原文の改行・タブ・段落構造をそのまま維持する

{translation_rules}

### 出力形式
訳文: 英語翻訳

解説:
- この表現を選んだ理由（1行）
- 言い換えのポイント（1行）
- 使用場面・注意点（1行）

解説は必ず日本語で書いてください。

{reference_section}

---

以下のテキストを翻訳してください:
{input_text}
"""

DEFAULT_TEXT_TO_EN_COMPARE_TEMPLATE = """## Text Translation Request (Style Comparison)
Translate the following Japanese text into English in three styles: standard, concise, minimal.

### Common rules
- Preserve line breaks, tabs, and paragraph structure.
- If the input is already English, keep it as is.
- Follow the translation rules below.
- Translate ONLY the text between the input markers.
- Do NOT translate or paraphrase any other part of this prompt.
- Do NOT output the marker lines `===INPUT_TEXT===` or `===END_INPUT_TEXT===`.

### Style rules
[standard]
- Natural, business-ready English.
- Use articles (a/an/the) appropriately.
- Use common business abbreviations when suitable (YoY, QoQ, CAGR).

[concise]
- Make it concise; avoid wordiness.
- Prefer common abbreviations (info, FYI, ASAP, etc.).
- Simplify phrases (e.g., "in order to" -> "to", "due to the fact that" -> "because").

[minimal]
- Minimum words; suitable for headings/subject lines/tables.
- Articles can be omitted.
- Maximize abbreviations.
- Allowed symbols: & / vs. % # w/ w/o @ +

### Output format (exact)
[standard]
Translation:
Explanation:

[concise]
Translation:
Explanation:

[minimal]
Translation:
Explanation:

- Do not output anything else.
- Explain in Japanese with the same level of detail as an individual translation. Do not be overly brief.
- In each Explanation, describe how the source expressions were rendered and any key term mappings.
- Do not include headings or labels such as "翻訳のポイント:" in the output.

{translation_rules}

{reference_section}

---

### INPUT (translate only this block)
===INPUT_TEXT===
{input_text}
===END_INPUT_TEXT===
"""

DEFAULT_TEXT_TO_JP_TEMPLATE = """## テキスト翻訳リクエスト（日本語への翻訳）

テキストを自然な日本語に翻訳してください。

### 翻訳ガイドライン
- 自然で読みやすい日本語
- 簡潔な表現を心がける
- 既に日本語の場合はそのまま出力
- 原文の改行・タブをそのまま維持

### 数値表記ルール
- oku → 億（例: 4,500 oku → 4,500億）
- k → 千または000（例: 12k → 12,000）
- () → ▲（例: (50) → ▲50）

### 出力形式
訳文: 日本語翻訳

解説:
- 文法・構文のポイント（1行）
- 重要な語句・表現（1行）
- 使用場面・ニュアンス（1行）

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
    Common translation rules are loaded from translation_rules.txt.
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir
        # Templates cache: {(lang, style): template_str}
        self._templates: dict[tuple[str, str], str] = {}
        # Text translation templates cache: {(lang, style): template_str}
        self._text_templates: dict[tuple[str, str], str] = {}
        # Text translation comparison template
        self._text_compare_template: Optional[str] = None
        # Common translation rules cache
        self._translation_rules: str = ""
        self._load_templates()

    def _load_translation_rules(self) -> str:
        """Load common translation rules from translation_rules.txt."""
        if self.prompts_dir:
            rules_file = self.prompts_dir / "translation_rules.txt"
            if rules_file.exists():
                return rules_file.read_text(encoding='utf-8')
        return DEFAULT_TRANSLATION_RULES

    def _load_templates(self) -> None:
        """Load prompt templates from files or use defaults"""
        styles = ["standard", "concise", "minimal"]

        # Load common translation rules
        self._translation_rules = self._load_translation_rules()
        self._text_compare_template = DEFAULT_TEXT_TO_EN_COMPARE_TEMPLATE

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

            text_compare = self.prompts_dir / "text_translate_to_en_compare.txt"
            if text_compare.exists():
                self._text_compare_template = text_compare.read_text(encoding='utf-8')
        else:
            # Use defaults
            for style in styles:
                self._templates[("en", style)] = DEFAULT_TO_EN_TEMPLATE
                self._templates[("jp", style)] = DEFAULT_TO_JP_TEMPLATE
                self._text_templates[("en", style)] = DEFAULT_TEXT_TO_EN_TEMPLATE
                self._text_templates[("jp", style)] = DEFAULT_TEXT_TO_JP_TEMPLATE
            self._text_compare_template = DEFAULT_TEXT_TO_EN_COMPARE_TEMPLATE

    def get_translation_rules(self) -> str:
        """Get the common translation rules.

        Returns:
            Translation rules content string
        """
        return self._translation_rules

    def get_translation_rules_path(self) -> Optional[Path]:
        """Get the path to translation_rules.txt file.

        Returns:
            Path to translation_rules.txt if prompts_dir is set, None otherwise
        """
        if self.prompts_dir:
            return self.prompts_dir / "translation_rules.txt"
        return None

    def reload_translation_rules(self) -> None:
        """Reload translation rules from file.

        Call this after user edits the translation_rules.txt file.
        """
        self._translation_rules = self._load_translation_rules()

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

    def get_text_compare_template(self) -> Optional[str]:
        """Get cached text translation comparison template."""
        return self._text_compare_template

    def _apply_placeholders(self, template: str, reference_section: str, input_text: str, translation_style: str = "concise") -> str:
        """Apply all placeholder replacements to a template.

        Args:
            template: Prompt template string
            reference_section: Reference section content
            input_text: Input text to translate
            translation_style: Translation style name

        Returns:
            Template with all placeholders replaced
        """
        # Always reload translation rules from file to pick up user edits
        self._translation_rules = self._load_translation_rules()

        # Replace placeholders
        prompt = template.replace("{translation_rules}", self._translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", input_text)
        # Remove old style placeholder if present (for backwards compatibility)
        prompt = prompt.replace("{translation_style}", translation_style)
        prompt = prompt.replace("{style}", translation_style)

        return prompt

    def build(
        self,
        input_text: str,
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        glossary_content: Optional[str] = None,
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            input_text: Text or batch to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output
            glossary_content: Optional glossary content to embed in prompt (faster than file attachment)

        Returns:
            Complete prompt string
        """
        # Build reference section
        reference_section = ""
        if glossary_content:
            # Embed glossary directly in prompt (faster than file attachment)
            reference_section = GLOSSARY_EMBEDDED_INSTRUCTION.format(glossary_content=glossary_content)
        elif has_reference_files:
            # Reference files attached to Copilot
            reference_section = REFERENCE_INSTRUCTION

        # Get appropriate template based on language and style
        template = self._get_template(output_language, translation_style)

        return self._apply_placeholders(template, reference_section, input_text, translation_style)

    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        glossary_content: Optional[str] = None,
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            texts: List of texts to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output
            glossary_content: Optional glossary content to embed in prompt (faster than file attachment)

        Returns:
            Complete prompt with numbered input
        """
        # Format as numbered list
        numbered_input = "\n".join(
            f"{i+1}. {text}" for i, text in enumerate(texts)
        )

        return self.build(numbered_input, has_reference_files, output_language, translation_style, glossary_content)

    def build_reference_section(
        self,
        reference_files: Optional[Sequence[Path]],
        glossary_content: Optional[str] = None,
    ) -> str:
        """Return reference section text when reference files or glossary are provided.

        Args:
            reference_files: Optional reference files being attached
            glossary_content: Optional glossary content to embed in prompt

        Returns:
            Reference section text for prompt
        """
        if glossary_content:
            return GLOSSARY_EMBEDDED_INSTRUCTION.format(glossary_content=glossary_content)
        elif reference_files:
            return REFERENCE_INSTRUCTION
        return ""

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
                text = match.group(1)
            else:
                text = line

            translations.append(text)

        # Pad with empty strings if needed
        while len(translations) < expected_count:
            translations.append("")

        return translations[:expected_count]
