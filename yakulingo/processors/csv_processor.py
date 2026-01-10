# yakulingo/processors/csv_processor.py
"""
Processor for CSV files (.csv).
"""

from __future__ import annotations

import codecs
import csv
import io
import logging
from pathlib import Path
from typing import Any, Iterator, Optional

from yakulingo.models.types import TextBlock, FileInfo, FileType
from yakulingo.processors.base import FileProcessor
from yakulingo.processors.translators import CellTranslator

logger = logging.getLogger(__name__)

_SNIFF_SAMPLE_SIZE = 8192
_SNIFF_DELIMITERS = [",", ";", "\t", "|"]


def _detect_newline(raw: bytes) -> str:
    if b"\r\n" in raw:
        return "\r\n"
    if b"\n" in raw:
        return "\n"
    if b"\r" in raw:
        return "\r"
    return "\n"


def _decode_csv_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for encoding in ("utf-8", "cp932"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    logger.warning(
        "CSV decode fallback used; output may contain replacement characters"
    )
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _sniff_dialect(text: str) -> csv.Dialect:
    if not text:
        return csv.excel
    sample = text[:_SNIFF_SAMPLE_SIZE]
    sniffer = csv.Sniffer()
    try:
        return sniffer.sniff(sample, delimiters=_SNIFF_DELIMITERS)
    except csv.Error:
        if (
            "\t" in sample
            and "," not in sample
            and ";" not in sample
            and "|" not in sample
        ):
            return csv.excel_tab
        return csv.excel


class CsvProcessor(FileProcessor):
    """
    Processor for CSV files (.csv).
    """

    def __init__(self) -> None:
        self._cell_translator = CellTranslator()

    @property
    def file_type(self) -> FileType:
        return FileType.EXCEL

    @property
    def supported_extensions(self) -> list[str]:
        return [".csv"]

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file metadata for UI display."""
        return FileInfo(
            path=file_path,
            file_type=FileType.EXCEL,
            size_bytes=file_path.stat().st_size,
            sheet_count=1,
        )

    def extract_text_blocks(
        self,
        file_path: Path,
        output_language: str = "en",
        selected_sections: Optional[list[int]] = None,
    ) -> Iterator[TextBlock]:
        """
        Extract text blocks from CSV cells.
        """
        rows, _dialect, _encoding, _newline = self._load_csv(file_path)
        for row_idx, row in enumerate(rows):
            for col_idx, cell in enumerate(row):
                if self._cell_translator.should_translate(
                    cell, output_language=output_language
                ):
                    yield TextBlock(
                        id=self._block_id(row_idx, col_idx),
                        text=cell,
                        location=f"Row {row_idx + 1}, Col {col_idx + 1}",
                        metadata={
                            "row_idx": row_idx,
                            "col_idx": col_idx,
                        },
                    )

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
        selected_sections: Optional[list[int]] = None,
        text_blocks=None,
    ) -> Optional[dict[str, Any]]:
        """
        Apply translations to CSV file.
        """
        rows, dialect, encoding, newline = self._load_csv(input_path)

        for row_idx, row in enumerate(rows):
            for col_idx, _cell in enumerate(row):
                block_id = self._block_id(row_idx, col_idx)
                if block_id in translations:
                    row[col_idx] = translations[block_id]

        line_terminator = newline or "\n"
        with output_path.open("w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle, dialect=dialect, lineterminator=line_terminator)
            writer.writerows(rows)

        logger.info("CSV translation applied: %s -> %s", input_path, output_path)
        return None

    @staticmethod
    def _block_id(row_idx: int, col_idx: int) -> str:
        return f"r{row_idx}_c{col_idx}"

    def _load_csv(
        self, file_path: Path
    ) -> tuple[list[list[str]], csv.Dialect, str, str]:
        raw = file_path.read_bytes()
        newline = _detect_newline(raw)
        text, encoding = _decode_csv_bytes(raw)
        dialect = _sniff_dialect(text)
        rows = list(csv.reader(io.StringIO(text), dialect=dialect))
        return rows, dialect, encoding, newline
