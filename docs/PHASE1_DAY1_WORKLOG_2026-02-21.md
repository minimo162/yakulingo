# Phase 1 Day1 作業ログ

日付: 2026-02-21  
対象: RunPod セットアップ（将来構想 To-Be 実行）

## ログ

```text
2026-02-21 --:-- | A-1 RunPodアカウント作成 | done | ユーザー実施
2026-02-21 --:-- | A-2-Prep クレジットカード登録 | done | チャージ前の準備完了
2026-02-21 --:-- | A-2 Billing $25チャージ | done | ユーザー実施
2026-02-21 --:-- | A-3 作業ログファイル作成 | done | docs/PHASE1_DAY1_WORKLOG_2026-02-21.md を作成
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
2026-02-21 --:-- | G-2 モデル方針変更 | in_progress | 4090向けに `gpt-oss:20b` を主軸、Swallow-20Bは比較導入
```

## メモ

- 次の着手: `G-3 RTX 4090 Pod の再作成` と `gpt-oss:20b` ベースで再検証
