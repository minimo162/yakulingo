"""
CSV file processor for comma-separated value (.csv) files.

Translates cell contents while preserving CSV structure.
Supports UTF-8, Shift_JIS, and CP932 encoding auto-detection.
"""

import csv
import logging
from pathlib import Path
from typing import Any, Iterator, Optional

from yakulingo.models.types import FileInfo, FileType, TextBlock
from yakulingo.processors.base import FileProcessor

logger = logging.getLogger(__name__)

_ENCODINGS = ["utf-8-sig", "utf-8", "cp932", "shift_jis", "latin-1"]


def _detect_encoding(file_path: Path) -> str:
    """Try multiple encodings and return the first that works."""
    raw = file_path.read_bytes()
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


class CsvProcessor(FileProcessor):
    """Processor for CSV files (.csv)."""

    @property
    def file_type(self) -> FileType:
        return FileType.CSV

    @property
    def supported_extensions(self) -> list[str]:
        return [".csv"]

    def get_file_info(self, file_path: Path) -> FileInfo:
        enc = _detect_encoding(file_path)
        with file_path.open(encoding=enc, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        return FileInfo(
            path=file_path,
            file_type=FileType.CSV,
            size_bytes=file_path.stat().st_size,
            page_count=len(rows),
            section_details=[],
        )

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        enc = _detect_encoding(file_path)
        with file_path.open(encoding=enc, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            return

        for row_idx, row in enumerate(rows):
            if row_idx == 0:
                continue
            for col_idx, cell in enumerate(row):
                if self.should_translate(cell):
                    yield TextBlock(
                        id=f"row_{row_idx}_col_{col_idx}",
                        text=cell,
                        location=f"行 {row_idx + 1}, 列 {col_idx + 1}",
                        metadata={"row": row_idx, "col": col_idx},
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
        enc = _detect_encoding(input_path)
        with input_path.open(encoding=enc, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        for row_idx, row in enumerate(rows):
            for col_idx in range(len(row)):
                block_id = f"row_{row_idx}_col_{col_idx}"
                if block_id in translations:
                    row[col_idx] = translations[block_id]

        with output_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        logger.info("CSV translation applied: %s -> %s", input_path, output_path)
        return None
