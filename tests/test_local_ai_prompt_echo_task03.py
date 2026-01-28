from yakulingo.services.local_ai_client import strip_prompt_echo


_SIMPLE_PROMPT_GLOSSARY = """
Important Terminology:
- 1,000億円: 1,000 oku yen
- ▲1,000億円: (1,000) oku yen 
"""


def _make_prompt(text: str) -> str:
    return (
        f"<bos><start_of_turn>user\n"
        f"Instruction: Please translate this into natural English suitable for financial statements. No other responses are necessary.\n"
        f"{_SIMPLE_PROMPT_GLOSSARY}\n"
        f"Source: Japanese\n"
        f"Target: English\n"
        f"Text: {text}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


def test_strip_prompt_echo_removes_full_prompt() -> None:
    prompt = _make_prompt("こんにちは")
    assert strip_prompt_echo(prompt, prompt) == ""


def test_strip_prompt_echo_removes_prompt_prefix() -> None:
    prompt = _make_prompt("こんにちは")
    raw = f"{prompt}\n\nHello."
    assert strip_prompt_echo(raw, prompt) == "Hello."
