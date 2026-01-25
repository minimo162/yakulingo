# task-02: 修正実装（バッチ翻訳/ファイル翻訳経路での数値ルール整合）

## 目的
- Copilot バッチ翻訳（ファイル翻訳で利用）でも、JP→EN の数値ルールが確実に適用されるようにする。
- 具体的には `billion/bn/trillion` を残さず、可能なら **自動補正で無通信修正**、難しければ **最小回数で再試行** する。

## 想定所要（タイムボックス）
- 15〜60分

## 変更対象（予定）
- `yakulingo/services/translation_service.py`（`BatchTranslator` 周辺）

## 実装方針（候補）
- 方針A（最小・安全）: Copilot バッチ翻訳の各アイテムに対して
  - `_fix_to_en_oku_numeric_unit_if_possible()` を適用（source_text と訳文を突き合わせて安全に置換）
  - それでも `billion/bn/trillion` が残る場合のみ「数値ルール再試行」を発動
- 方針B（プロンプトで予防）:
  - バッチの入力内に億/兆が存在する場合、最初から `_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION` と `_build_to_en_numeric_hints()` を `prompt` に注入
  - ただし prompt サイズ増を避けるため、ヒントは上限付き（例: 12行）で運用

## 作業手順
1. task-01 のテストが通るように `BatchTranslator` の後処理/再試行に数値ルールを組み込む
2. 既存の「出力言語ミスマッチ再試行」と整合するように、再試行回数・対象アイテム数・文字数上限を設定
3. 既存のテキスト翻訳（`_translate_text_with_options_on_copilot`）と矛盾しないように挙動を合わせる

## DoD
- task-01 の回帰テストが通る
- `billion/bn/trillion` が残らない（少なくとも定義した再現ケースで）
- 不要なCopilot再呼び出しを増やしていない（必要時のみ再試行）
