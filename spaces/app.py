from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import gradio as gr

_SPACES_DIR = Path(__file__).resolve().parent
if str(_SPACES_DIR) not in sys.path:
    sys.path.insert(0, str(_SPACES_DIR))

from translator import get_translator  # noqa: E402

try:
    import spaces as hf_spaces  # type: ignore[import-not-found]
except ModuleNotFoundError:
    hf_spaces = None

_RE_JP_KANA = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F]")
_RE_HANGUL = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")
_RE_LATIN_ALPHA = re.compile(r"[A-Za-z]")

_DEFAULT_MAX_CHARS = 2000
_DEFAULT_GGUF_REPO_ID = "mradermacher/translategemma-27b-it-i1-GGUF"
_DEFAULT_GGUF_FILENAME = "translategemma-27b-it.i1-Q4_K_M.gguf"
_DEFAULT_ZEROGPU_SIZE = "large"
_DEFAULT_ZEROGPU_DURATION_S = 120

_CSS = """
:root {
  /* Minimal tokens (keep small for Spaces) */
  --md-sys-color-primary: #4355B9;
  --md-sys-color-on-primary: #FFFFFF;
  --yak-border: #E5E7EB;
  --yak-surface: #FFFFFF;
  --yak-surface-muted: #F3F4F6;
  --yak-text: #111827;
  --yak-text-muted: #6B7280;
}

.gradio-container {
  background: var(--yak-surface) !important;
  color: var(--yak-text) !important;
  /* HF Spaces / Gradio の既定 max-width を確実に上書き */
  max-width: none !important;
  width: 100% !important;
  margin: 0 auto !important;
  padding: 0 24px !important;
}

.yak-page {
  width: min(1320px, 100%);
  margin: 0 auto;
  padding: 28px 0 40px;
}

.yak-header {
  text-align: center;
  margin: 8px 0 22px;
}

.yak-header h1 {
  font-size: 40px;
  line-height: 1.1;
  font-weight: 750;
  margin: 0;
}

/* Buttons */
#translate_btn button {
  background: var(--md-sys-color-primary) !important;
  color: var(--md-sys-color-on-primary) !important;
  border-radius: 9999px !important;
  padding: 10px 18px !important;
}

#clear_btn button {
  border-radius: 9999px !important;
  padding: 10px 18px !important;
}

/* OpenAI 翻訳UI風: 言語セレクタ行 */
.yak-lang-row {
  display: grid !important;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 14px;
  align-items: center;
  margin: 0 0 18px 0;
}

.yak-swap button {
  border-radius: 9999px !important;
  min-width: 44px !important;
  height: 44px !important;
  padding: 0 !important;
  border: 1px solid var(--yak-border) !important;
  background: var(--yak-surface) !important;
}

/* 2ペイン */
.yak-panels {
  display: grid !important;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 24px;
  align-items: stretch;
  margin: 0 0 14px 0;
}

@media (max-width: 1100px) {
  .yak-lang-row {
    grid-template-columns: 1fr;
  }
  .yak-panels {
    grid-template-columns: 1fr;
  }
  .yak-swap {
    display: none;
  }
}

.yak-panel {
  border-radius: 22px;
  overflow: hidden;
  border: 1px solid var(--yak-border);
  background: var(--yak-surface);
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}

.yak-panel-output {
  background: var(--yak-surface-muted);
}

/* Textbox を container=False で使う前提: id が textarea 自体になる場合もある */
#input_text,
#output_text,
#input_text textarea,
#output_text textarea {
  width: 100% !important;
  min-height: 420px !important;
  font-size: 18px !important;
  line-height: 1.6 !important;
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
  padding: 18px 18px !important;
  margin: 0 !important;
  resize: none !important;
  background: transparent !important;
}

#output_text,
#output_text textarea {
  color: var(--yak-text) !important;
}

/* disabled の見た目を薄くしすぎない */
#output_text:disabled,
#output_text textarea:disabled {
  opacity: 1 !important;
  -webkit-text-fill-color: var(--yak-text) !important;
}

/* セレクタの見た目（Dropdown） */
.yak-select,
.yak-select * {
  box-shadow: none !important;
}

.yak-select {
  /* remove Gradio block frame around dropdown */
  background: transparent !important;
  border: none !important;
  padding: 0 !important;
  margin: 0 !important;
  border-radius: 0 !important;
  --block-background-fill: transparent;
  --block-border-width: 0px;
  --block-padding: 0px;
  --block-radius: 0px;
}

.yak-select > div,
.yak-select .wrap,
.yak-select label,
.yak-select .container,
.yak-select .input-container {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  margin: 0 !important;
  border-radius: 0 !important;
}

.yak-select select,
.yak-select input {
  border-radius: 9999px !important;
  border: 1px solid var(--yak-border) !important;
  padding: 10px 14px !important;
  height: 44px !important;
  background: var(--yak-surface) !important;
}

/* Result meta: minimal chips */
#result_meta {
  color: var(--yak-text-muted);
  margin-top: 6px;
}
"""


def _has_hf_token() -> bool:
    return bool(
        (
            os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
            or os.environ.get("HUGGINGFACE_HUB_TOKEN")
            or ""
        ).strip()
    )


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


def _gguf_repo_id() -> str:
    return (
        os.environ.get("YAKULINGO_SPACES_GGUF_REPO_ID") or _DEFAULT_GGUF_REPO_ID
    ).strip()


def _gguf_filename() -> str:
    return (
        os.environ.get("YAKULINGO_SPACES_GGUF_FILENAME") or _DEFAULT_GGUF_FILENAME
    ).strip()


def _quant_label() -> str:
    match = re.search(r"-(Q[^.]+)\.gguf$", _gguf_filename(), re.IGNORECASE)
    return match.group(1) if match else "unknown"

def _translator_backend_label(translator: object) -> str:
    value = getattr(translator, "backend_label", None)
    if callable(value):
        try:
            return str(value())
        except Exception:
            return "unknown"
    return "unknown"


def _translator_engine_label(translator: object) -> str:
    value = getattr(translator, "engine_label", None)
    if callable(value):
        try:
            return str(value())
        except Exception:
            return "unknown"
    return "unknown"


def _translator_quant_label(translator: object) -> str:
    value = getattr(translator, "quant_label", None)
    if callable(value):
        try:
            return str(value())
        except Exception:
            return _quant_label()
    return _quant_label()


def _backend_status_lines(translator: object) -> str:
    backend = _translator_backend_label(translator)
    if backend == "transformers":
        model_id = (os.environ.get("YAKULINGO_SPACES_HF_MODEL_ID") or "").strip() or "google/translategemma-27b-it"
        load_in_4bit = (os.environ.get("YAKULINGO_SPACES_HF_LOAD_IN_4BIT") or "").strip()
        load_in_4bit = load_in_4bit if load_in_4bit else "1"
        return f"- hf_model: `{model_id}`\n- hf_load_in_4bit: `{load_in_4bit}`"
    engine = _translator_engine_label(translator)
    engine_line = f"\n- gguf_engine: `{engine}`" if engine != "unknown" else ""
    return f"- gguf_repo: `{_gguf_repo_id()}`\n- gguf_file: `{_gguf_filename()}`{engine_line}"


def _result_meta_markdown(
    label: str, *, translator: object, device: str, elapsed_s: float | None
) -> str:
    parts: list[str] = [f"**{label}**"]
    parts.append(f"`device={device}`")
    if elapsed_s is not None:
        parts.append(f"`{elapsed_s:.2f}s`")
    parts.append(f"`backend={_translator_backend_label(translator)}`")
    engine = _translator_engine_label(translator)
    if engine != "unknown":
        parts.append(f"`engine={engine}`")
    parts.append(f"`{_translator_quant_label(translator)}`")
    return " ".join(parts)


def _swap_langs(source: str, target: str) -> tuple[str, str]:
    if source == "言語を検出する":
        return source, target
    if target == "自動":
        return source, target
    return target, source


def _ui_dropdown(  # type: ignore[no-untyped-def]
    *,
    choices: list[str],
    value: str,
    elem_id: str,
    elem_classes: list[str],
):
    """Gradio Dropdown が無い環境（テスト用のfake gradio）でも import できるようにする。"""
    Dropdown = getattr(gr, "Dropdown", None)
    if Dropdown is None:
        return gr.Textbox(
            value=value,
            label="",
            show_label=False,
            interactive=False,
            elem_id=elem_id,
            elem_classes=elem_classes,
        )
    return Dropdown(
        choices=choices,
        value=value,
        label="",
        show_label=False,
        elem_id=elem_id,
        elem_classes=elem_classes,
    )


def _zerogpu_size() -> str:
    raw = (
        os.environ.get("YAKULINGO_SPACES_ZEROGPU_SIZE") or _DEFAULT_ZEROGPU_SIZE
    ).strip()
    value = raw.lower()
    return value if value in ("large", "xlarge") else _DEFAULT_ZEROGPU_SIZE


def _zerogpu_duration_seconds() -> int:
    raw = (
        os.environ.get("YAKULINGO_SPACES_ZEROGPU_DURATION")
        or str(_DEFAULT_ZEROGPU_DURATION_S)
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_ZEROGPU_DURATION_S
    return max(1, value)


def _zerogpu_gpu_decorator():  # type: ignore[no-untyped-def]
    gpu = getattr(hf_spaces, "GPU", None) if hf_spaces is not None else None
    if gpu is None:

        def noop(fn):  # type: ignore[no-untyped-def]
            return fn

        return noop
    return gpu(size=_zerogpu_size(), duration=_zerogpu_duration_seconds())


def _error_hint(message: str) -> str:
    lowered = message.lower()
    if "gpu が利用できません" in lowered:
        return "Space の Hardware を ZeroGPU に設定してください（またはデバッグ用途で `YAKULINGO_SPACES_ALLOW_CPU=1`）。"
    if "401" in lowered or "unauthorized" in lowered or "gated" in lowered:
        if not _has_hf_token():
            return (
                "このモデルは gated（利用条件の同意/アクセス許可が必要）な可能性があります。"
                "Spaces の Secret に `HF_TOKEN` を設定し、モデルページで同意/許可を済ませてください。"
            )
        return (
            "HF_TOKEN は設定されていますが、モデルへのアクセス権がない可能性があります。"
            "モデルページで同意/許可を確認し、Space を再起動してください。"
        )
    if (
        "llama-server" in lowered
        or "llama.cpp" in lowered
        or "llama_cpp" in lowered
        or "llama-cpp-python" in lowered
    ):
        return (
            "llama.cpp（llama-server / llama-cpp-python）周りで失敗している可能性があります。"
            "Space のログを確認し、llama-server を使う場合は `YAKULINGO_SPACES_LLAMA_CPP_*`（URL/ASSET_SUFFIX など）"
            "や `HF_HOME`（キャッシュ）を見直してください。"
            "llama-cpp-python を使う場合は `requirements.txt` の `--extra-index-url`（CUDA wheel）設定も確認してください。"
        )
    if "bitsandbytes" in lowered or "transformers" in lowered or "torch" in lowered:
        return (
            "Transformers（PyTorch）経由の起動/量子化に失敗している可能性があります。"
            "依存関係（`torch`/`transformers`/`bitsandbytes`）と Space のログを確認し、"
            "必要なら `YAKULINGO_SPACES_HF_LOAD_IN_4BIT=0` を試してください。"
        )
    if "huggingface_hub" in lowered or "hf_hub_download" in lowered:
        return (
            "モデルのダウンロードに失敗している可能性があります。"
            "（gated の場合は `HF_TOKEN`、キャッシュは `HF_HOME` を確認してください）"
        )
    if "cuda" in lowered:
        return "CUDA 周りで失敗している可能性があります。ZeroGPU の割当と依存関係を確認してください。"
    return ""


@_zerogpu_gpu_decorator()
def _translate(text: str, source: str, target: str) -> tuple[str, str, str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return "", "", ""

    translator = get_translator()
    if target == "自動":
        output_language, label = _detect_direction(cleaned)
    else:
        output_language = "en" if target == "英語" else "ja"
        if source == "言語を検出する":
            label = f"自動 → {target}"
        else:
            label = f"{source} → {target}"
    if len(cleaned) > _max_chars():
        return (
            "",
            _result_meta_markdown(
                label, translator=translator, device="unknown", elapsed_s=None
            ),
            f"入力が長すぎます（{len(cleaned)}文字）。{_max_chars()}文字以内に短縮してください。",
        )

    start = time.monotonic()
    try:
        translated = translator.translate(cleaned, output_language=output_language)  # type: ignore[arg-type]
    except Exception as e:
        hint = _error_hint(str(e))
        detail = f"エラー: {e}"
        if hint:
            detail = f"{detail}\n\n**ヒント**: {hint}"
        meta = _result_meta_markdown(
            label,
            translator=translator,
            device=translator.runtime_device(),
            elapsed_s=None,
        )
        status = (
            f"{detail}\n\n"
            f"{_backend_status_lines(translator)}"
        )
        return "", meta, status

    elapsed_s = time.monotonic() - start
    action = "英訳しました" if output_language == "en" else "和訳しました"
    meta = _result_meta_markdown(
        label,
        translator=translator,
        device=translator.runtime_device(),
        elapsed_s=elapsed_s,
    )
    status = f"**{action}**"
    return translated, meta, status


def _server_port() -> int:
    try:
        return int(os.environ.get("PORT", "7860"))
    except ValueError:
        return 7860


with gr.Blocks(title="YakuLingo", css=_CSS) as demo:
    with gr.Column(elem_classes=["yak-page"]):
        gr.Markdown("# YakuLingo", elem_classes=["yak-header"])

        with gr.Row(elem_classes=["yak-lang-row"]):
            source_lang = _ui_dropdown(
                choices=["言語を検出する", "日本語", "英語"],
                value="言語を検出する",
                elem_id="source_lang",
                elem_classes=["yak-select"],
            )
            swap_btn = gr.Button("⇄", elem_id="swap_btn", elem_classes=["yak-swap"])
            target_lang = _ui_dropdown(
                choices=["自動", "英語", "日本語"],
                value="自動",
                elem_id="target_lang",
                elem_classes=["yak-select"],
            )

        with gr.Row(elem_classes=["yak-panels"]):
            with gr.Column(elem_classes=["yak-panel"]):
                input_text = gr.Textbox(
                    label="",
                    show_label=False,
                    lines=18,
                    placeholder="翻訳するテキストを入力するか、貼り付けます",
                    elem_id="input_text",
                    container=False,
                )

            with gr.Column(elem_classes=["yak-panel", "yak-panel-output"]):
                output_text = gr.Textbox(
                    label="",
                    show_label=False,
                    lines=18,
                    elem_id="output_text",
                    interactive=False,
                    container=False,
                )

        with gr.Row():
            translate_btn = gr.Button("翻訳", elem_id="translate_btn")
            clear_btn = gr.Button("クリア", elem_id="clear_btn")

        result_meta = gr.Markdown(elem_id="result_meta")
        status = gr.Markdown()

        with gr.Accordion("詳細", open=False):
            gr.Markdown(
                "**設定（環境変数）**  \n"
                f"- gguf_repo: `{_gguf_repo_id()}`  \n"
                f"- gguf_file: `{_gguf_filename()}`  \n"
                f"- ZeroGPU: size=`{_zerogpu_size()}` duration=`{_zerogpu_duration_seconds()}s`  \n"
                f"- HF_TOKEN: `{('set' if _has_hf_token() else 'not set')}`",
            )

    translate_btn.click(
        _translate,
        inputs=[input_text, source_lang, target_lang],
        outputs=[output_text, result_meta, status],
    )
    swap_btn.click(
        _swap_langs,
        inputs=[source_lang, target_lang],
        outputs=[source_lang, target_lang],
    )
    clear_btn.click(
        lambda: ("", "", "", "", "言語を検出する", "自動"),
        outputs=[input_text, output_text, result_meta, status, source_lang, target_lang],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=_server_port())
