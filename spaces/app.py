from __future__ import annotations

import os
import re

import gradio as gr

_RE_JP_KANA = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F]")
_RE_HANGUL = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")
_RE_LATIN_ALPHA = re.compile(r"[A-Za-z]")


def _detect_direction(text: str) -> tuple[str, str]:
    """Return (output_language, label)."""
    if _RE_JP_KANA.search(text):
        return "en", "日本語 → 英語"
    if _RE_HANGUL.search(text):
        return "en", "（韓国語検出）→ 英語"
    if _RE_LATIN_ALPHA.search(text):
        return "ja", "英語 → 日本語"
    return "en", "（既定）日本語 → 英語"


def _translate_stub(text: str) -> tuple[str, str]:
    text = (text or "").strip()
    if not text:
        return "", ""
    _, label = _detect_direction(text)
    return f"（デモ準備中: {label}）\n\n{text}", label


with gr.Blocks(title="YakuLingo (訳リンゴ) – HF Spaces Demo") as demo:
    gr.Markdown("# YakuLingo (訳リンゴ) – Hugging Face Spaces デモ")
    gr.Markdown(
        "※ これは Spaces 用のデモUI骨格です。翻訳バックエンドは後続タスクで実装します。"
    )

    with gr.Row():
        input_text = gr.Textbox(
            label="入力テキスト",
            lines=10,
            placeholder="日本語または英語を入力してください",
        )
        output_text = gr.Textbox(label="出力", lines=10)

    direction = gr.Textbox(label="判定（暫定）", interactive=False)

    with gr.Row():
        translate_btn = gr.Button("翻訳（スタブ）", variant="primary")
        clear_btn = gr.Button("クリア")

    translate_btn.click(
        _translate_stub, inputs=[input_text], outputs=[output_text, direction]
    )
    clear_btn.click(lambda: ("", "", ""), outputs=[input_text, output_text, direction])

    gr.Examples(
        examples=[
            ["お世話になっております。こちらの資料をご確認ください。"],
            ["This is a demo. Please translate this sentence into Japanese."],
        ],
        inputs=[input_text],
    )


def _server_port() -> int:
    try:
        return int(os.environ.get("PORT", "7860"))
    except ValueError:
        return 7860


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=_server_port())
