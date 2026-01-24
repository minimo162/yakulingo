# log

## task-00（ケース管理ファイル追加）
- ブランチ: `case-yakulingo-local-ai-model-shisa-v2-1-qwen3-8b-iq4-xs-20260124-080716-task-00-case-scaffold`
- コミット: `ffcdbb4d`（task-00: ケース管理ファイルを追加）
- 検証: `uv run pyright` / `uv run ruff check .` / `uv run --extra test pytest`（306 passed）
- 統合: `main` に ff-only で取り込み → `origin/main` へ push 済み
- クリーンアップ: remote/local ブランチ削除済み（`git ls-remote --heads` / `git branch --list` が空を確認）

## task-01（既定ローカルAIモデルパス更新）
- ブランチ: `case-yakulingo-local-ai-model-shisa-v2-1-qwen3-8b-iq4-xs-20260124-080716-task-01-default-model-path`
- コミット: `84221179`（task-01: 既定ローカルAIモデルパスを更新）
- 検証: `uv run pyright` / `uv run ruff check .` / `uv run --extra test pytest`（306 passed）
- 統合: `main` に ff-only で取り込み → `origin/main` へ push 済み
- クリーンアップ: remote/local ブランチ削除済み（`git ls-remote --heads` / `git branch --list` が空を確認）

## task-02（インストーラ固定モデル更新）
- ブランチ: `case-yakulingo-local-ai-model-shisa-v2-1-qwen3-8b-iq4-xs-20260124-080716-task-02-installer-fixed-model`
- コミット: `d3c06843`（task-02: インストーラの固定モデルを更新）
- URL確認: `https://huggingface.co/dahara1/shisa-v2.1-qwen3-8b-UD-japanese-imatrix/resolve/main/shisa-v2.1-qwen3-8B-IQ4_XS.gguf` → HTTP 200
- 検証: `uv run pyright` / `uv run ruff check .` / `uv run --extra test pytest`（306 passed）
- 統合: `main` に ff-only で取り込み → `origin/main` へ push 済み
- クリーンアップ: remote/local ブランチ削除済み（`git ls-remote --heads` / `git branch --list` が空を確認）

## task-03（配布スクリプト固定モデル名更新）
- ブランチ: `case-yakulingo-local-ai-model-shisa-v2-1-qwen3-8b-iq4-xs-20260124-080716-task-03-dist-fixed-model`
- コミット: `65e7cb21`（task-03: 配布スクリプトの固定モデル名を更新）
- 検証: `uv run pyright` / `uv run ruff check .` / `uv run --extra test pytest`（306 passed）
- 統合: `main` に ff-only で取り込み → `origin/main` へ push 済み
- クリーンアップ: remote/local ブランチ削除済み（`git ls-remote --heads` / `git branch --list` が空を確認）

## task-05（DONE）

- インストーラ実行: `powershell -NoProfile -ExecutionPolicy Bypass -File packaging\install_local_ai.ps1`
  - モデル: `local_ai/models/shisa-v2.1-qwen3-8B-IQ4_XS.gguf` を取得
  - `local_ai/manifest.json` の model.repo/file を Shisa に更新し、sha256 を記録
  - NOTE: LICENSE 取得が 404 で警告（モデル本体DLは成功）
- スモーク: `uv run python tools/repro_local_ai_translation.py --input <temp> --mode jp-to-en --style minimal --restart-server --timeout 300 --json`
  - 出力例: `This is a smoke test for local AI translation.`
- 品質ゲート（rules.md）
  - `uv run pyright`: 0 errors
  - `uv run ruff check .`: All checks passed
  - `uv run --extra test pytest`: 306 passed
- 統合: `main` に fast-forward で `0f2a9b71` を取り込み、`origin/main` へ push
- ブランチ削除証明（task-05）
  - remote: `git ls-remote --heads origin case-yakulingo-local-ai-model-shisa-v2-1-qwen3-8b-iq4-xs-20260124-080716-task-05-smoke-local-ai` => empty
  - local: `git branch --list case-yakulingo-local-ai-model-shisa-v2-1-qwen3-8b-iq4-xs-20260124-080716-task-05-smoke-local-ai` => empty
