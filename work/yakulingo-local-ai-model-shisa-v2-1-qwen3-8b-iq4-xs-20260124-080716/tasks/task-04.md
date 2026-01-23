# task-04: ドキュメントの既定モデル参照を新モデルへ更新（README/docs）

## 目標（30–60分）
ドキュメント内の「既定モデル」参照を新モデルへ統一し、手順のコピペで迷わない状態にする。

## 手順
1. ブランチ作成  
   - `case/<CASE_ID>/task-04-docs-default-model`
2. 参照箇所を列挙して更新
   - `README.md`
   - `docs/PERFORMANCE_LOCAL_AI.md`
   - `docs/LOCAL_AI_AGENTCPM_EXPLORE.md`
   - `docs/LOCAL_AI_VULKAN_IGPU_WINDOWS_AMD.md`
   - `docs/DISTRIBUTION.md`
   - `docs/SPECIFICATION.md`
   - `docs/PROMPT_TEMPLATES_SSOT.md`
   - ※ `rg` で `translategemma-12b-it.i1-IQ3_XXS.gguf` 等を検索し、残りが無いこと
3. 品質ゲート（rules.md の canonical commands）
   - `uv run pyright`
   - `uv run ruff check .`
   - `uv run --extra test pytest`
4. PR → `main` マージ
5. ブランチ削除（remote + local）と削除証明

## DoD
- 主要ドキュメントの既定モデル参照が新モデルに統一されている
- `pyright` / `ruff` / `pytest` がパス
- ブランチ削除（remote + local）と削除証明がログに残っている

## 変更対象（このタスクで触る）
- `README.md`
- `docs/*`（上記の列挙箇所）
