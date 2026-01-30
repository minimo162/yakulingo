# rules

## 非交渉（Non-negotiables）
- **タスクごとにブランチを切る**（DEFAULT_BRANCHに直コミット禁止）
- **そのタスクだけをやる**（スコープ拡張・ついで修正禁止）
- **各タスクで必ず Typecheck + Lint + Full Tests を実行**（テストの削除/スキップ禁止）
- **各タスクのDoD（厳格ゲート）**
  1. DEFAULT_BRANCHへマージ（PRマージ推奨）
  2. マージ完了をpush/反映で確認
  3. 作業ブランチ削除（remote + local）
  4. 削除を証明（remote/local双方でブランチが存在しないことを確認）
- **コミットメッセージは日本語**（短文で変更理由が伝わること）

## DEFAULT_BRANCH
- `main`

## Canonical commands（このリポジトリでの正）
### install
- `uv sync --extra test`

### typecheck
- `uv run --extra test pyright`

### lint
- `uv run --extra test ruff check .`

### test（full）
- `uv run --extra test pytest`

### run（参考）
- `uv run python app.py`

## ブランチ運用（推奨テンプレ）
- ブランチ名: `case/yakulingo-concise-mode-toggle-3pass-20260130-221337/task-XX-<short-slug>`
- PRタイトル: `task-XX: <要約>`

## ブランチ削除の証明（例）
- remote削除: `git push origin --delete <branch>`
- local削除: `git branch -D <branch>`
- 確認（remote）: `git ls-remote --heads origin <branch>`
- 確認（local）: `git branch --list <branch>`
