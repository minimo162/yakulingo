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
- 翻訳バックエンドは Transformers（`google/translategemma-27b-it`）で実装します（後続タスクで差し替え）。
- Hugging Face Spaces では `sdk=gradio` で `app_file=spaces/app.py` を指定する想定です。
- モデル選定メモ: `docs/HF_SPACES_MODEL.md`
