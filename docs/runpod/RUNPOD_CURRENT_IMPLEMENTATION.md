# RunPod 現行実装（2026-02-24）

## 1. 目的
`tools/runpod_eval/node_htmx_client` を使い、ローカルは薄いラッパーのまま、推論は RunPod 側で完結させる。

## 2. 現行アーキテクチャ
- 推論基盤: **Ollama on RunPod**
- 公開経路: `https://<pod-id>-11434.proxy.runpod.net/v1`
- 認証: Nginx 前段で `x-api-key` / `Authorization: Bearer`
- ローカル UI: FastAPI + HTMX
- 内部エンジン: Node (`_internal/server.mjs`)
- live-web: Playwright 連携を **サーバー関数実行**で利用

## 3. 主要環境変数（標準）
- `RUNPOD_INFERENCE_PROVIDER=ollama`
- `RUNPOD_API_KEY=<gateway token>`
- `RUNPOD_UPSTREAM_API_KEY=<optional upstream bearer>`
- `CODEX_PROVIDER_ID=ollama-runpod`
- `CODEX_WIRE_API=chat`
- `LIVE_WEB_TOOL_EXEC_MODE=engine_primary`
- `LIVE_WEB_REQUIRE_EVIDENCE=1`
- `CODEX_EXEC_ROUTE_MODE=resilient`

## 4. 非推奨（使用しない）
- `RUNPOD_LMSTUDIO_CHAT_*`
- `CODEX_LMSTUDIO_PROVIDER_ID`
- `WEATHER_VERIFIED_FETCH_*`（Open-Meteo 検証経路）
- `LMSTUDIO_API_TOKEN`

## 5. RunPod ブートストラップ
- `tools/runpod_eval/runpod_nv_bootstrap.sh`
  - Ollama インストール/起動
  - Nginx `:11434 -> 127.0.0.1:11435`
  - Playwright MCP 同居（`127.0.0.1:8931`）
  - 起動ゲート:
    - `/v1/models`
    - `/v1/chat/completions`

## 6. live-web 品質要件（天気）
- 最終回答に以下を必須化
  - `source_url`
  - `page_date_text`
  - `requested_date`
- 証跡不足時は再取得 1 回。未解決なら失敗を明示（捏造禁止）。

## 7. 動作確認手順（最短）
1. `start.bat` 実行
2. `/health` 確認
   - `service=fastapi-htmx-client`
   - `inference_provider=ollama`
3. `こんにちは` で通常応答
4. `今日の広島の天気を調べて`
   - 進行ログに `外部情報取得`
   - 最終回答に `source_url`, `page_date_text`, `requested_date`
   - `plugin権限不足` が出ない

## 8. 既知の注意点
- Pod 再作成直後はモデル準備に時間がかかる。
- `MODEL_PULL_ENABLED=1` で pull が失敗する場合は、`MODEL_CREATE_FROM_GGUF=1` + `MODEL_SOURCE_DIR` を利用する。
