# ユーザープロンプトのみ（task-00 監査メモ）

## 目的
intent.md の要件:
- **システムプロンプトは削除**
- **AIに渡すのはユーザープロンプトだけ**
- **ユーザープロンプトは指定テンプレのみ**（他に余計な文章を送信しない）

このタスクでは、現状コードで「AIへ送る文字列」がどこで生成され、どこで追加文章が混入しているかを棚卸しする。

## 現状の入口（主にローカルAI経路）
- `yakulingo/services/local_ai_client.py`
  - `_build_chat_payload()` は `messages=[{\"role\":\"user\",...}]` のみ（= system role なし）
  - 一方で、プロンプト内容が JSON 形式を要求する場合 `response_format` を付与する設計（local_* テンプレ前提）
- `yakulingo/services/prompt_builder.py`
  - `build_simple_prompt()` は `SIMPLE_PROMPT_TEMPLATE` を返す（intent のユーザープロンプト本体に相当）
  - `build()` / `build_batch()` はテンプレ構造上、`reference_section` や出力フォーマット指示等が混ざる余地がある
- `yakulingo/services/translation_service.py`
  - テキスト翻訳のローカル経路は **2系統**:
    - `force_simple_prompt=True` のとき: `PromptBuilder.build_simple_prompt()` のみを送る
    - それ以外: `LocalPromptBuilder` + `prompts/local_*.txt` で **追加文章（JSON/Rules/Glossary/extra_instruction）を含む** プロンプトを組み立てる
  - さらに、ルール違反時のリトライで `extra_instruction` に **CRITICAL/Rules 等の追加文章**を差し込み、再送している
- `yakulingo/services/local_ai_prompt_builder.py`
  - `build_text_to_en_3style()` / `build_text_to_en_missing_styles()` / `build_batch()` は `prompts/local_*.txt`（JSON返却/スタイル指示等）をベースに組み立てる
  - `_append_simple_prompt()` により、テンプレ本文とは別に `build_simple_prompt()` を後ろへ連結する（= ユーザープロンプト以外の文章が同一リクエストに混在）

## 追加文章が混入している具体箇所（intent違反候補）
### 1) local_* テンプレ自体が「余計な文章」
- `prompts/local_text_translate_to_en_3style_json.txt`
  - 3スタイル/JSON only/Rules/Self-check などの文章を含む
- `prompts/local_text_translate_to_en_missing_styles_json.txt`
  - styles_json / JSON only / Rules / Self-check を含む
- `prompts/local_batch_translate_to_en_json.txt` / `prompts/local_batch_translate_to_jp_json.txt`
  - items_json / JSON only / Rules /（JP側は numeric notation rules）を含む
- `prompts/local_text_translate_to_jp_json.txt`
  - numeric notation rules 等を含む

### 2) Glossary 埋め込み（reference_section）が「余計な文章」
- `yakulingo/services/local_ai_prompt_builder.py: build_reference_embed()`
  - `### Glossary (CSV)\nApply glossary terms verbatim.\n\n...` というヘッダー＋本文をプロンプトに埋め込む
  - intent 要件の「指定テンプレ以外を送信しない」と衝突する

### 3) リトライ時の extra_instruction 注入が「余計な文章」
- `yakulingo/services/translation_service.py`
  - 例: `_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION` / `BatchTranslator._EN_STRICT_OUTPUT_LANGUAGE_INSTRUCTION` 等を `extra_instruction` に積み、`LocalPromptBuilder.build_text_to_en_single(..., extra_instruction=...)` で再送する
  - intent 要件では「再送時もユーザープロンプトのみ」が必要になるため、後続タスクで撤去/後処理化が必要

## 影響（テスト/機能）
- ローカルAIの **style comparison**（3スタイル）や **JSONレスポンス前提**、**ルール強制リトライ** は intent と整合しないため、後続タスクで縮退/置換が必要
- 影響が出やすいテスト群（例）:
  - `tests/test_local_ai_prompt_templates.py`（local_* テンプレ前提）
  - `tests/test_local_ai_rule_enforcement_task00.py` / `tests/test_text_translation_retry.py`（リトライ・ルール強制前提）
  - `tests/test_local_ai_style_comparison_*`（3スタイルJSON前提）

## 次タスクへの引き継ぎ（要点）
- task-01: `build_simple_prompt()` の文字列を intent テンプレと完全一致（改行含む）で固定し、ゴールデンテスト化
- task-02〜04: ローカルAIへ送るのは常に `build_simple_prompt()` のみに統一し、local_* JSONテンプレ/extra_instruction 注入を撤去（必要な補正は後処理へ）

