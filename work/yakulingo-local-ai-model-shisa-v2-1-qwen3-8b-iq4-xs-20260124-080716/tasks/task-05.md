# task-05: （任意）インストーラ実行で新モデル導入→ローカルAI翻訳スモーク

## 目標（30–60分 / ネットワーク速度に依存）
新固定モデルが実際にダウンロード・起動でき、ローカルAI翻訳が最小限動作することを確認する。

## 前提
- ネットワーク（プロキシ含む）が Hugging Face / GitHub Releases に到達できる
- 数GBのダウンロードが発生しうる
- 実機依存（CPU/GPU/空き容量）

## 手順
1. ブランチ作成  
   - `case/<CASE_ID>/task-05-smoke-local-ai`
2. インストーラ実行（必要に応じてプロキシ）
   - `powershell -NoProfile -ExecutionPolicy Bypass -File packaging\\install_local_ai.ps1`
3. モデル/サーバが揃ったことを確認
   - `local_ai/models/shisa-v2.1-qwen3-8B-IQ4_XS.gguf` が存在
   - `local_ai/manifest.json` が新 repo/file を記録
4. スモーク（最小）
   - `uv run python tools/repro_local_ai_translation.py`（可能なら）
5. 品質ゲート（rules.md の canonical commands）
   - `uv run pyright`
   - `uv run ruff check .`
   - `uv run --extra test pytest`
6. PR → `main` マージ
7. ブランチ削除（remote + local）と削除証明

## DoD
- 新モデルでのローカルAI翻訳が1回通る（最小確認）
- `local_ai/manifest.json` の記録が新 repo/file に更新されている
- `pyright` / `ruff` / `pytest` がパス
- ブランチ削除（remote + local）と削除証明がログに残っている

## 変更対象（このタスクで触る）
- （必要なら）`local_ai/manifest.json`
