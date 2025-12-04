# yakulingo/processors/translators.py
"""
Unified translation logic for Excel/Word/PowerPoint.
CellTranslator: For table cells (Excel-compatible logic)
ParagraphTranslator: For body paragraphs
"""

import re


class CellTranslator:
    """
    Unified cell translation logic for Excel/Word/PowerPoint tables.
    Follows Excel translation rules for consistency.
    """

    # 翻訳スキップパターン
    SKIP_PATTERNS = [
        r'^[\d\s\.,\-\+\(\)\/]+$',           # 数値のみ
        r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$',    # 日付 (YYYY-MM-DD)
        r'^\d{1,2}[-/]\d{1,2}[-/]\d{4}$',    # 日付 (DD/MM/YYYY)
        r'^[\w\.\-]+@[\w\.\-]+\.\w+$',        # メールアドレス
        r'^https?://\S+$',                    # URL
        r'^[A-Z]{2,5}[-_]?\d+$',              # コード (ABC-123)
        r'^[\d\s%]+$',                        # パーセント付き数値
        r'^[¥$€£]\s*[\d,\.]+$',               # 通貨記号付き数値
        r'^\d+[年月日時分秒]',                  # 日本語日時
    ]

    # Class-level compiled regex patterns (shared across all instances)
    _compiled_skip_regex = None

    @classmethod
    def _get_skip_regex(cls):
        """Get compiled skip regex patterns (lazy initialization)."""
        if cls._compiled_skip_regex is None:
            cls._compiled_skip_regex = [re.compile(p) for p in cls.SKIP_PATTERNS]
        return cls._compiled_skip_regex

    def __init__(self):
        # Use class-level compiled patterns
        self._skip_regex = self._get_skip_regex()

    def should_translate(self, text: str, output_language: str = "en") -> bool:
        """
        Determine if cell text should be translated.
        Same logic used for Excel cells, Word table cells, and PPT table cells.

        Skip conditions:
        - Empty or whitespace only
        - Numbers only (with formatting characters)
        - Date patterns
        - Email addresses
        - URLs
        - Product/Document codes
        - For JP→EN (output_language="en"): Skip text without Japanese characters
        - For EN→JP (output_language="jp"): Skip text that is Japanese-only

        Args:
            text: Text to check
            output_language: "en" for JP→EN, "jp" for EN→JP
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # Check against skip patterns first (fast rejection)
        for regex in self._skip_regex:
            if regex.match(text):
                return False

        # Language-based filtering depends on translation direction
        if output_language == "en":
            # JP→EN: Skip text without Japanese characters
            # (e.g., "USA", "Canada", "FY26/3" are skipped)
            if not self._contains_japanese(text):
                return False
        else:
            # EN→JP: Skip text that is Japanese-only
            # (e.g., "こんにちは" is skipped, but "Hello こんにちは" is translated)
            if self._is_japanese_only(text):
                return False

        return True

    def _contains_japanese(self, text: str) -> bool:
        """
        Check if text contains Japanese characters or Japanese document symbols.

        Includes:
        - Hiragana (U+3040-U+309F)
        - Katakana (U+30A0-U+30FF)
        - CJK Kanji (U+4E00-U+9FFF)
        - Japanese document symbols:
          - ▲ (U+25B2): Black up-pointing triangle (negative number marker)
          - △ (U+25B3): White up-pointing triangle
          - 〇 (U+3007): Ideographic number zero
          - ※ (U+203B): Reference mark
        """
        for char in text:
            code = ord(char)
            if (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF or  # Katakana
                0x4E00 <= code <= 0x9FFF or  # CJK Kanji
                code == 0x25B2 or            # ▲ (negative marker)
                code == 0x25B3 or            # △
                code == 0x3007 or            # 〇 (ideographic zero)
                code == 0x203B):             # ※ (reference mark)
                return True
        return False

    def _is_japanese_only(self, text: str) -> bool:
        """
        Check if text contains Japanese-specific characters (hiragana/katakana).

        Used for X→JP translation to skip already-Japanese text.
        Returns True if text has hiragana/katakana but no alphabetic characters.

        IMPORTANT: CJK Kanji alone does NOT count as "Japanese-only" because
        Chinese text also uses the same kanji range (U+4E00-U+9FFF).
        Only hiragana/katakana are unique to Japanese.

        Examples:
            "こんにちは" → True (has kana, skip for X→JP)
            "日本語" → False (kanji only, might be Chinese, translate)
            "你好世界" → False (Chinese, translate for X→JP)
            "Hello" → False (English only, translate for X→JP)
            "Hello こんにちは" → False (mixed with alphabet, translate)
            "売上げ" → True (has hiragana, skip for X→JP)
        """
        has_kana = False
        has_alphabetic = False

        for char in text:
            code = ord(char)
            # Check for Japanese-specific characters (hiragana/katakana only)
            # CJK Kanji is excluded because it's shared with Chinese
            if (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF):   # Katakana
                has_kana = True
            # Check for alphabetic characters (A-Z, a-z)
            elif (0x0041 <= code <= 0x005A or  # A-Z
                  0x0061 <= code <= 0x007A):   # a-z
                has_alphabetic = True

            # Early exit if we found both
            if has_kana and has_alphabetic:
                return False

        # Japanese-only if has kana but no alphabetic
        return has_kana and not has_alphabetic


class ParagraphTranslator:
    """
    Paragraph translation logic for Word/PowerPoint body text.
    Preserves paragraph-level styles, but not individual run formatting.
    """

    # 翻訳スキップパターン（段落用）
    SKIP_PATTERNS = [
        r'^[\d\s\.,\-\+\(\)\/]+$',           # 数値のみ
        r'^https?://\S+$',                    # URL
        r'^[\w\.\-]+@[\w\.\-]+\.\w+$',        # メールアドレス
    ]

    # Class-level compiled regex patterns (shared across all instances)
    _compiled_skip_regex = None

    @classmethod
    def _get_skip_regex(cls):
        """Get compiled skip regex patterns (lazy initialization)."""
        if cls._compiled_skip_regex is None:
            cls._compiled_skip_regex = [re.compile(p) for p in cls.SKIP_PATTERNS]
        return cls._compiled_skip_regex

    def __init__(self):
        # Use class-level compiled patterns
        self._skip_regex = self._get_skip_regex()

    def should_translate(self, text: str, output_language: str = "en") -> bool:
        """
        Determine if paragraph should be translated.
        Similar to CellTranslator but may have different rules.

        Skip conditions:
        - Empty or whitespace only
        - Numbers only (with formatting characters)
        - URLs
        - Email addresses
        - For JP→EN (output_language="en"): Skip text without Japanese characters
        - For EN→JP (output_language="jp"): Skip text that is Japanese-only

        Args:
            text: Text to check
            output_language: "en" for JP→EN, "jp" for EN→JP
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # Check against skip patterns first (fast rejection)
        for regex in self._skip_regex:
            if regex.match(text):
                return False

        # Language-based filtering depends on translation direction
        if output_language == "en":
            # JP→EN: Skip text without Japanese characters
            if not self._contains_japanese(text):
                return False
        else:
            # EN→JP: Skip text that is Japanese-only
            if self._is_japanese_only(text):
                return False

        return True

    def _contains_japanese(self, text: str) -> bool:
        """
        Check if text contains Japanese characters or Japanese document symbols.

        Includes:
        - Hiragana (U+3040-U+309F)
        - Katakana (U+30A0-U+30FF)
        - CJK Kanji (U+4E00-U+9FFF)
        - Japanese document symbols:
          - ▲ (U+25B2): Black up-pointing triangle (negative number marker)
          - △ (U+25B3): White up-pointing triangle
          - 〇 (U+3007): Ideographic number zero
          - ※ (U+203B): Reference mark
        """
        for char in text:
            code = ord(char)
            if (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF or  # Katakana
                0x4E00 <= code <= 0x9FFF or  # CJK Kanji
                code == 0x25B2 or            # ▲ (negative marker)
                code == 0x25B3 or            # △
                code == 0x3007 or            # 〇 (ideographic zero)
                code == 0x203B):             # ※ (reference mark)
                return True
        return False

    def _is_japanese_only(self, text: str) -> bool:
        """
        Check if text contains Japanese-specific characters (hiragana/katakana).

        Used for X→JP translation to skip already-Japanese text.
        Returns True if text has hiragana/katakana but no alphabetic characters.

        IMPORTANT: CJK Kanji alone does NOT count as "Japanese-only" because
        Chinese text also uses the same kanji range (U+4E00-U+9FFF).
        Only hiragana/katakana are unique to Japanese.
        """
        has_kana = False
        has_alphabetic = False

        for char in text:
            code = ord(char)
            # Check for Japanese-specific characters (hiragana/katakana only)
            # CJK Kanji is excluded because it's shared with Chinese
            if (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF):   # Katakana
                has_kana = True
            # Check for alphabetic characters (A-Z, a-z)
            elif (0x0041 <= code <= 0x005A or  # A-Z
                  0x0061 <= code <= 0x007A):   # a-z
                has_alphabetic = True

            # Early exit if we found both
            if has_kana and has_alphabetic:
                return False

        # Japanese-only if has kana but no alphabetic
        return has_kana and not has_alphabetic

    def extract_paragraph_text(self, paragraph) -> str:
        """
        Extract full text from paragraph.

        Safely handles different paragraph types:
        - python-docx Paragraph objects
        - python-pptx paragraph objects
        - XML Element objects (falls back to itertext)
        """
        # First try the standard .text attribute
        if hasattr(paragraph, 'text'):
            return paragraph.text

        # For XML Elements, use itertext() to get all text content
        if hasattr(paragraph, 'itertext'):
            return ''.join(paragraph.itertext())

        # Last resort: try string conversion
        return str(paragraph) if paragraph else ""

    def apply_translation_to_paragraph(self, paragraph, translated_text: str) -> None:
        """
        Apply translation while preserving paragraph style.

        Strategy:
        1. Clear all runs except the first
        2. Set translated text to first run
        3. Paragraph style (Heading 1, Body, etc.) is preserved
        4. First run's basic formatting is preserved
        """
        if hasattr(paragraph, 'runs') and paragraph.runs:
            # Keep first run's formatting, clear others
            paragraph.runs[0].text = translated_text
            for run in paragraph.runs[1:]:
                run.text = ""
        elif hasattr(paragraph, 'add_run'):
            # No runs - add text via a new run (paragraph.text is read-only in docx/pptx)
            paragraph.add_run().text = translated_text
