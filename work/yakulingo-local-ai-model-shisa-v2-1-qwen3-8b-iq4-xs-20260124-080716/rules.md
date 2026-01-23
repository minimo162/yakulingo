# Rules

## 非交渉事項（Non-negotiables）
- DEFAULT_BRANCH は `main`
- **タスクごとに必ずブランチを切る**（`main` へ直接コミットしない）
- **そのタスクの範囲だけ**を実施（スコープ拡張禁止）
- **各タスクで必ず** `typecheck + lint + full tests` を実行（テストのスキップ/削除禁止）
- 各タスク完了後の DoD ゲート（厳守）
  1. PR作成 → レビュー → `main` にマージ（または PR-merge）
  2. push/merge 完了を確認
  3. ブランチ削除（remote + local）
  4. 削除の証明（両方）
     - `git branch --list <branch>` が空
     - `git ls-remote --heads origin <branch>` が空

## ブランチ命名
- `case/yakulingo-local-ai-model-shisa-v2-1-qwen3-8b-iq4-xs-20260124-080716/task-XX-<short>`

## コミットメッセージ
- 日本語で短文（変更理由が伝わる）

## Canonical commands（このリポジトリの標準コマンド）
```bash
# install
uv sync
uv sync --extra test

# typecheck
uv run pyright

# lint
uv run ruff check .

# full tests
uv run --extra test pytest
```
