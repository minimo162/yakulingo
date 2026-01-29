from __future__ import annotations

from yakulingo.services.translation_service import _fix_to_en_oku_numeric_unit_if_possible


def test_to_en_converts_cho_oku_to_trillion_billion_correctly() -> None:
    source_text = (
        "[経営成績]\n"
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円(前年同期比1,554億円減、6.5％減)、営業損失は\n"
        "539億円(前年同期は1,030億円の利益)、経常損失は213億円(前年同期は835億円の利益)となりました。親会社株主に\n"
        "帰属する中間純損失は、特別退職費用やクレジット資産評価損の計上等により、453億円(前年同期は353億円の利益)\n"
        "となりました。"
    )
    translated_text = (
        "Consolidated results for the interim period: Net sales were 2.2385 trillion yen "
        "(down by 1,554 billion yen, down 6.5% YoY), operating loss was 539 billion yen "
        "(profit of 1,030 billion yen in the same period last year), ordinary loss was 213 billion yen "
        "(profit of 835 billion yen in the same period last year). Net loss attributable to owners of parent "
        "was 453 billion yen (profit of 353 billion yen in the same period last year)."
    )

    fixed_text, changed = _fix_to_en_oku_numeric_unit_if_possible(
        source_text=source_text,
        translated_text=translated_text,
    )

    assert changed is True
    assert "¥2,238.5 billion" in fixed_text
    for expected in (
        "¥155.4 billion",
        "¥53.9 billion",
        "¥103.0 billion",
        "¥21.3 billion",
        "¥83.5 billion",
        "¥45.3 billion",
        "¥35.3 billion",
    ):
        assert expected in fixed_text
    for forbidden in (
        "1,554 billion",
        "539 billion",
        "1,030 billion",
        "213 billion",
        "835 billion",
        "453 billion",
        "353 billion",
    ):
        assert forbidden not in fixed_text


def test_to_en_fixes_cho_oku_when_model_treats_cho_as_1000_oku() -> None:
    source_text = (
        "[資産、負債及び純資産]\n"
        "当中間連結会計期間末の総資産は、前連結会計年度末より622億円減少の4兆279億円となり、負債合計は、前連結\n"
        "会計年度末より108億円減少の2兆2,693億円となりました。\n"
        "純資産は、親会社株主に帰属する中間純損失453億円等により、前連結会計年度末より514億円減少の1兆7,586億円\n"
        "となりました。自己資本比率は、前連結会計年度末より0.6ポイント減少の43.2％(劣後特約付ローンの資本性考慮後\n"
        "44.1％)となりました。"
    )
    translated_text = (
        "[Assets, liabilities and net assets]\n"
        "Total assets were 4,279 billion yen (down 622 billion yen), and total liabilities were "
        "2.2693 trillion yen (down 108 billion yen). Net assets were 1.7586 trillion yen "
        "(down 514 billion yen) due in part to a net loss of 453 billion yen attributable to owners of parent. "
        "The equity ratio was 43.2% (44.1% after considering the equity nature of subordinated loans)."
    )

    fixed_text, changed = _fix_to_en_oku_numeric_unit_if_possible(
        source_text=source_text,
        translated_text=translated_text,
    )

    assert changed is True
    assert "¥4,027.9 billion" in fixed_text
    for expected in (
        "¥62.2 billion",
        "¥10.8 billion",
        "¥2,269.3 billion",
        "¥1,758.6 billion",
        "¥51.4 billion",
        "¥45.3 billion",
    ):
        assert expected in fixed_text
    for forbidden in (
        "4,279 billion",
        "622 billion",
        "108 billion",
        "514 billion",
        "453 billion",
    ):
        assert forbidden not in fixed_text


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
    translated_text = (
        "[Cash Flow]\n"
        "Cash and cash equivalents decreased by 523 billion yen, reaching 1.533 billion yen. "
        "Interest-bearing liabilities increased by 969 billion yen to 8,021 billion yen. "
        "As a result, the net cash position was 2,512 billion yen. "
        "Cash flow from operating activities decreased by 1,979 billion yen "
        "(an increase of 507 billion yen in the same period last year), "
        "primarily due to a net loss before taxes, etc. of 436 billion yen."
    )

    fixed_text, changed = _fix_to_en_oku_numeric_unit_if_possible(
        source_text=source_text,
        translated_text=translated_text,
    )

    assert changed is True
    assert "¥1,053.3 billion" in fixed_text
    for expected in (
        "¥52.3 billion",
        "¥96.9 billion",
        "¥802.1 billion",
        "¥251.2 billion",
        "¥43.6 billion",
        "¥197.9 billion",
        "¥50.7 billion",
    ):
        assert expected in fixed_text
    for forbidden in (
        "523 billion",
        "1.533 billion",
        "969 billion",
        "8,021 billion",
        "2,512 billion",
        "436 billion",
        "1,979 billion",
        "507 billion",
    ):
        assert forbidden not in fixed_text
