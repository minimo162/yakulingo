# ecm_translate/processors/translators.py
"""
Unified translation logic for Excel/Word/PowerPoint.
CellTranslator: For table cells (Excel-compatible logic)
ParagraphTranslator: For body paragraphs
"""

import re
from typing import Optional


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

    def __init__(self):
        self._skip_regex = [re.compile(p) for p in self.SKIP_PATTERNS]

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
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # Very short text (likely labels)
        if len(text) < 2:
            return False

        # Check against skip patterns
        for regex in self._skip_regex:
            if regex.match(text):
                return False

        return True


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

    def __init__(self):
        self._skip_regex = [re.compile(p) for p in self.SKIP_PATTERNS]

    def should_translate(self, text: str) -> bool:
        """
        Determine if paragraph should be translated.
        Similar to CellTranslator but may have different rules.
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # Skip very short text (likely labels/numbers)
        if len(text) < 2:
            return False

        # Check against skip patterns
        for regex in self._skip_regex:
            if regex.match(text):
                return False

        return True

    def extract_paragraph_text(self, paragraph) -> str:
        """Extract full text from paragraph"""
        return paragraph.text

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
        else:
            paragraph.text = translated_text
