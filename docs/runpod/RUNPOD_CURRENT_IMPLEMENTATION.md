# RunPod 現行実装サマリ（2026-02-24 JST）

## 1. このドキュメントの範囲
本書は、`tools/runpod_eval/node_htmx_client` を中心とした RunPod 連携の「現在の実装」を運用者向けに要約したものです。  
特に、`codex exec --json` を中核にした構成を正本として扱います。

## 2. 現在の実行アーキテクチャ

### 2.1 全体像
- RunPod 側: LM Studio API を `https://<pod-id>-11434.proxy.runpod.net/v1` で公開
- ローカル側: FastAPI + HTMX + Alpine.js + Tailwind UI
- 推論経路: FastAPI から `codex exec --json` を実行し、Codex CLI が RunPod (LM Studio) へ接続

### 2.2 重要な前提
- モデル選択はサーバ設定固定（UI選択なし）
- バックエンドは `codex_cli` 固定
- `CODEX_REQUIRE_BUNDLED=1` により同梱 codex を優先使用

## 3. 実行・起動フロー

### 3.1 起動エントリ
- `tools/runpod_eval/node_htmx_client/start.bat`
- 実体は `_internal/start.ps1`

### 3.2 起動時の処理
- `.env.local` -> `.env.example` 順で設定読み込み
- RunPod 接続テスト (`/v1/models`) をリトライ付きで実施
- 同梱ランタイム不足時に自動準備
  - codex (`.runtime/codex`)
  - Node (`.runtime/node`)
  - uv/Python (`.runtime/uv`, `.runtime/python-managed`)
- 旧プロセスが残っている場合は PID を見て停止してから再起動
- FastAPI 起動後にブラウザを開く

## 4. 設定と認証情報

### 4.1 設定ファイル
- 共有既定値: `tools/runpod_eval/node_htmx_client/_internal/.env.example`
- 個人設定（非追跡）: `tools/runpod_eval/node_htmx_client/_internal/.env.local`

### 4.2 APIキー
- 優先: DPAPI 保管  
  `%LOCALAPPDATA%\YakuLingoRunpodHtmx\runpod_api_key.dpapi`
- 代替: 共有難読化ファイル  
  `tools/runpod_eval/node_htmx_client/_internal/runpod_api_key.obf`

### 4.3 ワークスペース状態
- `%LOCALAPPDATA%\YakuLingoRunpodHtmx\workspace-state.json`
- UIで選択したワークスペースは次回起動時に復元される

## 5. Codex CLI と RunPod 接続設定

### 5.1 主要環境変数（既定）
- `CODEX_EXEC_MODEL=gpt-oss-swallow-120b-iq4xs`
- `CODEX_LMSTUDIO_PROVIDER_ID=lmstudio-runpod`
- `CODEX_NATIVE_MODE=1`
- `CODEX_PROVIDER_REQUEST_MAX_RETRIES=1`
- `CODEX_PROVIDER_STREAM_MAX_RETRIES=1`
- `CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS=45000`
- `CODEX_MODEL_CONTEXT_WINDOW=32768`
- `CODEX_PROMPT_MAX_CHARS=12000`

### 5.2 生成される Codex 設定の要点
FastAPI 側で `config.toml` を動的生成し、以下方針を適用します。
- `model_provider = "lmstudio-runpod"`
- `oss_provider = "lmstudio"`
- ベース URL は `RUNPOD_BASE_URL`（必要に応じて候補 URL へフェイルオーバー）

## 6. 安定化ロジック（現行）

### 6.1 RunPod 通信安定化
- ルート健全性プローブ  
  `RUNPOD_ROUTE_PROBE_ENABLED=1`
- 候補 URL フェイルオーバー  
  `RUNPOD_BASE_URL_CANDIDATES`
- HTTP リトライ  
  `RUNPOD_HTTP_RETRY_MAX_ATTEMPTS=5`

### 6.2 起動時接続テスト
- 既定モード: `RUNPOD_CONNECTION_TEST_MODE=strict`
- 既定リトライ: 4回、待機2秒、タイムアウト8秒

### 6.3 ストリーム保護
- 進捗 ping 出力  
  `CODEX_EXEC_PROGRESS_PING_INTERVAL_MS=8000`
- keepalive  
  `STREAM_KEEPALIVE_INTERVAL_MS=10000`
- Responses background poll 併用  
  `RUNPOD_RESPONSES_BACKGROUND_ENABLED=1`

## 7. ツール実行ポリシー

### 7.1 ファイル操作制約
- `read` / `read_file`: ワークスペース外も読取可、`http(s)` URL 読取可
- `list_dir` / `write` / `apply_patch`: 選択中ワークスペース内のみ

### 7.2 Office/PDF 対応
- 読み取り: `.pdf`, `.xlsx`, `.docx`, `.pptx`
- 書き込み: `.xlsx`, `.docx`, `.pptx`（JSON/テキスト入力を受け付け）

## 8. 主要 API（FastAPI）
- `GET /health`
- `GET /api/models/options`
- `POST /api/chat/form`
- `POST /api/session/reset`
- `GET|POST /workspace/{path}`

## 9. RunPod 自動運用（GitHub Actions）
- 朝起動: `.github/workflows/runpod-morning-resume.yml`
- 夕方停止: `.github/workflows/runpod-window-stop.yml`
- Pod の resume/stop と通知運用を定時化

## 10. 関連ドキュメント
- 現行サマリ: `docs/runpod/RUNPOD_CURRENT_IMPLEMENTATION.md`（本書）
- 評価計画/結果: `docs/runpod/RUNPOD_GPTOSS_SWALLOW_IQ4XS_2WEEK_EVAL.md`
- 当日ログ: `docs/runpod/PHASE1_DAY1_WORKLOG_2026-02-23.md`
- 旧資料: `docs/runpod/old/`

## 11. 更新ルール
RunPod 実装変更時は、最低限以下を同一PR/同一コミット系で更新します。
- `docs/runpod/RUNPOD_CURRENT_IMPLEMENTATION.md`
- 必要に応じて `docs/runpod/README.md`
- 実行手順変更がある場合 `tools/runpod_eval/node_htmx_client/README.md`
