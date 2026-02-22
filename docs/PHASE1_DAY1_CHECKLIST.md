# Phase 1 Day1 チェックリスト

用途: RunPodデモ開始日の実行手順（最短）

## A. 準備

- [x] RunPodアカウント作成
- [x] Billingで `$25` チャージ
- [x] 作業ログファイル作成（時刻と結果を残す）

## B. Pod作成

- [x] GPU: `A100 PCIe 80GB`
- [x] Template: `RunPod PyTorch 2.8`
- [x] SSH Terminal Access: `OFF`（暫定）
- [x] Expose Ports: `11434,8080`
- [x] Container Disk: `20GB`
- [x] Volume Disk: `100GB`
- [x] Env: `OLLAMA_HOST=0.0.0.0`
- [x] Deploy実行

## C. 初期セットアップ

- [x] Web Terminal接続
- [x] Ollamaインストール
- [x] `ollama serve` 起動
- [x] `curl http://localhost:11434` で応答確認

## D. モデル準備（最低限）

- [x] `gpt-oss:120b` pull（テンプレ抽出）
- [x] Swallow GGUFダウンロード開始
- [x] Modelfile作成
- [x] `gpt-oss-swallow:120b` 作成
- [ ] 日本語プロンプトで応答確認（Swallowは現在blocked）

## D'. フォールバック実測（A100での事実）

- [x] `gpt-oss:120b` API応答確認（`/api/generate`）
- [x] 初回遅延の内訳確認（`load_duration` が支配的）
- [x] ウォーム時の速度確認（`~0.7s` 台）
- [x] 5秒要件は「ウォーム運用」なら満たせることを確認

## E. 認証

- [ ] `AUTH_TOKEN` 生成と保存（`/workspace/.auth_token`）
- [ ] Basic認証作成（`/workspace/.htpasswd`）
- [ ] Nginx設定配置（`/workspace/nginx-auth-proxy.conf`）
- [ ] `11434` 認証付き疎通確認

## F. Day1 完了条件

- [ ] 公式モデルで応答成功（Swallow成功は必須条件から除外）
- [ ] API認証成功（401/200の切り分け確認）
- [ ] 明日の残タスクを3行で記録

## G. 方針変更（2026-02-21）

- [x] デモ基盤を `RTX 4090` 単一GPU前提に変更する意思決定
- [x] 120B中心の説明を補助位置づけへ変更（参考デモ扱い）
- [ ] 新Podを `RTX 4090 24GB` で再作成
- [ ] モデル方針を `gpt-oss:20b` 主軸へ変更（Tool Use/コーディング）
- [ ] 翻訳品質強化は `Swallow-20B` を比較導入（任意）
- [ ] KPI再計測（品質8/10、5秒以内、5人100回）を4090構成で記録

## 実行ログ（追記用）

```text
YYYY-MM-DD HH:MM | step | result | note
2026-02-21 --:-- | A-1 RunPodアカウント作成 | done | ユーザー実施
2026-02-21 --:-- | A-2-Prep クレジットカード登録 | done | チャージ前の準備完了
2026-02-21 --:-- | A-2 Billing $25チャージ | done | ユーザー実施
2026-02-21 --:-- | A-3 作業ログファイル作成 | done | docs/PHASE1_DAY1_WORKLOG_2026-02-21.md
2026-02-21 --:-- | B-1 GPU選択 | done | A100 PCIe 80GB
2026-02-21 --:-- | B-1b Template選択 | done | RunPod PyTorch 2.8
2026-02-21 --:-- | B-1c SSH設定 | done | SSH Terminal Accessは暫定OFF
2026-02-21 --:-- | B-2 Expose Ports設定 | done | 11434,8080
2026-02-21 --:-- | B-3 Container Disk設定 | done | 20GB
2026-02-21 --:-- | B-4 Volume Disk設定 | done | 100GB
2026-02-21 --:-- | B-5 Env設定 | done | OLLAMA_HOST=0.0.0.0
2026-02-21 --:-- | B-6 Deploy実行 | done | Podデプロイ開始
2026-02-21 --:-- | C-1 Web Terminal接続 | done | Pod内ターミナル接続完了
2026-02-21 --:-- | C-2 Ollamaインストール | done | systemd非稼働警告あり（手動起動で運用）
2026-02-21 --:-- | C-3 ollama serve起動 | done | バックグラウンド起動
2026-02-21 --:-- | C-4 API疎通確認 | done | pull/show成功により11434疎通確認
2026-02-21 --:-- | D-1 gpt-oss取得/テンプレ抽出 | done | /workspace/official-gptoss-modelfile.txt 作成
2026-02-21 --:-- | C-3b 再接続後ollama再起動 | done | セッション切断後に再起動（PID 7482）
2026-02-21 --:-- | C-4b API再疎通確認 | done | curlで `Ollama is running` を確認
2026-02-21 --:-- | D-2a Swallow取得試行 | blocked | `huggingface-cli` コマンド未検出（`hf`へ切替）
2026-02-21 --:-- | D-2b Swallow取得開始 | in_progress | `hf download` で 24% (15.9G/66.2G)
2026-02-21 --:-- | D-2c Swallow取得完了 | done | 66.2GB ダウンロード完了（6 files）
2026-02-21 --:-- | D-3 Modelfile作成 | done | GGUF_PATH確定後に /workspace/Modelfile-swallow 再生成
2026-02-21 --:-- | D-4 モデル登録 | done | `ollama create` success / `ollama list` 反映
2026-02-21 --:-- | D-4b サイズ注意 | todo | `ollama list` 上は 11GB 表示のため実行品質で要検証
2026-02-21 --:-- | D-5 実行テスト | blocked | `ollama run gpt-oss-swallow:120b` が 500 で失敗（model failed to load）
2026-02-21 --:-- | D-5a split統合試行 | blocked | merged作成で `Disk quota exceeded`（100GB上限超過）
2026-02-21 --:-- | D-5b splitリンク再登録 | blocked | 依然11GB表示 / 実行500
2026-02-21 --:-- | D-5c root cause | done | Swallow分割GGUFをOllamaが正しくロードできず
2026-02-21 --:-- | D-6a フォールバックpull | done | `ollama pull gpt-oss:120b` success
2026-02-21 --:-- | D-6b フォールバック実行テスト | done | `/api/generate` で応答確認（初回~3分、ウォーム~0.7秒）
2026-02-21 --:-- | G-1 方針決定 | done | デモは RTX 4090 単一GPU 前提に変更
2026-02-21 --:-- | G-2 モデル方針 | in_progress | 4090向けに `gpt-oss:20b` 主軸へ再構成
```
