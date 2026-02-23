# RunPod 現行実装サマリ（2026-02-23時点）

## 1. 目的
このドキュメントは、YakuLingo リポジトリ内の RunPod 関連実装の最新版を、運用目線で一枚にまとめたものです。

## 2. 現行ドキュメントと実装の正本
- 現行サマリ: `docs/runpod/RUNPOD_CURRENT_IMPLEMENTATION.md`（このファイル）
- 詳細評価ガイド: `docs/runpod/RUNPOD_GPTOSS_SWALLOW_IQ4XS_2WEEK_EVAL.md`
- 最新運用ログ: `docs/runpod/PHASE1_DAY1_WORKLOG_2026-02-23.md`
- RunPod ツール群: `tools/runpod_eval/`
- 自動運用 Workflow:
  - `.github/workflows/runpod-morning-resume.yml`
  - `.github/workflows/runpod-window-stop.yml`

## 3. 自動運用（GitHub Actions）
### 3.1 朝の起動 (`runpod-morning-resume`)
- 実行タイミング:
  - `cron: 50 23 * * 0-4`（UTC）
  - JST では平日 08:50
- 実行内容:
  - `RUNPOD_POD_NAME`（または `RUNPOD_POD_ID`）で既存 Pod を解決
  - 既存 Pod が停止中なら `podResume`
  - 既存 Pod が無ければ `REST /v1/pods` で新規作成
  - `networkVolumeId` 不一致検知時は失敗扱い（誤 Volume への接続防止）
  - Proxy URL の warning（`critical error on this machine`）を検知
  - 任意で Slack 通知
- デフォルトの起動コマンド:
  - `runpod_nv_bootstrap.sh` を `FAST_START=1` で実行
  - `/workspace/.enable_lobehub_bootstrap` がある場合のみ `runpod_lobehub_bootstrap.sh` も実行

### 3.2 夕方の停止 (`runpod-window-stop`)
- 実行タイミング:
  - `cron: 0 9 * * 1-5`（UTC）
  - JST では平日 18:00
- 実行内容:
  - `RUNPOD_POD_NAME`（または `RUNPOD_POD_ID`）で Pod を特定
  - 固定ポリシーで `podStop` 実行（ID維持を優先）
  - 任意で Slack 通知

## 4. Pod 内ブートストラップ
### 4.1 `runpod_nv_bootstrap.sh`
主用途: LM Studio + Swallow モデル + API 認証プロキシの復旧。

主要処理:
- 基本パッケージ導入
- `yakulingo` リポジトリ同期（設定で無効化可）
- `lms` 導入
- モデル shard 配置確認と import/link
- `runtime.env`、`.auth_token`、Nginx 設定、`start.sh` 生成
- `AUTO_START=1` 時はそのまま起動

主要環境変数（抜粋）:
- `MODEL_SOURCE_DIR`（既定: `/workspace/models/swallow-120b/IQ4_XS`）
- `MODEL_ID`（既定: `gpt-oss-swallow-120b-iq4xs`）
- `CONTEXT_LENGTH`（既定: `4096`）
- `FAST_START`（`1` で軽量復旧）
- `SYNC_YAKULINGO`、`SKIP_BASE_PACKAGES`

### 4.2 `runpod_lobehub_bootstrap.sh`
主用途: LobeHub 同居 PoC 構成の復旧。

主要処理:
- Node/pnpm 導入
- PostgreSQL + pgvector 構成
- LobeHub 取得・依存解決・マイグレーション
- `next start` または `next dev` で起動
- Basic 認証付き Nginx（既定 `3211`）構築

主要環境変数（抜粋）:
- `LOBE_RUN_MODE`（`start` / `dev`）
- `OPENAI_PROXY_URL`（既定: `http://127.0.0.1:11434/v1`）
- `FAST_START`、`SKIP_PNPM_INSTALL`

## 5. 評価スクリプト実装
### 5.1 Step8 ゲート
- スクリプト: `tools/runpod_eval/step8_gate_check.py`
- 確認対象:
  - `/v1/chat/completions`（one-shot / multi-turn）
  - `/v1/responses`（non-stream / stream）
- 主な成果物:
  - `step8_gate_summary.json`
  - `step8_gate_summary.txt`
  - `chat_gate_oneshot.json`
  - `chat_gate_multi.json`
  - `resp_gate_non_stream.json`
  - `resp_gate_stream.txt`

### 5.2 Step9 性能評価
- スクリプト: `tools/runpod_eval/benchmark_step9.py`
- 指標:
  - 成功率
  - P95 TTFB
  - P95 Total
  - `tok/s` 中央値
- 成果物:
  - raw CSV
  - summary log

### 5.3 会話継続率評価
- スクリプト: `tools/runpod_eval/conversation_continuity_check.py`
- モード:
  - `--api-mode chat`
  - `--api-mode responses`
- 評価内容:
  - 3ターン連続会話でキーワード保持を確認
  - responses モードでは `previous_response_id` 連鎖も確認

### 5.4 Responses 互換プロキシ
- スクリプト: `tools/runpod_eval/responses_chat_proxy.py`
- 役割:
  - `/v1/responses` を upstream `/chat/completions` へ変換
  - stream/non-stream の両方を OpenAI Responses 互換形式で返却

### 5.5 Workflow 実行履歴取得
- スクリプト: `tools/runpod_eval/fetch_workflow_runs.py`
- 役割:
  - `runpod-morning-resume` / `runpod-window-stop` の GitHub Actions 実行履歴を JST 日付で集計

## 6. node_htmx_client 連携
- クライアント: `tools/runpod_eval/node_htmx_client/`
- 起動/停止:
  - `start.bat`
  - `stop.bat`
- 設定の正本:
  - `_internal/.env.example`
- API キー管理:
  - 端末ローカル DPAPI: `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod_api_key.dpapi`
  - 共有難読化鍵: `_internal/runpod_api_key.obf`（任意）
- サーバ API（抜粋）:
  - `GET /health`
  - `GET /api/models/options`
  - `POST /api/chat/form`
  - `POST /api/session/reset`

## 7. 評価の一括実行
- ラッパー: `tools/runpod_eval/run_eval_with_node_htmx.ps1`
- 目的:
  - node_htmx_client の設定/鍵を再利用し、Step8・Step9・継続率を一括実行
- 主なオプション:
  - `-SkipStep8`
  - `-SkipBenchmark`
  - `-SkipContinuity`
  - `-ContinuityApiMode chat|responses`
  - `-OutputDir <path>`

## 8. 必須/主要 Secrets（Workflow 側）
- 必須:
  - `RUNPOD_API_KEY`
  - `RUNPOD_POD_NAME`（または `RUNPOD_POD_ID`）
- 新規作成に必要:
  - `RUNPOD_GPU_TYPE_ID`
  - `RUNPOD_IMAGE_NAME`（または `RUNPOD_TEMPLATE_ID`）
  - `RUNPOD_NETWORK_VOLUME_ID`（Volume 運用時）
- 任意:
  - `RUNPOD_DATA_CENTER_ID`
  - `RUNPOD_DOCKER_START_CMD_JSON`
  - `SLACK_WEBHOOK_URL`

## 9. 運用ルール（現行）
- 日次運用は「朝 resume / 夕方 stop」を基本にする。
- Volume 永続化を前提にし、Pod ID の安定運用を優先する。
- 旧構成や旧検証メモは `docs/runpod/old/` を参照する。

## 10. 更新ポリシー
RunPod 実装を変更した場合は、最低限以下を同時更新する。
- `docs/runpod/RUNPOD_CURRENT_IMPLEMENTATION.md`
- 必要に応じて `docs/runpod/PHASE1_DAY1_WORKLOG_2026-02-23.md`（または後続ログ）
- `tools/runpod_eval/README.md`（実行手順に変更がある場合）
