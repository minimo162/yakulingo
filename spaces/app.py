from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import gradio as gr

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spaces.translator import get_translator  # noqa: E402

_RE_JP_KANA = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F]")
_RE_HANGUL = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")
_RE_LATIN_ALPHA = re.compile(r"[A-Za-z]")

_DEFAULT_MAX_CHARS = 2000
_DEFAULT_MODEL_ID = "google/translategemma-27b-it"


def _detect_direction(text: str) -> tuple[str, str]:
    """Return (output_language, label)."""
    if _RE_JP_KANA.search(text):
        return "en", "日本語 → 英語"
    if _RE_HANGUL.search(text):
        return "en", "（韓国語検出）→ 英語"
    if _RE_LATIN_ALPHA.search(text):
        return "ja", "英語 → 日本語"
    return "en", "（既定）日本語 → 英語"


def _max_chars() -> int:
    try:
        return int(
            os.environ.get("YAKULINGO_SPACES_MAX_CHARS", str(_DEFAULT_MAX_CHARS))
        )
    except ValueError:
        return _DEFAULT_MAX_CHARS


def _model_id() -> str:
    return (os.environ.get("YAKULINGO_SPACES_MODEL_ID") or _DEFAULT_MODEL_ID).strip()


def _quant() -> str:
    return (os.environ.get("YAKULINGO_SPACES_QUANT") or "4bit").strip()


def _error_hint(message: str) -> str:
    lowered = message.lower()
    if "gpu が利用できません" in message:
        return "Space の Hardware を ZeroGPU に設定してください（またはデバッグ用途で `YAKULINGO_SPACES_ALLOW_CPU=1`）。"
    if "401" in lowered or "unauthorized" in lowered or "gated" in lowered:
        return "モデルが gated の可能性があります。Spaces の Secret に `HF_TOKEN` を設定してください。"
    if "bitsandbytes" in lowered:
        return "bitsandbytes の導入に失敗している可能性があります。依存関係（`requirements.txt`）を確認してください。"
    if "cuda" in lowered:
        return "CUDA 周りで失敗している可能性があります。ZeroGPU の割当と依存関係を確認してください。"
    return ""


def _translate(text: str) -> tuple[str, str, str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return "", "", ""

    output_language, label = _detect_direction(cleaned)
    if len(cleaned) > _max_chars():
        return (
            "",
            label,
            f"入力が長すぎます（{len(cleaned)}文字）。{_max_chars()}文字以内に短縮してください。",
        )

    translator = get_translator()
    start = time.monotonic()
    try:
        translated = translator.translate(cleaned, output_language=output_language)  # type: ignore[arg-type]
    except Exception as e:
        hint = _error_hint(str(e))
        detail = f"エラー: {e}"
        if hint:
            detail = f"{detail}\n\n**ヒント**: {hint}"
        status = (
            f"{label} / model=`{_model_id()}` / quant=`{_quant()}` / device={translator.runtime_device()}"
            f"\n\n{detail}"
        )
        return "", label, status

    elapsed_s = time.monotonic() - start
    status = f"{label} / model=`{_model_id()}` / quant=`{_quant()}` / device={translator.runtime_device()} / {elapsed_s:.2f}s"
    return translated, label, status


def _server_port() -> int:
    try:
        return int(os.environ.get("PORT", "7860"))
    except ValueError:
        return 7860


_JP_EXAMPLE = "お世話になっております。こちらの資料をご確認ください。"
_EN_EXAMPLE = "This is a demo. Please translate this sentence into Japanese."


with gr.Blocks(title="YakuLingo (訳リンゴ) – HF Spaces Demo") as demo:
    gr.Markdown("# YakuLingo (訳リンゴ) – Hugging Face Spaces デモ")
    gr.Markdown("日本語/英語を入力すると自動判定して翻訳します（ZeroGPU 想定）。")
    gr.Markdown(
        f"**Model**: `{_model_id()}`  \n"
        f"**Quant**: `{_quant()}`  \n"
        "（必要に応じて Spaces の Secret に `HF_TOKEN` を設定してください）"
    )

    input_text = gr.Textbox(
        label="入力テキスト",
        lines=10,
        placeholder="日本語または英語を入力してください",
    )

    with gr.Row():
        translate_btn = gr.Button("翻訳", variant="primary")
        clear_btn = gr.Button("クリア")
        ja_example_btn = gr.Button("日本語例文")
        en_example_btn = gr.Button("英語例文")

    output_text = gr.Textbox(label="翻訳結果", lines=10)
    direction = gr.Textbox(label="判定", interactive=False)
    status = gr.Markdown()

    translate_btn.click(
        _translate, inputs=[input_text], outputs=[output_text, direction, status]
    )
    clear_btn.click(
        lambda: ("", "", "", ""), outputs=[input_text, output_text, direction, status]
    )
    ja_example_btn.click(lambda: _JP_EXAMPLE, outputs=[input_text])
    en_example_btn.click(lambda: _EN_EXAMPLE, outputs=[input_text])

    gr.Examples(examples=[[_JP_EXAMPLE], [_EN_EXAMPLE]], inputs=[input_text])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=_server_port())
