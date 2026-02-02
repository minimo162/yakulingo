from pathlib import Path


def test_spaces_app_ui_strings_match_intent() -> None:
    app_path = Path(__file__).resolve().parents[1] / "spaces" / "app.py"
    text = app_path.read_text(encoding="utf-8")

    assert 'title="YakuLingo"' in text
    assert 'gr.Markdown("# YakuLingo"' in text

    assert "Hugging Face Spaces（ZeroGPU）対応" not in text
    assert "YakuLingo (訳リンゴ)" not in text

    assert "label=\"入力テキスト\"" not in text
    assert "label=\"翻訳結果\"" not in text
    assert "show_label=False" in text


def test_spaces_app_result_source_field_removed() -> None:
    app_path = Path(__file__).resolve().parents[1] / "spaces" / "app.py"
    text = app_path.read_text(encoding="utf-8")

    assert 'label="原文"' not in text
    assert "source_text" not in text
