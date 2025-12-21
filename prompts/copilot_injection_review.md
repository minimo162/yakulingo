# Copilot Prompt Injection Review

This document captures a manual review of the translation and writing prompts to see whether they are likely to be flagged as prompt-injection attempts by GitHub Copilot or similar systems. None of the prompts attempt to override platform policies or request ignored safeguards, so they present a low risk of refusal.

| Prompt file | Intended behavior | Injection risk notes |
| --- | --- | --- |
| `adjust_custom.txt` | Adjust, summarize, or draft replies based on provided source text and translation. | Contains only task-specific formatting; no attempts to override assistant rules. |
| `detect_language.txt` | Return the language name of the input text. | Single-purpose query with no meta-instructions; low risk. |
| `file_translate_to_en_concise.txt` | Concise English translation with numeric/symbol conventions. | Direct translation guidance; no system-manipulation language. |
| `file_translate_to_en_minimal.txt` | Highly abbreviated English translation for headings/tables. | Focused on output style; no adversarial directives. |
| `file_translate_to_en_standard.txt` | Standard English translation plus short Japanese explanation. | Only translation steps and output formatting; safe. |
| `file_translate_to_jp.txt` | Concise Japanese translation with numeric notation rules. | Pure translation task; no override language. |
| `text_alternatives.txt` | Suggest an alternative English wording given a current translation. | Style guidance only; lacks injection-style phrases. |
| `text_check_my_english.txt` | Validate user-edited English against a reference translation. | Error-checking instructions without policy-bypassing requests. |
| `text_question.txt` | Answer user questions about a translation with explanations. | Educational guidance; no instructions to ignore system behavior. |
| `text_reply_email.txt` | Draft a reply email matching intent and tone guidelines. | Standard composition prompt without meta-instructions. |
| `text_review_en.txt` | Review English text for correctness and business fit. | Review rubric only; no content that would trigger injection heuristics. |
| `text_summarize.txt` | Summarize key points in Japanese with ordered highlights. | Summarization-only; does not include harmful control phrases. |
| `text_translate_to_en_compare.txt` | English translation with standard/concise/minimal variants and explanations. | Structured translation output; no policy-override phrasing. |
| `text_translate_to_en_clipboard.txt` | Clipboard translation to English (concise) with explanations. | Translation-only instructions; no injection language. |
| `text_translate_to_jp.txt` | Natural Japanese translation with brief explanation. | Straightforward translation instructions; no injection content. |
| `text_translate_to_jp_clipboard.txt` | Clipboard translation to Japanese with explanations. | Task-scoped translation guidance; no policy-override directives. |

## Overall conclusion
All reviewed prompts are narrowly scoped to translation, summarization, or editing tasks. They do not contain phrases such as "ignore previous instructions" or requests to bypass safety systems, so they should not be rejected as prompt-injection attempts by Copilot. If Copilot flags any of these prompts, the likely cause would be false positives rather than embedded injection content.
