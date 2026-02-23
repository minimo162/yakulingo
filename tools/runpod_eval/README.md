# RunPod 検証ツール

このディレクトリは、YakuLingo 本体機能ではなく RunPod 検証専用の補助ツールを格納する。

## 目的

- RunPod 上の LM Studio / API 疎通確認
- 性能測定（Step 9）
- 会話継続率測定
- `responses -> chat` 変換プロキシ検証
- RunPod 復旧/同居ブートストラップ

## 主なスクリプト

- `tools/runpod_eval/step8_gate_check.py`
- `tools/runpod_eval/benchmark_step9.py`
- `tools/runpod_eval/conversation_continuity_check.py`
- `tools/runpod_eval/responses_chat_proxy.py`
- `tools/runpod_eval/runpod_nv_bootstrap.sh`
- `tools/runpod_eval/runpod_lobehub_bootstrap.sh`
- `tools/runpod_eval/run_eval_with_node_htmx.ps1`

## 関連ドキュメント

- `docs/runpod/`
