# Hugging Face Spaces 用アプリ（骨格）

## 目的
- 既存の `app.py`（NiceGUI/デスクトップ向け）とは別に、Hugging Face Spaces で起動できる最小 UI を提供します。

## ローカル起動
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r spaces/requirements.txt
python spaces/app.py
```

## 備考
- CUDA（GGUF を Python で直接ロードする）: `YAKULINGO_SPACES_BACKEND=llama-cpp-python`（または `gguf-python`）
- 翻訳バックエンドは GGUF（llama.cpp / llama-server（事前ビルド済みバイナリ））で実装しています。
- ZeroGPU で CUDA を使いたい場合は `YAKULINGO_SPACES_BACKEND=transformers`（PyTorch/Transformers）を利用してください。
- Hugging Face Spaces では `sdk=gradio` で `app_file=spaces/app.py` を指定する想定です。
- ZeroGPU では `@spaces.GPU` で GPU を動的に割り当てます（`YAKULINGO_SPACES_ZEROGPU_SIZE` / `YAKULINGO_SPACES_ZEROGPU_DURATION`）。
- モデル選定メモ: `docs/HF_SPACES_MODEL.md`
- 既定モデル: `mradermacher/translategemma-27b-it-i1-GGUF`（`translategemma-27b-it.i1-Q4_K_M.gguf`）
  - 必要に応じて `YAKULINGO_SPACES_GGUF_REPO_ID` / `YAKULINGO_SPACES_GGUF_FILENAME` で差し替えできます。
  - gated / 同意が必要な場合は Spaces の Secret に `HF_TOKEN` を設定してください。
- ZeroGPU の Python は `3.12.12` を推奨します（本リポジトリは Python 3.11+ 前提のため）。
