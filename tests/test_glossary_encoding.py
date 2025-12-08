from pathlib import Path


GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "glossary.csv"


def test_glossary_is_utf8_without_replacement_characters():
    raw_bytes = GLOSSARY_PATH.read_bytes()

    text = raw_bytes.decode("utf-8")

    assert "\ufffd" not in text, "Found Unicode replacement characters, possible mojibake"
