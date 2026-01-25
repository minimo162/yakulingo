# task-01: 回帰テスト追加（Copilot/バッチ翻訳の billion 混入を固定）

## 目的
- 「billion表記になる」ケースを **自動テストで再現** し、修正後に二度と戻らないように固定する。
- 特にファイル翻訳で使われる `BatchTranslator`（Copilot `translate_sync`）経路をカバーする。

## 想定所要（タイムボックス）
- 15〜60分

## 変更対象（予定）
- `tests/`（新規 or 既存ファイル拡張）
  - 既存の類似テスト（例: `tests/test_batch_translation_output_language_retry.py`）のパターンを踏襲

## テスト設計（例）
- **Case A（ラベル誤りの典型）**
  - 入力: `売上高は22,385億円。`
  - Copilot 返答（初回）: `Net sales were 22,385 billion yen.`
  - 期待: 最終結果が `22,385 oku yen` になり、`billion` が残らない（自動補正で直る）
- **Case B（自動補正できない）**（必要なら）
  - 入力: `売上高は22,385億円。`
  - Copilot 返答（初回）: `Net sales were 22,384 billion yen.`
  - 期待: 数値ルールの再試行が走り、最終的に `oku` に収束（または安全に失敗扱い）

## 作業手順
1. `BatchTranslator.translate_blocks_with_result()` の入力（`TextBlock`）を最小で組む
2. ダミーCopilot（`translate_sync` を持つ）で「billionを返す」挙動を再現
3. 期待値を **最小限** にする（`billion` を含まない、`oku` を含む、など）
4. テストが今は落ちる状態（RED）を確認（task-02 で直す）

## DoD
- 失敗を再現するテストが追加され、修正前は落ちる（または期待通りに未実装箇所を示す）
- テストは外部依存なしで安定（モック/ダミーで完結）
