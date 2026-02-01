# HF Spaces（ZeroGPU）: 翻訳モデル選定

## 前提
- 目的: Hugging Face Spaces（ZeroGPU）で「日本語 ↔ 英語」のテキスト翻訳デモを公開する。
- 制約:
  - GPU が常時使えるとは限らない（CPU フォールバックが必要）
  - コールドスタート（初回モデルDL/ロード）を許容しつつ、できるだけ軽量にする
  - 依存関係は Spaces でインストール可能な範囲に限定する

## 候補
### 1) OPUS / MarianMT（採用）
- `Helsinki-NLP/opus-mt-ja-en`（日本語→英語）
- `Helsinki-NLP/opus-tatoeba-en-ja`（英語→日本語）
- 利点:
  - 比較的軽量で、CPU でも動作しやすい
  - Transformers（PyTorch）で実装できる
  - ライセンスが明記されており、デモ公開の説明がしやすい

### 2) NLLB / M2M100（不採用）
- `facebook/nllb-200-distilled-600M` / `facebook/m2m100_418M` など
- 不採用理由:
  - モデルが重く、ZeroGPU + コールドスタート前提のデモでは体験が不安定になりやすい

## 採用モデル（決定）
- 日本語 → 英語: `Helsinki-NLP/opus-mt-ja-en`
- 英語 → 日本語: `Helsinki-NLP/opus-tatoeba-en-ja`

## 実装方針（task-02 で実装）
- Transformers を使用し、モデルは HF Hub から初回ダウンロードしてキャッシュする
- device 選択:
  - `torch.cuda.is_available()` が真なら GPU を優先（可能なら fp16）
  - それ以外は CPU（fp32）
- 入力ガード:
  - 文字数上限（例: 2,000 文字）を設ける
  - 超過時は UI で短縮を促す

## 推奨の環境変数（Spaces）
- `HF_HOME`（キャッシュ先。永続ストレージを使う場合はそこへ）
- `HF_HUB_DISABLE_TELEMETRY=1`
- `YAKULINGO_SPACES_MODEL_JA_EN`（既定: `Helsinki-NLP/opus-mt-ja-en`）
- `YAKULINGO_SPACES_MODEL_EN_JA`（既定: `Helsinki-NLP/opus-tatoeba-en-ja`）

## ライセンス（モデルカード参照）
- `Helsinki-NLP/opus-mt-ja-en`: Apache-2.0
- `Helsinki-NLP/opus-tatoeba-en-ja`: Apache-2.0

