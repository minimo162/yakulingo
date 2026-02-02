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
  /* M3-ish design tokens (subset) */
  --md-sys-color-primary: #4355B9;
  --md-sys-color-on-primary: #FFFFFF;
  --md-sys-color-primary-container: #DEE0FF;
  --md-sys-color-on-primary-container: #00105C;

  --md-sys-color-secondary-container: #E6E7EB;
  --md-sys-color-on-secondary-container: #1F2328;

  --md-sys-color-surface: #FCFCFD;
  --md-sys-color-surface-container: #EEF0F5;
  --md-sys-color-on-surface: #1D1D1F;
  --md-sys-color-on-surface-variant: #5A5A63;
  --md-sys-color-outline: #7E7E87;
  --md-sys-color-outline-variant: #D0D2DA;
}

.gradio-container {
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
  /* HF Spaces / Gradio の既定 max-width を確実に上書き */
  max-width: none !important;
  width: 100% !important;
  margin: 0 auto;
  padding: 0 16px;
}

/* Card container */
.yak-card {
  background: var(--md-sys-color-surface-container);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: 28px;
  padding: 18px 18px 14px 18px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}

.yak-title h1 {
  margin: 0.25rem 0 0.25rem 0;
}

.yak-subtitle {
  color: var(--md-sys-color-on-surface-variant);
  margin-top: 0.25rem;
}

/* Buttons */
#translate_btn button {
  background: var(--md-sys-color-primary) !important;
  color: var(--md-sys-color-on-primary) !important;
  border-radius: 9999px !important;
}

#clear_btn button {
  border-radius: 9999px !important;
}

/* Result meta: direction chip + badges */
#result_meta strong {
  display: inline-block;
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  padding: 0.25rem 0.6rem;
  border-radius: 9999px;
  font-weight: 650;
}

#result_meta code {
  display: inline-block;
  background: var(--md-sys-color-surface);
  border: 1px solid var(--md-sys-color-outline-variant);
  color: var(--md-sys-color-on-surface);
  padding: 0.15rem 0.45rem;
  border-radius: 9999px;
}

/* Textareas */
#input_text textarea,
#output_text textarea {
  border-radius: 12px !important;
  border-color: var(--md-sys-color-outline-variant) !important;
  font-size: 18px !important;
  line-height: 1.5;
}

/* Remove the extra white rectangle around textareas (Gradio Textbox container) */
#input_text,
#output_text,
#input_text > div,
#output_text > div,
#input_text .wrap,
#output_text .wrap,
#input_text .container,
#output_text .container {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  margin: 0 !important;
  border-radius: 0 !important;
}

/* More aggressive: Gradio v4 wrapper variations (keep scope under elem_id) */
#input_text .gr-block,
#output_text .gr-block,
#input_text .gr-box,
#output_text .gr-box,
#input_text .gr-panel,
#output_text .gr-panel,
#input_text .gr-form,
#output_text .gr-form {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  margin: 0 !important;
  border-radius: 0 !important;
}

/* Main layout: keep the centerline between the two cards at the screen center */
.yak-main-row {
  display: grid !important;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
  align-items: start;
  width: min(1680px, 100%);
  margin: 0 auto;
}

.yak-main-row > * {
  min-width: 0;
}

@media (max-width: 1100px) {
  .yak-main-row {
    grid-template-columns: 1fr;
  }
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
def _translate(text: str) -> tuple[str, str, str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return "", "", ""

    translator = get_translator()
    output_language, label = _detect_direction(cleaned)
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
    gr.Markdown("# YakuLingo", elem_classes=["yak-title"])

    with gr.Row(elem_classes=["yak-main-row"]):
        with gr.Column(scale=1, min_width=520, elem_classes=["yak-card"]):
            gr.Markdown("## 入力")
            input_text = gr.Textbox(
                label="",
                show_label=False,
                lines=18,
                placeholder="日本語または英語を入力してください",
                elem_id="input_text",
            )

            with gr.Row():
                translate_btn = gr.Button("翻訳", elem_id="translate_btn")
                clear_btn = gr.Button("クリア", elem_id="clear_btn")

        with gr.Column(scale=1, min_width=520, elem_classes=["yak-card"]):
            gr.Markdown("## 翻訳結果")
            output_text = gr.Textbox(
                label="",
                show_label=False,
                lines=18,
                elem_id="output_text",
            )
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
        inputs=[input_text],
        outputs=[output_text, result_meta, status],
    )
    clear_btn.click(
        lambda: ("", "", "", ""),
        outputs=[input_text, output_text, result_meta, status],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=_server_port())
