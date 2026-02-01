# Hugging Face Spaces 用デモ（骨格）

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
- 翻訳バックエンドは Transformers（`google/translategemma-27b-it`）で実装しています。
- Hugging Face Spaces では `sdk=gradio` で `app_file=spaces/app.py` を指定する想定です。
- ZeroGPU では `@spaces.GPU` で GPU を動的に割り当てます（`YAKULINGO_SPACES_ZEROGPU_SIZE` / `YAKULINGO_SPACES_ZEROGPU_DURATION`）。
- モデル選定メモ: `docs/HF_SPACES_MODEL.md`
- gated の場合は Spaces の Secret に `HF_TOKEN` を設定してください。
- 既定は `YAKULINGO_SPACES_QUANT=4bit` を想定しています。
- ZeroGPU の Python は `3.12.12` を推奨します（本リポジトリは Python 3.11+ 前提のため）。
