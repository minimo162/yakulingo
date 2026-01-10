from __future__ import annotations

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
