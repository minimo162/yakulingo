# task-06: 仕上げ（回帰確認、UI文言整備、full gate）

見積: 15–45分

## ゴール
- UI/サービスのつなぎ込み最終確認（標準/簡潔の切替、英訳/和訳どちらも）
- intentの“最終出力=3回目”が一貫していることを確認
- full gate（typecheck/lint/test）を必ず通す

## 手順
1. UI文言/区切り表現の微調整（必要最小限）
2. 標準モードと簡潔モードの両方でスモーク（手動/ログ）
3. full gateを実行して完了

## 検証（必須）
- `uv run --extra test pyright`
- `uv run --extra test ruff check .`
- `uv run --extra test pytest`

## DoD（完了条件）
- intentの要件に対して挙動が揃っている
- typecheck/lint/testが全て通る
