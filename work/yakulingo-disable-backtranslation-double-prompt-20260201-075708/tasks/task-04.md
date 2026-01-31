# Task 04: 戻し訳用プロンプト/テンプレート/PromptBuilderを整理し、テストを更新

## 目的

- 戻し訳用テンプレート（back translate / revision）と、それを組み立てる `PromptBuilder` のAPIを削除する。
- それに依存するテストを更新する（削除/置換）。

## 変更対象（想定）

- `yakulingo/services/prompt_builder.py`
  - `build_back_translation_prompt()` / `build_translation_revision_prompt()` の削除
  - 参照箇所の削除（呼び出し元は task-02 で落ちている前提）
- `prompts/`
  - `text_back_translate*.txt`
  - `text_translate_revision_to_*.txt`
  - `text_back_translate.txt`
- `tests/`
  - PromptBuilder/戻し訳テンプレに依存するテストの整理

## 実装方針

- テンプレート削除は「使われなくなったこと」を確認した上で行う（task-02 完了が前提）。
- プロンプトテンプレの削除でアプリ起動時に参照されないこと（遅延ロード/読み込み時点）を確認する。

## DoD

- typecheck: `uv run --extra test pyright`
- lint: `uv run --extra test ruff check .`
- tests: `uv run --extra test pytest`
- PR-merge → ブランチ削除（remote+local）→ 削除証明

