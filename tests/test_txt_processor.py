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


class TestTxtProcessorApplyTranslations:
    def test_preserves_missing_chunk_translations(self, tmp_path, monkeypatch):
        processor = TxtProcessor()
        monkeypatch.setattr("yakulingo.processors.txt_processor.MAX_CHARS_PER_BLOCK", 10)

        original_path = tmp_path / "original.txt"
        output_path = tmp_path / "translated.txt"

        # Single paragraph split into 3 chunks (10, 10, 5 characters)
        paragraph = "A" * 25
        original_path.write_text(paragraph, encoding="utf-8")

        translations = {
            "para_0_chunk_0": "T0",
            # Missing translation for chunk_1 on purpose
            "para_0_chunk_2": "T2",
        }

        processor.apply_translations(original_path, output_path, translations)

        content = output_path.read_text(encoding="utf-8")

        # Expect translated -> original (missing chunk) -> translated order
        assert content == "T0" + ("A" * 10) + "T2"
