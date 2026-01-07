# yakulingo/services/prompt_builder.py
"""
Builds translation prompts for YakuLingo.

Prompt file structure:
- translation_rules.txt: Translation rules with optional [COMMON]/[TO_EN]/[TO_JP] sections
- file_translate_to_en_{style}.txt: File translation → English (standard/concise/minimal)
- file_translate_to_jp.txt: File translation → Japanese
- text_translate_to_en_compare.txt: Text translation → English (standard/concise/minimal in one response)
- text_translate_to_jp.txt: Text translation → Japanese (with explanation)
- adjust_*.txt: Adjustment prompts (shorter, longer, custom)

Translation rules are loaded from translation_rules.txt and injected into
each prompt template via the {translation_rules} placeholder. When sections
are present, only the relevant rules for the output language are inserted.
"""

import re
from pathlib import Path
from typing import Optional, Sequence


_RULE_SECTION_PATTERN = re.compile(r'^\s*\[(COMMON|TO_EN|TO_JP)\]\s*$', re.IGNORECASE)
_RULE_SECTION_KEYS = {
    "COMMON": "common",
    "TO_EN": "en",
    "TO_JP": "jp",
}

# 参考ファイル参照の指示文（ファイル添付時のみ挿入）
REFERENCE_INSTRUCTION = """
参考ファイル (Reference Files)
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
"""
ID_MARKER_INSTRUCTION = """
### Item ID markers (critical)
- Each output item must start with "<number>. [[ID:n]]" (example: "1. [[ID:1]] ...").
- Output must include every ID from 1 to N exactly once (no omissions, no extras).
- Do not remove, change, or relocate the marker; keep it on the same line as the item number.
- If you cannot translate an item, copy the original text after the marker (do not leave it empty).
- Do not output other prompt markers (e.g., "===INPUT_TEXT===" / "===END_INPUT_TEXT===").
"""

# 用語集埋め込み時の指示文（プロンプト内に用語集を含める場合）
# 共通翻訳ルール（translation_rules.txt が存在しない場合のデフォルト）
DEFAULT_TRANSLATION_RULES = """## 翻訳ルール（Translation Rules）

[COMMON]
- 原文の改行・タブ・段落構造を維持する
- 箇条書き・表形式を崩さない
- 数字の桁/カンマは変更しない

[TO_EN]
- 記号禁止: > < >=/≥/≧ <=/≤/≦ ~ → ↑ ↓ は使わず言葉で表現する
  - >: more than / exceeding / over
  - <: less than / under / below
  - >=: or more / at least
  - <=: or less / at most
  - ~: approximately / about
  - →: leads to / results in / which enhances
  - ↑: increased / up / higher
  - ↓: decreased / down / lower
- 数値/単位:
  - 兆/億→oku (1兆=10,000億=10,000 oku; X兆Y億→(X*10,000+Y) oku)
  - 千→k
  - ▲→() （負数は数値のみ括弧）
  - YoY/QoQ/CAGR を使用
  - billion/trillion には変換しない
- 月名は略語: Jan., Feb., Mar., Apr., May, Jun., Jul., Aug., Sep., Oct., Nov., Dec.
- 「+」は追加の意味のみ。比較は "higher than" などで表現する

[TO_JP]
- 数値/単位:
  - oku→億 (22,385 oku→2兆2,385億)
  - k→千または000
  - ¥/￥ + 数値 + (billion/bn) は「数値 × 10億円」として、兆/億/万の和文表記に変換する
    - 例: ¥2,238.5billion → 2兆2,385億円
  - ()→▲
"""

# Fallback template for → English (used when translate_to_en.txt doesn't exist)
DEFAULT_TO_EN_TEMPLATE = """## ファイル翻訳リクエスト

重要: 出力は必ず入力と同じ番号付きリスト形式で出力してください。

### 出力形式（最優先ルール）
- 入力: 番号付きリスト（1., 2., 3., ...）
- 出力: 必ず同じ番号付きリスト形式で出力
- 各項目は必ず「番号. 」で始める（例: "1. Hello"）
- 改行がある場合は2行目以降に番号を付けず、1つ以上の空白/タブでインデントする
- 番号を飛ばしたり、統合したりしないこと
- 解説、Markdown、追加テキストは不要
- 番号なしの出力は禁止

### 翻訳スタイル
- ビジネス文書向けで自然で読みやすい英語
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
- 各項目は必ず「番号. 」で始める（例: "1. こんにちは"）
- 改行がある場合は2行目以降に番号を付けず、1つ以上の空白/タブでインデントする
- 番号を飛ばしたり、統合したりしないこと
- 解説、Markdown、追加テキストは不要
- 番号なしの出力は禁止

### 翻訳ガイドライン
- ビジネス文書向けで自然で読みやすい日本語
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

日本語をビジネス文書向けの英語に翻訳してください。

### 翻訳ガイドライン
- 自然で読みやすい英語
- 既に英語の場合はそのまま出力
- 原文の改行・タブ・段落構造をそのまま維持する

{translation_rules}

### 出力形式
訳文: 英語翻訳

解説:
- 原文の表現がどう訳されたか、注意すべき語句の対応を具体的に説明（見出し・ラベルなし）

解説は日本語で簡潔に書いてください。

### 禁止事項（絶対に出力しないこと）
- 「続けますか？」「他にありますか？」などの質問
- 「〜も翻訳できます」「必要なら〜」などの提案
- プロンプトの指示をそのまま繰り返すような補足（例：「数値はoku変換済み」「略語を使用」「簡潔化した」など）
- 訳文と解説以外のテキスト

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

テキストをビジネス文書向けの日本語に翻訳してください。

### 翻訳ガイドライン
- ビジネス文書向けで自然で読みやすい日本語
- 簡潔な表現を心がける
- 既に日本語の場合はそのまま出力
- 原文の改行・タブをそのまま維持

### 数値表記ルール
- oku → 億（例: 4,500 oku → 4,500億）
- k → 千または000（例: 12k → 12,000）
- () → ▲（例: (50) → ▲50）

{translation_rules}

### 出力形式
訳文: 日本語翻訳

解説:
- 原文の表現がどう訳されたか、注意すべき語句の対応を具体的に説明（見出し・ラベルなし）

解説は日本語で簡潔に書いてください。

### 禁止事項（絶対に出力しないこと）
- 「続けますか？」「他にありますか？」などの質問
- 「〜も翻訳できます」「必要なら〜」などの提案
- プロンプトの指示をそのまま繰り返すような補足（例：「数値はoku変換済み」「略語を使用」「簡潔化した」など）
- 訳文と解説以外のテキスト

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
    Translation rules are loaded from translation_rules.txt.
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir
        # Templates cache: {(lang, style): template_str}
        self._templates: dict[tuple[str, str], str] = {}
        # Text translation templates cache: {(lang, style): template_str}
        self._text_templates: dict[tuple[str, str], str] = {}
        # Text translation comparison template
        self._text_compare_template: Optional[str] = None
        # Translation rules cache (raw + parsed sections)
        self._translation_rules_raw: str = ""
        self._translation_rules_sections: dict[str, str] = {}
        self._translation_rules_has_sections: bool = False
        self._load_templates()

    def _load_translation_rules(self) -> str:
        """Load translation rules from translation_rules.txt."""
        rules_text = DEFAULT_TRANSLATION_RULES
        if self.prompts_dir:
            rules_file = self.prompts_dir / "translation_rules.txt"
            if rules_file.exists():
                rules_text = rules_file.read_text(encoding='utf-8')

        self._translation_rules_raw = rules_text
        sections, has_sections = self._parse_translation_rules_sections(rules_text)
        self._translation_rules_sections = sections
        self._translation_rules_has_sections = has_sections
        return rules_text

    def _parse_translation_rules_sections(self, rules_text: str) -> tuple[dict[str, str], bool]:
        """Parse optional [COMMON]/[TO_EN]/[TO_JP] sections from rules text."""
        sections = {"common": "", "en": "", "jp": ""}
        seen_tag = False
        current_key: Optional[str] = None
        unsectioned_lines: list[str] = []

        for line in rules_text.splitlines():
            match = _RULE_SECTION_PATTERN.match(line)
            if match:
                seen_tag = True
                current_key = _RULE_SECTION_KEYS.get(match.group(1).upper())
                continue

            if seen_tag:
                if current_key:
                    sections[current_key] += line + "\n"
            else:
                unsectioned_lines.append(line)

        if not seen_tag:
            return {"common": "\n".join(unsectioned_lines).strip(), "en": "", "jp": ""}, False

        for key in sections:
            sections[key] = sections[key].strip()
        return sections, True

    def _load_templates(self) -> None:
        """Load prompt templates from files or use defaults"""
        styles = ["standard", "concise", "minimal"]

        # Load common translation rules
        self._load_translation_rules()
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
            # Text translation to Japanese (no style variations)
            text_to_jp = self.prompts_dir / "text_translate_to_jp.txt"
            if text_to_jp.exists():
                jp_text_template = text_to_jp.read_text(encoding='utf-8')
            else:
                jp_text_template = DEFAULT_TEXT_TO_JP_TEMPLATE

            for style in styles:
                self._text_templates.setdefault(("jp", style), jp_text_template)

            text_compare = self.prompts_dir / "text_translate_to_en_compare.txt"
            if text_compare.exists():
                self._text_compare_template = text_compare.read_text(encoding='utf-8')

        else:
            # Use defaults
            for style in styles:
                self._templates[("en", style)] = DEFAULT_TO_EN_TEMPLATE
                self._templates[("jp", style)] = DEFAULT_TO_JP_TEMPLATE
                self._text_templates[("jp", style)] = DEFAULT_TEXT_TO_JP_TEMPLATE
            self._text_compare_template = DEFAULT_TEXT_TO_EN_COMPARE_TEMPLATE

    def get_translation_rules(self, output_language: Optional[str] = None) -> str:
        """Get translation rules for the given output language.

        Args:
            output_language: "en", "jp", or "common". None returns all sections
                             for backward compatibility.

        Returns:
            Translation rules content string
        """
        if not self._translation_rules_raw:
            self._load_translation_rules()

        if not self._translation_rules_has_sections:
            return self._translation_rules_raw.strip()

        if output_language == "common":
            return self._translation_rules_sections.get("common", "")

        if output_language in {"en", "jp"}:
            parts = [
                self._translation_rules_sections.get("common", ""),
                self._translation_rules_sections.get(output_language, ""),
            ]
            return "\n\n".join([part for part in parts if part])

        parts = [
            self._translation_rules_sections.get("common", ""),
            self._translation_rules_sections.get("en", ""),
            self._translation_rules_sections.get("jp", ""),
        ]
        return "\n\n".join([part for part in parts if part])

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
        self._load_translation_rules()

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
        if output_language == "en":
            # English text translation uses the compare template instead.
            return None

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

    def _apply_placeholders(
        self,
        template: str,
        reference_section: str,
        input_text: str,
        output_language: str = "en",
        translation_style: str = "concise",
    ) -> str:
        """Apply all placeholder replacements to a template.

        Args:
            template: Prompt template string
            reference_section: Reference section content
            input_text: Input text to translate
            output_language: "en", "jp", or "common"
            translation_style: Translation style name

        Returns:
            Template with all placeholders replaced
        """
        # Always reload translation rules from file to pick up user edits
        self._load_translation_rules()
        translation_rules = self.get_translation_rules(output_language)

        # Replace placeholders
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", input_text)
        # Remove old style placeholder if present (for backwards compatibility)
        prompt = prompt.replace("{translation_style}", translation_style)
        prompt = prompt.replace("{style}", translation_style)

        return prompt

    def _insert_extra_instruction(self, prompt: str, extra_instruction: str) -> str:
        """Insert extra instruction before the input marker if present."""
        marker = "===INPUT_TEXT==="
        extra_instruction = extra_instruction.strip()
        if not extra_instruction:
            return prompt
        if marker in prompt:
            return prompt.replace(marker, f"{extra_instruction}\n{marker}", 1)
        return f"{extra_instruction}\n{prompt}"

    def build(
        self,
        input_text: str,
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        extra_instruction: Optional[str] = None,
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            input_text: Text or batch to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output
            extra_instruction: Optional instruction inserted before input markers

        Returns:
            Complete prompt string
        """
        # Build reference section
        reference_section = ""
        if has_reference_files:
            # Reference files attached to Copilot
            reference_section = REFERENCE_INSTRUCTION

        # Get appropriate template based on language and style
        template = self._get_template(output_language, translation_style)

        prompt = self._apply_placeholders(
            template,
            reference_section,
            input_text,
            output_language,
            translation_style,
        )
        if extra_instruction:
            prompt = self._insert_extra_instruction(prompt, extra_instruction)
        return prompt

    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            texts: List of texts to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output
            include_item_ids: Prepend [[ID:n]] marker for stable parsing

        Returns:
            Complete prompt with numbered input
        """
        extra_instruction = None
        if include_item_ids:
            extra_instruction = ID_MARKER_INSTRUCTION
            texts = [f"[[ID:{i + 1}]] {text}" for i, text in enumerate(texts)]

        # Format as numbered list
        numbered_input = "\n".join(
            f"{i+1}. {text}" for i, text in enumerate(texts)
        )

        return self.build(
            numbered_input,
            has_reference_files,
            output_language,
            translation_style,
            extra_instruction=extra_instruction,
        )

    def build_reference_section(
        self,
        reference_files: Optional[Sequence[Path]],
    ) -> str:
        """Return reference section text when reference files are provided.

        Args:
            reference_files: Optional reference files being attached

        Returns:
            Reference section text for prompt
        """
        if reference_files:
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
