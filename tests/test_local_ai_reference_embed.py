from __future__ import annotations

import pytest
from pathlib import Path

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


def test_local_reference_embed_filters_bundled_glossary(tmp_path: Path) -> None:
    builder = _make_builder()
    glossary_path = tmp_path / "glossary.csv"
    glossary_path.write_text("営業利益,Operating Profit\n売上高,Revenue\n", encoding="utf-8")
    embedded = builder.build_reference_embed([glossary_path], input_text="営業利益が増加")
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
    embedded = builder.build_reference_embed([path_a, path_b, path_c], input_text="sample")
    assert embedded.truncated is True
    assert any("合計上限 4000 文字" in w for w in embedded.warnings)


def test_local_followup_reference_embed_pending() -> None:
    pytest.xfail("TODO: local follow-up/back-translate should embed references")
