# Task 06: 統合リグレッション（typecheck/lint/full tests）と仕上げ

## 目的

- 戻し訳廃止とプロンプト二重送信の一連の変更が、リポジトリ全体で整合していることを確認する。
- 取りこぼし（未参照になった定数、未更新のテスト、残骸のテンプレ参照）を解消する。

## チェックリスト

- `rg` で「戻し訳/backtranslation」残骸が意図通りか確認（コメントや履歴互換の最小限を除く）
- `uv run --extra test pyright`
- `uv run --extra test ruff check .`
- `uv run --extra test pytest`

## DoD

- 上記3コマンドがすべて成功
- PR-merge → ブランチ削除（remote+local）→ 削除証明

