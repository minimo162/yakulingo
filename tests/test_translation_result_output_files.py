from __future__ import annotations

from pathlib import Path

from yakulingo.models.types import TranslationResult, TranslationStatus


def test_translation_result_output_files_orders_primary_extra_bilingual(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "out.xlsx"
    extra_a = tmp_path / "out_standard.xlsx"
    extra_b = tmp_path / "out_minimal.xlsx"
    bilingual_path = tmp_path / "out_bilingual.xlsx"

    for path in (output_path, extra_a, extra_b, bilingual_path):
        path.write_text("x", encoding="utf-8")

    result = TranslationResult(
        status=TranslationStatus.COMPLETED,
        output_path=output_path,
        bilingual_path=bilingual_path,
        extra_output_files=[
            (extra_a, "翻訳ファイル（標準）"),
            (extra_b, "翻訳ファイル（最簡潔）"),
        ],
    )

    assert result.output_files == [
        (output_path, "翻訳ファイル"),
        (extra_a, "翻訳ファイル（標準）"),
        (extra_b, "翻訳ファイル（最簡潔）"),
        (bilingual_path, "対訳ファイル"),
    ]


def test_translation_result_output_files_skips_missing_and_deduplicates(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "out.xlsx"
    extra = tmp_path / "out_concise.xlsx"
    missing = tmp_path / "missing.xlsx"

    output_path.write_text("x", encoding="utf-8")
    extra.write_text("x", encoding="utf-8")

    result = TranslationResult(
        status=TranslationStatus.COMPLETED,
        output_path=output_path,
        extra_output_files=[
            (output_path, "DUPLICATE"),
            (missing, "MISSING"),
            (extra, "翻訳ファイル（簡潔）"),
        ],
    )

    assert result.output_files == [
        (output_path, "翻訳ファイル"),
        (extra, "翻訳ファイル（簡潔）"),
    ]
