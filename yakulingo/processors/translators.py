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

    def should_translate(self, text: str) -> bool:
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
        - Single non-Japanese characters (e.g., "A", "1")
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # For single characters, only translate if it's Japanese
        # (e.g., "億", "円", "個" should be translated)
        if len(text) < 2:
            return self._contains_japanese(text)

        # Check against skip patterns
        for regex in self._skip_regex:
            if regex.match(text):
                return False

        return True

    def _contains_japanese(self, text: str) -> bool:
        """Check if text contains Japanese characters (hiragana, katakana, kanji)."""
        for char in text:
            code = ord(char)
            if (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF or  # Katakana
                0x4E00 <= code <= 0x9FFF):   # CJK Kanji
                return True
        return False


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

    def should_translate(self, text: str) -> bool:
        """
        Determine if paragraph should be translated.
        Similar to CellTranslator but may have different rules.

        Skip conditions:
        - Empty or whitespace only
        - Numbers only (with formatting characters)
        - URLs
        - Email addresses
        - Single non-Japanese characters (e.g., "A", "1")
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # For single characters, only translate if it's Japanese
        # (e.g., "億", "円", "個" should be translated)
        if len(text) < 2:
            return self._contains_japanese(text)

        # Check against skip patterns
        for regex in self._skip_regex:
            if regex.match(text):
                return False

        return True

    def _contains_japanese(self, text: str) -> bool:
        """Check if text contains Japanese characters (hiragana, katakana, kanji)."""
        for char in text:
            code = ord(char)
            if (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF or  # Katakana
                0x4E00 <= code <= 0x9FFF):   # CJK Kanji
                return True
        return False

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
