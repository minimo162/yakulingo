# HF Spaces（ZeroGPU）: 翻訳モデル選定

## 前提
- 目的: Hugging Face Spaces（ZeroGPU）で「日本語 ↔ 英語」のテキスト翻訳デモを公開する。
- 制約:
  - ZeroGPU は GPU が常時使えるとは限らない（GPU 非利用時の挙動を決める必要がある）
  - コールドスタート（初回モデルDL/ロード）を許容しつつ、デモとして成立させる
  - 依存関係は Spaces でインストール可能な範囲に限定する

## 採用モデル（決定）
- `google/translategemma-27b-it`

## 実行方式（決定）
- Transformers で **生成（text-generation）** として翻訳を行う（MarianMT の `translation` pipeline は使用しない）
- ZeroGPU 前提で **量子化を既定** とする
  - 既定: bitsandbytes 4-bit（VRAM 節約）
  - 代替: 8-bit / 非量子化（環境が許す場合）
- GPU が使えない場合:
  - 既定は「エラーで案内」（CPU フォールバックは現実的に遅くなり得るため）
  - デバッグ用途で CPU 許可のフラグを用意する（後続タスクで実装）

## 実装方針（後続タスクで実装）
- モデルは HF Hub から初回ダウンロードしてキャッシュする（`HF_HOME` を推奨）
- 方向ごとにプロンプトを組み立て（JP→EN / EN→JP）、出力は「翻訳文のみ」を要求する
- 出力の後処理（余計な前置き/コードフェンス/ラベル）を実装する
- 入力ガード:
  - 文字数上限（既定: 2,000 文字）を設ける
  - 超過時は UI で短縮を促す

## 推奨の環境変数（Spaces）
- `HF_HOME`（キャッシュ先。永続ストレージを使う場合はそこへ）
- `HF_HUB_DISABLE_TELEMETRY=1`
- `YAKULINGO_SPACES_MODEL_ID`（既定: `google/translategemma-27b-it`）
- `YAKULINGO_SPACES_QUANT`（既定: `4bit`）
- `HF_TOKEN`（モデルが gated の場合）

## ライセンス / 利用条件
- Hugging Face のモデルカードを SSOT とする（Spaces 公開前に必ず確認）
- gated / 同意が必要な場合は、Spaces の Secret に `HF_TOKEN` を設定する
