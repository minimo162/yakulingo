# task-01: 既定の local_ai_model_path を新モデルへ更新（AppSettings + template）

## 目標（15–45分）
ローカルAIの既定モデルパスを、SSOT のモデルファイル名へ切り替える。

- 新既定（SSOT）: `local_ai/models/shisa-v2.1-qwen3-8B-IQ4_XS.gguf`

## 手順
1. ブランチ作成  
   - `case/<CASE_ID>/task-01-default-model-path`
2. 既定値更新
   - `yakulingo/config/settings.py` の `local_ai_model_path`
   - `config/settings.template.json` の `local_ai_model_path`
3. 影響確認
   - `tests/test_settings_template_defaults.py` が意図どおり（template と AppSettings が一致）であること
4. 品質ゲート（rules.md の canonical commands）
   - `uv run pyright`
   - `uv run ruff check .`
   - `uv run --extra test pytest`
5. PR → `main` マージ
6. ブランチ削除（remote + local）と削除証明

## DoD
- 既定の `local_ai_model_path` が新モデルへ切り替わっている（上記2ファイルで一致）
- `pyright` / `ruff` / `pytest` がパス
- ブランチ削除（remote + local）と削除証明がログに残っている

## 変更対象（このタスクで触る）
- `yakulingo/config/settings.py`
- `config/settings.template.json`
- （必要なら）`tests/test_settings_template_defaults.py`
