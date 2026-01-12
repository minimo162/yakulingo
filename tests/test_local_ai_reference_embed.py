from __future__ import annotations

from pathlib import Path

from unittest.mock import Mock, patch

from yakulingo.services.translation_service import TranslationService
from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import TranslationBackend

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _make_builder() -> LocalPromptBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=AppSettings(),
    )


def test_local_reference_embed_supports_binary_formats(tmp_path: Path) -> None:
    builder = _make_builder()
    cases: list[tuple[Path, str]] = []

    from docx import Document

    docx_path = tmp_path / "ref.docx"
    doc = Document()
    doc.add_paragraph("Docx content")
    doc.save(docx_path)
    cases.append((docx_path, "Docx content"))

    import openpyxl

    xlsx_path = tmp_path / "ref.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Xlsx content"
    wb.save(xlsx_path)
    wb.close()
    cases.append((xlsx_path, "Xlsx content"))

    from pptx import Presentation
    from pptx.util import Inches

    pptx_path = tmp_path / "ref.pptx"
    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    textbox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    textbox.text_frame.text = "Pptx content"
    pres.save(pptx_path)
    cases.append((pptx_path, "Pptx content"))

    import fitz

    pdf_path = tmp_path / "ref.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Pdf content")
    pdf.save(pdf_path)
    pdf.close()
    cases.append((pdf_path, "Pdf content"))

    for path, expected in cases:
        embedded = builder.build_reference_embed([path], input_text="sample")
        assert expected in embedded.text
        assert not any("未対応の参照ファイル" in w for w in embedded.warnings)


def test_local_prompt_includes_translation_rules_for_short_text() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single(
        "短文",
        style="concise",
        reference_files=None,
        detected_language="日本語",
    )
    expected_rules = builder._get_translation_rules("en").strip()
    assert expected_rules
    assert expected_rules in prompt


def test_local_prompt_includes_numeric_hints_for_oku() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single(
        "売上高は2兆2,385億円(前年同期比1,554億円減)となりました。",
        style="concise",
        reference_files=None,
        detected_language="日本語",
    )
    assert "数値変換ヒント" in prompt
    assert "2兆2,385億円 -> 22,385 oku yen" in prompt
    assert "1,554億円 -> 1,554 oku yen" in prompt


def test_local_reference_embed_filters_bundled_glossary(tmp_path: Path) -> None:
    builder = _make_builder()
    glossary_path = tmp_path / "glossary.csv"
    glossary_path.write_text(
        "営業利益,Operating Profit\n売上高,Revenue\n", encoding="utf-8"
    )
    embedded = builder.build_reference_embed(
        [glossary_path], input_text="営業利益が増加"
    )
    assert "営業利益,Operating Profit" in embedded.text
    assert "売上高,Revenue" not in embedded.text


def test_local_reference_embed_truncates_large_file(tmp_path: Path) -> None:
    builder = _make_builder()
    ref_path = tmp_path / "ref.txt"
    ref_path.write_text("A" * 2100, encoding="utf-8")
    embedded = builder.build_reference_embed([ref_path], input_text="sample")
    assert embedded.truncated is True
    assert any("上限 2000 文字" in w for w in embedded.warnings)


def test_local_reference_embed_truncates_total_limit(tmp_path: Path) -> None:
    builder = _make_builder()
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_c = tmp_path / "c.txt"
    path_a.write_text("A" * 2000, encoding="utf-8")
    path_b.write_text("B" * 2000, encoding="utf-8")
    path_c.write_text("C" * 10, encoding="utf-8")
    embedded = builder.build_reference_embed(
        [path_a, path_b, path_c], input_text="sample"
    )
    assert embedded.truncated is True
    assert any("合計上限 4000 文字" in w for w in embedded.warnings)


def test_local_reference_embed_uses_file_cache_for_text(tmp_path: Path) -> None:
    builder = _make_builder()
    ref_path = tmp_path / "ref.txt"
    ref_path.write_text("Reference content", encoding="utf-8")

    original_read_text = Path.read_text
    with patch.object(Path, "read_text", autospec=True) as mock_read:
        mock_read.side_effect = lambda self, *args, **kwargs: original_read_text(
            self, *args, **kwargs
        )
        first = builder.build_reference_embed([ref_path], input_text="alpha")
        second = builder.build_reference_embed([ref_path], input_text="beta")

    assert "Reference content" in first.text
    assert "Reference content" in second.text
    assert mock_read.call_count == 1


def test_local_followup_reference_embed_includes_local_reference(
    tmp_path: Path,
) -> None:
    settings = AppSettings()
    settings.translation_backend = "local"
    app = YakuLingoApp()
    app.translation_service = TranslationService(
        Mock(),
        settings,
        prompts_dir=Path(__file__).resolve().parents[1] / "prompts",
    )
    app.state.translation_backend = TranslationBackend.LOCAL

    ref_path = tmp_path / "ref.txt"
    ref_path.write_text("Reference content", encoding="utf-8")

    prompt = app._build_follow_up_prompt(
        "review",
        source_text="source",
        translation="translation",
        reference_files=[ref_path],
    )
    assert prompt is not None
    assert "[REFERENCE:file=ref.txt]" in prompt
    assert "Reference content" in prompt


def test_local_prompt_includes_json_guard_block() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single(
        "sample",
        style="concise",
        reference_files=None,
        detected_language="Japanese",
    )
    assert "JSON OUTPUT (MUST)" in prompt


def test_local_batch_embed_reference_even_when_flag_false(tmp_path: Path) -> None:
    builder = _make_builder()
    ref_path = tmp_path / "ref.txt"
    ref_path.write_text("Reference content", encoding="utf-8")
    prompt = builder.build_batch(
        ["sample"],
        has_reference_files=False,
        output_language="en",
        translation_style="concise",
        reference_files=[ref_path],
    )
    assert "[REFERENCE:file=ref.txt]" in prompt
