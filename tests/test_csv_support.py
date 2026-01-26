from __future__ import annotations

import csv
import io
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.processors.csv_processor import CsvProcessor
from yakulingo.services.translation_service import TranslationService


def test_translation_service_supports_csv() -> None:
    service = TranslationService(config=AppSettings())
    assert service.is_supported_file(Path("sample.csv")) is True
    assert ".csv" in service.get_supported_extensions()


def test_csv_processor_preserves_dialect(tmp_path: Path) -> None:
    content = 'col1;col2;col3\r\napple;"http://example.com?a=b;c=d";note\r\n'
    input_path = tmp_path / "sample.csv"
    input_path.write_bytes(content.encode("utf-8"))

    processor = CsvProcessor()
    blocks = list(processor.extract_text_blocks(input_path, output_language="jp"))
    translations = {block.id: f"{block.text}-x" for block in blocks}

    output_path = tmp_path / "sample_translated.csv"
    processor.apply_translations(input_path, output_path, translations)

    output_bytes = output_path.read_bytes()
    assert b"\r\n" in output_bytes

    output_text = output_bytes.decode("utf-8")
    dialect = csv.Sniffer().sniff(output_text, delimiters=[",", ";", "\t", "|"])
    assert dialect.delimiter == ";"
    assert '"http://example.com?a=b;c=d"' in output_text

    rows = list(csv.reader(io.StringIO(output_text), dialect=dialect))
    assert rows[1][0].endswith("-x")
    assert rows[1][1] == "http://example.com?a=b;c=d"
    assert rows[1][2].endswith("-x")
