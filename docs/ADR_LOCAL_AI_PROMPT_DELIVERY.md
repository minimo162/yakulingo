# ADR: ローカルAIでのSSOTプロンプト送信方式（chat/completions vs completions）

## 結論
- **採用: 方針B（`/v1/completions` を追加し、raw prompt をそのまま送る）**

## 背景
- YakuLingo のローカルAIは llama.cpp の `llama-server`（OpenAI互換）を使用している。
- 現状の実装は `POST /v1/chat/completions` に **messages**（`role=user`）で送信しており、**chat template が適用される**。
- 今回のSSOTプロンプトは `<bos><start_of_turn>...<end_of_turn>...` を含む（TranslateGemma/Gemma系の会話テンプレ前提）。

## 問題（cross-template / 二重適用）
- `chat/completions` はモデル（または指定）由来の chat template で prompt へ変換する。
- そのため、**ユーザーメッセージ本文に `<bos><start_of_turn>...` を埋め込むと、chat template 次第で二重にテンプレが適用**され、意図しないトークン列になり得る。
- llama.cpp `llama-server` は chat template を既定で有効にしており、CLIにも `--chat-template`/`--chat-template-file` が存在する（= chat template 変換が前提のインタフェース）。

## 検討した方針
### 方針A: `chat/completions` 継続（SSOTの文字列は「例」とみなす）
- メリット: 実装変更が最小
- デメリット: SSOTの「そのまま送る」要求に反する／テンプレ差分が出る可能性が残る

### 方針B: raw prompt を送れる経路を追加（`/v1/completions` 等）
- メリット: SSOT（`<bos>...` を含む）を **文字列どおり**に送れる。二重テンプレ問題を回避できる。
- デメリット: `LocalAIClient` に completions 経路（+ streaming 対応の要否）を追加する実装が必要

## 採用理由（方針B）
- SSOTプロンプトを **厳密一致**で送る要件を満たすため。
- `chat/completions` の chat template 変換はモデル依存であり、SSOT文字列を本文に入れる方式だと二重適用のリスクが消えないため。

## 影響範囲 / フォローアップ
- 実装は task-02 で行う（`LocalAIClient` に `/v1/completions` 経路を追加し、SSOTプロンプト時に使用）。
- 既存の `chat/completions` 経路は、SSOTでない通常プロンプト（または将来のJSONスキーマ系）で継続利用する。
- テスト（promptパススルー/echo除去）とドキュメント（SSOT記述）を task-02〜05 で更新する。

