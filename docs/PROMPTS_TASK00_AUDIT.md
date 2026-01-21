# Prompt Audit (task-00)

Purpose: inventory current prompt templates and the parsing expectations,
then map the INTENT prompt patterns to YakuLingo usage and list risks/next files.

> Note (2026-01-18): 現行のJP→ENは minimal-only（単一出力）です。multi-style（CopilotのcompareセクションやLocal AIの3style/missing_styles）は後方互換のため残っていても、メイン経路では未使用です。

## Inventory (by backend)

Copilot (non-JSON):
- prompts/translation_rules.txt
- prompts/file_translate_to_en_standard.txt
- prompts/file_translate_to_en_concise.txt
- prompts/file_translate_to_en_minimal.txt
- prompts/file_translate_to_jp.txt
- prompts/text_translate_to_en_compare.txt
- prompts/text_translate_to_jp.txt
- prompts/text_back_translate.txt
- prompts/text_alternatives.txt
- prompts/text_review_en.txt
- prompts/text_check_my_english.txt
- prompts/text_summarize.txt
- prompts/text_question.txt
- prompts/text_reply_email.txt
- prompts/adjust_custom.txt

Local AI (JSON):
- prompts/local_text_translate_to_en_single_json.txt
- prompts/local_text_translate_to_jp_json.txt
- prompts/local_batch_translate_to_en_json.txt
- prompts/local_batch_translate_to_jp_json.txt
- (legacy/unused) prompts/local_text_translate_to_en_3style_json.txt
- (legacy/unused) prompts/local_text_translate_to_en_missing_styles_json.txt

## Placeholders by file (from prompts/*.txt)

adjust_custom.txt: input_text, source_text, translation_rules, user_instruction
file_translate_to_en_concise.txt: input_text, reference_section, translation_rules
file_translate_to_en_minimal.txt: input_text, reference_section, translation_rules
file_translate_to_en_standard.txt: input_text, reference_section, translation_rules
file_translate_to_jp.txt: input_text, reference_section, translation_rules
local_batch_translate_to_jp_json.txt: items_json, n_items, reference_section, translation_rules
local_batch_translate_to_en_json.txt: items_json, n_items, numeric_hints, reference_section, style, translation_rules
local_text_translate_to_en_3style_json.txt: extra_instruction, input_text, numeric_hints, reference_section, translation_rules
local_text_translate_to_en_missing_styles_json.txt: extra_instruction, input_text, n_styles, numeric_hints, reference_section, styles_json, translation_rules
local_text_translate_to_en_single_json.txt: extra_instruction, input_text, numeric_hints, reference_section, style, translation_rules
local_text_translate_to_jp_json.txt: input_text, reference_section, translation_rules
text_alternatives.txt: current_translation, reference_section, source_text, style, translation_rules
text_back_translate.txt: input_text, reference_section, translation_rules
text_check_my_english.txt: reference_section, reference_translation, user_english
text_question.txt: input_text, question, reference_section, translation
text_reply_email.txt: input_text, reference_section, reply_intent, translation
text_review_en.txt: input_text, reference_section, translation
text_summarize.txt: input_text, reference_section, translation
text_translate_to_en_compare.txt: input_text, reference_section, translation_rules
text_translate_to_jp.txt: input_text, reference_section, translation_rules
translation_rules.txt: -

Note (Copilot EN→JP):
- `text_translate_to_jp.txt` は `Translation:` のみを出力し、Explanation ブロックは含まない（translation-only 契約）。

## Local AI JSON shapes (parser expectations)

Batch translation (yakulingo/services/local_ai_client.py):
- Expected JSON: {"items":[{"id":1,"translation":"..."}]}
- "id" can be int or digit string; missing/invalid id is skipped.
- Fallbacks: [[ID:n]] blocks or numbered lines ("1. ...").

Text JP->EN (minimal-only) / EN->JP (single):
- Expected JSON: {"translation":"..."}（`explanation` は optional 互換あり）
- 過去互換として `explanation` が来た場合は空文字扱い。

Note: `LocalPromptBuilder` が `detected_language` などを置換できる実装でも、
テンプレート側にプレースホルダが無い場合は単に無視される（互換維持）。

## Contracts (inputs → prompt → expected output → parser)

最優先: 既存のパーサが前提としている「出力形状」を壊さないこと。
プロンプト側の改善は、まず出力形状のブレを減らす（安定性）→ その上で短文化（速度）を行う。

### Copilot (non-JSON)

- File translation (batch)
  - Prompt: `prompts/file_translate_to_en_{style}.txt`, `prompts/file_translate_to_jp.txt`
  - Input: numbered list (`1. ...`, `2. ...`, ...)
    - `include_item_ids=True` の場合は `[[ID:n]]` が各項目に付与され、保持が強制される（`yakulingo/services/prompt_builder.py::ID_MARKER_INSTRUCTION`）
  - Expected output: numbered listのみ（入力と同じ番号・順序、複数行は同一項目内で継続行インデント）
  - Parser: `yakulingo/services/copilot_handler.py::_parse_batch_result`（IDありは `_parse_batch_result_by_id`）

- Text JP→EN (minimal-only)
  - Prompt: `prompts/text_translate_to_en_compare.txt`
  - Expected output: `[minimal]` セクション + `Translation:`（解説なし）
    - 互換: 応答に `[concise]` / `[standard]` が混在してもパースは受け付け、常に `minimal` 1件を返す
  - Parser: `yakulingo/services/translation_service.py::_parse_style_comparison_result` → `_parse_single_translation_result`（常に `minimal` を選択）
  - Contract test: `tests/test_text_compare_template_contract.py`, `tests/test_text_translation_retry.py`（出力言語ガード/リトライも含む）

- Text EN→JP (single)
  - Prompt: `prompts/text_translate_to_jp.txt`
  - Expected output: `Translation:` のみ（解説なし）
  - Parser: `yakulingo/services/translation_service.py::_parse_single_translation_result`

### Local AI (JSON)

- Batch translation
  - Prompt: `prompts/local_batch_translate_to_{en|jp}_json.txt`
  - Expected output JSON: `{"items":[{"id":1,"translation":"..."}]}`
  - Parser: `yakulingo/services/local_ai_client.py::parse_batch_translations`
  - Fallbacks: `[[ID:n]] ...` ブロック、または `1. ...` 行

- Text JP→EN (minimal-only) / EN→JP (single)
  - Prompt: `prompts/local_text_translate_to_en_single_json.txt`, `prompts/local_text_translate_to_jp_json.txt`
  - Expected output JSON: `{"translation":"..."}`（`explanation` は optional 互換あり）
  - Parser: `yakulingo/services/local_ai_client.py::parse_text_single_translation`

## Known failure patterns (things prompts must prevent)

- Code fence (` ```json `) が混入する / JSON以外の前置き・後置きが付く（Local AI）
  - Parser側は `loads_json_loose` で吸収するが、発生率を下げるのが本筋（JSON only を強める）
- `response_format` が未対応/部分対応で失敗する（Local AI）
  - client 側は `json_schema` → `json_object` →（最終）無し の順でフォールバックする
- JSONの形状が崩れる（キー名変更、`options/items` 欠落、`id` 非数値、末尾カンマ等）
- Copilotが余計な見出し/解説/注意書きを出す（「出力は〜のみ」を徹底）
- Copilotの番号付きリストで欠番・重複・並べ替えが起きる（バッチ結果の対応ズレ）
- Copilot内でネストした番号付きリストが出てパースが誤作動する（`_parse_batch_result` はインデントで抑止）
- (legacy) 3styleでスタイル欠落/順序崩れが起きる（現行経路では未使用）

## Evaluation axes (stability / speed)

- Parse failure rate: `LocalAI parse failure:` ログ（`yakulingo/services/local_ai_client.py`）と、Copilot側の欠番/空訳/混入（`yakulingo/services/copilot_handler.py`）
- Prompt length: `{translation_rules}`/`{reference_section}`/入力を含めた「送信プロンプトの文字数」（短縮の主指標）
- Output length: 返答の文字数（特に Explanation の膨張が速度/安定性を落とす）

## Baseline prompt length audit (Local AI)

ローカルAI向けプロンプトの「素材（テンプレ/翻訳ルール）」と「組み立て後（build_*）」の文字数を、サーバ無しで確認する。

```bash
uv run python tools/audit_local_prompt_lengths.py
```

## Improvement priority (stability → speed)

1. 既存パーサ契約（出力形状）を壊さない
2. 出力形状の厳格化でパース失敗を減らす（余計な文・見出し・コードブロックの禁止）
3. プロンプト短縮で速度を上げる（重複ルールを削り、`translation_rules` 側へ寄せる）
4. 出力長の抑制（Explanationを短く、必要最小限にする）

## Contract tests

- Local AI JSON parsing: `tests/test_local_ai_json_parsing.py`
- Copilot 3style parsing/retry: `tests/test_text_translation_retry.py`

## INTENT prompt mapping (current fit)

INTENT template -> YakuLingo surface:
- ZH<=>XX translation:
  - Closest: text/file translate templates (Copilot) and Local AI JSON templates,
    but YakuLingo does not expose "target_language" as a variable today.
- XX<=>XX translation (non-ZH):
  - Matches existing text/file translate templates (Copilot) and Local AI JSON.
- Terminology intervention:
  - Best fit: reference_section (glossary) + translation_rules.
  - Optional: extra_instruction in Local AI or PromptBuilder extra insertion.
- Contextual translation:
  - Best fit: extra_instruction (prepend context) or reference_section.
  - There is no dedicated {context} placeholder in current templates.
- Formatted translation (<source>/<sn>/<target>):
  - No direct template today; closest is "preserve structure" in translation_rules.
  - If needed, use adjust_custom.txt or add a dedicated template later.

## Next task candidate files (expected changes)

Local AI prompts:
- prompts/local_text_translate_to_en_3style_json.txt
- prompts/local_text_translate_to_en_single_json.txt
- prompts/local_text_translate_to_en_missing_styles_json.txt
- prompts/local_text_translate_to_jp_json.txt
- prompts/local_batch_translate_to_en_json.txt
- prompts/local_batch_translate_to_jp_json.txt

Builders/parsers:
- yakulingo/services/local_ai_prompt_builder.py (insert order, extra_instruction)
- yakulingo/services/prompt_builder.py (extra instruction insertion for Copilot)
- yakulingo/services/local_ai_client.py (parser expectations; tests)

Docs (if usage changes):
- README.md
- docs/SPECIFICATION.md (prompt section)
- docs/PERFORMANCE_LOCAL_AI.md (if inference params are cited)

## Risks / compatibility notes

- Changing JSON keys (options/items/translation) breaks parser expectations.
- Tightening "JSON only" constraints may reduce fallback usefulness.
- Adding context/terminology instructions increases prompt length and can hit
  LOCAL_PROMPT_TOO_LONG (ctx/max_tokens).
- Local AI templates contain fields not used by the parser; changing them may
  be low-risk but should remain consistent for future tooling.
