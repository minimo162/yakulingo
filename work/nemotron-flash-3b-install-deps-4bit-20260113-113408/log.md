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

### 2026-01-13 task-07（Step 7 [1] 落ちる）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-07-step7-choice1-crash`
- コミット: `7c4def27888e0dc75da2854306984e4e33bcd649`
- 変更点: Step 7 の `[1]`（HF→GGUF→4bit）で不足しがちな依存（`torch`/`transformers`/`sentencepiece`/`safetensors` 等）を `install_deps.bat` 側で事前導入し、失敗時も復旧コマンドを表示する
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）

### 2026-01-13 task-08（Step 7 分離）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-08-step7-split`
- コミット: `7e7cfb2eb7b27a1ea5bef46b726435bb2b741a63`
- 変更点: Step 7（ローカルAI導入）を `packaging/install_deps_step7_local_ai.bat` に切り出し、`packaging/install_deps.bat` は呼び出しのみの薄い実装に変更
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）
- フォローアップ:
  - Step 7 の `[1]` 選択で「落ちる」現象がまだ残る場合は、task-09 で原因特定と「落ちない/理由表示」へ修正する

### 2026-01-13 task-09（Step 7 入力で落ちる）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-09-step7-choice1-fix`
- コミット: `bb379d5ff08a82868326caabba1958dcb61f3357`
- 原因: Step 7 分離時に `NO_PROXY` の行の閉じ括弧 `)` が欠落していたのと、`if (...)` ブロック内の `echo ... (...)` の括弧がエスケープされておらず、選択直後にバッチの構文エラーで終了していた
- 変更点:
  - `packaging/install_deps_step7_local_ai.bat` の括弧・分岐を修正し、失敗しても「落ちない」+ `install_local_ai.ps1` の exit code を表示
  - `packaging/install_deps.bat` から呼び出す場合は `YAKULINGO_INSTALL_DEPS_STEP7` を立て、Step 7 単体起動時のみ終了前に `pause`（ウィンドウ即閉じ対策）
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）

### 2026-01-13 task-10（Step 7 単体プロキシ選択）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-10-step7-proxy-choice`
- コミット: `57ba029357fa351629267bfd2a4912774f0b2b4f`
- 変更点: `packaging/install_deps_step7_local_ai.bat` を単体実行した場合に限り、`install_deps.bat` と同等のプロキシ選択（proxy/direct/skip SSL）と認証情報入力を追加し、`install_local_ai.ps1` 実行時の `USE_PROXY` / `PROXY_*` を正しくセットできるようにした
- 互換性: `YAKULINGO_INSTALL_DEPS_STEP7=1`（`install_deps.bat` 経由）では二重にプロキシ選択を出さず、親側の設定を尊重する
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）

### 2026-01-13 task-11（HF→GGUF変換: llama.cpp ソース取得 404 回避）
- ブランチ: `case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-11-llama-ref-404`
- コミット: `9a30661e27ad40b5095269b889d3b650058691aa`
- 変更点: `tools/hf_to_gguf_quantize.py` の llama.cpp ソース取得で、`master/main` は `refs/heads` を優先し、404 時は `tags/heads` を相互フォールバックして再試行するようにした（失敗時は試行URL一覧を出力）
- 検証:
  - `uv sync`
  - `uv sync --extra test`
  - `uv run python -m compileall yakulingo`
  - `uv run --extra test pytest`（112 passed）
- フォローアップ:
  - `install_local_ai.ps1` から `hf_to_gguf_quantize.py --llama-tag <release tag>` を明示的に渡して、manifest が無い新規環境で `master` 既定に戻らないようにする（task-12）
