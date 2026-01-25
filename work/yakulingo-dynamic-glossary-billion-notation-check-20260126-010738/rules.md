# ルール（非交渉）

## ブランチ運用
- `DEFAULT_BRANCH`: `main`
- タスクごとに **必ず1ブランチ** を切る（例: `case-<CASE_ID>-task-01-...`）
- `main` に直接コミットしない（PR/merge 経由）

## スコープ厳守
- `scope.md` に書いた範囲だけを触る（スコープ拡張禁止）
- 「ついで修正」「ついでリファクタ」はやらない（必要なら別ケース）

## 品質ゲート（必須）
- **typecheck + lint + full tests** を毎タスクで実行（テストのスキップ/削除禁止）

## タスク完了DoD（厳格ゲート）
1. PR を `main` に merge（または同等の手順で確実に統合）
2. `origin/main` への push/merge 完了を確認
3. 作業ブランチを削除（remote + local）
4. 削除の証明（例: `git branch -a | rg <branch>` が 0 件）
5. `work/yakulingo-dynamic-glossary-billion-notation-check-20260126-010738/tasks/index.md` の `Status/Branch/Commit` を更新

## Canonical Commands（このリポジトリでの正）
- Install: `uv sync --extra test`
- Typecheck: `pyright`
- Lint: `ruff check .`
- Tests: `uv run --extra test pytest`
