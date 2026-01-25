# ルール（非交渉）

## ブランチ運用
- `DEFAULT_BRANCH`: `main`
- 各タスクにつき **1ブランチ**（例: `case/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/task-01`）
- `main` へ直コミット禁止（必ずブランチ→PR/merge）

## スコープ厳守
- `scope.md` に書いた範囲のみ対応する（“ついで対応”“軽微だから”は禁止）
- 影響が広がる場合は、まず `task-00` で設計・方針を確定してから着手する

## 品質（必須）
- **typecheck + lint + full tests** を必ず実行（スキップ/削除/無効化禁止）
- 失敗した場合は、当該タスクの範囲で修正してから次へ進む

## タスク完了 DoD（厳格ゲート / 毎タスク共通）
1. PR作成→`DEFAULT_BRANCH` にmerge（または同等の手順で確実に統合）
2. `origin/main` へ push/merge 完了を確認
3. ブランチ削除（remote + local）
4. 削除を証明（例: `git branch -a | rg <branch>` が 0件）
5. `work/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/tasks/index.md` の `Status/Branch/Commit` を更新

## Canonical Commands（このリポジトリの正）
- Install: `uv sync --extra test`
- Typecheck: `pyright`
- Lint: `ruff check .`
- Tests: `uv run --extra test pytest`

