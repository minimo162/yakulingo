from yakulingo.processors.txt_processor import TxtProcessor


class TestTxtProcessorBilingualDocument:
    def test_handles_mismatched_paragraph_counts(self, tmp_path):
        original_path = tmp_path / "original.txt"
        translated_path = tmp_path / "translated.txt"
        output_path = tmp_path / "bilingual.txt"

        original_path.write_text("段落1\n\n段落2\n\n段落3", encoding="utf-8")
        translated_path.write_text("Paragraph 1\n\nParagraph 2", encoding="utf-8")

        processor = TxtProcessor()
        processor.create_bilingual_document(original_path, translated_path, output_path)

        content = output_path.read_text(encoding="utf-8")

        assert content.count("【原文】") == 3
        assert "段落3" in content
        assert "Paragraph 1" in content
        assert "Paragraph 2" in content
        assert "【訳文】\n" in content  # Includes placeholder for missing translation
