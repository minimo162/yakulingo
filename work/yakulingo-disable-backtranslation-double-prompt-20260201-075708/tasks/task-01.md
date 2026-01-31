# Task 01: 設定/モード/ルーティングから戻し訳モードを廃止（互換考慮）

## 目的

- テキスト翻訳の「戻し訳」モード（例: `standard` が backtranslation に流れる等）を廃止し、設定/UI/ルーティングを一貫させる。
- 可能な範囲で互換（既存の設定値が残っていてもアプリが壊れない）を担保する。

## 変更対象（想定）

- `yakulingo/config/settings.py`
  - `AppSettings.text_translation_mode` の意味・許容値の整理
- `config/settings.template.json`
  - テンプレの `text_translation_mode` の更新
- `yakulingo/services/translation_service.py`
  - `translate_text_with_style_comparison()` のモード分岐から戻し訳ルート削除

## 非対象

- 戻し訳パイプライン本体の削除（task-02）
- プロンプトテンプレ/PromptBuilderの削除（task-04）
- UIの表示整理（task-05）

## 実装方針

- `text_translation_mode` の旧値（例: `backtranslation`, `review`, `3pass`）を受け取った場合は、
  - **壊さず**に、戻し訳ではない新しい既定挙動（例: 通常翻訳 or concise）へマッピングする。
- UI側でモード選択がある場合は、戻し訳系の選択肢を露出しない。

## テスト観点

- 旧モード値が残っている設定ファイル読み込みでも例外にならない
- `standard` が backtranslation に流れない

## DoD

- typecheck: `uv run --extra test pyright`
- lint: `uv run --extra test ruff check .`
- tests: `uv run --extra test pytest`
- PR-merge → ブランチ削除（remote+local）→ 削除証明

