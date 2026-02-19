from yakulingo.services.local_ai_client import strip_prompt_echo


def _make_prompt(text: str) -> str:
    return (
        f"<bos><start_of_turn>user\n"
        f"Instruction: Please translate this into natural English suitable for financial statements. No other responses are necessary.\n"
        f"Source: Japanese\n"
        f"Target: English\n"
        f"Text: {text}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


def test_strip_prompt_echo_removes_full_prompt() -> None:
    prompt = _make_prompt("source")
    assert strip_prompt_echo(prompt, prompt) == ""


def test_strip_prompt_echo_removes_prompt_prefix() -> None:
    prompt = _make_prompt("source")
    raw = f"{prompt}\n\nHello."
    assert strip_prompt_echo(raw, prompt) == "Hello."


def test_strip_prompt_echo_removes_leading_think_block() -> None:
    prompt = _make_prompt("source")
    raw = f"{prompt}<think>\ninternal reasoning\n</think>\n\nHello."
    assert strip_prompt_echo(raw, prompt) == "Hello."


def test_strip_prompt_echo_drops_unclosed_leading_think_block() -> None:
    raw = "<think>\ninternal reasoning only"
    assert strip_prompt_echo(raw, None) == ""


def test_strip_prompt_echo_can_keep_leading_think_block_for_streaming() -> None:
    raw = "<think>\ninternal reasoning only"
    assert (
        strip_prompt_echo(raw, None, strip_leading_thinking=False)
        == "<think>\ninternal reasoning only"
    )


def test_strip_prompt_echo_removes_leaked_critical_instruction_block() -> None:
    raw = (
        "CRITICAL:\n"
        "- English only; no Japanese/Chinese/Korean characters or Japanese punctuation.\n"
        "- Translation only (no labels/explanations); do not echo input.\n\n"
        "Revenue increased by 10% year over year."
    )
    assert strip_prompt_echo(raw, "unrelated prompt") == (
        "Revenue increased by 10% year over year."
    )


def test_strip_prompt_echo_removes_leaked_simple_instruction_line() -> None:
    raw = (
        "Translate Japanese to English for financial statements. Keep all content, "
        "line breaks, and numbers. English only. Translation only. Do not echo input.\n"
        "Operating income rose."
    )
    assert strip_prompt_echo(raw, "unrelated prompt") == "Operating income rose."


def test_strip_prompt_echo_keeps_normal_critical_sentence() -> None:
    raw = "Critical: The schedule is tight, but achievable."
    assert strip_prompt_echo(raw, "unrelated prompt") == raw
