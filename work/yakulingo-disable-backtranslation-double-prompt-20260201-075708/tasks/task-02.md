# Task 02: 翻訳サービスから3pass戻し訳パイプラインを削除し、呼び出し元を更新

## 目的

- `translate_text_with_backtranslation_review()`（3pass: translation → back translation → revision）を廃止する。
- 呼び出し元（モード分岐、ストリーミングイベント、結果メタデータ）を戻し訳無しの設計に更新する。

## 変更対象（想定）

- `yakulingo/services/translation_service.py`
  - 戻し訳パイプライン関数・関連データ構造・イベント/メタデータの整理
  - 影響する呼び出し元の更新
- `tests/`（戻し訳パイプラインに依存するテストの更新/削除）

## 非対象

- PromptBuilder / prompts の整理（task-04）
- UI表示整理（task-05）
- プロンプト二重送信の適用（task-03）

## 実装方針

- 戻し訳パス（pass2/pass3）を前提とする `TextTranslationPass` の扱いを整理する。
- 既存の「concise mode（翻訳→簡潔化）」が必要なら、それは残す（戻し訳ではないため）。
- `metadata["text_translation_mode"]` 等、UI/履歴で参照される値は壊さないか、互換マッピングを入れる。

## テスト観点

- 戻し訳関連のテストは、機能廃止に合わせて削除/置換（「戻し訳が走る」前提を撤廃）
- 既存のテキスト翻訳（JP→EN 3スタイル、EN→JP単一）と concise が維持される

## DoD

- typecheck: `uv run --extra test pyright`
- lint: `uv run --extra test ruff check .`
- tests: `uv run --extra test pytest`
- PR-merge → ブランチ削除（remote+local）→ 削除証明

