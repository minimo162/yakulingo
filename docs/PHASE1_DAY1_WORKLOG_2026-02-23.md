# Phase 1 Day1 作業ログ

日付: 2026-02-23  
対象: RunPod GPT-OSS-Swallow-120B IQ4_XS 2週間検証（引き継ぎ再開）

## 事前確認

- [x] `docs/RUNPOD_GPTOSS_SWALLOW_IQ4XS_2WEEK_EVAL.md` の引き継ぎメモ（2026-02-22, 2026-02-23）を確認
- [x] `.github/workflows/runpod-morning-resume.yml` の実装確認（`REST /v1/pods` 作成・`networkVolumeId` ガード・警告検知）
- [x] `.github/workflows/runpod-window-stop.yml` の実装確認（`terminate/stop` 分岐）
- [x] GitHub公開APIで 2026-02-23 の Actions 実行履歴を取得（Run ID / SHA / 成否）
- [x] Pod 自動起動成功を確認（ユーザー報告）
- [x] GitHub Secrets 更新（`RUNPOD_DATA_CENTER_ID`, `RUNPOD_GPU_TYPE_ID`, `RUNPOD_NETWORK_VOLUME_ID`）
- [x] `runpod-morning-resume` 手動実行（`workflow_dispatch` 成功履歴を確認）
- [x] `networkVolumeId` 一致確認（`eu-se-1-a40x2-workspace` 設定を確認）
- [x] `nv_canary` 永続化確認（`window-stop` -> `morning-resume`、値一致: `nv-canary-2026-02-23-011150`）
- [ ] 必要時リージョン切替（`US-MO-1` or `EU-FR-1`）

## RunPod 自動化ログ（2026-02-23 JST）

- runpod-morning-resume
  - 実行種別: `workflow_dispatch`（最新） / `schedule`
  - GitHub Actions Run ID: `22289428434`（workflow_dispatch, 10:07 JST）
  - Head SHA: `da5ec59fc5b71fdacfa6f428800b4a8b6b86aa82`
  - 結果: `completed/success`
  - サマリ: Secrets設定後の `workflow_dispatch` で Pod 作成成功を確認（Run ID: `22289428434`）
  - 参考: `runpod-morning-resume` が 2026-02-23 JST で連続成功（Run IDs: `22289428434`, `22288243386`, `22287458821`, `22287379762`, `22287299598`）
  - 追記: Pod自動起動は成功（ユーザー確認）
  - 追記: Network Volume は `eu-se-1-a40x2-workspace` が設定されていることを確認（ユーザー確認）
  - Pod ID: （未取得: Actionsログ本文の取得は認証付きAPIが必要）
  - `create config` 抜粋: （未取得: 同上）
  - Run URL（代表）: `https://github.com/minimo162/yakulingo/actions/runs/22289428434`

- runpod-window-stop
  - 実行種別: `workflow_dispatch`（2026-02-23 JST 実績）
  - GitHub Actions Run ID: `22286793260`（07:32 JST）
  - Head SHA: `eb19c806961b280f99c063268bdd2d2978048002`
  - 結果: `completed/success`
  - サマリ: 2026-02-23 JST の `workflow_dispatch` 実行が成功（Run IDs: `22286793260`, `22286241852`, `22285651487`）
  - Pod ID: （未取得: Actionsログ本文の取得は認証付きAPIが必要）
  - Run URL（代表）: `https://github.com/minimo162/yakulingo/actions/runs/22286793260`

## 永続化検証（nv_canary）

```text
1) Pod内で作成:
   echo "nv-canary-2026-02-23-011150" > /workspace/nv_canary.txt

2) runpod-window-stop 実行後:
   Podが停止/削除されたことを確認

3) runpod-morning-resume 実行後:
   cat /workspace/nv_canary.txt
   => 実測値: nv-canary-2026-02-23-011150
   => 判定: OK（Network Volume 永続化成功）
```

## メモ

- 取得スクリプト: `python tools/runpod_eval/fetch_workflow_runs.py --date-jst 2026-02-23`
- `GET /actions/runs/{run_id}/logs` は認証なしだと `403` のため、`Pod ID` と `create config` の確定には `GITHUB_TOKEN` 付き取得が必要。
- `US-KS-2` で `critical error on this machine` が再発した場合は、`RUNPOD_DATA_CENTER_ID` を `US-MO-1` または `EU-FR-1` に切替して再試行する。
- Secrets 更新時は `RUNPOD_NETWORK_VOLUME_ID` のリージョン整合性を最優先で確認する。

## LobeHub PoC 進捗（同一Pod同居、2026-02-23）

- [x] `pnpm install` 完了（`Done in 15m 37.5s`）
- [x] `pnpm approve-builds` で必要ビルド許可（`@swc/core`, `better-sqlite3`, `esbuild`, `onnxruntime-node`, `sharp`）
- [x] `pnpm rebuild` 完了
- [x] `pnpm exec next dev -H 0.0.0.0 -p 3210` で起動確認
- [x] `KEY_VAULTS_SECRET` 不足エラーの解消
- [x] `DATABASE_URL` 必須エラーの切り分け完了（LobeHub 2.x はDB必須）
- [x] 同一Pod内 PostgreSQL 接続確認（`DB OK`）
- [x] `pnpm db:migrate` 成功（`database migration pass`）
- [ ] `curl http://127.0.0.1:3210/` の `200` 最終確認
- [ ] LobeHub UI から `OPENAI_PROXY_URL=http://127.0.0.1:11434/v1` 経由の対話確認

### LobeHub PoC 補足

- `pnpm dev --host ...` は失敗（`next dev` が `--host` 非対応）するため、`pnpm exec next dev -H 0.0.0.0 -p 3210` を使う。
- `DATABASE_URL` にプレースホルダ（`<user>` 形式）を入れると `source` が失敗する。必ず実URLを設定する。
- 起動時に `@grpc/grpc-js` 由来の `stream` 解決エラーが出る場合があり、`--webpack` 起動固定で再試行する。
