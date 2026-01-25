# task-00: 現状調査（再現条件と原因仮説の確定）

## 目的
- 「billion表記になる」症状が **どの経路**（テキスト翻訳/ファイル翻訳、Copilot/Local）で起きるかを切り分ける。
- 動的用語集が指す対象を特定する（例: インライン用語集、Local AI 生成グロッサリー、数値ヒント挿入）。
- 修正方針（プロンプト強化で防ぐ/自動補正で直す/再試行を入れる）を最小変更で決める。

## 想定所要（タイムボックス）
- 15〜60分

## 調査観点（見る場所）
- `yakulingo/services/prompt_builder.py`
  - `_build_inline_glossary_section()` の抽出条件・上限（`_INLINE_GLOSSARY_MAX_LINES/_CHARS`）と選定ロジック
- `yakulingo/services/translation_service.py`
  - JP→EN 数値ヒント: `_build_to_en_numeric_hints()`
  - `billion/bn/trillion` の検出・補正: `_fix_to_en_oku_numeric_unit_if_possible()` とその適用箇所
  - Copilot テキスト翻訳: `_translate_text_with_options_on_copilot()`（数値ルールの再試行があるか）
  - バッチ翻訳（ファイル翻訳側）: `BatchTranslator` の retry/補正が Copilot 経路にも効いているか
- `yakulingo/services/local_ai_prompt_builder.py`
  - 生成グロッサリー（`_extract_to_en_dynamic_glossary_pairs()` など）が数値ヒントを拾えているか

## 最小再現（候補）
- 入力例（JP→EN）:
  - `売上高は22,385億円。`
  - `売上高は2兆2,385億円。`
  - `▲10億円`（負数記号も絡む）
- 期待: `billion/bn/trillion` を使わず `oku`（必要なら `oku yen`）になる

## 作業手順
1. 「症状が出る画面/操作」を確認（テキスト翻訳か、ファイル翻訳か、どちらもか）
2. 既存テストのカバレッジ確認（`tests/` で `billion` 周りを検索し、未カバー経路を特定）
3. 実際に `BatchTranslator` の Copilot 経路で数値ルールが適用されているかをコードで追う
4. 原因仮説を1つに絞る（例: Copilot バッチ翻訳に数値自動補正が無い/動的用語集が上限で落ちる）
5. task-01（テスト）で固定すべき「失敗する入力/出力」を決定し、`tasks/index.md` を更新

## DoD
- 再現条件（入力・出力・経路）が `task-01` にそのまま落とせる粒度で確定している
- 変更方針が1つに収束している（どこを直すか: `BatchTranslator`/`PromptBuilder`/両方）
