from __future__ import annotations

from yakulingo.services.prompt_builder import PromptBuilder


def test_to_en_converts_cho_oku_to_trillion_billion_correctly() -> None:
    source_text = (
        "[経営成績]\n"
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円(前年同期比1,554億円減、6.5％減)、営業損失は\n"
        "539億円(前年同期は1,030億円の利益)、経常損失は213億円(前年同期は835億円の利益)となりました。親会社株主に\n"
        "帰属する中間純損失は、特別退職費用やクレジット資産評価損の計上等により、453億円(前年同期は353億円の利益)\n"
        "となりました。"
    )

    normalized = PromptBuilder.normalize_input_text(source_text, output_language="en")
    assert "¥2,238.5 billion" in normalized
    for expected in (
        "¥155.4 billion",
        "¥53.9 billion",
        "¥103.0 billion",
        "¥21.3 billion",
        "¥83.5 billion",
        "¥45.3 billion",
        "¥35.3 billion",
    ):
        assert expected in normalized


def test_to_en_fixes_cho_oku_when_model_treats_cho_as_1000_oku() -> None:
    source_text = (
        "[資産、負債及び純資産]\n"
        "当中間連結会計期間末の総資産は、前連結会計年度末より622億円減少の4兆279億円となり、負債合計は、前連結\n"
        "会計年度末より108億円減少の2兆2,693億円となりました。\n"
        "純資産は、親会社株主に帰属する中間純損失453億円等により、前連結会計年度末より514億円減少の1兆7,586億円\n"
        "となりました。自己資本比率は、前連結会計年度末より0.6ポイント減少の43.2％(劣後特約付ローンの資本性考慮後\n"
        "44.1％)となりました。"
    )

    normalized = PromptBuilder.normalize_input_text(source_text, output_language="en")
    assert "¥4,027.9 billion" in normalized
    for expected in (
        "¥62.2 billion",
        "¥10.8 billion",
        "¥2,269.3 billion",
        "¥1,758.6 billion",
        "¥51.4 billion",
        "¥45.3 billion",
    ):
        assert expected in normalized


def test_to_en_fixes_cho_oku_when_model_outputs_concatenated_decimal_billion() -> None:
    source_text = (
        "[キャッシュ・フロー]\n"
        "当中間連結会計期間末において、現金及び現金同等物は、前連結会計年度末より523億円減少の1兆533億円となり、\n"
        "有利子負債は969億円増加の8,021億円となりました。この結果、2,512億円のネット・キャッシュ・ポジションとな\n"
        "りました。\n"
        "当中間連結会計期間における各キャッシュ・フローの状況は次のとおりです。\n"
        "営業活動によるキャッシュ・フロー\n"
        "営業活動によるキャッシュ・フローは、税金等調整前中間純損失436億円に加え、棚卸資産の増加等により、\n"
        "1,979億円の減少(前年同期は507億円の増加)となりました。"
    )

    normalized = PromptBuilder.normalize_input_text(source_text, output_language="en")
    assert "¥1,053.3 billion" in normalized
    for expected in (
        "¥52.3 billion",
        "¥96.9 billion",
        "¥802.1 billion",
        "¥251.2 billion",
        "¥43.6 billion",
        "¥197.9 billion",
        "¥50.7 billion",
    ):
        assert expected in normalized
