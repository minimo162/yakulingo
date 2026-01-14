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
- {target_language} is not a direct runtime variable in YakuLingo.
- Use the output-language selection (Copilot/Local template choice) instead.
- {source_text} maps to {input_text}.

## Template: XX<=>XX Translation (excluding ZH<=>XX)

Purpose: translate non-Chinese input; output translation only.

Variables:
- {target_language}
- {source_text}

Template (verbatim):
Translate the following segment into {target_language}, without additional explanation.

{source_text}

Notes for YakuLingo:
- Same mapping as ZH<=>XX for {target_language} and {source_text}.

## Template: Terminology Intervention

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
- Preferred path: glossary/reference files (reference_section) + translation_rules.
- Alternative: inject with extra_instruction (Local AI) or extra instruction in PromptBuilder.

## Template: Contextual Translation

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
- Use extra_instruction to prepend {context} when needed.
- Keep context separate from {input_text} to avoid re-translation.

## Template: Formatted Translation

Purpose: preserve tags and formatting markers in translation output.

Variables:
- {src_text_with_format}

Template (verbatim):
将以下<source></source>之间的文本翻译为中文，注意只需要输出翻译后的结果，不要额外解释，原文中的<sn></sn>标签表示标签内文本包含格式信息，需要在译文中相应的位置尽量保留该标签。输出格式为：<target>str</target>

<source>{src_text_with_format}</source>

Notes for YakuLingo:
- No direct template exists today; use adjust_custom.txt or introduce a dedicated template.
- Keep <sn></sn> tags in the translated output in the same relative position.

## llama.cpp Usage Example (verbatim)

```bash
llama-cli -hf tencent/HY-MT1.5-7B-GGUF:Q8_0 -p "Translate the following segment into Chinese, without additional explanation.\n\nIt’s on the house." -n 4096 --temp 0.7 --top-k 20 --top-p 0.6 --repeat-penalty 1.05 --no-warmup
```

## ollama Usage Example (verbatim)

```bash
echo 'FROM hf.co/tencent/HY-MT1.5-7B-GGUF:Q8_0
TEMPLATE """<｜hy_begin▁of▁sentence｜>{{ if .System }}{{ .System }}<｜hy_place▁holder▁no▁3｜>{{ end }}{{ if .Prompt }}<｜hy_User｜>{{ .Prompt }}{{ end }}<｜hy_Assistant｜>"""' > Modelfile
ollama create hy-mt1.5-7b -f Modelfile
ollama run hy-mt1.5-7b
```

## Recommended Inference Parameters (verbatim)

Note: the model does not have a default system_prompt.

```json
{
  "top_k": 20,
  "top_p": 0.6,
  "repetition_penalty": 1.05,
  "temperature": 0.7
}
```

## YakuLingo Placeholder Mapping (summary)

- {source_text} -> {input_text}
- {target_language} -> template selection (en/jp) rather than a runtime variable
- {context} -> extra_instruction (Local AI) or inserted instruction in PromptBuilder
- terminology: reference_section + translation_rules (preferred), extra_instruction (optional)

## JSON Wrapper Guidance (Local AI)

Local AI templates require JSON output shapes. These base templates are meant to be
embedded inside the JSON-oriented prompt files under prompts/local_*_json.txt.
