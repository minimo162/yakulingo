# Prompt Templates SSOT

This document is the single source of truth for the base prompt templates.
It captures the intent-level templates and how they map to YakuLingo usage.

## Template: ZH<=>XX Translation

Purpose: translate Chinese to/from a target language; output translation only.

Variables:
- {target_language}
- {source_text}

Template (verbatim):
将以下文本翻译为{target_language}，注意只需要输出翻译后的结果，不要额外解释：

{source_text}

Notes for YakuLingo:
- {target_language} is substituted at runtime (e.g., "English", "Japanese") based on the translation direction.
- {source_text} maps to {input_text}.
- YakuLingo does not post-check or rewrite the model output (translation only).

## Template: JP<=>EN Translation (financial statements, Local AI raw prompt)

Purpose: translate Japanese <=> English suitable for financial statements; output translation only.

Variables:
- {text}

Template (verbatim, to EN):
```text
<bos><start_of_turn>user
Translate the Japanese text into English suitable for financial statements. Treat 1 billion as 10 oku (10億). Convert oku → billion by ÷10 (drop one zero). The response should include only the translated text.
Text: {text}<end_of_turn>
<start_of_turn>model
```

Template (verbatim, to JP):
```text
<bos><start_of_turn>user
Translate the text into Japanese suitable for financial statements. Treat 1 billion as 10 oku (10億). Convert billion → oku (億) by ×10 (add one zero).. The response should include only the translated text.
Text: {text}<end_of_turn>
<start_of_turn>model
```

Notes for YakuLingo:
- These templates are sent via `/v1/completions` (raw prompt) to avoid double-applying chat templates.

## Template: terminology intervention.

Purpose: enforce a specific term translation for consistency.

Variables:
- {source_term}
- {target_term}
- {target_language}
- {source_text}

Template (verbatim):
参考下面的翻译：
{source_term} 翻译成 {target_term}

将以下文本翻译为{target_language}，注意只需要输出翻译后的结果，不要额外解释：
{source_text}

Notes for YakuLingo:
- Preferred path: glossary/reference files ({reference_section}).
- Alternative: inject with extra_instruction (Local AI) or extra instruction in PromptBuilder.

## Template: contextual translation.

Purpose: provide context without translating the context block.

Variables:
- {context}
- {target_language}
- {source_text}

Template (verbatim):
{context}
参考上面的信息，把下面的文本翻译成{target_language}，注意不需要翻译上文，也不要额外解释：
{source_text}

Notes for YakuLingo:
- Local AI: prepend {context} via {extra_instruction} when needed.
- Keep context separate from {input_text} to avoid re-translation.

## Template: formatted translation.

Purpose: preserve tags and formatting markers in translation output.

Variables:
- {src_text_with_format}

Template (verbatim):
将以下<source></source>之间的文本翻译为中文，注意只需要输出翻译后的结果，不要额外解释，原文中的<sn></sn>标签表示标签内文本包含格式信息，需要在译文中相应的位置尽量保留该标签。输出格式为：<target>str</target>

<source>{src_text_with_format}</source>

Notes for YakuLingo:
- Local AI JSON templates do not output <target> wrappers; they should still preserve <sn></sn> (and similar) tags inside the JSON "translation" field.

## llama.cpp Usage Example (verbatim)

```bash
llama-cli -m local_ai/models/translategemma-12b-it.i1-IQ3_XXS.gguf -p "<bos><start_of_turn>user\nTranslate the Japanese text into English suitable for financial statements. Treat 1 billion as 10 oku (10億). Convert oku → billion by ÷10 (drop one zero). The response should include only the translated text.\nText: こんにちは<end_of_turn>\n<start_of_turn>model\n" -n 4096 --temp 0.7 --top-k 64 --top-p 0.95 --repeat-penalty 1.05 --no-warmup
```

## ollama Usage Example

> **Note**: Ollama の `TEMPLATE` はモデルの chat template に強く依存します。YakuLingo のローカルAIバックエンドは llama.cpp を直接利用するため、本ドキュメントでは Ollama 用テンプレは提供しません。

## Recommended Inference Parameters (verbatim)

Note: the model does not have a default system_prompt.

```json
{
  "top_k": 64,
  "top_p": 0.95,
  "repetition_penalty": 1.05,
  "temperature": 0.7
}
```

## YakuLingo Placeholder Mapping (summary)

- {source_text} -> {input_text}
- {target_language} -> resolved language name (e.g., "English", "Japanese") derived from output_language
- {context} -> {extra_instruction} (Local AI) or inserted instruction in PromptBuilder
- terminology -> {reference_section} (preferred), {extra_instruction} (optional)

## JSON Wrapper Guidance (Local AI)

Local AI templates require JSON output shapes. These base templates are meant to be
embedded inside the JSON-oriented prompt files under prompts/local_*_json.txt.
