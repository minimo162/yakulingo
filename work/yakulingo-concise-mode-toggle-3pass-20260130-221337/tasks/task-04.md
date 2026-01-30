# task-04: 同一言語“abbreviation多用”簡潔化プロンプト（英/日）＋安全ガード

見積: 30–60分

## ゴール
- 2回目/3回目で使用する「同一言語の簡潔化」プロンプトを実装する。
- abbreviation多用（intent）を満たしつつ、出力言語の逸脱/ラベル混入/入力反復を抑制する。

## 変更範囲（ファイル）
- 触る:
  - `yakulingo/services/prompt_builder.py`（生成API追加）
  - `prompts/`（テンプレ化する場合のみ）
  - `yakulingo/services/translation_service.py`（プロンプトの適用とガード）
- 触らない:
  - 既存のファイル翻訳プロンプト（`file_translate_*`）は原則変更しない

## 実装方針（推奨）
- リライト対象は「1回目/2回目の訳文」そのもの（入力原文ではない）。
- 出力は **本文のみ**（Translation:等のラベル禁止）を徹底。
- 英語/日本語それぞれで「同一言語で出力する」ガード文を入れる。

## 手順
1. `PromptBuilder`に `build_concise_rewrite_prompt(text, output_language, pass_index)` を追加
2. `TranslationService`側で2回目/3回目に適用
3. 出力が空/言語不一致の場合のフォールバックを定義（例: 直前の成功結果を採用）

## 検証
- `uv run --extra test pyright`
- `uv run --extra test ruff check .`
- `uv run --extra test pytest`

## DoD（完了条件）
- 2回目/3回目が「同一言語の簡潔化」プロンプトで動作する
- 出力形式の逸脱が起きにくい（テストで最低限担保）
- typecheck/lint/testが全て通る
