# Prompt Audit (task-00)

Purpose: inventory current prompt templates and the parsing expectations,
then map the INTENT prompt patterns to YakuLingo usage and list risks/next files.

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
- prompts/local_text_translate_to_en_3style_json.txt
- prompts/local_text_translate_to_en_single_json.txt
- prompts/local_text_translate_to_en_missing_styles_json.txt
- prompts/local_text_translate_to_jp_json.txt
- prompts/local_batch_translate_to_en_json.txt
- prompts/local_batch_translate_to_jp_json.txt

## Placeholders by file (from prompts/*.txt)

adjust_custom.txt: input_text, source_text, translation_rules, user_instruction
file_translate_to_en_concise.txt: input_text, reference_section, translation_rules
file_translate_to_en_minimal.txt: input_text, reference_section, translation_rules
file_translate_to_en_standard.txt: input_text, reference_section, translation_rules
file_translate_to_jp.txt: input_text, reference_section, translation_rules
local_batch_translate_to_en_json.txt: items_json, n_items, reference_section, style, translation_rules
local_batch_translate_to_jp_json.txt: items_json, n_items, reference_section, translation_rules
local_text_translate_to_en_3style_json.txt: detected_language, input_text, reference_section, translation_rules
local_text_translate_to_en_missing_styles_json.txt: detected_language, input_text, n_styles, reference_section, styles_json, translation_rules
local_text_translate_to_en_single_json.txt: detected_language, extra_instruction, input_text, numeric_hints, reference_section, style, translation_rules
local_text_translate_to_jp_json.txt: detected_language, input_text, reference_section, translation_rules
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

## Local AI JSON shapes (parser expectations)

Batch translation (yakulingo/services/local_ai_client.py):
- Expected JSON: {"items":[{"id":1,"translation":"..."}]}
- "id" can be int or digit string; missing/invalid id is skipped.
- Fallbacks: [[ID:n]] blocks or numbered lines ("1. ...").

Text JP->EN (3 style):
- Expected JSON: {"options":[{"style":"standard","translation":"...","explanation":"..."}]}
- "style" is normalized to standard/concise/minimal.
- Missing styles are filled by order if options list has entries.

Text single (JP->EN single or EN->JP):
- Expected JSON: {"translation":"..."}（EN→JPは `explanation` キーを出さない）
- 過去互換として `explanation` が来た場合は空文字扱い。

Note: "output_language" / "detected_language" are in templates but not required
by the parser today.

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
