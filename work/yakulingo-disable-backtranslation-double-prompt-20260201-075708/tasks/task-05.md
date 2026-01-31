# Task 05: UI表示（戻し訳/パス）を整理し、設定UIの選択肢を更新

## 目的

- 戻し訳に関するUI表示（パスラベル、説明、カード等）を廃止し、残るパイプライン（例: concise の rewrite）に合わせて表示を簡素化する。
- 設定UIに戻し訳関連の選択肢がある場合は撤去する。

## 変更対象（想定）

- `yakulingo/ui/components/text_panel.py`
  - `back_translation` / `revision` 等の表示分岐を削除
  - 残るモード（通常/concise）に最適化
- `yakulingo/ui/app.py` / `yakulingo/ui/state.py`（必要な範囲のみ）
  - モード選択や状態名に戻し訳が残っていれば削除/置換

## 非対象

- UIデザインの刷新（レイアウト大変更）

## テスト観点

- UIはテスト外が多いが、UIに依存する状態/メタデータ（例: `text_translation_mode`）の扱いはユニットテストで担保する

## DoD

- typecheck: `uv run --extra test pyright`
- lint: `uv run --extra test ruff check .`
- tests: `uv run --extra test pytest`
- PR-merge → ブランチ削除（remote+local）→ 削除証明

