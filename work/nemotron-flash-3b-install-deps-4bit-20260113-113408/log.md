# 作業ログ: nemotron-flash-3b-install-deps-4bit-20260113-113408

## エントリ
<!-- ここに時系列で追記（まだ空） -->

### 2026-01-13 task-00（設計）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-00-design-notes`
- コミット: `ef001c084c47f82a2382baddd34e7d17e76a380d`
- 変更点: `tasks/task-00-notes.md` に Nemotron 切替の差分点と暫定決定を整理
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）
- フォローアップ:
  - `docs/LOCAL_AI_AGENTCPM_EXPLORE.md` や `docs/PERFORMANCE_LOCAL_AI.md` が AgentCPM/Qwen3 前提の章を含むため、Nemotron 前提への更新方針を task-06/05 で確定する
  - `work/` は `.gitignore` 対象のため、以降タスクでもケース成果物を push/merge する場合は `git add -f` が必要

### 2026-01-13 task-01（install_deps Step 7）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-01-installer-defaults`
- コミット: `744021eea51c2cc1cb3b7c43785c84e28ca180fc`
- 変更点: `packaging/install_deps.bat` の Step 7 を Nemotron 既定（repo/quant/base_name/表示文言）へ更新
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）

### 2026-01-13 task-02（install_local_ai 既定モデル）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-02-install-local-ai-defaults`
- コミット: `f8d941e69393c898e1d934b2c557d671d7dbf6c1`
- 変更点: `packaging/install_local_ai.ps1` の既定モデルを Nemotron（HF→GGUF→4bit）へ更新し、`kind=hf` の生成GGUF名を `Nemotron-Flash-3B-Instruct.Q4_K_M.gguf` に統一
- 互換性: `kind=gguf` を明示した場合で repo/file 未指定のときは、従来通り既知のGGUF（Shisa）へフォールバックして回帰を避ける
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）
- フォローアップ:
  - `config/settings.template.json` / `yakulingo/config/settings.py` の `local_ai_model_path` は task-03 で Nemotron のGGUF名へ更新して整合させる

### 2026-01-13 task-03（既定モデルパス）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-03-app-default-model`
- コミット: `e79b0489972f8909a048ad3b7d8b4390233adcc4`
- 変更点: `local_ai_model_path` の既定を `Nemotron-Flash-3B-Instruct.Q4_K_M.gguf` に更新（テンプレ/コード/READMEの既定値参照）
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）
- フォローアップ:
  - `README.md` の Step 7 説明など、既定モデルに関する文章レベルの更新は task-06 でまとめて対応する
