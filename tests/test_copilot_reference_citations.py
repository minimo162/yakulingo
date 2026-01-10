from pathlib import Path

from yakulingo.services.copilot_handler import _strip_reference_citations


def test_strip_reference_citations_removes_suffix_and_standalone_lines() -> None:
    text = (
        "Fin Planning, IRglossary\n\n"
        "Fundingglossary\n\n"
        "Accountingglossary\n\n"
        "Fin Controlglossary\n\n"
        "Domestic DLR Finance\n"
        "glossary\n"
    )
    cleaned = _strip_reference_citations(text, [Path("glossary.csv")])
    assert cleaned == (
        "Fin Planning, IR\n\n"
        "Funding\n\n"
        "Accounting\n\n"
        "Fin Control\n\n"
        "Domestic DLR Finance"
    )


def test_strip_reference_citations_keeps_original_when_only_label() -> None:
    assert _strip_reference_citations("glossary", [Path("glossary.csv")]) == "glossary"


def test_strip_reference_citations_handles_filename_with_extension() -> None:
    assert (
        _strip_reference_citations("添付glossary.csv\n", [Path("glossary.csv")])
        == "添付"
    )
