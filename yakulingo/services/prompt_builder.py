# yakulingo/services/prompt_builder.py
"""
Builds translation prompts for YakuLingo.

Prompt file structure:
- file_translate_to_en_minimal.txt: File translation → English (minimal only; SSOT)
- file_translate_to_jp.txt: File translation → Japanese
- text_translate_to_en_compare.txt: Text translation → English (minimal only)
- text_translate_to_jp.txt: Text translation → Japanese (translation-only)
- adjust_*.txt: Adjustment prompts (shorter, longer, custom)

Translation rules are no longer injected into prompts.
"""

import csv
import heapq
import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Optional, Sequence


_RE_GLOSSARY_MATCH_SEPARATORS = re.compile(r"[\s_/\\-]+")
_RE_GLOSSARY_ASCII_WORD = re.compile(r"^[a-z0-9]+$")
_RE_GLOSSARY_TEXT_ASCII_WORD = re.compile(r"[a-z0-9]+")
_ASCII_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_INLINE_GLOSSARY_MAX_LINES = 40
_INLINE_GLOSSARY_MAX_CHARS = 2000

_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_RE_YEN_BILLION = re.compile(
    rf"(?i)(?P<sign1>[+-])?\s*(?P<currency>[¥￥])\s*(?P<sign2>[+-])?\s*(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN})\s*(?P<unit>billion|bn)\b(?:\s*yen\b)?"
)
_YEN_AMOUNT_MULTIPLIER_BILLION = Decimal("1000000000")
_YEN_UNIT_CHOU = 1_000_000_000_000
_YEN_UNIT_OKU = 100_000_000
_YEN_UNIT_MAN = 10_000


def _format_japanese_yen_amount(yen_amount: Decimal) -> str:
    sign_prefix = "-" if yen_amount < 0 else ""
    yen_amount = abs(yen_amount)
    try:
        yen_total = int(yen_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return f"{sign_prefix}0円"

    chou = yen_total // _YEN_UNIT_CHOU
    yen_total %= _YEN_UNIT_CHOU
    oku = yen_total // _YEN_UNIT_OKU
    yen_total %= _YEN_UNIT_OKU
    man = yen_total // _YEN_UNIT_MAN
    yen = yen_total % _YEN_UNIT_MAN

    parts: list[str] = []
    if chou:
        parts.append(f"{chou}兆")
    if oku:
        parts.append(f"{oku:,}億")
    if man:
        if yen:
            parts.append(f"{man:,}万")
        else:
            parts.append(f"{man:,}万円")
    if yen:
        parts.append(f"{yen:,}円")

    if not parts:
        parts.append("0円")
    elif not parts[-1].endswith("円"):
        parts[-1] = f"{parts[-1]}円"

    return f"{sign_prefix}{''.join(parts)}"


def _normalize_yen_billion_expressions_to_japanese(text: str) -> str:
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        sign1 = match.group("sign1") or ""
        sign2 = match.group("sign2") or ""
        sign = sign1 or sign2
        try:
            amount_billion = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            return match.group(0)

        if sign == "-":
            amount_billion = -amount_billion

        yen_amount = amount_billion * _YEN_AMOUNT_MULTIPLIER_BILLION
        return _format_japanese_yen_amount(yen_amount)

    return _RE_YEN_BILLION.sub(repl, text)


# 参考ファイル参照の指示文（ファイル添付時のみ挿入）
REFERENCE_INSTRUCTION = """### Glossary (CSV)
Use the attached glossary CSV. If a term matches, apply the glossary translation verbatim."""
ID_MARKER_INSTRUCTION = """
### Item ID markers (critical)
- Each output item must start with "<number>. [[ID:n]]" (example: "1. [[ID:1]] ...").
- Output must include every ID from 1 to N exactly once (no omissions, no extras).
- Do not remove, change, or relocate the marker; keep it on the same line as the item number.
- If you cannot translate an item, copy the original text after the marker (do not leave it empty).
- Do not output other prompt markers (e.g., "===INPUT_TEXT===" / "===END_INPUT_TEXT===").
"""

_LEGACY_SIMPLE_PROMPT_TEMPLATE = """You are a professional {SOURCE_LANG} ({SOURCE_CODE}) to {TARGET_LANG} ({TARGET_CODE}) translator. Your goal is to accurately convey the meaning and nuances of the original {SOURCE_LANG} text while adhering to {TARGET_LANG} grammar, vocabulary, and cultural sensitivities.
Produce only the {TARGET_LANG} translation, without any additional explanations or commentary. Please translate the following {SOURCE_LANG} text into {TARGET_LANG}:


{TEXT}"""

# Fallback template for → English (used when translate_to_en.txt doesn't exist)
DEFAULT_TO_EN_TEMPLATE = """## ファイル翻訳リクエスト

重要: 出力は必ず入力と同じ番号付きリスト形式で出力してください。

### 出力形式（最優先ルール）
- 入力: 番号付きリスト（1., 2., 3., ...）
- 出力: 必ず同じ番号付きリスト形式で出力
- 各項目は必ず「番号. 」で始める（例: "1. Hello"）
- 改行がある場合は2行目以降に番号を付けず、1つ以上の空白/タブでインデントする
- 番号を飛ばしたり、統合したりしないこと
- 解説、Markdown、追加テキストは不要
- 番号なしの出力は禁止

### 翻訳スタイル
- ビジネス文書向けで自然で読みやすい英語
- 既に英語の場合はそのまま出力

{reference_section}

---

{input_text}
"""

# Fallback template for → Japanese (used when translate_to_jp.txt doesn't exist)
DEFAULT_TO_JP_TEMPLATE = """## ファイル翻訳リクエスト（日本語への翻訳）

重要: 出力は必ず入力と同じ番号付きリスト形式で出力してください。

### 出力形式（最優先ルール）
- 入力: 番号付きリスト（1., 2., 3., ...）
- 出力: 必ず同じ番号付きリスト形式で出力
- 各項目は必ず「番号. 」で始める（例: "1. こんにちは"）
- 改行がある場合は2行目以降に番号を付けず、1つ以上の空白/タブでインデントする
- 番号を飛ばしたり、統合したりしないこと
- 解説、Markdown、追加テキストは不要
- 番号なしの出力は禁止

### 翻訳ガイドライン
- ビジネス文書向けで自然で読みやすい日本語
- 簡潔な表現を心がける
- 既に日本語の場合はそのまま出力

### 数値表記ルール
- oku → 億（例: 4,500 oku → 4,500億）
- k → 千または000（例: 12k → 12,000）
- () → ▲（例: (50) → ▲50）

{reference_section}

---

{input_text}
"""

# Fallback templates for text translation (used when text_translate_*.txt don't exist)
DEFAULT_TEXT_TO_EN_COMPARE_TEMPLATE = """## Text Translation Request (Minimal)
Translate the Japanese text into minimal, business-ready English.

### Rules (critical)
- Output must match the exact format below (no extra headings/notes/Markdown/code fences).
- In the "Translation:" content must be English only:
  - Do NOT include Japanese scripts (hiragana/katakana/kanji) or Japanese punctuation (、。).
  - If any Japanese appears, rewrite it until it contains no Japanese characters.
- Do NOT output any explanations/notes or any extra text.
- Translate only the text between the input markers; do not output the marker lines or any other prompt text.
- Preserve line breaks and tabs as much as possible.
- If the input is already English, keep it as is.
- If the source contains Japanese-only tokens (e.g., names, company types, place names), translate or romanize them; do not leave them in Japanese script.
- Follow the Translation Rules section for numbers/units/symbols; do not output Japanese unit characters in any Translation (e.g., 円/万/億/兆).

### Style rules
[minimal]
- Make it as short as possible while preserving meaning and key facts.
- Intended for headings/tables; use abbreviations aggressively.
- Use compact, business-formal English; remove non-essential modifiers.
- Use common business abbreviations when suitable (YoY, QoQ, CAGR).

### Output format (exact)
[minimal]
Translation:

{reference_section}

---

### INPUT (translate only this block)
===INPUT_TEXT===
{input_text}
===END_INPUT_TEXT===
"""

DEFAULT_TEXT_TO_EN_TEMPLATE = """You are a professional {SOURCE_LANG} ({SOURCE_CODE}) to {TARGET_LANG} ({TARGET_CODE}) translator. Your goal is to accurately convey the meaning and nuances of the original {SOURCE_LANG} text while adhering to {TARGET_LANG} grammar, vocabulary, and cultural sensitivities.
Produce only the {TARGET_LANG} translation, without any additional explanations or commentary.

{reference_section}

### Output format (exact)
Translation:

---

### INPUT (translate only this block)
===INPUT_TEXT===
{input_text}
===END_INPUT_TEXT===
"""


DEFAULT_TEXT_TO_JP_TEMPLATE = """## テキスト翻訳リクエスト（日本語への翻訳）

テキストをビジネス文書向けの日本語に翻訳してください。

### 翻訳ガイドライン
- ビジネス文書向けで自然で読みやすい日本語
- 簡潔な表現を心がける
- 既に日本語の場合はそのまま出力
- 原文の改行・タブをそのまま維持

### 数値表記ルール
- oku → 億（例: 4,500 oku → 4,500億）
- k → 千または000（例: 12k → 12,000）
- () → ▲（例: (50) → ▲50）

### 出力形式
訳文: 日本語翻訳

解説:
- 原文の表現がどう訳されたか、注意すべき語句の対応を具体的に説明（見出し・ラベルなし）

解説は日本語で簡潔に書いてください。

### 禁止事項（絶対に出力しないこと）
- 「続けますか？」「他にありますか？」などの質問
- 「〜も翻訳できます」「必要なら〜」などの提案
- プロンプトの指示をそのまま繰り返すような補足（例：「数値はoku変換済み」「略語を使用」「簡潔化した」など）
- 訳文と解説以外のテキスト

{reference_section}

---

以下のテキストを翻訳してください:
{input_text}
"""


class PromptBuilder:
    """
    Builds translation prompts for file translation.
    Reference files are handled out-of-band (attached/embedded depending on backend).

    Supports style-specific prompts for English output (standard/concise).
    Translation rules are no longer injected (glossary-centered prompts).
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir
        # Templates cache: {(lang, style): template_str}
        self._templates: dict[tuple[str, str], str] = {}
        # Text translation templates cache: {(lang, style): template_str}
        self._text_templates: dict[tuple[str, str], str] = {}
        # Text translation comparison template
        self._text_compare_template: Optional[str] = None
        # Glossary cache: {(path, mtime, size): pairs}
        self._glossary_pairs_cache: dict[
            tuple[str, int, int], list[tuple[str, str, str, str, str, str]]
        ] = {}
        self._load_templates()

    @staticmethod
    def normalize_input_text(input_text: str, output_language: str) -> str:
        if output_language != "jp" or not input_text:
            return input_text
        lowered = input_text.lower()
        if ("billion" not in lowered and "bn" not in lowered) or (
            "¥" not in input_text and "￥" not in input_text
        ):
            return input_text
        return _normalize_yen_billion_expressions_to_japanese(input_text)

    @staticmethod
    def _rules_file_key(path: Path) -> tuple[str, int, int]:
        try:
            stat = path.stat()
            mtime_ns = getattr(stat, "st_mtime_ns", None)
            mtime_key = (
                int(mtime_ns) if isinstance(mtime_ns, int) else int(stat.st_mtime)
            )
            return (str(path), mtime_key, int(stat.st_size))
        except OSError:
            return (str(path), 0, 0)

    @staticmethod
    def _normalize_for_glossary_match(text: str) -> str:
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKC", text)
        normalized = normalized.replace("\u3000", " ")
        return normalized.casefold()

    @staticmethod
    def _compact_for_glossary_match(text_folded: str) -> str:
        if not text_folded:
            return ""
        return _RE_GLOSSARY_MATCH_SEPARATORS.sub("", text_folded)

    @staticmethod
    def _is_numeric_unit_glossary_term(
        *, source_folded: str, target_folded: str
    ) -> bool:
        folded = (
            f"{(source_folded or '').strip()} {(target_folded or '').strip()}".strip()
        )
        if not folded:
            return False
        if "億" in folded or "兆" in folded:
            return True
        if "円" in folded and any(unit in folded for unit in ("千", "万", "億", "兆")):
            return True
        if "oku" in folded:
            return True
        return "k yen" in folded

    @staticmethod
    def _matches_glossary_term(
        *,
        text_folded: str,
        text_compact: str,
        term_folded: str,
        term_compact: str,
    ) -> bool:
        term_folded = (term_folded or "").strip()
        if not term_folded:
            return False

        if term_folded.isascii() and _RE_GLOSSARY_ASCII_WORD.match(term_folded):
            term_len = len(term_folded)
            start = 0
            while True:
                idx = text_folded.find(term_folded, start)
                if idx < 0:
                    break
                before_ok = idx == 0 or text_folded[idx - 1] not in _ASCII_ALNUM
                after_pos = idx + term_len
                after_ok = (
                    after_pos >= len(text_folded)
                    or text_folded[after_pos] not in _ASCII_ALNUM
                )
                if before_ok and after_ok:
                    return True
                start = idx + term_len
        else:
            if term_folded in text_folded:
                return True

        term_compact = (term_compact or "").strip()
        if not term_compact:
            return False
        if len(term_compact) < 4:
            return False
        return term_compact in text_compact

    def _load_glossary_pairs(
        self, path: Path
    ) -> list[tuple[str, str, str, str, str, str]]:
        file_key = self._rules_file_key(path)
        cached = self._glossary_pairs_cache.get(file_key)
        if cached is not None:
            return cached

        try:
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            pairs: list[tuple[str, str, str, str, str, str]] = []
        else:
            pairs = []
            for row in csv.reader(io.StringIO(raw)):
                if not row:
                    continue
                first = (row[0] or "").strip()
                if not first or first.startswith("#"):
                    continue
                second = (row[1] or "").strip() if len(row) > 1 else ""
                source_folded = self._normalize_for_glossary_match(first)
                target_folded = (
                    self._normalize_for_glossary_match(second) if second else ""
                )
                source_compact = self._compact_for_glossary_match(source_folded)
                target_compact = self._compact_for_glossary_match(target_folded)
                pairs.append(
                    (
                        first,
                        second,
                        source_folded,
                        target_folded,
                        source_compact,
                        target_compact,
                    )
                )

        self._glossary_pairs_cache[file_key] = pairs
        return pairs

    @staticmethod
    def _filter_glossary_pairs_for_inline(
        pairs: list[tuple[str, str, str, str, str, str]],
        input_text: str,
        *,
        max_lines: int,
    ) -> tuple[list[tuple[str, str]], bool]:
        text = (input_text or "").strip()
        if not text:
            return [], False

        text_folded = PromptBuilder._normalize_for_glossary_match(text)
        text_compact = PromptBuilder._compact_for_glossary_match(text_folded)

        seen: set[str] = set()
        heap: list[tuple[int, int, int, str, str]] = []
        matched_count = 0

        for idx, (
            source,
            target,
            source_folded,
            target_folded,
            source_compact,
            target_compact,
        ) in enumerate(pairs):
            source = (source or "").strip()
            if not source:
                continue
            if source in seen:
                continue

            matched = PromptBuilder._matches_glossary_term(
                text_folded=text_folded,
                text_compact=text_compact,
                term_folded=source_folded,
                term_compact=source_compact,
            )
            if not matched and target:
                matched = PromptBuilder._matches_glossary_term(
                    text_folded=text_folded,
                    text_compact=text_compact,
                    term_folded=target_folded,
                    term_compact=target_compact,
                )
            if not matched:
                continue

            seen.add(source)
            matched_count += 1
            priority = (
                1
                if PromptBuilder._is_numeric_unit_glossary_term(
                    source_folded=source_folded, target_folded=target_folded
                )
                else 0
            )
            key = max(len(source_folded or source), len(target_folded or target))
            item = (priority, key, -idx, source, target)
            if len(heap) < max_lines:
                heapq.heappush(heap, item)
            else:
                if item > heap[0]:
                    heapq.heapreplace(heap, item)

        if not heap:
            return [], False

        selected = sorted(heap, key=lambda x: (-x[0], -x[1], -x[2]))
        return [(source, target) for _, _, _, source, target in selected], (
            matched_count > max_lines
        )

    def _build_inline_glossary_section(
        self,
        reference_files: Optional[Sequence[Path]],
        *,
        input_text: str,
    ) -> str:
        if not reference_files:
            return ""
        text = (input_text or "").strip()
        if not text:
            return ""

        glossary_paths = [
            path for path in reference_files if path.suffix.casefold() == ".csv"
        ]
        if not glossary_paths:
            return ""

        pairs: list[tuple[str, str, str, str, str, str]] = []
        for path in glossary_paths:
            pairs.extend(self._load_glossary_pairs(path))
        if not pairs:
            return ""

        selected, truncated = self._filter_glossary_pairs_for_inline(
            pairs, text, max_lines=_INLINE_GLOSSARY_MAX_LINES
        )
        if not selected:
            return ""

        header = "### Glossary (matched; apply verbatim)\n"
        parts: list[str] = [header.rstrip("\n")]
        total = len(header)

        for source, target in selected:
            if not target:
                continue
            line = f"- JP: {source} | EN: {target}"
            needed = len(line) + 1
            if total + needed > _INLINE_GLOSSARY_MAX_CHARS:
                truncated = True
                break
            parts.append(line)
            total += needed

        if truncated:
            note = "- (more glossary matches omitted)"
            if total + len(note) + 1 <= _INLINE_GLOSSARY_MAX_CHARS:
                parts.append(note)

        return "\n".join(parts).strip()

    def _load_templates(self) -> None:
        """Load prompt templates from files or use defaults"""
        styles = ["standard", "concise", "minimal"]
        self._text_compare_template = DEFAULT_TEXT_TO_EN_TEMPLATE

        if self.prompts_dir:
            # English file translation template: minimal is SSOT (style variants are ignored).
            to_en_prompt = self.prompts_dir / "file_translate_to_en_minimal.txt"
            if to_en_prompt.exists():
                en_template = to_en_prompt.read_text(encoding="utf-8")
            else:
                old_prompt = self.prompts_dir / "file_translate_to_en.txt"
                if old_prompt.exists():
                    en_template = old_prompt.read_text(encoding="utf-8")
                else:
                    en_template = DEFAULT_TO_EN_TEMPLATE

            for style in styles:
                self._templates[("en", style)] = en_template

            # Japanese template (no style variations)
            to_jp_prompt = self.prompts_dir / "file_translate_to_jp.txt"
            if to_jp_prompt.exists():
                jp_template = to_jp_prompt.read_text(encoding="utf-8")
            else:
                jp_template = DEFAULT_TO_JP_TEMPLATE

            # Use same JP template for all styles
            for style in styles:
                self._templates[("jp", style)] = jp_template

            # Load text translation templates (text_translate_to_*)
            # Text translation to Japanese (no style variations)
            text_to_jp = self.prompts_dir / "text_translate_to_jp.txt"
            if text_to_jp.exists():
                jp_text_template = text_to_jp.read_text(encoding="utf-8")
            else:
                jp_text_template = DEFAULT_TEXT_TO_JP_TEMPLATE

            for style in styles:
                self._text_templates.setdefault(("jp", style), jp_text_template)

            text_compare = self.prompts_dir / "text_translate_to_en_compare.txt"
            if text_compare.exists():
                en_text_template = text_compare.read_text(encoding="utf-8")
            else:
                en_text_template = DEFAULT_TEXT_TO_EN_TEMPLATE
            for style in styles:
                self._text_templates.setdefault(("en", style), en_text_template)
            self._text_compare_template = en_text_template

        else:
            # Use defaults
            for style in styles:
                self._templates[("en", style)] = DEFAULT_TO_EN_TEMPLATE
                self._templates[("jp", style)] = DEFAULT_TO_JP_TEMPLATE
                self._text_templates[("jp", style)] = DEFAULT_TEXT_TO_JP_TEMPLATE
                self._text_templates[("en", style)] = DEFAULT_TEXT_TO_EN_TEMPLATE
            self._text_compare_template = DEFAULT_TEXT_TO_EN_TEMPLATE

    def _get_template(
        self, output_language: str = "en", translation_style: str = "concise"
    ) -> str:
        """Get appropriate template based on output language and style."""
        key = (output_language, translation_style)
        if key in self._templates:
            return self._templates[key]

        # Fallback to concise if style not found
        fallback_key = (output_language, "concise")
        if fallback_key in self._templates:
            return self._templates[fallback_key]

        # Ultimate fallback
        return (
            DEFAULT_TO_EN_TEMPLATE
            if output_language == "en"
            else DEFAULT_TO_JP_TEMPLATE
        )

    def _resolve_langs(self, output_language: str) -> tuple[str, str, str, str]:
        if output_language == "jp":
            return "English", "en", "Japanese", "ja"
        return "Japanese", "ja", "English", "en"

    def build_simple_prompt(
        self,
        input_text: str,
        *,
        output_language: str = "en",
    ) -> str:
        user_input = self.normalize_input_text(input_text, output_language)
        if output_language == "jp":
            return (
                f"<bos><start_of_turn>user\n"
                f"Translate the text into Japanese suitable for financial statements. Treat 1 billion as 10 oku (10億). Convert billion → oku (億) by ×10 (add one zero). Translate every sentence/clause; do not omit or summarize. Do not echo or repeat the input text. Preserve line breaks and all numeric facts. Output must be Japanese only. Output the translation only (no labels, no commentary). Do not output other prompt markers (e.g., \"===INPUT_TEXT===\" / \"===END_INPUT_TEXT===\").\n"
                f"Text:\n"
                f"===INPUT_TEXT===\n"
                f"{user_input}\n"
                f"===END_INPUT_TEXT===<end_of_turn>\n"
                f"<start_of_turn>model\n"
            )
        return (
            f"<bos><start_of_turn>user\n"
            f"Translate the Japanese text into English suitable for financial statements. Treat 1 billion as 10 oku (10億). Convert oku → billion by ÷10 (drop one zero). Translate every sentence/clause; do not omit or summarize. Do not echo or repeat the input text. Preserve line breaks and all numeric facts. Output must be English only. Output the translation only (no labels, no commentary). Do not output other prompt markers (e.g., \"===INPUT_TEXT===\" / \"===END_INPUT_TEXT===\").\n"
            f"Text:\n"
            f"===INPUT_TEXT===\n"
            f"{user_input}\n"
            f"===END_INPUT_TEXT===<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )

    def _build_legacy_simple_prompt(
        self,
        input_text: str,
        *,
        output_language: str = "en",
    ) -> str:
        normalized_text = self.normalize_input_text(input_text, output_language)
        source_lang, source_code, target_lang, target_code = self._resolve_langs(
            output_language
        )
        prompt = _LEGACY_SIMPLE_PROMPT_TEMPLATE.replace("{SOURCE_LANG}", source_lang)
        prompt = prompt.replace("{SOURCE_CODE}", source_code)
        prompt = prompt.replace("{TARGET_LANG}", target_lang)
        prompt = prompt.replace("{TARGET_CODE}", target_code)
        prompt = prompt.replace("{TEXT}", normalized_text)
        return prompt

    def _append_simple_prompt(self, prompt: str, simple_prompt: str) -> str:
        existing = (prompt or "").strip()
        if not existing:
            return simple_prompt
        if simple_prompt in existing:
            return existing
        return f"{existing}\n\n{simple_prompt}"

    def get_text_template(
        self, output_language: str = "en", translation_style: str = "concise"
    ) -> Optional[str]:
        """Get cached text translation template.

        Args:
            output_language: "en" or "jp"
            translation_style: "standard" or "concise" (for backward compatibility, "minimal" is treated as "concise")

        Returns:
            Cached template string, or None if not found
        """
        key = (output_language, translation_style)
        if key in self._text_templates:
            return self._text_templates[key]

        # Fallback to concise if style not found
        fallback_key = (output_language, "concise")
        if fallback_key in self._text_templates:
            return self._text_templates[fallback_key]

        return None

    def get_text_compare_template(self) -> Optional[str]:
        """Get cached text translation comparison template."""
        return self._text_compare_template

    def _apply_placeholders(
        self,
        template: str,
        reference_section: str,
        input_text: str,
        output_language: str = "en",
        translation_style: str = "concise",
    ) -> str:
        """Apply all placeholder replacements to a template.

        Args:
            template: Prompt template string
            reference_section: Reference section content
            input_text: Input text to translate
            output_language: "en", "jp", or "common"
            translation_style: Translation style name

        Returns:
            Template with all placeholders replaced
        """
        input_text = self.normalize_input_text(input_text, output_language)

        source_lang, source_code, target_lang, target_code = self._resolve_langs(
            output_language
        )

        # Replace placeholders
        prompt = template.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", input_text)
        prompt = prompt.replace("{TEXT}", input_text)
        prompt = prompt.replace("{SOURCE_LANG}", source_lang)
        prompt = prompt.replace("{SOURCE_CODE}", source_code)
        prompt = prompt.replace("{TARGET_LANG}", target_lang)
        prompt = prompt.replace("{TARGET_CODE}", target_code)
        # Remove old style placeholder if present (for backwards compatibility)
        prompt = prompt.replace("{translation_style}", translation_style)
        prompt = prompt.replace("{style}", translation_style)

        return prompt

    def _insert_extra_instruction(self, prompt: str, extra_instruction: str) -> str:
        """Insert extra instruction before the input marker if present."""
        marker = "===INPUT_TEXT==="
        extra_instruction = extra_instruction.strip()
        if not extra_instruction:
            return prompt
        if marker in prompt:
            return prompt.replace(marker, f"{extra_instruction}\n{marker}", 1)
        return f"{extra_instruction}\n{prompt}"

    def build(
        self,
        input_text: str,
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        extra_instruction: Optional[str] = None,
        reference_files: Optional[Sequence[Path]] = None,
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            input_text: Text or batch to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard" or "concise" (default: "concise")
                              Only affects English output
            extra_instruction: Optional instruction inserted before input markers

        Returns:
            Complete prompt string
        """
        reference_section = ""

        # Get appropriate template based on language and style
        template = self._get_template(output_language, translation_style)

        prompt = self._apply_placeholders(
            template,
            reference_section,
            input_text,
            output_language,
            translation_style,
        )
        simple_prompt = self._build_legacy_simple_prompt(
            input_text,
            output_language=output_language,
        )
        prompt = self._append_simple_prompt(prompt, simple_prompt)
        if extra_instruction:
            prompt = self._insert_extra_instruction(prompt, extra_instruction)
        return prompt

    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        reference_files: Optional[Sequence[Path]] = None,
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            texts: List of texts to translate
            has_reference_files: Whether reference files are attached
            output_language: "en" or "jp" (default: "en")
            translation_style: "standard" or "concise" (default: "concise")
                              Only affects English output
            include_item_ids: Prepend [[ID:n]] marker for stable parsing
            reference_files: Optional reference files (attached/embedded depending on backend)

        Returns:
            Complete prompt with numbered input
        """
        extra_instruction = None
        if include_item_ids:
            extra_instruction = ID_MARKER_INSTRUCTION
            texts = [f"[[ID:{i + 1}]] {text}" for i, text in enumerate(texts)]

        # Format as numbered list
        numbered_input = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(texts))

        return self.build(
            numbered_input,
            has_reference_files,
            output_language,
            translation_style,
            extra_instruction=extra_instruction,
            reference_files=reference_files,
        )

    def build_reference_section(
        self,
        reference_files: Optional[Sequence[Path]],
    ) -> str:
        """Return reference section text (deprecated).

        Args:
            reference_files: Optional reference files being attached

        Returns:
            Reference section text for prompt
        """
        return ""
