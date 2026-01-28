from yakulingo.services.local_ai_client import strip_prompt_echo


def test_strip_prompt_echo_removes_full_prompt() -> None:
    prompt = (
        "You are a professional Japanese (ja) to English (en) translator.\n"
        "Produce only the English translation.\n\n"
        "こんにちは"
    )
    assert strip_prompt_echo(prompt, prompt) == ""


def test_strip_prompt_echo_removes_prompt_prefix() -> None:
    prompt = (
        "You are a professional Japanese (ja) to English (en) translator.\n"
        "Produce only the English translation.\n\n"
        "こんにちは"
    )
    raw = f"{prompt}\n\nHello."
    assert strip_prompt_echo(raw, prompt) == "Hello."
