# LocaLingo (RunPod Ollama Client)

`tools/runpod_eval/node_htmx_client` は、ローカル PC から RunPod 上の Ollama に接続するための軽量クライアントです。
UI は FastAPI + HTMX、内部エンジンは Node (`_internal/server.mjs`) です。

## 現在の前提
- 推論基盤: **RunPod Ollama**
- 公開 URL: `https://<pod-id>-11434.proxy.runpod.net/v1`
- live-web: **サーバー関数ツール実行**（Playwright 連携）
- LM Studio plugin / ephemeral_mcp は使用しません

## 起動
1. `start.bat` を実行
2. 初回は `_internal/.env.local` を作成（テンプレートは `_internal/.env.local.example`）
3. 必須設定
   - `RUNPOD_BASE_URL=https://<pod-id>-11434.proxy.runpod.net/v1`
   - `RUNPOD_API_KEY=__USE_DPAPI__`（DPAPI 管理推奨）

## 主要設定（.env）
- `RUNPOD_INFERENCE_PROVIDER=ollama`
- `RUNPOD_UPSTREAM_API_KEY=`（空なら `RUNPOD_API_KEY` を流用）
- `CODEX_PROVIDER_ID=ollama-runpod`
- `CODEX_WIRE_API=chat`
- `CODEX_EXEC_ROUTE_MODE=resilient`
- `LIVE_WEB_TOOL_EXEC_MODE=engine_primary`
- `LIVE_WEB_REQUIRE_EVIDENCE=1`
- `CODEX_TOOL_FALLBACK_TO_ENGINE=1`
- `CODEX_TOOL_FALLBACK_FORCE_FOR_LIVE_WEB=1`

## live-web の品質ルール（天気）
- 最終回答に以下を必須化
  - `source_url`
  - `page_date_text`
  - `requested_date`
- 証跡不足時は 1 回だけ再取得し、再度不足なら取得失敗を明示

## ヘルスチェック
`start.bat` 後に以下を確認します。

- `GET /health`
  - `service=fastapi-htmx-client`
  - `inference_provider=ollama`
  - `live_web_tool_exec_mode=engine_primary`

## 手動疎通確認（例）
```powershell
$TOKEN = "<your token>"
curl -sS http://127.0.0.1:11434/v1/models -H "x-api-key: $TOKEN"
curl -sS http://127.0.0.1:11434/v1/chat/completions `
  -H "x-api-key: $TOKEN" -H "Content-Type: application/json" `
  -d '{"model":"gpt-oss-swallow-120b-iq4xs","messages":[{"role":"user","content":"こんにちは"}]}'
```

## 補足
- 旧 LM Studio 向け設定（`RUNPOD_LMSTUDIO_CHAT_*`, `CODEX_LMSTUDIO_PROVIDER_ID` など）は非推奨です。
- Open-Meteo 検証経路は使いません（Playwright 経路のみ）。
