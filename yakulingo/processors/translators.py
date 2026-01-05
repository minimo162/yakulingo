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
        # 数値と記号の組み合わせ（▲△▼▽●○■□〇※など）
        # 例: "35,555", "△1,731,269", "35,555 1,731,269 △1,731,269"
        # (?=.*\d) で少なくとも1つの数字を含むことを要求
        r'^(?=.*\d)[\d\s\.,\-\+\(\)\/\%▲△▼▽●○■□〇※]+$',
        r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$',    # 日付 (YYYY-MM-DD)
        r'^\d{1,2}[-/]\d{1,2}[-/]\d{4}$',    # 日付 (DD/MM/YYYY)
        r'^[\w\.\-]+@[\w\.\-]+\.\w+$',        # メールアドレス
        r'^https?://\S+$',                    # URL
        r'^[A-Z]{2,5}[-_]?\d+$',              # コード (ABC-123)
        r'^[\d\s%]+$',                        # パーセント付き数値
        '^[\u00A5\uFFE5\u0024\uFF04\u20AC\u00A3\uFFE1]\\s*[\\d,\\.]+$',  # 通貨記号付き数値（半角/全角）
        r'^\d+[月日時分秒]$',                   # 日本語日時（完全マッチのみ）
    ]

    # Class-level compiled regex patterns (shared across all instances)
    _compiled_skip_regex = None

    # Pre-compiled regex for Japanese detection (much faster than char-by-char loop)
    # Includes:
    # - Hiragana (U+3040-U+309F): あ-ん, including voiced marks (U+3099-U+309C)
    # - Katakana (U+30A0-U+30FF): ア-ン, including ・(U+30FB) and ー(U+30FC)
    # - Half-width Katakana (U+FF65-U+FF9F): ｱ-ﾝ, including ･(U+FF65) and ｰ(U+FF70)
    # - CJK Kanji (U+4E00-U+9FFF): 漢字
    # - Japanese document symbols: ▲(U+25B2), △(U+25B3), 〇(U+3007), ※(U+203B)
    _japanese_pattern = re.compile(
        r'[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F\u4E00-\u9FFF\u25B2\u25B3\u3007\u203B]'
    )

    # Pre-compiled regex for CID notation detection
    # CID notation (e.g., "(cid:12345)") is used by pdfminer when font encoding
    # cannot be resolved. This typically indicates Japanese PDF content with
    # embedded fonts that don't have Unicode mappings.
    _cid_pattern = re.compile(r'\(cid:\d+\)')

    # Pre-compiled regex for kana detection (hiragana/katakana only, excludes kanji)
    # Includes both full-width and half-width forms
    _kana_pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F]')

    # Pre-compiled regex for alphabetic detection (A-Z, a-z)
    _alphabetic_pattern = re.compile(r'[A-Za-z]')

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
        - CID notation (cid:xxxxx): Indicates Japanese PDF content with embedded fonts

        Uses pre-compiled regex for better performance than char-by-char loop.
        """
        # Check for standard Japanese characters
        if self._japanese_pattern.search(text):
            return True

        # Check for CID notation (indicates Japanese PDF content)
        # CID notation appears when pdfminer cannot resolve font encoding,
        # which typically happens with Japanese PDFs using embedded fonts
        if self._cid_pattern.search(text):
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

        Uses pre-compiled regex for better performance than char-by-char loop.
        """
        has_kana = bool(self._kana_pattern.search(text))
        if not has_kana:
            return False

        has_alphabetic = bool(self._alphabetic_pattern.search(text))
        return not has_alphabetic


class ParagraphTranslator:
    """
    Paragraph translation logic for Word/PowerPoint body text.
    Preserves paragraph-level styles, but not individual run formatting.
    """

    # 翻訳スキップパターン（段落用）
    SKIP_PATTERNS = [
        # 数値と記号の組み合わせ（▲△▼▽●○■□〇※など）
        # 例: "35,555", "△1,731,269", "35,555 1,731,269 △1,731,269"
        # (?=.*\d) で少なくとも1つの数字を含むことを要求
        r'^(?=.*\d)[\d\s\.,\-\+\(\)\/\%▲△▼▽●○■□〇※]+$',
        r'^https?://\S+$',                    # URL
        r'^[\w\.\-]+@[\w\.\-]+\.\w+$',        # メールアドレス
    ]

    # Class-level compiled regex patterns (shared across all instances)
    _compiled_skip_regex = None

    # Pre-compiled regex for Japanese detection (much faster than char-by-char loop)
    # Includes:
    # - Hiragana (U+3040-U+309F): あ-ん, including voiced marks (U+3099-U+309C)
    # - Katakana (U+30A0-U+30FF): ア-ン, including ・(U+30FB) and ー(U+30FC)
    # - Half-width Katakana (U+FF65-U+FF9F): ｱ-ﾝ, including ･(U+FF65) and ｰ(U+FF70)
    # - CJK Kanji (U+4E00-U+9FFF): 漢字
    # - Japanese document symbols: ▲(U+25B2), △(U+25B3), 〇(U+3007), ※(U+203B)
    _japanese_pattern = re.compile(
        r'[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F\u4E00-\u9FFF\u25B2\u25B3\u3007\u203B]'
    )

    # Pre-compiled regex for CID notation detection
    # CID notation (e.g., "(cid:12345)") is used by pdfminer when font encoding
    # cannot be resolved. This typically indicates Japanese PDF content with
    # embedded fonts that don't have Unicode mappings.
    _cid_pattern = re.compile(r'\(cid:\d+\)')

    # Pre-compiled regex for kana detection (hiragana/katakana only, excludes kanji)
    # Includes both full-width and half-width forms
    _kana_pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F]')

    # Pre-compiled regex for alphabetic detection (A-Z, a-z)
    _alphabetic_pattern = re.compile(r'[A-Za-z]')

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
        - CID notation (cid:xxxxx): Indicates Japanese PDF content with embedded fonts

        Uses pre-compiled regex for better performance than char-by-char loop.
        """
        # Check for standard Japanese characters
        if self._japanese_pattern.search(text):
            return True

        # Check for CID notation (indicates Japanese PDF content)
        # CID notation appears when pdfminer cannot resolve font encoding,
        # which typically happens with Japanese PDFs using embedded fonts
        if self._cid_pattern.search(text):
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

        Uses pre-compiled regex for better performance than char-by-char loop.
        """
        has_kana = bool(self._kana_pattern.search(text))
        if not has_kana:
            return False

        has_alphabetic = bool(self._alphabetic_pattern.search(text))
        return not has_alphabetic

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
