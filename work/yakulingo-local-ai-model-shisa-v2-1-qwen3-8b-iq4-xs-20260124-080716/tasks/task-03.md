# task-03: 配布スクリプトの固定モデル名を新モデルへ更新（make_distribution.bat）

## 目標（15–45分）
配布物作成時に「同梱する固定 GGUF」を新モデル名へ切り替える（スクリプトの参照整合）。

## 手順
1. ブランチ作成  
   - `case/<CASE_ID>/task-03-dist-fixed-model`
2. `packaging/make_distribution.bat` の `FIXED_MODEL_GGUF` を更新
   - 期待値: `shisa-v2.1-qwen3-8B-IQ4_XS.gguf`
3. 参照整合の確認
   - `robocopy` の除外/固定コピーの挙動が新ファイル名でも同様であること（読み合わせ）
4. 品質ゲート（rules.md の canonical commands）
   - `uv run pyright`
   - `uv run ruff check .`
   - `uv run --extra test pytest`
5. PR → `main` マージ
6. ブランチ削除（remote + local）と削除証明

## DoD
- `make_distribution.bat` の固定モデル参照が新モデル名になっている
- `pyright` / `ruff` / `pytest` がパス
- ブランチ削除（remote + local）と削除証明がログに残っている

## 変更対象（このタスクで触る）
- `packaging/make_distribution.bat`
