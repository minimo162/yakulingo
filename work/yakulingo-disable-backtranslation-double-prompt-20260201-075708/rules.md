# ルール（非交渉）

## 進め方（ブランチ運用）

- **タスクごとに必ずブランチを切る。**
- **DEFAULT_BRANCH（`main`）に直接コミットしない。**
- 1タスク=1目的=最小差分。タスク完了後に `main` へ取り込む。

## スコープ厳守

- **そのタスクに書いてあることだけをやる。**
- 追加の改善・ついで修正・リファクタはしない（必要なら別ケース/別タスク化）。

## 品質ゲート（必須）

- **各タスクの完了条件（DoD）として、必ず以下を実行し、成功させる。**
  - typecheck（Pyright）
  - lint（Ruff）
  - full tests（pytest 全件。skip しない／テスト削除しない）

## タスク完了後のDoD（厳格ゲート）

各タスク完了時に必ず以下を満たす（**毎タスク**）：

1) PR を作成し、**PR-merge で `main` に取り込む**（ローカルの直マージはしない）  
2) `main` が最新になっていることを確認（fetch/pull）  
3) **作業ブランチを削除（remote+local）**  
4) **削除を証明**（ローカルとリモートの両方で存在しないことを表示）

### 削除証明（例）

- リモート: `git ls-remote --heads origin <branch>`
  - 何も出なければOK
- ローカル: `git branch --list <branch>`
  - 何も出なければOK

## Canonical Commands（このリポジトリでの正）

### セットアップ

- `uv sync`

### typecheck

- `uv run --extra test pyright`

### lint

- `uv run --extra test ruff check .`

### tests（重要：必ず --extra test）

- `uv run --extra test pytest`

## コミットメッセージ

- **日本語で短く、変更理由が伝わる文**にする。
