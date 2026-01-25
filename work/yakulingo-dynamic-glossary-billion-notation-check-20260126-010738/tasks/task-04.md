# task-04: 仕上げ（品質ゲート通過・回帰確認）

## 目的
- 変更の整合性を確認し、品質ゲート（typecheck/lint/full tests）を全て通す。
- `billion` 混入が再発しないことを確認し、ケース資料（`tasks/index.md` と `log.md`）を更新する。

## 想定所要（タイムボックス）
- 15〜60分

## 実行コマンド
- Install: `uv sync --extra test`
- Typecheck: `pyright`
- Lint: `ruff check .`
- Tests: `uv run --extra test pytest`

## DoD
- 上記コマンドが全て成功
- `tasks/index.md` の `Status/Branch/Commit` が最新
- ブランチ削除まで `rules.md` の DoD を満たしている
