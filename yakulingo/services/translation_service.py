# yakulingo/services/translation_service.py
"""
Main translation service.
Coordinates between UI, Copilot, and file processors.
Bidirectional translation: Japanese → English, Other → Japanese (auto-detected).
"""

# ruff: noqa: E402

import csv
import logging
import os
import threading
import time
from contextlib import contextmanager, nullcontext
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING
from zipfile import BadZipFile
import unicodedata

import re

from yakulingo.services.local_ai_client import is_truncated_json

# Module logger
logger = logging.getLogger(__name__)

_LOCAL_AI_TIMING_ENABLED = os.environ.get("YAKULINGO_LOCAL_AI_TIMING") == "1"

DEFAULT_TEXT_STYLE = "minimal"
TEXT_STYLE_ORDER: tuple[str, ...] = ("minimal",)

_TEXT_TO_EN_OUTPUT_LANGUAGE_RETRY_INSTRUCTION = (
    "CRITICAL: English only (no Japanese/Chinese/Korean scripts; no Japanese punctuation). "
    "Keep the exact output format (Translation sections only; no explanations/notes)."
)
_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION = (
    "CRITICAL: Follow numeric conversion rules. "
    "Do not use 'billion', 'trillion', or 'bn'. Use 'oku' (and 'k') as specified. "
    "If numeric conversion hints are provided, use them verbatim."
)

# Pre-compiled regex patterns for performance
# Support both half-width (:) and full-width (：) colons, and markdown bold (**訳文:**)
_RE_MULTI_OPTION = re.compile(
    r"\[(\d+)\]\s*\**訳文\**[:：]\s*(.+?)\s*\**解説\**[:：]\s*(.+?)(?=\[\d+\]|$)",
    re.DOTALL,
)
_RE_STYLE_SECTION = re.compile(
    r"^\s*(?:>\s*)?(?:#{1,6}\s*)?[\[［]\s*(standard|concise|minimal)\s*[\]］]",
    re.IGNORECASE | re.MULTILINE,
)

# Translation text pattern - supports multiple formats:
# - Japanese: 訳文 (colon optional), 翻訳 (colon REQUIRED to avoid "翻訳してください" match)
#   NOTE: 「訳」単体は「英訳」「和訳」等にマッチしてしまうため除外
# - English: Translation, Translated (colon REQUIRED to avoid false matches)
# - Formats: "訳文:", "**訳文:**", "[訳文]", "### 訳文:", "> 訳文:", "Translation:"
_RE_TRANSLATION_TEXT = re.compile(
    r"[#>*\s-]*[\[\(]?\**(?:"
    r"訳文[:：]?"  # 訳文 - colon optional
    r"|翻訳[:：]"  # 翻訳 - colon REQUIRED (avoid "翻訳してください" match)
    r"|(?:Translation|Translated)[:：]"  # English labels - colon REQUIRED
    r")\**[\]\)]?\s*"
    r"(.+?)"
    # Lookahead: 解説 must be at line start (after \n) to avoid "解説付き" false match
    r"(?=\n[#>*\s-]*[\[\(]?\**(?:解説|説明|Explanation|Notes?|Commentary)\**[\]\)]?[:：]?\s*|$)",
    re.DOTALL | re.IGNORECASE,
)

# Explanation pattern - supports multiple formats:
# - Japanese: 解説, 説明 (colon optional)
# - English: Explanation, Notes, Note, Commentary (colon optional for flexibility)
# NOTE: Must be at line start (after ^ or \n) to avoid "解説付き" false match
_RE_EXPLANATION = re.compile(
    r"(?:^|\n)[#>*\s-]*[\[\(]?\**(?:解説|説明|Explanation|Notes?|Commentary)\**[\]\)]?[:：]?\s*(.+)",
    re.DOTALL | re.IGNORECASE,
)
_RE_MARKDOWN_SEPARATOR = re.compile(r"\n?\s*[\*\-]{3,}\s*$")
_RE_FILENAME_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RE_INPUT_MARKER_LINE = re.compile(
    r"^\s*(?:###\s*INPUT\b.*|<<<INPUT_TEXT>>>|<<<END_INPUT_TEXT>>>|===INPUT_TEXT===|===END_INPUT_TEXT===)\s*$",
    re.IGNORECASE,
)

# Pattern to remove translation label prefixes from parsed result
# These labels come from prompt template output format examples (e.g., "訳文: 英語翻訳")
# When Copilot follows the format literally, these labels appear at the start of the translation
_RE_TRANSLATION_LABEL = re.compile(
    r"^(?:英語翻訳|日本語翻訳|English\s*Translation|Japanese\s*Translation)\s*",
    re.IGNORECASE,
)

# Pattern to remove trailing attached filename from explanation
# Copilot sometimes appends the attached file name (e.g., "glossary", "glossary.csv") to the response
# This pattern matches common reference file names at the end of the explanation
_RE_TRAILING_FILENAME = re.compile(
    r"[\s。．.、,]*(glossary(?:_old)?|translation_rules|abbreviations|用語集|略語集)(?:\.[a-z]{2,4})?\s*$",
    re.IGNORECASE,
)

_RE_TRAILING_ATTACHMENT_LINK = re.compile(
    r"\s*\[[^\]]+?\|\s*(?:excel|word|powerpoint|pdf|csv|text|txt|file)\s*\]\([^)]+\)\s*$",
    re.IGNORECASE,
)
_RE_TRAILING_ATTACHMENT_LABEL = re.compile(
    r"\s*\[[^\]]+?\|\s*(?:excel|word|powerpoint|pdf|csv|text|txt|file)\s*\]\s*$",
    re.IGNORECASE,
)
_RE_ITEM_ID_MARKER = re.compile(r"^\s*\[\[ID:\d+\]\]\s*")

_RE_JP_KANA = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F]")
_RE_CJK_IDEOGRAPH = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
_RE_LATIN_ALPHA = re.compile(r"[A-Za-z]")
_RE_HANGUL = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")
_CHINESE_PUNCTUATION_HINTS = frozenset("，；：")
# NOTE: Also match unit tokens directly attached to numbers (e.g., "1.2bn", "2238.5billion").
_RE_EN_BILLION_TRILLION = re.compile(
    r"(?:\b(?:billion|trillion|bn)\b|(?<=\d)(?:billion|trillion|bn)\b)",
    re.IGNORECASE,
)
_RE_EN_OKU = re.compile(r"\boku\b", re.IGNORECASE)
_RE_JP_LARGE_UNIT = re.compile(r"[兆億]")
_INT_WITH_OPTIONAL_COMMAS_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_RE_JP_OKU_CHOU_YEN_AMOUNT = re.compile(
    rf"(?P<sign>[▲+\-])?\s*(?:(?P<trillion>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})兆(?:(?P<oku>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})億)?|(?P<oku_only>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})億)(?P<yen>円)?"
)
_RE_JP_MAN_YEN_AMOUNT = re.compile(
    rf"(?P<sign>[▲+\-])?\s*(?P<man>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})万円"
)
_RE_JP_YEN_AMOUNT = re.compile(
    rf"(?P<sign>[▲+\-])?\s*(?P<yen>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})円"
)
_JP_PUNCTUATION_GUARD_TRANSLATION_TABLE = str.maketrans(
    {
        "、": ",",
        "・": "·",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
    }
)
_RE_STYLE_DIFF_TOKENS = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _normalize_en_translation_for_output_language_guard(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").strip()
    if not normalized:
        return ""

    normalized = normalized.translate(_JP_PUNCTUATION_GUARD_TRANSLATION_TABLE)

    def parse_int(value: str) -> Optional[int]:
        try:
            return int(value.replace(",", ""))
        except ValueError:
            return None

    def format_int(value: int, sign: str) -> str:
        if not sign:
            return f"{value:,}"
        if sign == "▲":
            sign = "-"
        return f"{sign}{value:,}"

    def repl_oku_chou(match: re.Match[str]) -> str:
        sign = (match.group("sign") or "").strip()
        has_yen = bool(match.group("yen"))

        trillion_str = match.group("trillion") or ""
        oku_str = match.group("oku") or ""
        oku_only_str = match.group("oku_only") or ""

        if trillion_str:
            trillion = parse_int(trillion_str)
            if trillion is None:
                return match.group(0)
            oku_part = parse_int(oku_str) if oku_str else 0
            if oku_part is None:
                return match.group(0)
            total_oku = trillion * 10_000 + oku_part
        else:
            oku_only = parse_int(oku_only_str)
            if oku_only is None:
                return match.group(0)
            total_oku = oku_only

        formatted = format_int(total_oku, sign)
        return f"{formatted} oku yen" if has_yen else f"{formatted} oku"

    def repl_man(match: re.Match[str]) -> str:
        sign = (match.group("sign") or "").strip()
        man = parse_int(match.group("man") or "")
        if man is None:
            return match.group(0)
        k = man * 10
        return f"{format_int(k, sign)}k yen"

    def repl_yen(match: re.Match[str]) -> str:
        sign = (match.group("sign") or "").strip()
        yen = parse_int(match.group("yen") or "")
        if yen is None:
            return match.group(0)
        return f"{format_int(yen, sign)} yen"

    normalized = _RE_JP_OKU_CHOU_YEN_AMOUNT.sub(repl_oku_chou, normalized)
    normalized = _RE_JP_MAN_YEN_AMOUNT.sub(repl_man, normalized)
    normalized = _RE_JP_YEN_AMOUNT.sub(repl_yen, normalized)
    return normalized


def _tokenize_style_diff(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    if not normalized:
        return []
    return _RE_STYLE_DIFF_TOKENS.findall(normalized)


def _should_rewrite_compact_style(
    *,
    base_text: str,
    compact_text: str,
) -> bool:
    base = (base_text or "").strip()
    compact = (compact_text or "").strip()

    if not base or not compact:
        return False

    if compact == base:
        return True

    base_tokens = _tokenize_style_diff(base)
    compact_tokens = _tokenize_style_diff(compact)
    if len(base_tokens) < 12 or len(compact_tokens) < 8:
        return False

    compact_word_ratio = len(compact_tokens) / len(base_tokens)
    similarity_to_base = SequenceMatcher(None, base_tokens, compact_tokens).ratio()
    if compact_word_ratio >= 0.85 and similarity_to_base >= 0.92:
        return True

    return False


def _build_style_diff_rewrite_prompt(base_text: str, styles: list[str]) -> str:
    requested = [s for s in styles if s in TEXT_STYLE_ORDER]
    if not requested:
        requested = ["minimal"]

    labels = ", ".join(f"[{style}]" for style in requested)
    lines = [
        "Rewrite the provided English text into the requested style(s).",
        "Do NOT translate from Japanese; the input is already English.",
        "",
        "Rules (critical):",
        f"- Output ONLY the requested style sections: {labels}",
        "- Output must match the exact format shown below (no extra headings/notes/code fences).",
        "- English only (no Japanese/Chinese/Korean scripts; no Japanese punctuation).",
        "- Do NOT output any explanations/notes.",
        "- Keep numbers/units/proper nouns exactly as they appear in the input.",
        "- Preserve line breaks and tabs as much as possible.",
        "",
        "Style rules:",
    ]
    if "concise" in requested:
        lines += [
            "[concise]",
            "- Concise business English; remove wordiness; keep meaning.",
            "- Target length: ~70–85% of the input (rough word count).",
            "",
        ]
    if "minimal" in requested:
        lines += [
            "[minimal]",
            "- Minimal business English; keep core meaning; omit non-essential words.",
            "- Target length: ~60–75% of the input (rough word count).",
            "",
        ]
    lines.append("### Output format (exact)")
    for style in requested:
        lines += [f"[{style}]", "Translation:", "", ""]

    lines += [
        "### INPUT",
        "===INPUT_TEXT===",
        base_text,
        "===END_INPUT_TEXT===",
    ]
    return "\n".join(lines)


def _looks_untranslated_to_en(text: str) -> bool:
    """Return True when the 'English' translation looks mostly Japanese."""
    text = text.strip()
    if not text:
        return False

    kana_count = len(_RE_JP_KANA.findall(text))
    cjk_count = len(_RE_CJK_IDEOGRAPH.findall(text))
    latin_count = len(_RE_LATIN_ALPHA.findall(text))
    jp_total = kana_count + cjk_count

    if jp_total == 0:
        return False
    if latin_count == 0:
        return True

    total_letters = jp_total + latin_count
    jp_ratio = jp_total / total_letters if total_letters else 0.0

    if kana_count >= 1 and jp_total >= 5 and jp_ratio >= 0.05:
        return True
    if jp_total >= 20 and jp_ratio >= 0.25:
        return True
    if jp_total >= 50 and jp_ratio >= 0.15:
        return True
    return False


def _looks_like_chinese_in_kana_less_cjk(text: str) -> bool:
    """Heuristic for kana-less CJK that is likely Chinese (vs Japanese headings).

    This is intentionally conservative to avoid false positives for Japanese text.
    """
    if not text:
        return False
    if _RE_JP_KANA.search(text):
        return False
    if not _RE_CJK_IDEOGRAPH.search(text):
        return False

    if any(p in text for p in _CHINESE_PUNCTUATION_HINTS):
        return True

    cjk_count = len(_RE_CJK_IDEOGRAPH.findall(text))
    if any(p in text for p in LanguageDetector._JAPANESE_PUNCTUATION):
        return False
    if text.endswith("。") and cjk_count >= 8:
        return True
    if cjk_count >= 25:
        return True
    return False


def _insert_extra_instruction(prompt: str, extra_instruction: str) -> str:
    """Insert extra instruction before the input marker if present."""
    marker = "===INPUT_TEXT==="
    extra_instruction = extra_instruction.strip()
    if not extra_instruction:
        return prompt
    if marker in prompt:
        return prompt.replace(marker, f"{extra_instruction}\n{marker}", 1)
    return f"{extra_instruction}\n{prompt}"


def _build_to_en_numeric_hints(text: str) -> str:
    """Build per-input numeric conversion hints for JP→EN (兆/億 → oku)."""
    if not text:
        return ""
    if not _RE_JP_LARGE_UNIT.search(text):
        return ""

    def parse_int(value: str) -> Optional[int]:
        try:
            return int((value or "").replace(",", ""))
        except ValueError:
            return None

    conversions: list[tuple[str, str]] = []
    max_lines = 12
    seen: set[str] = set()
    for match in _RE_JP_OKU_CHOU_YEN_AMOUNT.finditer(text):
        raw = (match.group(0) or "").strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)

        sign_marker = (match.group("sign") or "").strip()
        is_negative = sign_marker == "▲" or sign_marker.startswith("-")

        has_yen = bool(match.group("yen"))
        trillion_str = match.group("trillion") or ""
        oku_str = match.group("oku") or ""
        oku_only_str = match.group("oku_only") or ""

        if trillion_str:
            trillion = parse_int(trillion_str)
            if trillion is None:
                continue
            oku_part = parse_int(oku_str) if oku_str else 0
            if oku_part is None:
                continue
            total_oku = trillion * 10_000 + oku_part
        else:
            oku_only = parse_int(oku_only_str)
            if oku_only is None:
                continue
            total_oku = oku_only

        formatted = f"{total_oku:,}"
        if is_negative:
            formatted = f"({formatted})"
        unit = "oku yen" if has_yen else "oku"
        conversions.append((raw, f"{formatted} {unit}".strip()))
        if len(conversions) >= max_lines:
            break

    if not conversions:
        return ""

    lines = ["### Numeric conversion hints (use verbatim)"]
    for raw, converted in conversions:
        lines.append(f"- {raw} -> {converted}")
    return "\n".join(lines) + "\n"


_RE_EN_NUMBER_WITH_BILLION_UNIT = re.compile(
    rf"(?P<prefix>[▲+\-]?\(?)"
    rf"(?P<number>{_INT_WITH_OPTIONAL_COMMAS_PATTERN}(?:\.\d+)?)"
    rf"(?P<suffix>\)?)"
    r"(?P<sep>\s*)"
    r"(?P<unit>billion|trillion|bn)\b",
    re.IGNORECASE,
)


def _collect_expected_oku_values_from_source_text(text: str) -> set[int]:
    """Extract expected `oku` values from JP source text containing 兆/億."""
    if not text:
        return set()
    if not _RE_JP_LARGE_UNIT.search(text):
        return set()

    def parse_int(value: str) -> Optional[int]:
        try:
            return int((value or "").replace(",", ""))
        except ValueError:
            return None

    expected: set[int] = set()
    for match in _RE_JP_OKU_CHOU_YEN_AMOUNT.finditer(text):
        trillion_str = match.group("trillion") or ""
        oku_str = match.group("oku") or ""
        oku_only_str = match.group("oku_only") or ""

        if trillion_str:
            trillion = parse_int(trillion_str)
            if trillion is None:
                continue
            oku_part = parse_int(oku_str) if oku_str else 0
            if oku_part is None:
                continue
            total_oku = trillion * 10_000 + oku_part
        else:
            oku_only = parse_int(oku_only_str)
            if oku_only is None:
                continue
            total_oku = oku_only

        expected.add(total_oku)

    return expected


def _fix_to_en_oku_numeric_unit_if_possible(
    *,
    source_text: str,
    translated_text: str,
) -> tuple[str, bool]:
    """Try to fix `billion/trillion/bn` → `oku` for JP→EN when it is safe.

    This targets common Copilot mistakes such as:
    - `22,385 billion yen` → `22,385 oku yen` (unit label mismatch; number is already in oku)
    - `2,238.5 billion yen` → `22,385 oku yen` (unit-based conversion to oku matches hints)
    """
    if not translated_text:
        return translated_text, False

    expected_oku_values = _collect_expected_oku_values_from_source_text(source_text)
    if not expected_oku_values:
        return translated_text, False

    if not _RE_EN_NUMBER_WITH_BILLION_UNIT.search(translated_text):
        return translated_text, False

    def parse_float(value: str) -> Optional[float]:
        try:
            return float((value or "").replace(",", ""))
        except ValueError:
            return None

    def as_int_if_close(value: float, tolerance: float = 1e-6) -> Optional[int]:
        rounded = round(value)
        if abs(value - rounded) <= tolerance:
            return int(rounded)
        return None

    def repl(match: re.Match[str]) -> str:
        prefix = match.group("prefix") or ""
        number_str = match.group("number") or ""
        suffix = match.group("suffix") or ""
        sep = match.group("sep") or ""
        unit = (match.group("unit") or "").lower()

        number = parse_float(number_str)
        if number is None:
            return match.group(0)

        safe_sep = sep if sep else " "

        # Case A: the number already equals the expected oku value (unit label only).
        number_int = as_int_if_close(number, tolerance=1e-9)
        if number_int is not None and number_int in expected_oku_values:
            return f"{prefix}{number_str}{suffix}{safe_sep}oku"

        # Case B: convert billion/trillion/bn → oku and verify it matches expected values.
        factor = 10.0 if unit in ("billion", "bn") else 10_000.0
        converted = number * factor
        converted_int = as_int_if_close(converted)
        if converted_int is None or converted_int not in expected_oku_values:
            return match.group(0)

        formatted = f"{converted_int:,}"
        return f"{prefix}{formatted}{suffix}{safe_sep}oku"

    fixed, count = _RE_EN_NUMBER_WITH_BILLION_UNIT.subn(repl, translated_text)
    return fixed, bool(count) and fixed != translated_text


def _needs_to_en_numeric_rule_retry_copilot(
    source_text: str,
    translated_text: str,
) -> bool:
    """Copilot向け: 明確に誤変換の可能性が高い場合のみ最小限でリトライする。

    - `billion/trillion/bn` は確実にNG
    - 兆/億を含む入力で `oku` が欠落していても、出力が兆/億を保持している場合は
      「表記が変換されていないだけ」で意味は崩れにくいのでリトライしない（速度優先）。
    """
    if not translated_text:
        return False
    if _RE_EN_BILLION_TRILLION.search(translated_text):
        return True

    if not _RE_JP_LARGE_UNIT.search(source_text):
        return False
    if _RE_EN_OKU.search(translated_text):
        return False
    if _RE_JP_LARGE_UNIT.search(translated_text):
        return False
    return True


def _needs_to_en_numeric_rule_retry_copilot_after_auto_fix(
    source_text: str,
    translated_text: str,
) -> bool:
    """Copilot再呼び出しが必要か（安全なローカル補正後もNGが残る場合のみTrue）。"""
    if not _needs_to_en_numeric_rule_retry_copilot(source_text, translated_text):
        return False

    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
        source_text=source_text,
        translated_text=translated_text,
    )
    if fixed and not _needs_to_en_numeric_rule_retry_copilot(source_text, fixed_text):
        return False

    return True


def _needs_to_en_numeric_rule_retry(source_text: str, translated_text: str) -> bool:
    if not translated_text:
        return False
    if _RE_EN_BILLION_TRILLION.search(translated_text):
        return True
    if _RE_JP_LARGE_UNIT.search(source_text) and not _RE_EN_OKU.search(translated_text):
        return True
    return False


def _looks_incomplete_translation_to_en(source_text: str, translated_text: str) -> bool:
    source = (source_text or "").strip()
    if len(source) < 40:
        return False

    translated = (translated_text or "").strip()
    if not translated:
        return True

    tokens = [token for token in translated.split() if token]
    if len(translated) <= 20 and len(tokens) <= 2:
        return True

    return False


def _sanitize_output_stem(name: str) -> str:
    """Sanitize a filename stem for cross-platform safety.

    Replaces characters forbidden on Windows (\\, /, :, *, ?, ", <, >, | and control chars)
    with underscores while preserving Unicode characters like Japanese or emoji.
    Returns a fallback name when the result would be empty.
    """

    sanitized = _RE_FILENAME_FORBIDDEN.sub("_", unicodedata.normalize("NFC", name))
    sanitized = sanitized.strip()
    return sanitized or "translated_file"


def _strip_input_markers(text: str) -> str:
    """Remove input marker lines accidentally echoed by Copilot."""
    if not text:
        return text
    lines = [
        line for line in text.splitlines() if not _RE_INPUT_MARKER_LINE.match(line)
    ]
    return "\n".join(lines).strip()


def _strip_trailing_attachment_links(text: str) -> str:
    """Remove trailing Copilot attachment links like [file | Excel](...)."""
    if not text:
        return text
    cleaned = text.strip()
    while True:
        updated = _RE_TRAILING_ATTACHMENT_LINK.sub("", cleaned)
        if updated == cleaned:
            break
        cleaned = updated.strip()
    cleaned = _RE_TRAILING_ATTACHMENT_LABEL.sub("", cleaned).strip()
    return cleaned


def _extract_json_string_partial(text: str, start_index: int) -> tuple[str, bool]:
    """Best-effort extraction for a JSON string value from a partial buffer."""
    out: list[str] = []
    escaped = False
    for ch in text[start_index:]:
        if escaped:
            out.append("\\" + ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            return "".join(out), True
        out.append(ch)
    if escaped:
        out.append("\\")
    return "".join(out), False


def _extract_first_translation_from_json(buffer: str) -> Optional[str]:
    key = '"translation"'
    key_idx = buffer.find(key)
    if key_idx == -1:
        return None
    colon_idx = buffer.find(":", key_idx + len(key))
    if colon_idx == -1:
        return None
    quote_idx = buffer.find('"', colon_idx + 1)
    if quote_idx == -1:
        return None
    value, _ = _extract_json_string_partial(buffer, quote_idx + 1)
    return value or None


def _extract_json_value_for_key(
    buffer: str,
    key: str,
    *,
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[str]:
    token = f'"{key}"'
    segment = buffer[start:end] if end is not None else buffer[start:]
    key_idx = segment.find(token)
    if key_idx == -1:
        return None
    colon_idx = segment.find(":", key_idx + len(token))
    if colon_idx == -1:
        return None
    quote_idx = segment.find('"', colon_idx + 1)
    if quote_idx == -1:
        return None
    value, _ = _extract_json_string_partial(segment, quote_idx + 1)
    return value or None


def _extract_options_preview(buffer: str) -> Optional[str]:
    if '"options"' not in buffer:
        return None
    positions: list[tuple[int, str]] = []
    for style in TEXT_STYLE_ORDER:
        idx = buffer.find(f'"style":"{style}"')
        if idx != -1:
            positions.append((idx, style))
    if not positions:
        return None
    positions.sort()
    lines: list[str] = []
    for i, (idx, style) in enumerate(positions):
        next_idx = positions[i + 1][0] if i + 1 < len(positions) else None
        translation = _extract_json_value_for_key(
            buffer, "translation", start=idx, end=next_idx
        )
        explanation = _extract_json_value_for_key(
            buffer, "explanation", start=idx, end=next_idx
        )
        if not translation and not explanation:
            continue
        if translation:
            lines.append(f"[{style}] {translation}")
        else:
            lines.append(f"[{style}]")
        if explanation:
            lines.append(f"- {explanation}")
    preview = "\n".join(lines).strip()
    return preview or None


def _wrap_local_streaming_on_chunk(
    on_chunk: Optional[Callable[[str], None]],
) -> Optional[Callable[[str], None]]:
    if on_chunk is None:
        return None
    last_emitted = ""
    last_emit_time = 0.0
    last_parse_time = 0.0
    raw_cached = ""
    raw_parts: list[str] = []
    raw_len = 0
    last_parse_len = 0
    has_options = False
    has_explanation = False
    parse_min_delta_chars = 128
    throttle_seconds = 0.08

    def _handle(delta: str) -> None:
        nonlocal last_emitted, last_emit_time, last_parse_time
        nonlocal raw_cached, raw_parts, raw_len, last_parse_len
        nonlocal has_options, has_explanation

        if not delta:
            return
        if raw_cached and delta.startswith(raw_cached):
            raw_cached = delta
            raw_parts.clear()
            raw_len = len(delta)
            last_parse_len = 0
        else:
            raw_parts.append(delta)
            raw_len += len(delta)

        if not has_options and '"options"' in delta:
            has_options = True
        if not has_explanation and '"explanation"' in delta:
            has_explanation = True

        now = time.monotonic()
        if (
            raw_len >= parse_min_delta_chars
            and (now - last_parse_time) < throttle_seconds
            and (raw_len - last_parse_len) < parse_min_delta_chars
            and not any(ch in delta for ch in ("}", "]"))
        ):
            return

        if raw_parts:
            raw_cached += "".join(raw_parts)
            raw_parts.clear()
        raw = raw_cached
        last_parse_len = raw_len
        last_parse_time = now

        if raw_len < 1024:
            if not has_options and '"options"' in raw:
                has_options = True
            if not has_explanation and '"explanation"' in raw:
                has_explanation = True

        candidate = _extract_options_preview(raw) if has_options else None
        if candidate is None:
            translation = _extract_first_translation_from_json(raw)
            if not translation:
                return
            explanation = (
                _extract_json_value_for_key(raw, "explanation")
                if has_explanation
                else None
            )
            if explanation:
                candidate = f"{translation}\n{explanation}"
            else:
                candidate = translation

        if candidate == last_emitted or len(candidate) < len(last_emitted):
            return
        delta_len = len(candidate) - len(last_emitted)
        if (now - last_emit_time) < throttle_seconds and delta_len < 3:
            stripped = raw.lstrip()
            if stripped.startswith(("{", "[")) and is_truncated_json(raw):
                return
        last_emitted = candidate
        last_emit_time = now
        on_chunk(candidate)

    return _handle


# =============================================================================
# Language Detection
# =============================================================================


class LanguageDetector:
    """
    Language detection with hybrid local/Copilot approach.

    Provides character-level detection helpers and text-level language detection.
    Use the singleton instance `language_detector` or create your own instance.

    Example:
        # Use singleton
        from yakulingo.services.translation_service import language_detector
        if language_detector.is_japanese("こんにちは"):
            print("Japanese text detected")

        # Or create instance
        detector = LanguageDetector()
        lang = detector.detect_local("Hello world")
    """

    # Detection constants
    MIN_TEXT_LENGTH_FOR_SAMPLING = 20  # Below this, check all chars directly
    MAX_ANALYSIS_LENGTH = 500  # Sample size for language detection

    # Staged early exit thresholds for faster detection
    # Each tuple: (min_chars, jp_threshold, non_jp_threshold)
    # More aggressive at early stages, more accurate with more samples
    EARLY_EXIT_STAGES = (
        (20, 0.85, 0.05),  # 20 chars: 85%+ → definitely Japanese, <5% → definitely not
        (35, 0.70, 0.08),  # 35 chars: 70%+ → likely Japanese, <8% → likely not
        (50, 0.60, 0.10),  # 50 chars: 60%+ → probably Japanese, <10% → probably not
    )

    # Japanese-specific punctuation (not used in Chinese)
    _JAPANESE_PUNCTUATION = frozenset("、・「」『』")

    # Chinese detection heuristic (no extra data):
    # Approximate "Japanese-usable character set" with shift_jisx0213.
    # If the text has no kana and contains >= N CJK ideographs that are not encodable
    # in shift_jisx0213, treat it as Chinese.
    #
    # This is intentionally conservative because JP→EN is the primary use case; false
    # positives (treating Japanese as Chinese) are more harmful than misses.
    _MIN_UNENCODABLE_CJK_FOR_CHINESE = 2

    @staticmethod
    @lru_cache(maxsize=4096)
    def _is_encodable_in_shift_jisx0213(char: str) -> bool:
        try:
            char.encode("shift_jisx0213")
            return True
        except UnicodeEncodeError:
            return False

    # =========================================================================
    # Character Detection Helpers (static methods)
    # =========================================================================

    @staticmethod
    def is_japanese_char(code: int) -> bool:
        """Check if a Unicode code point is a Japanese character."""
        return (
            0x3040 <= code <= 0x309F  # Hiragana
            or 0x30A0 <= code <= 0x30FF  # Katakana
            or 0x4E00 <= code <= 0x9FFF  # CJK Kanji
            or 0x31F0 <= code <= 0x31FF  # Katakana extensions
            or 0xFF65 <= code <= 0xFF9F
        )  # Halfwidth Katakana

    @staticmethod
    def is_hiragana(code: int) -> bool:
        """Check if a Unicode code point is Hiragana."""
        return 0x3040 <= code <= 0x309F

    @staticmethod
    def is_katakana(code: int) -> bool:
        """Check if a Unicode code point is Katakana (including extensions)."""
        return (
            0x30A0 <= code <= 0x30FF  # Katakana
            or 0x31F0 <= code <= 0x31FF  # Katakana extensions
            or 0xFF65 <= code <= 0xFF9F
        )  # Halfwidth Katakana

    @staticmethod
    def is_cjk_ideograph(code: int) -> bool:
        """Check if a Unicode code point is a CJK ideograph (Kanji/Hanzi)."""
        return 0x4E00 <= code <= 0x9FFF

    @staticmethod
    def is_hangul(code: int) -> bool:
        """Check if a Unicode code point is Korean Hangul."""
        return (
            0xAC00 <= code <= 0xD7AF  # Hangul Syllables
            or 0x1100 <= code <= 0x11FF  # Hangul Jamo
            or 0x3130 <= code <= 0x318F
        )  # Hangul Compatibility Jamo

    @staticmethod
    def is_latin(code: int) -> bool:
        """Check if a Unicode code point is Latin alphabet."""
        return (
            0x0041 <= code <= 0x005A  # A-Z
            or 0x0061 <= code <= 0x007A  # a-z
            or 0x00C0 <= code <= 0x024F
        )  # Latin Extended (accented chars)

    @staticmethod
    def is_punctuation(char: str) -> bool:
        """Check if char is punctuation (optimized with category prefix)."""
        cat = unicodedata.category(char)
        return cat[0] == "P"  # All punctuation categories start with 'P'

    @classmethod
    def has_japanese_punctuation(cls, text: str) -> bool:
        """Check if text contains Japanese-specific punctuation.

        These punctuation marks are unique to Japanese and not used in Chinese:
        - 、(touten): Japanese comma
        - ・(nakaguro): Japanese middle dot
        - 「」: Japanese quotation marks
        - 『』: Japanese double quotation marks
        """
        return any(char in cls._JAPANESE_PUNCTUATION for char in text)

    # =========================================================================
    # Text-Level Language Detection
    # =========================================================================

    def is_japanese(self, text: str, threshold: float = 0.3) -> bool:
        """
        Detect if text is primarily Japanese.

        Uses Unicode character ranges to identify Japanese characters:
        - Hiragana: U+3040 - U+309F
        - Katakana: U+30A0 - U+30FF
        - CJK Unified Ideographs (Kanji): U+4E00 - U+9FFF
        - Katakana Phonetic Extensions: U+31F0 - U+31FF
        - Halfwidth Katakana: U+FF65 - U+FF9F

        Args:
            text: Text to analyze
            threshold: Minimum ratio of Japanese characters (default 0.3)

        Returns:
            True if text is primarily Japanese

        Performance: Uses early exit for short text and samples for long text.
        """
        if not text:
            return False

        text_len = len(text)

        # Early exit for very short text: check all chars directly
        if text_len < self.MIN_TEXT_LENGTH_FOR_SAMPLING:
            meaningful_chars = [
                c for c in text if not c.isspace() and not self.is_punctuation(c)
            ]
            if not meaningful_chars:
                return False
            jp_count = sum(1 for c in meaningful_chars if self.is_japanese_char(ord(c)))
            return (jp_count / len(meaningful_chars)) >= threshold

        # For longer text, sample the first portion
        sample_text = (
            text[: self.MAX_ANALYSIS_LENGTH]
            if text_len > self.MAX_ANALYSIS_LENGTH
            else text
        )

        japanese_count = 0
        total_chars = 0
        stage_idx = 0  # Current stage index for early exit checks

        for char in sample_text:
            # Skip whitespace and punctuation
            if char.isspace() or self.is_punctuation(char):
                continue

            total_chars += 1
            if self.is_japanese_char(ord(char)):
                japanese_count += 1

            # Staged early exit: check progressively as we accumulate samples
            # This allows faster detection for clear-cut cases
            while stage_idx < len(self.EARLY_EXIT_STAGES):
                min_chars, jp_thresh, non_jp_thresh = self.EARLY_EXIT_STAGES[stage_idx]
                if total_chars < min_chars:
                    break  # Not enough chars for this stage yet

                ratio = japanese_count / total_chars
                if ratio >= jp_thresh or ratio < non_jp_thresh:
                    # Clear result at this stage - exit early
                    return ratio >= threshold

                stage_idx += 1  # Move to next stage

        if total_chars == 0:
            return False

        return (japanese_count / total_chars) >= threshold

    def detect_local(self, text: str) -> str:
        """
        Detect language locally without Copilot.

        Detection priority:
        1. Hiragana/Katakana present → "日本語" (definite Japanese)
        2. Hangul present → "韓国語" (definite Korean)
        3. CJK with many non-JIS ideographs → "中国語" (conservative heuristic)
        4. Latin alphabet dominant → "英語" (assume English for speed)
        5. CJK only (no kana) → "日本語" (assume Japanese for target users)
        6. Other/mixed → "日本語" (default fallback)

        Note: This method always returns a language name (never None) to avoid
        slow Copilot calls for language detection. Target users are Japanese,
        so Japanese is used as the default fallback.

        Args:
            text: Text to analyze

        Returns:
            Detected language name (always returns a value)
        """
        if not text:
            return "日本語"  # Default for empty text

        # Sample text for analysis
        sample = text[: self.MAX_ANALYSIS_LENGTH]

        has_hiragana = False
        has_katakana = False
        has_hangul = False
        has_cjk = False
        cjk_count = 0
        unencodable_cjk_count = 0
        latin_count = 0
        total_meaningful = 0

        for char in sample:
            if char.isspace() or self.is_punctuation(char):
                continue

            code = ord(char)
            total_meaningful += 1

            if self.is_hiragana(code):
                has_hiragana = True
            elif self.is_katakana(code):
                has_katakana = True
            elif self.is_hangul(code):
                has_hangul = True
            elif self.is_cjk_ideograph(code):
                has_cjk = True
                cjk_count += 1
                if not self._is_encodable_in_shift_jisx0213(char):
                    unencodable_cjk_count += 1
            elif self.is_latin(code):
                latin_count += 1

            # Early exit: if we found hiragana/katakana, it's definitely Japanese
            if has_hiragana or has_katakana:
                return "日本語"

            # Early exit: if we found hangul, it's Korean
            if has_hangul:
                return "韓国語"

        if total_meaningful == 0:
            return "日本語"  # Default for no meaningful characters

        if (
            has_cjk
            and not (has_hiragana or has_katakana)
            and cjk_count > 0
            and unencodable_cjk_count >= self._MIN_UNENCODABLE_CJK_FOR_CHINESE
        ):
            return "中国語"

        # If mostly Latin characters, assume English
        latin_ratio = latin_count / total_meaningful
        if latin_ratio > 0.5:
            return "英語"

        # CJK present → assume Japanese (target users are Japanese)
        # This handles mixed text like "AAT製", "IBM社", "Google翻訳"
        if has_cjk:
            return "日本語"

        # Other cases → assume Japanese as default
        return "日本語"

    def detect_local_with_reason(self, text: str) -> tuple[str, str]:
        """Detect language locally and return a reason code for UI."""
        if not text:
            return "日本語", "empty"

        sample = text[: self.MAX_ANALYSIS_LENGTH]

        has_hiragana = False
        has_katakana = False
        has_hangul = False
        has_cjk = False
        cjk_count = 0
        unencodable_cjk_count = 0
        latin_count = 0
        total_meaningful = 0

        for char in sample:
            if char.isspace() or self.is_punctuation(char):
                continue

            code = ord(char)
            total_meaningful += 1

            if self.is_hiragana(code):
                has_hiragana = True
            elif self.is_katakana(code):
                has_katakana = True
            elif self.is_hangul(code):
                has_hangul = True
            elif self.is_cjk_ideograph(code):
                has_cjk = True
                cjk_count += 1
                if not self._is_encodable_in_shift_jisx0213(char):
                    unencodable_cjk_count += 1
            elif self.is_latin(code):
                latin_count += 1

            if has_hiragana or has_katakana:
                return "日本語", "kana"
            if has_hangul:
                return "韓国語", "hangul"

        if total_meaningful == 0:
            return "日本語", "empty"

        if (
            has_cjk
            and not (has_hiragana or has_katakana)
            and cjk_count > 0
            and unencodable_cjk_count >= self._MIN_UNENCODABLE_CJK_FOR_CHINESE
        ):
            return "中国語", "cjk_unencodable"

        latin_ratio = latin_count / total_meaningful
        if latin_ratio > 0.5:
            return "英語", "latin"

        if has_cjk:
            return "日本語", "cjk_fallback"

        return "日本語", "default"


# Singleton instance for convenient access
language_detector = LanguageDetector()


def is_expected_output_language(text: str, output_language: str) -> bool:
    """Return True if text appears to match the expected output language.

    This is a lightweight guard for downstream retry/fallback logic.

    - output_language="en": reject Japanese/Chinese/Korean scripts (kana/CJK/Hangul),
      plus Japanese-specific punctuation.
      Numeric-only strings are allowed.
    - output_language="jp": rely on LanguageDetector; reject when detected language
      is not Japanese (e.g., Chinese/English/Korean).
      Numeric-only strings are allowed (LanguageDetector defaults to Japanese).
    """
    normalized = (text or "").strip()
    if not normalized:
        return True

    lang = (output_language or "").strip().lower()
    if lang == "en":
        for char in normalized:
            if char in LanguageDetector._JAPANESE_PUNCTUATION:
                return False
            code = ord(char)
            if (
                LanguageDetector.is_hiragana(code)
                or LanguageDetector.is_katakana(code)
                or LanguageDetector.is_cjk_ideograph(code)
                or LanguageDetector.is_hangul(code)
            ):
                return False
        return True

    if lang == "jp":
        return language_detector.detect_local(normalized) == "日本語"

    return True


def _is_jp_output_language_mismatch(text: str) -> bool:
    detected, reason = language_detector.detect_local_with_reason(text)
    if detected in ("中国語", "韓国語"):
        return True
    if detected == "英語":
        # Allow short Latin-only tokens (e.g., OK/PDF/FY2025) in Japanese output.
        if any(token in text for token in ("\n", "\t", " ")):
            return True
        return len(text) >= 12
    if detected != "日本語":
        return False

    if reason == "cjk_fallback" and _looks_like_chinese_in_kana_less_cjk(text):
        return True
    return False


def _is_text_output_language_mismatch(text: str, output_language: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False

    lang = (output_language or "").strip().lower()
    if lang == "en":
        normalized = _normalize_en_translation_for_output_language_guard(normalized)
        return not is_expected_output_language(normalized, "en")
    if lang != "jp":
        return False

    return _is_jp_output_language_mismatch(normalized)


# =============================================================================
# Backward Compatibility Functions
# =============================================================================


def is_japanese_text(text: str, threshold: float = 0.3) -> bool:
    """Detect if text is primarily Japanese.

    This is a convenience function that delegates to the singleton LanguageDetector.
    For new code, prefer using `language_detector.is_japanese()` directly.
    """
    return language_detector.is_japanese(text, threshold)


def detect_language_local(text: str) -> Optional[str]:
    """Detect language locally without Copilot.

    This is a convenience function that delegates to the singleton LanguageDetector.
    For new code, prefer using `language_detector.detect_local()` directly.
    """
    return language_detector.detect_local(text)


from yakulingo.models.types import (
    BatchTranslationResult,
    TranslationStatus,
    TranslationProgress,
    TranslationPhase,
    TranslationResult,
    TextTranslationResult,
    TranslationOption,
    FileInfo,
    FileType,
    TextBlock,
    ProgressCallback,
)
from yakulingo.config.settings import AppSettings
from yakulingo.services.copilot_handler import CopilotHandler, TranslationCancelledError
from yakulingo.services.prompt_builder import (
    PromptBuilder,
    REFERENCE_INSTRUCTION,
    DEFAULT_TEXT_TO_JP_TEMPLATE,
)
from yakulingo.processors.base import FileProcessor

if TYPE_CHECKING:
    from yakulingo.processors.pdf_processor import PdfProcessor


def scale_progress(
    progress: TranslationProgress,
    start: int,
    end: int,
    phase: TranslationPhase,
    phase_detail: Optional[str] = None,
) -> TranslationProgress:
    """
    Scale batch progress percentage to a target range.

    Args:
        progress: Original progress (0-100)
        start: Start of target range (e.g., 10)
        end: End of target range (e.g., 90)
        phase: Current translation phase
        phase_detail: Optional phase detail string

    Returns:
        New TranslationProgress with scaled percentage
    """
    range_size = end - start
    scaled = start + int(progress.percentage * range_size)
    return TranslationProgress(
        current=scaled,
        total=100,
        status=progress.status,
        phase=phase,
        phase_detail=phase_detail,
        phase_current=progress.phase_current,
        phase_total=progress.phase_total,
    )


class TranslationCache:
    """
    Translation cache for PDF and file translation with true LRU eviction.

    Caches translated text by source text hash to avoid re-translating
    identical content (e.g., repeated headers, footers, or common phrases).

    Uses OrderedDict for O(1) LRU operations: recently accessed items are
    moved to the end, and oldest items are evicted from the front.

    Thread-safe for concurrent access.

    Memory management:
        - Default max_size reduced to 1000 entries to prevent memory bloat
        - Estimated memory per entry: ~200 bytes (average text) + ~200 bytes (translation)
        - At max_size=1000: ~400KB memory usage
        - For large documents, use clear() between translations to free memory
    """

    # Default max size reduced from 10000 to 1000 to prevent memory issues
    DEFAULT_MAX_SIZE = 1000
    # Estimated average bytes per cache entry (source + translation)
    ESTIMATED_BYTES_PER_ENTRY = 400

    def __init__(self, max_size: int | None = None):
        """
        Initialize translation cache.

        Args:
            max_size: Maximum number of cached entries.
                      If None, uses DEFAULT_MAX_SIZE (1000).
                      Set to 0 to disable caching.
        """
        from collections import OrderedDict
        import threading

        self._cache: OrderedDict[str, str] = OrderedDict()
        self._max_size = max_size if max_size is not None else self.DEFAULT_MAX_SIZE
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()
        self._total_bytes = 0  # Track approximate memory usage

    def get(self, text: str) -> Optional[str]:
        """
        Get cached translation for text.

        LRU: Moves accessed item to end (most recently used).

        Args:
            text: Source text

        Returns:
            Cached translation or None if not found
        """
        with self._lock:
            if text in self._cache:
                self._hits += 1
                # Move to end (most recently used)
                self._cache.move_to_end(text)
                return self._cache[text]
            else:
                self._misses += 1
                return None

    def set(self, text: str, translation: str) -> None:
        """
        Cache a translation.

        LRU: If key exists, moves to end. If cache is full, evicts oldest entry.

        Args:
            text: Source text
            translation: Translated text
        """
        # Skip caching if disabled (max_size=0)
        if self._max_size <= 0:
            return

        entry_bytes = len(text.encode("utf-8")) + len(translation.encode("utf-8"))

        with self._lock:
            if text in self._cache:
                # Update existing entry and move to end
                old_translation = self._cache[text]
                old_bytes = len(text.encode("utf-8")) + len(
                    old_translation.encode("utf-8")
                )
                self._total_bytes -= old_bytes
                self._cache.move_to_end(text)
            elif len(self._cache) >= self._max_size:
                # Evict oldest (least recently used) entry
                oldest_key, oldest_val = self._cache.popitem(last=False)
                evicted_bytes = len(oldest_key.encode("utf-8")) + len(
                    oldest_val.encode("utf-8")
                )
                self._total_bytes -= evicted_bytes
                logger.debug(
                    "LRU eviction: removed oldest entry (freed %d bytes)", evicted_bytes
                )

            self._cache[text] = translation
            self._total_bytes += entry_bytes

    def clear(self) -> None:
        """Clear all cached translations and reset statistics."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._total_bytes = 0
            logger.debug("Translation cache cleared")

    @property
    def stats(self) -> dict:
        """Get cache statistics including memory usage."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            memory_kb = self._total_bytes / 1024
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.1f}%",
                "memory_kb": f"{memory_kb:.1f}",
            }


class BatchTranslator:
    """
    Handles batch translation of text blocks.
    """

    # Default values (used when settings not provided)
    DEFAULT_MAX_CHARS_PER_BATCH = 1000  # Characters per batch (Copilot input safety)
    DEFAULT_REQUEST_TIMEOUT = 600  # Default timeout for Copilot response (10 minutes)
    _SPLIT_REQUEST_MARKERS = (
        "入力テキスト量が非常に多いため",
        "メッセージ上限",
        "複数回に分割",
        "分割して送信",
        "ご希望は",
        "どちらですか",
    )
    _SPLIT_REQUEST_MIN_MATCHES = 2
    _SPLIT_RETRY_LIMIT = 2
    _MIN_SPLIT_BATCH_CHARS = 300
    _UNTRANSLATED_RETRY_MAX_CHARS = 800
    _EN_NO_HANGUL_INSTRUCTION = """### Language constraint (critical)
- Output must be English only.
- Do NOT output Korean (Hangul) characters.
- If the input contains non-English fragments (e.g., Japanese/Korean), translate only those fragments into English.
"""
    _EN_STRICT_OUTPUT_LANGUAGE_INSTRUCTION = """### Language constraint (critical)
- Output must be English only.
- Do NOT output Japanese/Chinese scripts (hiragana/katakana/kanji/hanzi) or Japanese punctuation (、・「」『』).
- Do NOT output Korean (Hangul) characters.
- If the source contains Japanese-only tokens (e.g., names, company types, place names), translate or romanize them; do not leave them in Japanese script.
"""
    _JP_STRICT_OUTPUT_LANGUAGE_INSTRUCTION = """### Language constraint (critical)
- Output must be Japanese only.
- Write natural Japanese with kana/okurigana; avoid Chinese-style wording.
- Do NOT output Chinese (Simplified/Traditional) text.
- Do NOT output English sentences.
"""

    def __init__(
        self,
        copilot: CopilotHandler,
        prompt_builder: PromptBuilder,
        max_chars_per_batch: Optional[int] = None,
        request_timeout: Optional[int] = None,
        enable_cache: bool = True,
        copilot_lock: Optional[threading.Lock] = None,
    ):
        self.copilot = copilot
        self.prompt_builder = prompt_builder
        self._copilot_lock = copilot_lock
        # Thread-safe cancellation using Event instead of bool flag
        self._cancel_event = threading.Event()

        # Use provided values or defaults
        self.max_chars_per_batch = (
            max_chars_per_batch or self.DEFAULT_MAX_CHARS_PER_BATCH
        )
        self.request_timeout = request_timeout or self.DEFAULT_REQUEST_TIMEOUT

        # Translation cache for avoiding re-translation of identical text
        self._cache = TranslationCache() if enable_cache else None

    @contextmanager
    def _ui_window_sync_scope(self, reason: str):
        """翻訳中だけEdgeをUIの背面に表示する（Windowsのみ・利用可能な場合）。"""
        copilot = getattr(self, "copilot", None)
        scope_factory = (
            getattr(copilot, "ui_window_sync_scope", None)
            if copilot is not None
            else None
        )
        if scope_factory is None:
            yield
            return

        try:
            scope = scope_factory(reason=reason)
        except Exception:
            yield
            return

        with scope:
            yield

    def cancel(self) -> None:
        """Request cancellation of batch translation (thread-safe)."""
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        """Reset cancellation flag (thread-safe)."""
        self._cancel_event.clear()

    def clear_cache(self) -> None:
        """Clear translation cache."""
        if self._cache:
            self._cache.clear()

    def get_cache_stats(self) -> Optional[dict]:
        """Get cache statistics."""
        if self._cache:
            return self._cache.stats
        return None

    def _clean_batch_translation(self, text: str) -> str:
        cleaned = _strip_input_markers(text)
        cleaned = _strip_trailing_attachment_links(cleaned)
        if cleaned:
            cleaned = _RE_ITEM_ID_MARKER.sub("", cleaned)
            cleaned = _RE_TRAILING_FILENAME.sub("", cleaned).strip()
        return cleaned

    @staticmethod
    def _build_cache_key(
        text: str, *, output_language: str, translation_style: str
    ) -> str:
        style_key = translation_style if output_language == "en" else ""
        return f"{output_language}\0{style_key}\0{text}"

    def _should_retry_translation(
        self, original: str, translated: str, output_language: str
    ) -> bool:
        if output_language != "en":
            return False
        if not original or not translated:
            return False
        original = original.strip()
        translated = translated.strip()
        if not original or not translated:
            return False
        if _RE_HANGUL.search(translated):
            return True
        if not language_detector.is_japanese(original):
            return False
        if original == translated:
            return True
        return language_detector.is_japanese(translated, threshold=0.6)

    def _is_output_language_mismatch(self, text: str, output_language: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return False
        if output_language == "en":
            return not is_expected_output_language(normalized, "en")
        if output_language != "jp":
            return False
        return _is_jp_output_language_mismatch(normalized)

    def _is_local_backend(self) -> bool:
        try:
            from yakulingo.services.local_ai_client import LocalAIClient
        except Exception:
            return False
        return isinstance(self.copilot, LocalAIClient)

    def translate_blocks(
        self,
        blocks: list[TextBlock],
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
    ) -> dict[str, str]:
        """
        Translate blocks in batches.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")
            include_item_ids: Include stable [[ID:n]] markers in batch prompts

        Returns:
            Mapping of block_id -> translated_text

        Raises:
            TranslationCancelledError: If translation was cancelled by user.
                Partial results are discarded to prevent incomplete translations.

        Note:
            For detailed results including error information, use
            translate_blocks_with_result() instead.
        """
        result = self.translate_blocks_with_result(
            blocks,
            reference_files,
            on_progress,
            output_language,
            translation_style,
            include_item_ids=include_item_ids,
        )
        # Raise exception if cancelled to prevent partial results from being applied
        if result.cancelled:
            raise TranslationCancelledError(
                "Translation cancelled by user. Partial results have been discarded."
            )
        return result.translations

    def translate_blocks_with_result(
        self,
        blocks: list[TextBlock],
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        _max_chars_per_batch: Optional[int] = None,
        _max_chars_per_batch_source: Optional[str] = None,
        _split_retry_depth: int = 0,
    ) -> BatchTranslationResult:
        """
        Translate blocks in batches with detailed result information.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")
            include_item_ids: Include stable [[ID:n]] markers in batch prompts

        Returns:
            BatchTranslationResult with translations and error details.
            Check result.cancelled to determine if translation was cancelled.

        Warning:
            If result.cancelled is True, the translations dict contains partial
            results from completed batches only. Callers should check this flag
            and handle accordingly (e.g., discard partial results or re-translate).

        Performance optimizations:
            - Translation cache: avoids re-translating identical text
            - Pre-builds all prompts before translation loop to minimize per-batch overhead
            - Uses concurrent.futures for parallel prompt construction when >2 batches
        """
        from concurrent.futures import ThreadPoolExecutor
        from yakulingo.models.types import BatchTranslationResult

        translations = {}
        untranslated_block_ids = []
        mismatched_batch_count = 0
        is_local_backend = self._is_local_backend()
        timing_enabled = (
            _LOCAL_AI_TIMING_ENABLED
            and logger.isEnabledFor(logging.DEBUG)
            and is_local_backend
        )
        retry_prompt_too_long = 0
        retry_local_error = 0
        retry_copilot_split = 0
        fallback_original_batches = 0

        if _split_retry_depth == 0:
            self._cancel_event.clear()  # Reset at start of new translation
        cancelled = False

        batch_char_limit = _max_chars_per_batch or self.max_chars_per_batch
        batch_limit_source = _max_chars_per_batch_source
        if not batch_limit_source:
            batch_limit_source = (
                "BatchTranslator.max_chars_per_batch"
                if _max_chars_per_batch is None
                else "override"
            )

        # Phase 0: Skip formula blocks and non-translatable blocks (preserve original text)
        formula_skipped = 0
        skip_translation_count = 0
        translatable_blocks = []

        for block in blocks:
            # Check if block is marked as formula (PDF processor)
            if block.metadata and block.metadata.get("is_formula"):
                translations[block.id] = block.text  # Keep original
                formula_skipped += 1
            # Check if block is marked for skip_translation (PDF processor: numbers, dates, etc.)
            elif block.metadata and block.metadata.get("skip_translation"):
                # Don't add to translations - apply_translations will handle preservation
                skip_translation_count += 1
            else:
                translatable_blocks.append(block)

        if formula_skipped > 0:
            logger.debug(
                "Skipped %d formula blocks (preserved original text)", formula_skipped
            )
        if skip_translation_count > 0:
            logger.debug(
                "Skipped %d non-translatable blocks (will preserve original in apply_translations)",
                skip_translation_count,
            )

        # Phase 1: Check cache for already-translated blocks
        uncached_blocks = []
        cache_hits = 0

        for block in translatable_blocks:
            if self._cache:
                cache_key = self._build_cache_key(
                    block.text,
                    output_language=output_language,
                    translation_style=translation_style,
                )
                cached = self._cache.get(cache_key)
                if cached is not None:
                    translations[block.id] = cached
                    cache_hits += 1
                    continue
            uncached_blocks.append(block)

        if cache_hits > 0:
            logger.debug(
                "Cache hits: %d/%d blocks (%.1f%%)",
                cache_hits,
                len(translatable_blocks),
                cache_hits / len(translatable_blocks) * 100
                if translatable_blocks
                else 0,
            )

        # If all blocks were cached, return early
        if not uncached_blocks:
            logger.info("All %d blocks served from cache", len(blocks))
            return BatchTranslationResult(
                translations=translations,
                untranslated_block_ids=[],
                mismatched_batch_count=0,
                total_blocks=len(blocks),
                translated_count=len(translations),
                cancelled=False,
            )

        # Phase 2: Batch translate uncached blocks
        batches = self._create_batches(uncached_blocks, batch_char_limit)
        if is_local_backend:
            logger.debug(
                "Local AI batching: max_chars_per_batch=%d (source=%s), batches=%d",
                batch_char_limit,
                batch_limit_source,
                len(batches),
            )
        # has_refs is used for reference file attachment indicator
        has_refs = bool(reference_files)
        files_to_attach = reference_files if has_refs else None

        # Pre-build unique text data for each batch to avoid re-translating duplicates
        # within the same batch (e.g., repeated headers, footers, common phrases)
        batch_unique_data: list[tuple[list[str], list[int]]] = []
        total_original = 0
        total_unique = 0

        for batch in batches:
            texts = [b.text for b in batch]
            unique_texts: list[str] = []
            text_to_unique_idx: dict[str, int] = {}
            original_to_unique_idx: list[int] = []

            for text in texts:
                if text not in text_to_unique_idx:
                    text_to_unique_idx[text] = len(unique_texts)
                    unique_texts.append(text)
                original_to_unique_idx.append(text_to_unique_idx[text])

            batch_unique_data.append((unique_texts, original_to_unique_idx))
            total_original += len(texts)
            total_unique += len(unique_texts)

        # Log deduplication stats if there were duplicates
        if total_unique < total_original:
            logger.info(
                "Batch deduplication: %d unique texts from %d original (%.1f%% reduction)",
                total_unique,
                total_original,
                (1 - total_unique / total_original) * 100,
            )

        # Pre-build all prompts before translation loop for efficiency
        # This eliminates prompt construction time from the translation loop
        def build_prompt(unique_texts: list[str]) -> str:
            return self.prompt_builder.build_batch(
                unique_texts,
                has_reference_files=has_refs,
                output_language=output_language,
                translation_style=translation_style,
                include_item_ids=include_item_ids,
                reference_files=reference_files,
            )

        # Use parallel prompt construction for multiple batches
        t_prompt_build = time.perf_counter() if timing_enabled else 0.0
        unique_texts_list = [d[0] for d in batch_unique_data]
        if len(batches) > 2:
            with ThreadPoolExecutor(max_workers=min(4, len(batches))) as executor:
                prompts = list(executor.map(build_prompt, unique_texts_list))
        else:
            prompts = [build_prompt(texts) for texts in unique_texts_list]

        if timing_enabled:
            logger.debug(
                "[TIMING] BatchTranslator.prompt_build: %.3fs (batches=%d max_chars_per_batch=%d source=%s)",
                time.perf_counter() - t_prompt_build,
                len(batches),
                batch_char_limit,
                batch_limit_source,
            )
        logger.debug("Pre-built %d prompts for batch translation", len(prompts))

        for i, batch in enumerate(batches):
            # Check for cancellation between batches (thread-safe)
            if self._cancel_event.is_set():
                logger.info(
                    "Batch translation cancelled at batch %d/%d", i + 1, len(batches)
                )
                cancelled = True
                break

            if on_progress:
                on_progress(
                    TranslationProgress(
                        current=i,
                        total=len(batches),
                        status=f"Batch {i + 1} of {len(batches)}",
                        phase_current=i + 1,
                        phase_total=len(batches),
                    )
                )

            unique_texts, original_to_unique_idx = batch_unique_data[i]
            prompt = prompts[i]  # Use pre-built prompt

            # Translate unique texts only
            # Skip clear wait for 2nd+ batches (we just finished getting a response)
            skip_clear_wait = i > 0
            try:
                lock = self._copilot_lock or nullcontext()
                with lock:
                    self.copilot.set_cancel_callback(
                        lambda: self._cancel_event.is_set()
                    )
                    try:
                        with self._ui_window_sync_scope("translate_blocks_with_result"):
                            unique_translations = self.copilot.translate_sync(
                                unique_texts,
                                prompt,
                                files_to_attach,
                                skip_clear_wait,
                                timeout=self.request_timeout,
                                include_item_ids=include_item_ids,
                            )
                    finally:
                        self.copilot.set_cancel_callback(None)
            except TranslationCancelledError:
                logger.info(
                    "Translation cancelled during batch %d/%d", i + 1, len(batches)
                )
                cancelled = True
                break
            except RuntimeError as e:
                message = str(e)
                if (
                    "LOCAL_PROMPT_TOO_LONG" in message
                    and _split_retry_depth < self._SPLIT_RETRY_LIMIT
                    and batch_char_limit > self._MIN_SPLIT_BATCH_CHARS
                ):
                    reduced_limit = max(
                        self._MIN_SPLIT_BATCH_CHARS, batch_char_limit // 2
                    )
                    retry_prompt_too_long += 1
                    logger.warning(
                        "Local AI prompt too long for batch %d; retrying with max_chars_per_batch=%d (was %d, source=%s) (%s)",
                        i + 1,
                        reduced_limit,
                        batch_char_limit,
                        batch_limit_source,
                        message[:120],
                    )
                    retry_result = self.translate_blocks_with_result(
                        batch,
                        reference_files=reference_files,
                        on_progress=None,
                        output_language=output_language,
                        translation_style=translation_style,
                        include_item_ids=include_item_ids,
                        _max_chars_per_batch=reduced_limit,
                        _max_chars_per_batch_source=batch_limit_source,
                        _split_retry_depth=_split_retry_depth + 1,
                    )
                    translations.update(retry_result.translations)
                    untranslated_block_ids.extend(retry_result.untranslated_block_ids)
                    mismatched_batch_count += retry_result.mismatched_batch_count
                    if retry_result.cancelled:
                        cancelled = True
                        break
                    continue
                if is_local_backend:
                    if (
                        _split_retry_depth < self._SPLIT_RETRY_LIMIT
                        and batch_char_limit > self._MIN_SPLIT_BATCH_CHARS
                    ):
                        reduced_limit = max(
                            self._MIN_SPLIT_BATCH_CHARS, batch_char_limit // 2
                        )
                        retry_local_error += 1
                        logger.warning(
                            "Local AI error in batch %d; retrying with max_chars_per_batch=%d (was %d, source=%s) (%s)",
                            i + 1,
                            reduced_limit,
                            batch_char_limit,
                            batch_limit_source,
                            message[:120],
                        )
                        retry_result = self.translate_blocks_with_result(
                            batch,
                            reference_files=reference_files,
                            on_progress=None,
                            output_language=output_language,
                            translation_style=translation_style,
                            include_item_ids=include_item_ids,
                            _max_chars_per_batch=reduced_limit,
                            _max_chars_per_batch_source=batch_limit_source,
                            _split_retry_depth=_split_retry_depth + 1,
                        )
                        translations.update(retry_result.translations)
                        untranslated_block_ids.extend(
                            retry_result.untranslated_block_ids
                        )
                        mismatched_batch_count += retry_result.mismatched_batch_count
                        if retry_result.cancelled:
                            cancelled = True
                            break
                        continue
                    logger.warning(
                        "Local AI error in batch %d; using original text (max_chars_per_batch=%d, source=%s) (%s)",
                        i + 1,
                        batch_char_limit,
                        batch_limit_source,
                        message[:120],
                    )
                    fallback_original_batches += 1
                    for block in batch:
                        translations[block.id] = block.text
                        untranslated_block_ids.append(block.id)
                    continue
                raise

            if self._looks_like_split_request(unique_translations):
                if (
                    _split_retry_depth < self._SPLIT_RETRY_LIMIT
                    and batch_char_limit > self._MIN_SPLIT_BATCH_CHARS
                ):
                    reduced_limit = max(
                        self._MIN_SPLIT_BATCH_CHARS, batch_char_limit // 2
                    )
                    retry_copilot_split += 1
                    logger.warning(
                        "Copilot requested split for batch %d; retrying with max_chars_per_batch=%d (was %d)",
                        i + 1,
                        reduced_limit,
                        batch_char_limit,
                    )
                    retry_result = self.translate_blocks_with_result(
                        batch,
                        reference_files=reference_files,
                        on_progress=None,
                        output_language=output_language,
                        translation_style=translation_style,
                        include_item_ids=include_item_ids,
                        _max_chars_per_batch=reduced_limit,
                        _max_chars_per_batch_source=batch_limit_source,
                        _split_retry_depth=_split_retry_depth + 1,
                    )
                    translations.update(retry_result.translations)
                    untranslated_block_ids.extend(retry_result.untranslated_block_ids)
                    mismatched_batch_count += retry_result.mismatched_batch_count
                    if retry_result.cancelled:
                        cancelled = True
                        break
                    continue

                logger.warning(
                    "Copilot split request persisted; using original text for batch %d",
                    i + 1,
                )
                unique_translations = [""] * len(unique_texts)

            # Validate translation count matches unique text count
            if len(unique_translations) != len(unique_texts):
                mismatched_batch_count += 1
                diff = len(unique_texts) - len(unique_translations)
                missing_count = max(0, diff)
                extra_count = max(0, -diff)
                logger.warning(
                    "Translation count mismatch in batch %d: expected %d unique, got %d (missing %d, extra %d). "
                    "Affected texts will use original content as fallback.",
                    i + 1,
                    len(unique_texts),
                    len(unique_translations),
                    missing_count,
                    extra_count,
                )

                if missing_count:
                    # Log which unique texts are missing translations (first 3 for brevity)
                    missing_indices = list(
                        range(len(unique_translations), len(unique_texts))
                    )
                    for miss_idx in missing_indices[:3]:
                        original_text = (
                            unique_texts[miss_idx][:50] + "..."
                            if len(unique_texts[miss_idx]) > 50
                            else unique_texts[miss_idx]
                        )
                        logger.warning(
                            "  Missing translation for unique_idx %d: '%s'",
                            miss_idx,
                            original_text,
                        )
                    if len(missing_indices) > 3:
                        logger.warning(
                            "  ... and %d more missing translations",
                            len(missing_indices) - 3,
                        )

                    # Pad missing translations to maintain index mapping.
                    unique_translations = unique_translations + ([""] * missing_count)

                if extra_count:
                    # Extra items make index mapping unreliable (often caused by nested numbering).
                    # On retries, prefer safety and fall back to original content.
                    if _split_retry_depth > 0:
                        unique_translations = [""] * len(unique_texts)
                    else:
                        unique_translations = unique_translations[: len(unique_texts)]

            cleaned_unique_translations = []
            hangul_indices: list[int] = []
            output_language_mismatch_indices: list[int] = []
            for idx, translated_text in enumerate(unique_translations):
                cleaned_text = self._clean_batch_translation(translated_text)
                if not cleaned_text or not cleaned_text.strip():
                    cleaned_unique_translations.append("")
                    continue
                if output_language == "en" and _RE_HANGUL.search(cleaned_text):
                    hangul_indices.append(idx)
                    cleaned_unique_translations.append(cleaned_text)
                    continue
                if self._is_output_language_mismatch(cleaned_text, output_language):
                    output_language_mismatch_indices.append(idx)
                    cleaned_unique_translations.append(cleaned_text)
                    continue
                if self._should_retry_translation(
                    unique_texts[idx], cleaned_text, output_language
                ):
                    preview = unique_texts[idx][:50].replace("\n", " ")
                    logger.debug("Scheduling retry for JP->EN text: '%s'", preview)
                    cleaned_unique_translations.append("")
                    continue
                cleaned_unique_translations.append(cleaned_text)

            if (
                hangul_indices
                and output_language == "en"
                and not self._cancel_event.is_set()
            ):
                repair_texts = [unique_texts[idx] for idx in hangul_indices]
                repair_prompt = self.prompt_builder.build_batch(
                    repair_texts,
                    has_reference_files=has_refs,
                    output_language=output_language,
                    translation_style=translation_style,
                    include_item_ids=include_item_ids,
                    reference_files=reference_files,
                )
                repair_prompt = _insert_extra_instruction(
                    repair_prompt,
                    self._EN_NO_HANGUL_INSTRUCTION,
                )
                logger.warning(
                    "Batch %d: Hangul detected in %d English translations; retrying with stricter prompt",
                    i + 1,
                    len(hangul_indices),
                )
                try:
                    lock = self._copilot_lock or nullcontext()
                    with lock:
                        self.copilot.set_cancel_callback(
                            lambda: self._cancel_event.is_set()
                        )
                        try:
                            with self._ui_window_sync_scope(
                                "translate_blocks_with_result_hangul_retry"
                            ):
                                repair_translations = self.copilot.translate_sync(
                                    repair_texts,
                                    repair_prompt,
                                    files_to_attach,
                                    True,
                                    timeout=self.request_timeout,
                                    include_item_ids=include_item_ids,
                                )
                        finally:
                            self.copilot.set_cancel_callback(None)
                except TranslationCancelledError:
                    logger.info(
                        "Translation cancelled during batch %d/%d", i + 1, len(batches)
                    )
                    cancelled = True
                    break

                if len(repair_translations) != len(repair_texts):
                    logger.warning(
                        "Batch %d: Hangul retry count mismatch: expected %d, got %d; using fallbacks where needed",
                        i + 1,
                        len(repair_texts),
                        len(repair_translations),
                    )
                    if len(repair_translations) < len(repair_texts):
                        repair_translations = repair_translations + (
                            [""] * (len(repair_texts) - len(repair_translations))
                        )
                    else:
                        repair_translations = repair_translations[: len(repair_texts)]

                for repair_pos, repaired_text in enumerate(repair_translations):
                    original_idx = hangul_indices[repair_pos]
                    cleaned_repair = self._clean_batch_translation(repaired_text)
                    if (
                        not cleaned_repair
                        or not cleaned_repair.strip()
                        or _RE_HANGUL.search(cleaned_repair)
                    ):
                        preview = unique_texts[original_idx][:50].replace("\n", " ")
                        logger.warning(
                            "Batch %d: Hangul retry failed for text '%s'; using fallback/retry flow",
                            i + 1,
                            preview,
                        )
                        cleaned_unique_translations[original_idx] = ""
                    else:
                        cleaned_unique_translations[original_idx] = cleaned_repair

            if (
                output_language_mismatch_indices
                and output_language in ("en", "jp")
                and not self._cancel_event.is_set()
            ):
                # Extend with mismatches introduced by the Hangul repair path (if any).
                existing = set(output_language_mismatch_indices)
                for idx, translated_text in enumerate(cleaned_unique_translations):
                    if idx in existing:
                        continue
                    if not translated_text or not translated_text.strip():
                        continue
                    if self._is_output_language_mismatch(
                        translated_text, output_language
                    ):
                        existing.add(idx)
                        output_language_mismatch_indices.append(idx)

                if output_language_mismatch_indices:
                    repair_texts = [
                        unique_texts[idx] for idx in output_language_mismatch_indices
                    ]
                    repair_prompt = self.prompt_builder.build_batch(
                        repair_texts,
                        has_reference_files=has_refs,
                        output_language=output_language,
                        translation_style=translation_style,
                        include_item_ids=include_item_ids,
                        reference_files=reference_files,
                    )
                    extra_instruction = (
                        self._EN_STRICT_OUTPUT_LANGUAGE_INSTRUCTION
                        if output_language == "en"
                        else self._JP_STRICT_OUTPUT_LANGUAGE_INSTRUCTION
                    )
                    repair_prompt = _insert_extra_instruction(
                        repair_prompt,
                        extra_instruction,
                    )
                    logger.warning(
                        "Batch %d: Output language mismatch detected in %d translations (target=%s); retrying with stricter prompt",
                        i + 1,
                        len(output_language_mismatch_indices),
                        output_language,
                    )
                    try:
                        lock = self._copilot_lock or nullcontext()
                        with lock:
                            self.copilot.set_cancel_callback(
                                lambda: self._cancel_event.is_set()
                            )
                            try:
                                with self._ui_window_sync_scope(
                                    "translate_blocks_with_result_output_language_retry"
                                ):
                                    repair_translations = self.copilot.translate_sync(
                                        repair_texts,
                                        repair_prompt,
                                        files_to_attach,
                                        True,
                                        timeout=self.request_timeout,
                                        include_item_ids=include_item_ids,
                                    )
                            finally:
                                self.copilot.set_cancel_callback(None)
                    except TranslationCancelledError:
                        logger.info(
                            "Translation cancelled during batch %d/%d",
                            i + 1,
                            len(batches),
                        )
                        cancelled = True
                        break

                    if len(repair_translations) != len(repair_texts):
                        logger.warning(
                            "Batch %d: Output language retry count mismatch: expected %d, got %d; using fallbacks where needed",
                            i + 1,
                            len(repair_texts),
                            len(repair_translations),
                        )
                        if len(repair_translations) < len(repair_texts):
                            repair_translations = repair_translations + (
                                [""] * (len(repair_texts) - len(repair_translations))
                            )
                        else:
                            repair_translations = repair_translations[
                                : len(repair_texts)
                            ]

                    for repair_pos, repaired_text in enumerate(repair_translations):
                        original_idx = output_language_mismatch_indices[repair_pos]
                        cleaned_repair = self._clean_batch_translation(repaired_text)
                        if self._is_output_language_mismatch(
                            cleaned_repair, output_language
                        ):
                            preview = unique_texts[original_idx][:50].replace("\n", " ")
                            logger.warning(
                                "Batch %d: Output language retry failed for text '%s'; using fallback/retry flow",
                                i + 1,
                                preview,
                            )
                            cleaned_unique_translations[original_idx] = ""
                        elif not cleaned_repair or not cleaned_repair.strip():
                            cleaned_unique_translations[original_idx] = ""
                        else:
                            cleaned_unique_translations[original_idx] = cleaned_repair

                # Safety: never accept mismatched outputs.
                for idx in output_language_mismatch_indices:
                    translated_text = (
                        cleaned_unique_translations[idx]
                        if idx < len(cleaned_unique_translations)
                        else ""
                    )
                    if (
                        translated_text
                        and translated_text.strip()
                        and self._is_output_language_mismatch(
                            translated_text, output_language
                        )
                    ):
                        cleaned_unique_translations[idx] = ""

            if (
                is_local_backend
                and output_language == "en"
                and not self._cancel_event.is_set()
            ):
                numeric_rule_violation_indices = [
                    idx
                    for idx, translated_text in enumerate(cleaned_unique_translations)
                    if translated_text
                    and translated_text.strip()
                    and _needs_to_en_numeric_rule_retry(
                        unique_texts[idx], translated_text
                    )
                ]
                if numeric_rule_violation_indices:
                    retry_instruction = (
                        "- CRITICAL: Follow numeric conversion rules strictly. "
                        "Do not use 'billion', 'trillion', or 'bn'. Use 'oku' (and 'k') "
                        "exactly as specified. If numeric hints are provided, use them verbatim."
                    )
                    max_retry_items = 20
                    max_retry_chars = min(batch_char_limit, 2000)
                    retry_indices: list[int] = []
                    retry_texts: list[str] = []
                    total_chars = 0
                    for idx in numeric_rule_violation_indices:
                        if len(retry_texts) >= max_retry_items:
                            break
                        text_to_retry = unique_texts[idx]
                        if not text_to_retry:
                            continue
                        if (
                            retry_texts
                            and total_chars + len(text_to_retry) > max_retry_chars
                        ):
                            break
                        retry_indices.append(idx)
                        retry_texts.append(text_to_retry)
                        total_chars += len(text_to_retry)

                    if retry_texts:
                        repair_prompt = self.prompt_builder.build_batch(
                            retry_texts,
                            has_reference_files=has_refs,
                            output_language=output_language,
                            translation_style=translation_style,
                            include_item_ids=include_item_ids,
                            reference_files=reference_files,
                        )
                        repair_prompt = _insert_extra_instruction(
                            repair_prompt,
                            retry_instruction,
                        )
                        logger.warning(
                            "Batch %d: Numeric rule violation detected in %d translations; retrying %d items",
                            i + 1,
                            len(numeric_rule_violation_indices),
                            len(retry_texts),
                        )
                        repair_translations: list[str] = []
                        try:
                            lock = self._copilot_lock or nullcontext()
                            with lock:
                                self.copilot.set_cancel_callback(
                                    lambda: self._cancel_event.is_set()
                                )
                                try:
                                    with self._ui_window_sync_scope(
                                        "translate_blocks_with_result_numeric_rule_retry"
                                    ):
                                        repair_translations = (
                                            self.copilot.translate_sync(
                                                retry_texts,
                                                repair_prompt,
                                                files_to_attach,
                                                True,
                                                timeout=self.request_timeout,
                                                include_item_ids=include_item_ids,
                                            )
                                        )
                                finally:
                                    self.copilot.set_cancel_callback(None)
                        except TranslationCancelledError:
                            logger.info(
                                "Translation cancelled during batch %d/%d",
                                i + 1,
                                len(batches),
                            )
                            cancelled = True
                            break
                        except RuntimeError as e:
                            logger.warning(
                                "Batch %d: Numeric rule retry failed: %s", i + 1, e
                            )

                        if repair_translations:
                            if len(repair_translations) != len(retry_texts):
                                logger.warning(
                                    "Batch %d: Numeric rule retry count mismatch: expected %d, got %d; keeping original translations where needed",
                                    i + 1,
                                    len(retry_texts),
                                    len(repair_translations),
                                )
                                if len(repair_translations) < len(retry_texts):
                                    repair_translations = repair_translations + (
                                        [""]
                                        * (len(retry_texts) - len(repair_translations))
                                    )
                                else:
                                    repair_translations = repair_translations[
                                        : len(retry_texts)
                                    ]

                            updated_count = 0
                            for repair_pos, repaired_text in enumerate(
                                repair_translations
                            ):
                                original_idx = retry_indices[repair_pos]
                                cleaned_repair = self._clean_batch_translation(
                                    repaired_text
                                )
                                if not cleaned_repair or not cleaned_repair.strip():
                                    continue
                                if _RE_HANGUL.search(cleaned_repair):
                                    continue
                                if self._is_output_language_mismatch(
                                    cleaned_repair, output_language
                                ):
                                    continue
                                if _looks_incomplete_translation_to_en(
                                    unique_texts[original_idx], cleaned_repair
                                ):
                                    continue
                                if _needs_to_en_numeric_rule_retry(
                                    unique_texts[original_idx], cleaned_repair
                                ):
                                    continue
                                cleaned_unique_translations[original_idx] = (
                                    cleaned_repair
                                )
                                updated_count += 1
                            if updated_count:
                                logger.debug(
                                    "Batch %d: Numeric rule retry updated %d/%d items",
                                    i + 1,
                                    updated_count,
                                    len(retry_texts),
                                )

            # Detect empty translations (Copilot may return empty strings for some items)
            empty_translation_indices = [
                idx
                for idx, trans in enumerate(cleaned_unique_translations)
                if not trans or not trans.strip()
            ]
            if empty_translation_indices:
                logger.warning(
                    "Batch %d: %d empty translations detected at indices %s",
                    i + 1,
                    len(empty_translation_indices),
                    empty_translation_indices[:5]
                    if len(empty_translation_indices) > 5
                    else empty_translation_indices,
                )

            # Process results, expanding unique translations to all original blocks
            for idx, block in enumerate(batch):
                unique_idx = original_to_unique_idx[idx]
                if unique_idx < len(cleaned_unique_translations):
                    translated_text = cleaned_unique_translations[unique_idx]
                    is_fallback = False

                    # Check for empty translation and log warning
                    if not translated_text or not translated_text.strip():
                        logger.warning(
                            "Block '%s' received empty translation, using original text as fallback",
                            block.id,
                        )
                        translated_text = block.text
                        untranslated_block_ids.append(block.id)
                        is_fallback = True

                    translations[block.id] = translated_text

                    # Cache the translation for future use (only if not a fallback)
                    if (
                        self._cache
                        and not is_fallback
                        and translated_text
                        and translated_text.strip()
                    ):
                        cache_key = self._build_cache_key(
                            block.text,
                            output_language=output_language,
                            translation_style=translation_style,
                        )
                        self._cache.set(cache_key, translated_text)
                else:
                    # Mark untranslated blocks with original text
                    untranslated_block_ids.append(block.id)
                    logger.warning(
                        "Block '%s' was not translated (unique_idx %d >= translation count %d)",
                        block.id,
                        unique_idx,
                        len(cleaned_unique_translations),
                    )
                    translations[block.id] = block.text

        # Retry missing translations once with smaller batches.
        # Skip when we already observed count mismatches: the response mapping is unreliable,
        # and retrying risks overwriting the "use original text" fallbacks.
        if (
            untranslated_block_ids
            and not cancelled
            and _split_retry_depth == 0
            and mismatched_batch_count == 0
        ):
            retry_ids = set(untranslated_block_ids)
            retry_blocks = [block for block in blocks if block.id in retry_ids]
            if retry_blocks and not self._cancel_event.is_set():
                retry_char_limit = max(
                    self._MIN_SPLIT_BATCH_CHARS,
                    min(batch_char_limit, self._UNTRANSLATED_RETRY_MAX_CHARS),
                )
                logger.info(
                    "Retrying %d untranslated blocks with max_chars_per_batch=%d (source=%s)",
                    len(retry_blocks),
                    retry_char_limit,
                    batch_limit_source,
                )
                retry_result = self.translate_blocks_with_result(
                    retry_blocks,
                    reference_files=reference_files,
                    on_progress=None,
                    output_language=output_language,
                    translation_style=translation_style,
                    include_item_ids=include_item_ids,
                    _max_chars_per_batch=retry_char_limit,
                    _max_chars_per_batch_source=batch_limit_source,
                    _split_retry_depth=_split_retry_depth + 1,
                )
                if retry_result.cancelled:
                    cancelled = True
                else:
                    mismatched_batch_count += retry_result.mismatched_batch_count
                    retry_untranslated = set(retry_result.untranslated_block_ids)
                    for block in retry_blocks:
                        if block.id in retry_untranslated:
                            continue
                        translated_text = retry_result.translations.get(block.id)
                        if translated_text and translated_text.strip():
                            translations[block.id] = translated_text
                    untranslated_block_ids = [
                        block_id
                        for block_id in untranslated_block_ids
                        if block_id in retry_untranslated
                    ]

        # Log cache stats after translation
        if self._cache:
            stats = self._cache.stats
            logger.debug("Translation cache stats: %s", stats)

        if timing_enabled and _split_retry_depth == 0:
            logger.debug(
                "[TIMING] BatchTranslator.retries: prompt_too_long=%d local_error=%d copilot_split=%d fallback_original_batches=%d mismatched_batches=%d untranslated_blocks=%d",
                retry_prompt_too_long,
                retry_local_error,
                retry_copilot_split,
                fallback_original_batches,
                mismatched_batch_count,
                len(untranslated_block_ids),
            )

        result = BatchTranslationResult(
            translations=translations,
            untranslated_block_ids=untranslated_block_ids,
            mismatched_batch_count=mismatched_batch_count,
            total_blocks=len(blocks),
            translated_count=len(translations) - len(untranslated_block_ids),
            cancelled=cancelled,
        )

        # Log summary if there were issues
        if result.has_issues:
            logger.warning(
                "Translation completed with issues: %s", result.get_summary()
            )

        # Memory management: warn if cache is large and clear if exceeds threshold
        if self._cache and _split_retry_depth == 0:
            stats = self._cache.stats
            memory_kb = float(stats.get("memory_kb", "0"))
            # Warn if cache exceeds 10MB (10240 KB)
            if memory_kb > 10240:
                logger.warning(
                    "Translation cache memory usage is high: %.1f MB. "
                    "Consider calling clear_cache() after large translations.",
                    memory_kb / 1024,
                )

        return result

    def _looks_like_split_request(self, translations: list[str]) -> bool:
        if not translations:
            return False
        sample = "\n".join(t for t in translations[:5] if t).strip()
        if not sample:
            return False
        hits = sum(marker in sample for marker in self._SPLIT_REQUEST_MARKERS)
        return hits >= self._SPLIT_REQUEST_MIN_MATCHES

    def _create_batches(
        self,
        blocks: list[TextBlock],
        max_chars_per_batch: Optional[int] = None,
    ) -> list[list[TextBlock]]:
        """
        Split blocks into batches based on configured character limits.

        Handles oversized blocks (exceeding max_chars_per_batch) by placing them
        in their own batch with a warning. These will be processed as
        single-item batches.
        """
        batches = []
        current_batch = []
        current_chars = 0
        char_limit = max_chars_per_batch or self.max_chars_per_batch

        for block in blocks:
            block_size = len(block.text)

            # Check if this single block exceeds the character limit
            if block_size > char_limit:
                # Finalize current batch first
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_chars = 0

                # Add oversized block as its own batch with warning
                logger.warning(
                    "Block '%s' exceeds max_chars_per_batch (%d > %d). "
                    "Will be processed as a single-item batch.",
                    block.id,
                    block_size,
                    char_limit,
                )
                batches.append([block])
                continue

            # Check character limit only (item merging is prevented by end markers)
            if current_chars + block_size > char_limit:
                if current_batch:
                    batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(block)
            current_chars += block_size

        if current_batch:
            batches.append(current_batch)

        return batches


class TranslationService:
    """
    Main translation service.
    Coordinates between UI, Copilot, and file processors.
    """

    def __init__(
        self,
        copilot: CopilotHandler,
        config: AppSettings,
        prompts_dir: Optional[Path] = None,
        copilot_lock: Optional[threading.Lock] = None,
    ):
        self.copilot = copilot
        self.config = config
        self.prompt_builder = PromptBuilder(prompts_dir)
        self.batch_translator = BatchTranslator(
            copilot,
            self.prompt_builder,
            max_chars_per_batch=config.max_chars_per_batch if config else None,
            request_timeout=config.request_timeout if config else None,
            copilot_lock=copilot_lock,
        )
        self._local_init_lock = threading.Lock()
        self._local_client = None
        self._local_prompt_builder = None
        self._local_batch_translator = None
        self._copilot_lock = copilot_lock
        # Thread-safe cancellation using Event instead of bool flag
        self._cancel_event = threading.Event()
        self._cancel_callback_depth = 0
        self._cancel_callback_lock = threading.Lock()

        # Lazy-loaded file processors for faster startup
        self._processors: Optional[dict[str, FileProcessor]] = None
        self._processors_lock = threading.Lock()

        # Translation cache is handled by BatchTranslator (PDFMathTranslate compliant)

    @property
    def processors(self) -> dict[str, FileProcessor]:
        """
        Lazy-load file processors on first access (thread-safe).
        This significantly improves startup time by deferring heavy imports
        (xlwings, openpyxl, python-docx, python-pptx, PyMuPDF) until needed.
        """
        if self._processors is None:
            with self._processors_lock:
                # Double-check locking pattern for thread safety
                if self._processors is None:
                    from yakulingo.processors.excel_processor import ExcelProcessor
                    from yakulingo.processors.csv_processor import CsvProcessor
                    from yakulingo.processors.word_processor import WordProcessor
                    from yakulingo.processors.pptx_processor import PptxProcessor
                    from yakulingo.processors.pdf_processor import PdfProcessor
                    from yakulingo.processors.txt_processor import TxtProcessor
                    from yakulingo.processors.msg_processor import MsgProcessor

                    # Note: Legacy formats (.doc, .ppt) are not supported
                    # Only Office Open XML formats are supported for Word/PowerPoint
                    self._processors = {
                        ".xlsx": ExcelProcessor(),
                        ".xls": ExcelProcessor(),
                        ".xlsm": ExcelProcessor(),
                        ".csv": CsvProcessor(),
                        ".docx": WordProcessor(),
                        ".pptx": PptxProcessor(),
                        ".pdf": PdfProcessor(),
                        ".txt": TxtProcessor(),
                        ".msg": MsgProcessor(),
                    }
        return self._processors

    def _use_local_backend(self) -> bool:
        try:
            return bool(
                self.config
                and getattr(self.config, "translation_backend", "copilot") == "local"
            )
        except Exception:
            return False

    def _ensure_local_backend(self) -> None:
        if (
            self._local_client is not None
            and self._local_prompt_builder is not None
            and self._local_batch_translator is not None
        ):
            return
        with self._local_init_lock:
            if self._local_client is None:
                from yakulingo.services.local_ai_client import LocalAIClient

                self._local_client = LocalAIClient(self.config)
            if self._local_prompt_builder is None:
                from yakulingo.services.local_ai_prompt_builder import (
                    LocalPromptBuilder,
                )

                self._local_prompt_builder = LocalPromptBuilder(
                    self.prompt_builder.prompts_dir,
                    base_prompt_builder=self.prompt_builder,
                    settings=self.config,
                )
            if self._local_batch_translator is None:
                max_chars = (
                    self._get_local_text_batch_limit()
                    or BatchTranslator.DEFAULT_MAX_CHARS_PER_BATCH
                )
                self._local_batch_translator = BatchTranslator(
                    self._local_client,
                    self._local_prompt_builder,
                    max_chars_per_batch=max_chars,
                    request_timeout=self.config.request_timeout
                    if self.config
                    else None,
                    copilot_lock=self._copilot_lock,
                )

    def _get_active_client(self):
        if self._use_local_backend():
            self._ensure_local_backend()
            return self._local_client
        return self.copilot

    def _get_active_batch_translator(self) -> BatchTranslator:
        if self._use_local_backend():
            self._ensure_local_backend()
            return self._local_batch_translator
        return self.batch_translator

    def _get_local_text_batch_limit(self) -> Optional[int]:
        if not self._use_local_backend() or self.config is None:
            return None
        limit = getattr(self.config, "local_ai_max_chars_per_batch", None)
        if isinstance(limit, int) and limit > 0:
            return limit
        return None

    def _get_local_file_batch_limit_info(self) -> tuple[Optional[int], str | None]:
        if not self._use_local_backend() or self.config is None:
            return None, None
        limit = getattr(self.config, "local_ai_max_chars_per_batch_file", None)
        if isinstance(limit, int) and limit > 0:
            return limit, "local_ai_max_chars_per_batch_file"
        fallback = getattr(self.config, "local_ai_max_chars_per_batch", None)
        if isinstance(fallback, int) and fallback > 0:
            return fallback, "local_ai_max_chars_per_batch"
        return None, None

    def _get_local_file_batch_limit(self) -> Optional[int]:
        limit, _ = self._get_local_file_batch_limit_info()
        return limit

    def clear_translation_cache(self) -> None:
        """
        Clear translation cache (PDFMathTranslate compliant).

        Delegates to BatchTranslator's TranslationCache.
        """
        self.batch_translator.clear_cache()
        if self._local_batch_translator is not None:
            self._local_batch_translator.clear_cache()
        logger.debug("Translation cache cleared")

    def get_cache_stats(self) -> Optional[dict]:
        """
        Get translation cache statistics.

        Returns:
            Dictionary with 'size', 'hits', 'misses', 'hit_rate' or None if cache disabled
        """
        return self._get_active_batch_translator().get_cache_stats()

    @contextmanager
    def _cancel_callback_scope(self):
        client = self._get_active_client()
        set_cb = getattr(client, "set_cancel_callback", None)
        if not callable(set_cb):
            yield
            return
        with self._cancel_callback_lock:
            self._cancel_callback_depth += 1
            if self._cancel_callback_depth == 1:
                set_cb(lambda: self._cancel_event.is_set())
        try:
            yield
        finally:
            with self._cancel_callback_lock:
                self._cancel_callback_depth = max(0, self._cancel_callback_depth - 1)
                if self._cancel_callback_depth == 0:
                    set_cb(None)

    @contextmanager
    def _ui_window_sync_scope(self, reason: str):
        """翻訳中のみ、EdgeウィンドウをUIの背面に同期表示する（対応環境のみ）。"""
        copilot = getattr(self, "copilot", None)
        scope_factory = (
            getattr(copilot, "ui_window_sync_scope", None)
            if copilot is not None
            else None
        )
        if scope_factory is None:
            yield
            return

        try:
            scope = scope_factory(reason=reason)
        except Exception:
            yield
            return

        with scope:
            yield

    def _translate_single_with_cancel(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> str:
        client = self._get_active_client()
        ui_scope = (
            nullcontext()
            if self._use_local_backend()
            else self._ui_window_sync_scope("translate_single")
        )
        with ui_scope:
            with self._cancel_callback_scope():
                lock = self._copilot_lock or nullcontext()
                with lock:
                    return client.translate_single(
                        text, prompt, reference_files, on_chunk
                    )

    def _translate_single_with_cancel_on_copilot(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> str:
        """Force a Copilot translate_single call regardless of translation_backend."""
        client = self.copilot
        set_cb = getattr(client, "set_cancel_callback", None)
        lock = self._copilot_lock or nullcontext()
        with self._ui_window_sync_scope("translate_single"):
            if callable(set_cb):
                try:
                    set_cb(lambda: self._cancel_event.is_set())
                except Exception:
                    set_cb = None
            try:
                with lock:
                    return client.translate_single(
                        text, prompt, reference_files, on_chunk
                    )
            finally:
                if callable(set_cb):
                    try:
                        set_cb(None)
                    except Exception:
                        pass

    def translate_text(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TranslationResult:
        """
        Legacy English-only text translation helper.

        Uses the file-translation prompt to produce English output or keep
        English input as-is. The main text UI uses translate_text_with_options
        or translate_text_with_style_comparison instead.

        Args:
            text: Source text to translate
            reference_files: Optional list of reference files to attach
            on_chunk: Optional callback called with partial text during streaming

        Returns:
            TranslationResult with output_text
        """
        start_time = time.monotonic()
        self._cancel_event.clear()

        try:
            # Build prompt (English-only legacy path)
            has_refs = bool(reference_files)
            prompt = self.prompt_builder.build(text, has_refs, output_language="en")

            # Translate
            result = self._translate_single_with_cancel(
                text, prompt, reference_files, on_chunk
            )

            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_text=result,
                blocks_translated=1,
                blocks_total=1,
                duration_seconds=time.monotonic() - start_time,
            )

        except TranslationCancelledError:
            logger.info("Text translation cancelled")
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                error_message="翻訳がキャンセルされました",
                duration_seconds=time.monotonic() - start_time,
            )
        except OSError as e:
            logger.warning("File I/O error during translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.monotonic() - start_time,
            )
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during text translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.monotonic() - start_time,
            )

    def detect_language(self, text: str) -> str:
        """
        入力テキストの言語をローカル判定します（Copilotは使用しません）。

        Priority:
        1. Hiragana/Katakana present → "日本語"
        2. Hangul present → "韓国語"
        3. Latin alphabet dominant → "英語"
        4. CJK only or other → "日本語" (default for Japanese users)

        Note: Copilot is no longer used for language detection to ensure
        fast response times. Japanese is used as the default fallback
        since target users are Japanese.

        Args:
            text: Text to analyze

        Returns:
            Detected language name (e.g., "日本語", "英語", "韓国語")
        """
        detected = language_detector.detect_local(text)
        logger.debug("Language detected locally: %s", detected)
        return detected

    def detect_language_with_reason(self, text: str) -> tuple[str, str]:
        """Detect language and return (language, reason_code) for UI display."""
        detected, reason = language_detector.detect_local_with_reason(text)
        logger.debug("Language detected locally: %s (%s)", detected, reason)
        return detected, reason

    def _translate_text_with_options_local(
        self,
        *,
        text: str,
        reference_files: Optional[list[Path]],
        style: str,
        detected_language: str,
        output_language: str,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TextTranslationResult:
        self._ensure_local_backend()
        from yakulingo.services.local_ai_client import (
            is_truncated_json,
            parse_text_single_translation,
        )
        from yakulingo.services.local_llama_server import LocalAIError

        local_builder = self._local_prompt_builder
        if local_builder is None:
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language=output_language,
                detected_language=detected_language,
                error_message="ローカルAIの初期化に失敗しました",
            )

        embedded_ref = local_builder.build_reference_embed(
            reference_files, input_text=text
        )
        metadata: dict = {"backend": "local"}
        if embedded_ref.warnings:
            metadata["reference_warnings"] = embedded_ref.warnings
        if embedded_ref.truncated:
            metadata["reference_truncated"] = True

        try:
            if output_language == "en":
                prompt = local_builder.build_text_to_en_single(
                    text,
                    style=style,
                    reference_files=reference_files,
                    detected_language=detected_language,
                )
                stream_handler = _wrap_local_streaming_on_chunk(on_chunk)
                raw = self._translate_single_with_cancel(
                    text, prompt, None, stream_handler
                )
                translation, explanation = parse_text_single_translation(raw)
                if not translation:
                    error_message = "ローカルAIの応答(JSON)を解析できませんでした（詳細はログを確認してください）"
                    if is_truncated_json(raw):
                        error_message = (
                            "ローカルAIの応答が途中で終了しました（JSONが閉じていません）。\n"
                            "max_tokens / ctx_size を見直してください。"
                        )
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message=error_message,
                        metadata=metadata,
                    )
                if _is_text_output_language_mismatch(translation, "en"):
                    metadata["output_language_mismatch"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳結果が英語ではありませんでした（出力言語ガード）",
                        metadata=metadata,
                    )
                if _looks_incomplete_translation_to_en(text, translation):
                    metadata["incomplete_translation"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳結果が不完全でした（短すぎます）。",
                        metadata=metadata,
                    )
                explanation = ""
                fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                    source_text=text,
                    translated_text=translation,
                )
                if fixed:
                    translation = fixed_text
                    metadata["to_en_numeric_unit_correction"] = True
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[
                        TranslationOption(
                            text=translation, explanation=explanation, style=style
                        )
                    ],
                    output_language=output_language,
                    detected_language=detected_language,
                    metadata=metadata,
                )

            prompt = local_builder.build_text_to_jp(
                text,
                reference_files=reference_files,
                detected_language=detected_language,
            )
            stream_handler = _wrap_local_streaming_on_chunk(on_chunk)
            raw = self._translate_single_with_cancel(text, prompt, None, stream_handler)
            translation, _ = parse_text_single_translation(raw)
            if not translation:
                error_message = "ローカルAIの応答(JSON)を解析できませんでした（詳細はログを確認してください）"
                if is_truncated_json(raw):
                    error_message = (
                        "ローカルAIの応答が途中で終了しました（JSONが閉じていません）。\n"
                        "max_tokens / ctx_size を見直してください。"
                    )
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message=error_message,
                    metadata=metadata,
                )
            if _is_text_output_language_mismatch(translation, "jp"):
                retry_instruction = (
                    BatchTranslator._JP_STRICT_OUTPUT_LANGUAGE_INSTRUCTION
                )
                retry_prompt = _insert_extra_instruction(prompt, retry_instruction)
                retry_raw = self._translate_single_with_cancel(
                    text, retry_prompt, None, None
                )
                retry_translation, _ = parse_text_single_translation(retry_raw)
                if retry_translation and not _is_text_output_language_mismatch(
                    retry_translation, "jp"
                ):
                    translation = retry_translation
                    metadata["output_language_retry"] = True
                else:
                    metadata["output_language_mismatch"] = True
                    metadata["output_language_retry_failed"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳結果が日本語ではありませんでした（出力言語ガード）",
                        metadata=metadata,
                    )
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                options=[TranslationOption(text=translation, explanation="")],
                output_language=output_language,
                detected_language=detected_language,
                metadata=metadata,
            )
        except LocalAIError as e:
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language=output_language,
                detected_language=detected_language,
                error_message=str(e),
                metadata=metadata,
            )

    def _translate_text_with_style_comparison_local(
        self,
        *,
        text: str,
        reference_files: Optional[list[Path]],
        styles: list[str],
        detected_language: str,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TextTranslationResult:
        _ = styles
        return self._translate_text_with_options_local(
            text=text,
            reference_files=reference_files,
            style="minimal",
            detected_language=detected_language,
            output_language="en",
            on_chunk=on_chunk,
        )
        self._ensure_local_backend()
        from yakulingo.services.local_ai_client import (
            is_truncated_json,
            parse_text_single_translation,
            parse_text_to_en_3style,
            parse_text_to_en_style_subset,
        )
        from yakulingo.services.local_llama_server import LocalAIError

        local_builder = self._local_prompt_builder
        if local_builder is None:
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",
                detected_language=detected_language,
                error_message="ローカルAIの初期化に失敗しました",
            )

        embedded_ref = local_builder.build_reference_embed(
            reference_files, input_text=text
        )
        metadata: dict = {"backend": "local"}
        if embedded_ref.warnings:
            metadata["reference_warnings"] = embedded_ref.warnings
        if embedded_ref.truncated:
            metadata["reference_truncated"] = True

        local_style_compare_call_budget = 2
        local_style_compare_call_count = 0
        local_style_compare_call_phases: list[str] = []
        local_style_compare_call_budget_exhausted_phases: list[str] = []

        def call_local(
            prompt: str,
            stream_handler: "Callable[[str], None] | None",
            phase: str,
        ) -> str | None:
            nonlocal local_style_compare_call_count

            if local_style_compare_call_count >= local_style_compare_call_budget:
                local_style_compare_call_budget_exhausted_phases.append(phase)
                return None

            local_style_compare_call_count += 1
            local_style_compare_call_phases.append(phase)
            return self._translate_single_with_cancel(
                text, prompt, None, stream_handler
            )

        style_list = [s for s in styles if s in TEXT_STYLE_ORDER]
        seen = set()
        style_list = [s for s in style_list if not (s in seen or seen.add(s))]
        if not style_list:
            style_list = list(TEXT_STYLE_ORDER)

        by_style: dict[str, tuple[str, str]] = {}
        truncated_detected = False
        wants_combined = (
            set(style_list) == set(TEXT_STYLE_ORDER) and len(style_list) > 1
        )
        try:
            if wants_combined:
                prompt = local_builder.build_text_to_en_3style(
                    text,
                    reference_files=reference_files,
                    detected_language=detected_language,
                )
                stream_handler = _wrap_local_streaming_on_chunk(on_chunk)
                raw = call_local(prompt, stream_handler, "combined_3style")
                if raw is not None:
                    by_style = parse_text_to_en_3style(raw)
                    if not by_style and is_truncated_json(raw):
                        truncated_detected = True

            options: list[TranslationOption] = []
            missing: list[str] = []
            for style in style_list:
                resolved_style = (
                    "standard"
                    if style == "concise"
                    and style not in by_style
                    and "standard" in by_style
                    else style
                )
                if resolved_style in by_style:
                    translation, _ = by_style[resolved_style]
                    options.append(
                        TranslationOption(
                            text=translation,
                            explanation="",
                            style=style,
                        )
                    )
                else:
                    missing.append(style)

            if wants_combined and missing:
                prompt = local_builder.build_text_to_en_missing_styles(
                    text,
                    styles=missing,
                    reference_files=reference_files,
                    detected_language=detected_language,
                )
                stream_handler = _wrap_local_streaming_on_chunk(on_chunk)
                raw = call_local(prompt, stream_handler, "missing_styles_subset")
                if raw is not None:
                    missing_by_style = parse_text_to_en_style_subset(raw, missing)
                    if missing_by_style:
                        for style, payload in missing_by_style.items():
                            if style not in by_style:
                                by_style[style] = payload
                    elif is_truncated_json(raw):
                        truncated_detected = True

                options = []
                missing = []
                for style in style_list:
                    resolved_style = (
                        "standard"
                        if style == "concise"
                        and style not in by_style
                        and "standard" in by_style
                        else style
                    )
                    if resolved_style in by_style:
                        translation, _ = by_style[resolved_style]
                        options.append(
                            TranslationOption(
                                text=translation,
                                explanation="",
                                style=style,
                            )
                        )
                    else:
                        missing.append(style)

            if missing:
                for style in missing:
                    prompt = local_builder.build_text_to_en_single(
                        text,
                        style=style,
                        reference_files=reference_files,
                        detected_language=detected_language,
                    )
                    stream_handler = _wrap_local_streaming_on_chunk(on_chunk)
                    raw = call_local(prompt, stream_handler, f"missing_single_{style}")
                    if raw is None:
                        break
                    translation, _ = parse_text_single_translation(raw)
                    if translation:
                        options.append(
                            TranslationOption(
                                text=translation,
                                explanation="",
                                style=style,
                            )
                        )
                    elif is_truncated_json(raw):
                        truncated_detected = True

            if options:
                options.sort(
                    key=lambda opt: TEXT_STYLE_ORDER.index(
                        opt.style or DEFAULT_TEXT_STYLE
                    )
                )
                mismatched_styles = [
                    opt.style
                    for opt in options
                    if opt.style and _is_text_output_language_mismatch(opt.text, "en")
                ]
                if mismatched_styles:
                    seen_retry = set()
                    retry_styles = [
                        s
                        for s in mismatched_styles
                        if not (s in seen_retry or seen_retry.add(s))
                    ]
                    retry_prompt = local_builder.build_text_to_en_missing_styles(
                        text,
                        styles=retry_styles,
                        reference_files=reference_files,
                        detected_language=detected_language,
                    )
                    retry_prompt = _insert_extra_instruction(
                        retry_prompt,
                        BatchTranslator._EN_STRICT_OUTPUT_LANGUAGE_INSTRUCTION,
                    )
                    retry_raw = call_local(retry_prompt, None, "output_language_retry")
                    retry_by_style = (
                        parse_text_to_en_style_subset(retry_raw, retry_styles)
                        if retry_raw is not None
                        else None
                    )
                    if retry_by_style:
                        updated = False
                        for opt in options:
                            style = opt.style
                            if not style or style not in retry_by_style:
                                continue
                            translation, _ = retry_by_style[style]
                            if translation and not _is_text_output_language_mismatch(
                                translation, "en"
                            ):
                                opt.text = translation
                                opt.explanation = ""
                                updated = True
                        if updated:
                            metadata["output_language_retry"] = True

                    remaining_mismatched_styles = [
                        opt.style
                        for opt in options
                        if opt.style
                        and _is_text_output_language_mismatch(opt.text, "en")
                    ]
                    if remaining_mismatched_styles:
                        has_correct = any(
                            opt.style
                            and not _is_text_output_language_mismatch(opt.text, "en")
                            for opt in options
                        )
                        if has_correct:
                            options = [
                                opt
                                for opt in options
                                if not _is_text_output_language_mismatch(opt.text, "en")
                            ]
                            metadata["output_language_mismatch_partial"] = True
                            metadata["output_language_mismatch_styles"] = sorted(
                                set(remaining_mismatched_styles)
                            )

                    if any(
                        _is_text_output_language_mismatch(opt.text, "en")
                        for opt in options
                    ):
                        metadata["output_language_mismatch"] = True
                        metadata["output_language_retry_failed"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language="en",
                            detected_language=detected_language,
                            error_message="翻訳結果が英語ではありませんでした（出力言語ガード）",
                            metadata=metadata,
                        )

                too_short_styles = [
                    opt.style
                    for opt in options
                    if opt.style and _looks_incomplete_translation_to_en(text, opt.text)
                ]
                if too_short_styles:
                    retry_instruction = (
                        "- CRITICAL: Translate the entire input text into English. "
                        "Do not output only a single keyword (e.g., 'Revenue') or a short label."
                    )
                    seen_retry = set()
                    retry_styles = [
                        s
                        for s in too_short_styles
                        if not (s in seen_retry or seen_retry.add(s))
                    ]
                    metadata["incomplete_translation_retry"] = True
                    retry_prompt = local_builder.build_text_to_en_missing_styles(
                        text,
                        styles=retry_styles,
                        reference_files=reference_files,
                        detected_language=detected_language,
                        extra_instruction=retry_instruction,
                    )
                    retry_raw = call_local(
                        retry_prompt, None, "incomplete_translation_retry"
                    )
                    retry_by_style = (
                        parse_text_to_en_style_subset(retry_raw, retry_styles)
                        if retry_raw is not None
                        else None
                    )
                    if retry_raw is None:
                        metadata[
                            "incomplete_translation_retry_skipped_due_to_budget"
                        ] = True
                    if retry_by_style:
                        for opt in options:
                            style = opt.style
                            if not style or style not in retry_by_style:
                                continue
                            retry_translation, _ = retry_by_style[style]
                            if (
                                retry_translation
                                and not _is_text_output_language_mismatch(
                                    retry_translation, "en"
                                )
                                and not _looks_incomplete_translation_to_en(
                                    text, retry_translation
                                )
                            ):
                                opt.text = retry_translation
                                opt.explanation = ""

                    incomplete_styles = {
                        opt.style
                        for opt in options
                        if opt.style
                        and _looks_incomplete_translation_to_en(text, opt.text)
                    }
                    if incomplete_styles:
                        has_complete = any(
                            opt.style
                            and not _looks_incomplete_translation_to_en(text, opt.text)
                            for opt in options
                        )
                        if not has_complete:
                            metadata["incomplete_translation"] = True
                            metadata["incomplete_translation_retry_failed"] = True
                            return TextTranslationResult(
                                source_text=text,
                                source_char_count=len(text),
                                output_language="en",
                                detected_language=detected_language,
                                error_message="翻訳結果が不完全でした（短すぎます）。",
                                metadata=metadata,
                            )
                        for opt in options:
                            if opt.style and opt.style in incomplete_styles:
                                opt.style = None

                numeric_rule_violation_styles = [
                    opt.style
                    for opt in options
                    if opt.style and _needs_to_en_numeric_rule_retry(text, opt.text)
                ]
                if numeric_rule_violation_styles:
                    retry_instruction = (
                        "- CRITICAL: Follow numeric conversion rules strictly. "
                        "Do not use 'billion', 'trillion', or 'bn'. Use 'oku' (and 'k') "
                        "exactly as specified. If numeric hints are provided, use them verbatim."
                    )
                    seen_retry = set()
                    retry_styles = [
                        s
                        for s in numeric_rule_violation_styles
                        if not (s in seen_retry or seen_retry.add(s))
                    ]
                    retry_prompt = local_builder.build_text_to_en_missing_styles(
                        text,
                        styles=retry_styles,
                        reference_files=reference_files,
                        detected_language=detected_language,
                        extra_instruction=retry_instruction,
                    )
                    retry_raw = call_local(
                        retry_prompt, None, "to_en_numeric_rule_retry"
                    )
                    retry_by_style = (
                        parse_text_to_en_style_subset(retry_raw, retry_styles)
                        if retry_raw is not None
                        else None
                    )
                    if retry_raw is None:
                        metadata["to_en_numeric_rule_retry_skipped_due_to_budget"] = (
                            True
                        )
                    else:
                        metadata["to_en_numeric_rule_retry"] = True
                        metadata["to_en_numeric_rule_retry_styles"] = retry_styles
                    updated = False
                    if retry_by_style:
                        for opt in options:
                            style = opt.style
                            if not style or style not in retry_by_style:
                                continue
                            translation, _ = retry_by_style[style]
                            if (
                                translation
                                and not _is_text_output_language_mismatch(
                                    translation, "en"
                                )
                                and not _looks_incomplete_translation_to_en(
                                    text, translation
                                )
                                and not _needs_to_en_numeric_rule_retry(
                                    text, translation
                                )
                            ):
                                opt.text = translation
                                opt.explanation = ""
                                updated = True
                    if updated:
                        metadata["to_en_numeric_rule_retry_updated"] = True

                    failed_styles = [
                        opt.style
                        for opt in options
                        if opt.style
                        and opt.style in retry_styles
                        and _needs_to_en_numeric_rule_retry(text, opt.text)
                    ]
                    if failed_styles or not retry_by_style:
                        metadata["to_en_numeric_rule_retry_failed"] = True
                        metadata["to_en_numeric_rule_retry_failed_styles"] = (
                            failed_styles if failed_styles else retry_styles
                        )

                corrected_styles: list[str] = []
                for opt in options:
                    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                        source_text=text,
                        translated_text=opt.text,
                    )
                    if not fixed:
                        continue
                    opt.text = fixed_text
                    opt.explanation = ""
                    if opt.style:
                        corrected_styles.append(opt.style)
                if corrected_styles:
                    metadata["to_en_numeric_unit_correction"] = True
                    metadata["to_en_numeric_unit_correction_styles"] = corrected_styles
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=options,
                    output_language="en",
                    detected_language=detected_language,
                    metadata=metadata,
                )

            error_message = "ローカルAIの応答(JSON)を解析できませんでした（詳細はログを確認してください）"
            if truncated_detected:
                error_message = (
                    "ローカルAIの応答が途中で終了しました（JSONが閉じていません）。\n"
                    "max_tokens / ctx_size を見直してください。"
                )
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",
                detected_language=detected_language,
                error_message=error_message,
                metadata=metadata,
            )
        except LocalAIError as e:
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",
                detected_language=detected_language,
                error_message=str(e),
                metadata=metadata,
            )
        finally:
            metadata["local_style_compare_call_budget"] = (
                local_style_compare_call_budget
            )
            metadata["local_style_compare_call_count"] = local_style_compare_call_count
            metadata["local_style_compare_call_phases"] = (
                local_style_compare_call_phases
            )
            if local_style_compare_call_budget_exhausted_phases:
                metadata["local_style_compare_call_budget_exhausted"] = True
                metadata["local_style_compare_call_budget_exhausted_phases"] = (
                    local_style_compare_call_budget_exhausted_phases
                )

    def _translate_text_with_options_on_copilot(
        self,
        *,
        text: str,
        reference_files: Optional[list[Path]],
        style: str,
        detected_language: str,
        output_language: str,
        on_chunk: "Callable[[str], None] | None",
        translate_single: Callable[..., str],
    ) -> TextTranslationResult:
        copilot_call_count = 0
        copilot_call_phases: list[str] = []

        def translate_single_tracked(
            phase: str,
            source_text: str,
            prompt: str,
            reference_files: Optional[list[Path]] = None,
            on_chunk: "Callable[[str], None] | None" = None,
        ) -> str:
            nonlocal copilot_call_count
            copilot_call_count += 1
            copilot_call_phases.append(phase)
            return translate_single(source_text, prompt, reference_files, on_chunk)

        def attach_copilot_telemetry(
            result: TextTranslationResult,
        ) -> TextTranslationResult:
            metadata = dict(result.metadata) if result.metadata else {}
            metadata.setdefault("backend", "copilot")
            metadata["copilot_call_count"] = copilot_call_count
            metadata["copilot_call_phases"] = list(copilot_call_phases)
            result.metadata = metadata
            return result

        if output_language == "en":
            template = self.prompt_builder.get_text_compare_template()
            if not template:
                return attach_copilot_telemetry(
                    TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="Missing text comparison template",
                    )
                )

            if reference_files:
                reference_section = REFERENCE_INSTRUCTION
                files_to_attach = reference_files
            else:
                reference_section = ""
                files_to_attach = None

            self.prompt_builder.reload_translation_rules_if_needed()
            translation_rules = self.prompt_builder.get_translation_rules(
                output_language
            )
            numeric_hints = _build_to_en_numeric_hints(text)

            def build_compare_prompt(extra_instruction: Optional[str] = None) -> str:
                prompt = template.replace("{translation_rules}", translation_rules)
                prompt = prompt.replace("{reference_section}", reference_section)
                prompt = prompt.replace("{input_text}", text)
                extra_parts: list[str] = []
                if extra_instruction:
                    extra_parts.append(extra_instruction.strip())
                if numeric_hints:
                    extra_parts.append(numeric_hints.strip())
                if extra_parts:
                    prompt = _insert_extra_instruction(prompt, "\n\n".join(extra_parts))
                return prompt

            def parse_compare_result(
                raw_result: str,
            ) -> Optional[TextTranslationResult]:
                parsed_options = self._parse_style_comparison_result(raw_result)
                if parsed_options:
                    options_by_style: dict[str, TranslationOption] = {}
                    for option in parsed_options:
                        if option.style and option.style not in options_by_style:
                            options_by_style[option.style] = option
                    selected_style = style
                    if selected_style == "standard":
                        selected_style = "concise"
                    selected = options_by_style.get(selected_style) or parsed_options[0]
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[selected],
                        output_language=output_language,
                        detected_language=detected_language,
                    )

                parsed_single = self._parse_single_translation_result(raw_result)
                if parsed_single:
                    option = parsed_single[0]
                    option.style = style
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[option],
                        output_language=output_language,
                        detected_language=detected_language,
                    )

                if raw_result.strip():
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[
                            TranslationOption(
                                text=raw_result.strip(),
                                explanation="",
                                style=style,
                            )
                        ],
                        output_language=output_language,
                        detected_language=detected_language,
                    )

                return None

            prompt = build_compare_prompt()
            logger.debug(
                "Sending text to Copilot (compare fallback, streaming=%s, refs=%d)",
                bool(on_chunk),
                len(files_to_attach) if files_to_attach else 0,
            )
            raw_result = translate_single_tracked(
                "initial", text, prompt, files_to_attach, on_chunk
            )
            result = parse_compare_result(raw_result)

            needs_output_language_retry = bool(
                result
                and result.options
                and _is_text_output_language_mismatch(result.options[0].text, "en")
            )
            needs_numeric_rule_retry = bool(
                result
                and result.options
                and _needs_to_en_numeric_rule_retry_copilot_after_auto_fix(
                    text, result.options[0].text
                )
            )
            if needs_output_language_retry or needs_numeric_rule_retry:
                retry_phase_parts: list[str] = []
                if needs_output_language_retry:
                    retry_phase_parts.append("output_language_retry")
                if needs_numeric_rule_retry:
                    retry_phase_parts.append("numeric_rule_retry")
                retry_phase = (
                    "+".join(retry_phase_parts) if retry_phase_parts else "retry"
                )

                retry_parts: list[str] = []
                if needs_output_language_retry:
                    retry_parts.append(_TEXT_TO_EN_OUTPUT_LANGUAGE_RETRY_INSTRUCTION)
                if needs_numeric_rule_retry:
                    retry_parts.append(_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION)
                retry_prompt = build_compare_prompt("\n".join(retry_parts))
                retry_raw = translate_single_tracked(
                    retry_phase, text, retry_prompt, files_to_attach, None
                )
                retry_result = parse_compare_result(retry_raw)

                if retry_result and retry_result.options:
                    retry_text = retry_result.options[0].text
                    fixed_retry_text, fixed_retry = (
                        _fix_to_en_oku_numeric_unit_if_possible(
                            source_text=text,
                            translated_text=retry_text,
                        )
                    )
                    if fixed_retry:
                        retry_result.options[0].text = fixed_retry_text
                        retry_result.options[0].explanation = ""
                        metadata = (
                            dict(retry_result.metadata) if retry_result.metadata else {}
                        )
                        metadata.setdefault("backend", "copilot")
                        metadata["to_en_numeric_unit_correction"] = True
                        retry_result.metadata = metadata
                        retry_text = fixed_retry_text
                    if not _is_text_output_language_mismatch(
                        retry_text, "en"
                    ) and not _needs_to_en_numeric_rule_retry_copilot(text, retry_text):
                        if needs_numeric_rule_retry:
                            metadata = (
                                dict(retry_result.metadata)
                                if retry_result.metadata
                                else {}
                            )
                            metadata.setdefault("backend", "copilot")
                            metadata["to_en_numeric_rule_retry"] = True
                            metadata["to_en_numeric_rule_retry_styles"] = [style]
                            retry_result.metadata = metadata
                        return attach_copilot_telemetry(retry_result)

                if needs_output_language_retry:
                    metadata = {
                        "backend": "copilot",
                        "output_language_mismatch": True,
                        "output_language_retry_failed": True,
                    }
                    if needs_numeric_rule_retry:
                        metadata["to_en_numeric_rule_retry"] = True
                        metadata["to_en_numeric_rule_retry_styles"] = [style]
                        metadata["to_en_numeric_rule_retry_failed"] = True
                        metadata["to_en_numeric_rule_retry_failed_styles"] = [style]
                    return attach_copilot_telemetry(
                        TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message="翻訳結果が英語ではありませんでした（出力言語ガード）",
                            metadata=metadata,
                        )
                    )

                if needs_numeric_rule_retry and result and result.options:
                    metadata = dict(result.metadata) if result.metadata else {}
                    metadata.setdefault("backend", "copilot")
                    metadata["to_en_numeric_rule_retry"] = True
                    metadata["to_en_numeric_rule_retry_styles"] = [style]
                    metadata["to_en_numeric_rule_retry_failed"] = True
                    metadata["to_en_numeric_rule_retry_failed_styles"] = [style]
                    result.metadata = metadata
                if (
                    retry_result
                    and retry_result.options
                    and not _is_text_output_language_mismatch(
                        retry_result.options[0].text, "en"
                    )
                ):
                    if needs_numeric_rule_retry:
                        metadata = (
                            dict(retry_result.metadata) if retry_result.metadata else {}
                        )
                        metadata.setdefault("backend", "copilot")
                        metadata["to_en_numeric_rule_retry"] = True
                        metadata["to_en_numeric_rule_retry_styles"] = [style]
                        metadata["to_en_numeric_rule_retry_failed"] = True
                        metadata["to_en_numeric_rule_retry_failed_styles"] = [style]
                        retry_result.metadata = metadata
                    return attach_copilot_telemetry(retry_result)

            if result:
                if result.output_language == "en" and result.options:
                    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                        source_text=text,
                        translated_text=result.options[0].text,
                    )
                    if fixed:
                        result.options[0].text = fixed_text
                        result.options[0].explanation = ""
                        metadata = dict(result.metadata) if result.metadata else {}
                        metadata.setdefault("backend", "copilot")
                        metadata["to_en_numeric_unit_correction"] = True
                        result.metadata = metadata
                return attach_copilot_telemetry(result)

            logger.warning("Empty response received from Copilot")
            return attach_copilot_telemetry(
                TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message="Copilotから応答がありませんでした。Edgeブラウザを確認してください。",
                )
            )

        template = self.prompt_builder.get_text_template(output_language, style)
        if template is None:
            logger.warning(
                "Missing JP text template (output_language=%s, style=%s); using default",
                output_language,
                style,
            )
            template = DEFAULT_TEXT_TO_JP_TEMPLATE

        if reference_files:
            reference_section = REFERENCE_INSTRUCTION
            files_to_attach = reference_files
        else:
            reference_section = ""
            files_to_attach = None

        self.prompt_builder.reload_translation_rules_if_needed()
        translation_rules = self.prompt_builder.get_translation_rules(output_language)

        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt_input_text = self.prompt_builder.normalize_input_text(
            text, output_language
        )
        prompt = prompt.replace("{input_text}", prompt_input_text)
        if output_language == "en":
            prompt = prompt.replace("{style}", style)

        logger.debug(
            "Sending text to Copilot (streaming=%s, refs=%d)",
            bool(on_chunk),
            len(files_to_attach) if files_to_attach else 0,
        )
        raw_result = translate_single_tracked(
            "initial", text, prompt, files_to_attach, on_chunk
        )
        options = self._parse_single_translation_result(raw_result)
        for opt in options:
            opt.style = style

        candidate = options[0].text if options else raw_result.strip()
        if _is_text_output_language_mismatch(candidate, "jp"):
            retry_instruction = (
                BatchTranslator._JP_STRICT_OUTPUT_LANGUAGE_INSTRUCTION
                + "\n- Keep the exact output format (Translation: ... only)."
            )
            retry_prompt = _insert_extra_instruction(prompt, retry_instruction)
            retry_raw = translate_single_tracked(
                "output_language_retry", text, retry_prompt, files_to_attach, None
            )
            retry_options = self._parse_single_translation_result(retry_raw)
            for opt in retry_options:
                opt.style = style
            if retry_options and not _is_text_output_language_mismatch(
                retry_options[0].text, "jp"
            ):
                return attach_copilot_telemetry(
                    TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=retry_options,
                        output_language=output_language,
                        detected_language=detected_language,
                    )
                )

            metadata = {
                "backend": "copilot",
                "output_language_mismatch": True,
                "output_language_retry_failed": True,
            }
            return attach_copilot_telemetry(
                TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message="翻訳結果が日本語ではありませんでした（出力言語ガード）",
                    metadata=metadata,
                )
            )

        if options:
            return attach_copilot_telemetry(
                TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=options,
                    output_language=output_language,
                    detected_language=detected_language,
                )
            )
        if raw_result.strip():
            return attach_copilot_telemetry(
                TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[
                        TranslationOption(
                            text=raw_result.strip(),
                            explanation="",
                            style=style,
                        )
                    ],
                    output_language=output_language,
                    detected_language=detected_language,
                )
            )

        logger.warning("Empty response received from Copilot")
        return attach_copilot_telemetry(
            TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language=output_language,
                detected_language=detected_language,
                error_message="Copilotから応答がありませんでした。Edgeブラウザを確認してください。",
            )
        )

    def translate_text_with_options(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        style: Optional[str] = None,
        pre_detected_language: Optional[str] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TextTranslationResult:
        """
        Translate text with language-specific handling:
        - Japanese input → English output (single translation based on style)
        - Other input → Japanese output (single translation + detailed explanation)

        Args:
            text: Source text to translate
            reference_files: Optional list of reference files to attach
            style: Translation style for English output ("standard", "concise", "minimal")
                   If None, uses DEFAULT_TEXT_STYLE (default: "concise")
            pre_detected_language: Pre-detected language from detect_language() to skip detection
            on_chunk: Optional callback called with partial text during streaming

        Returns:
            TextTranslationResult with options and output_language
        """
        detected_language: Optional[str] = None
        self._cancel_event.clear()
        try:
            # 事前判定があればそれを使用、なければローカル判定する（Copilotは使用しない）
            if pre_detected_language:
                detected_language = pre_detected_language
                logger.info("Using pre-detected language: %s", detected_language)
            else:
                detected_language = self.detect_language(text)
                logger.info("Detected language: %s", detected_language)

            # Determine output language based on detection
            is_japanese = detected_language == "日本語"
            output_language = "en" if is_japanese else "jp"

            # English output is minimal-only (ignore any requested style).
            if output_language == "en":
                style = "minimal"
            elif style is None:
                style = DEFAULT_TEXT_STYLE

            translate_single = self._translate_single_with_cancel
            copilot_on_chunk = on_chunk

            if self._use_local_backend():
                local_result = self._translate_text_with_options_local(
                    text=text,
                    reference_files=reference_files,
                    style=style,
                    detected_language=detected_language,
                    output_language=output_language,
                    on_chunk=on_chunk,
                )
                if (local_result.metadata or {}).get(
                    "output_language_mismatch"
                ) and bool(getattr(self.config, "copilot_enabled", True)):
                    logger.warning(
                        "Local text translation output language mismatch; falling back to Copilot"
                    )
                    translate_single = self._translate_single_with_cancel_on_copilot
                    copilot_on_chunk = None
                else:
                    return local_result

            return self._translate_text_with_options_on_copilot(
                text=text,
                reference_files=reference_files,
                style=style,
                detected_language=detected_language,
                output_language=output_language,
                on_chunk=copilot_on_chunk,
                translate_single=translate_single,
            )

        except TranslationCancelledError:
            logger.info("Text translation with options cancelled")
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                detected_language=detected_language,
                error_message="翻訳がキャンセルされました",
            )
        except OSError as e:
            logger.warning("File I/O error during translation: %s", e)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                detected_language=detected_language,
                error_message=str(e),
            )
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during text translation with options: %s", e)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                detected_language=detected_language,
                error_message=str(e),
            )

    def translate_text_with_style_comparison(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        styles: Optional[list[str]] = None,
        pre_detected_language: Optional[str] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TextTranslationResult:
        """Translate text with minimal-only English output.

        For non-Japanese input, falls back to single →jp translation.
        """
        detected_language = pre_detected_language
        if not detected_language:
            detected_language = self.detect_language(text)

        is_japanese = detected_language == "日本語"
        output_language = "en" if is_japanese else "jp"

        if output_language != "en":
            return self.translate_text_with_options(
                text,
                reference_files,
                None,
                detected_language,
                on_chunk,
            )
        return self.translate_text_with_options(
            text,
            reference_files,
            "minimal",
            detected_language,
            on_chunk,
        )

        def normalize_style(style_value: str) -> str:
            normalized = (style_value or "").strip().lower()
            if normalized == "standard":
                return "concise"
            return normalized

        style_list: list[str] = []
        if styles:
            for style_value in styles:
                normalized = normalize_style(style_value)
                if normalized in TEXT_STYLE_ORDER and normalized not in style_list:
                    style_list.append(normalized)

        style_list = [s for s in TEXT_STYLE_ORDER if s in style_list] or list(
            TEXT_STYLE_ORDER
        )
        for required_style in TEXT_STYLE_ORDER:
            if required_style not in style_list:
                style_list.append(required_style)

        def ensure_style_options(
            result: TextTranslationResult,
        ) -> TextTranslationResult:
            if result.output_language != "en":
                return result
            if not result.options:
                return result

            options_by_style: dict[str, TranslationOption] = {}
            for option in result.options:
                style = (option.style or "").strip().lower()
                if style and style in style_list and style not in options_by_style:
                    options_by_style[style] = option

            if not options_by_style:
                first = result.options[0]
                fallback_style = normalize_style(first.style or DEFAULT_TEXT_STYLE)
                if fallback_style in style_list:
                    options_by_style[fallback_style] = first

            if not options_by_style:
                return result

            fallback_preferences: dict[str, tuple[str, ...]] = {
                "concise": ("minimal",),
                "minimal": ("concise",),
            }

            style_fallback: dict[str, str] = {}
            ensured: list[TranslationOption] = []
            for style in style_list:
                if style in options_by_style:
                    option = options_by_style[style]
                    if option.style != style:
                        option.style = style
                    ensured.append(option)
                    continue

                source_style = None
                for candidate in fallback_preferences.get(style, ()):
                    if candidate in options_by_style:
                        source_style = candidate
                        break
                if source_style is None:
                    source_style = next(iter(options_by_style.keys()))
                source_option = options_by_style[source_style]
                ensured.append(
                    TranslationOption(
                        text=source_option.text,
                        explanation=source_option.explanation,
                        style=style,
                    )
                )
                style_fallback[style] = source_style

            if style_fallback:
                metadata = dict(result.metadata) if result.metadata else {}
                existing = metadata.get("style_fallback")
                if isinstance(existing, dict):
                    merged = dict(existing)
                    merged.update(style_fallback)
                    metadata["style_fallback"] = merged
                else:
                    metadata["style_fallback"] = style_fallback
                result.metadata = metadata

            result.options = ensured
            return result

        translate_single = self._translate_single_with_cancel
        copilot_on_chunk = on_chunk

        if self._use_local_backend():
            local_result = self._translate_text_with_style_comparison_local(
                text=text,
                reference_files=reference_files,
                styles=style_list,
                detected_language=detected_language,
                on_chunk=on_chunk,
            )
            if (local_result.metadata or {}).get("output_language_mismatch") and bool(
                getattr(self.config, "copilot_enabled", True)
            ):
                logger.warning(
                    "Local text style comparison output language mismatch; falling back to Copilot"
                )
                translate_single = self._translate_single_with_cancel_on_copilot
                copilot_on_chunk = None
            else:
                return ensure_style_options(local_result)

        telemetry_translate_single_calls = 0
        telemetry_translate_single_seconds_total = 0.0
        telemetry_translate_single_phases: list[str] = []
        telemetry_translate_single_phase_counts: dict[str, int] = {}
        telemetry_translate_single_phase_seconds: dict[str, float] = {}
        telemetry_output_language_retry_calls = 0
        telemetry_numeric_rule_retry_calls = 0
        telemetry_numeric_rule_retry_failed = False
        telemetry_fill_missing_styles_calls = 0
        telemetry_fill_missing_styles_styles: list[str] = []
        telemetry_style_diff_guard_calls = 0
        telemetry_style_diff_guard_styles: list[str] = []
        telemetry_combined_attempted = False
        telemetry_combined_succeeded = False
        telemetry_per_style_used = False

        def translate_single_timed(
            phase: str,
            source_text: str,
            prompt: str,
            reference_files: Optional[list[Path]] = None,
            on_chunk: "Callable[[str], None] | None" = None,
        ) -> str:
            nonlocal telemetry_translate_single_calls
            nonlocal telemetry_translate_single_seconds_total

            start = time.monotonic()
            raw = translate_single(source_text, prompt, reference_files, on_chunk)
            elapsed = time.monotonic() - start

            telemetry_translate_single_calls += 1
            telemetry_translate_single_seconds_total += elapsed
            telemetry_translate_single_phases.append(phase)
            telemetry_translate_single_phase_counts[phase] = (
                telemetry_translate_single_phase_counts.get(phase, 0) + 1
            )
            telemetry_translate_single_phase_seconds[phase] = (
                telemetry_translate_single_phase_seconds.get(phase, 0.0) + elapsed
            )
            return raw

        def attach_style_comparison_telemetry(
            result: TextTranslationResult,
        ) -> TextTranslationResult:
            metadata = dict(result.metadata) if result.metadata else {}
            metadata.setdefault("backend", "copilot")
            metadata["copilot_call_count"] = telemetry_translate_single_calls
            metadata["copilot_call_phases"] = list(telemetry_translate_single_phases)
            metadata["text_style_comparison_telemetry"] = {
                "translate_single_calls": telemetry_translate_single_calls,
                "translate_single_seconds_total": telemetry_translate_single_seconds_total,
                "translate_single_phases": telemetry_translate_single_phases,
                "translate_single_phase_counts": telemetry_translate_single_phase_counts,
                "translate_single_phase_seconds": telemetry_translate_single_phase_seconds,
                "output_language_retry_calls": telemetry_output_language_retry_calls,
                "numeric_rule_retry_calls": telemetry_numeric_rule_retry_calls,
                "numeric_rule_retry_failed": telemetry_numeric_rule_retry_failed,
                "fill_missing_styles_calls": telemetry_fill_missing_styles_calls,
                "fill_missing_styles_styles": telemetry_fill_missing_styles_styles,
                "style_diff_guard_calls": telemetry_style_diff_guard_calls,
                "style_diff_guard_styles": telemetry_style_diff_guard_styles,
                "combined_attempted": telemetry_combined_attempted,
                "combined_succeeded": telemetry_combined_succeeded,
                "per_style_used": telemetry_per_style_used,
            }
            result.metadata = metadata
            return result

        def apply_style_diff_guard(
            result: TextTranslationResult,
        ) -> TextTranslationResult:
            nonlocal telemetry_style_diff_guard_calls

            if result.output_language != "en":
                return result
            if not result.options:
                return result
            # Speed: avoid extra Copilot rewrite when we already needed additional calls
            # (fill missing styles / output language retry / numeric retry / per-style).
            if telemetry_translate_single_calls > 1:
                return result

            options_by_style: dict[str, TranslationOption] = {}
            for option in result.options:
                style = (option.style or "").strip().lower()
                if style and style not in options_by_style:
                    options_by_style[style] = option

            concise_option = options_by_style.get("concise")
            minimal_option = options_by_style.get("minimal")
            if concise_option is None or minimal_option is None:
                return result

            base_text = concise_option.text
            if not _should_rewrite_compact_style(
                base_text=base_text,
                compact_text=minimal_option.text,
            ):
                return result

            telemetry_style_diff_guard_calls += 1
            if "minimal" not in telemetry_style_diff_guard_styles:
                telemetry_style_diff_guard_styles.append("minimal")

            rewrite_prompt = _build_style_diff_rewrite_prompt(base_text, ["minimal"])
            rewrite_raw = translate_single_timed(
                "style_diff_guard_rewrite",
                base_text,
                rewrite_prompt,
                None,
                None,
            )
            rewritten = self._parse_style_comparison_result(rewrite_raw)
            for option in rewritten:
                if option.style != "minimal":
                    continue
                if option.text and not _is_text_output_language_mismatch(
                    option.text, "en"
                ):
                    minimal_option.text = option.text
                    minimal_option.explanation = ""
                break

            return result

        def apply_numeric_unit_correction(
            result: TextTranslationResult,
        ) -> TextTranslationResult:
            if result.output_language != "en":
                return result
            if not result.options:
                return result

            corrected_styles: list[str] = []
            for option in result.options:
                fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                    source_text=text,
                    translated_text=option.text,
                )
                if not fixed:
                    continue
                option.text = fixed_text
                option.explanation = ""
                if option.style:
                    corrected_styles.append(option.style)

            if corrected_styles:
                metadata = dict(result.metadata) if result.metadata else {}
                metadata.setdefault("backend", "copilot")
                metadata["to_en_numeric_unit_correction"] = True
                metadata["to_en_numeric_unit_correction_styles"] = corrected_styles
                result.metadata = metadata

            return result

        combined_error: Optional[str] = None
        wants_combined = (
            set(style_list) == set(TEXT_STYLE_ORDER) and len(style_list) > 1
        )

        if wants_combined:
            template = self.prompt_builder.get_text_compare_template()
            if template:
                try:
                    self._cancel_event.clear()
                    telemetry_combined_attempted = True

                    if reference_files:
                        reference_section = REFERENCE_INSTRUCTION
                        files_to_attach = reference_files
                    else:
                        reference_section = ""
                        files_to_attach = None

                    self.prompt_builder.reload_translation_rules_if_needed()
                    translation_rules = self.prompt_builder.get_translation_rules(
                        output_language
                    )
                    numeric_hints = _build_to_en_numeric_hints(text)

                    def build_compare_prompt(
                        extra_instruction: Optional[str] = None,
                    ) -> str:
                        prompt = template.replace(
                            "{translation_rules}", translation_rules
                        )
                        prompt = prompt.replace(
                            "{reference_section}", reference_section
                        )
                        prompt = prompt.replace("{input_text}", text)
                        extra_parts: list[str] = []
                        if extra_instruction:
                            extra_parts.append(extra_instruction.strip())
                        if numeric_hints:
                            extra_parts.append(numeric_hints.strip())
                        if extra_parts:
                            prompt = _insert_extra_instruction(
                                prompt, "\n\n".join(extra_parts)
                            )
                        return prompt

                    def fill_missing_styles(
                        base_options: dict[str, TranslationOption],
                        missing_styles: list[str],
                    ) -> None:
                        nonlocal telemetry_fill_missing_styles_calls
                        if not missing_styles:
                            return

                        telemetry_fill_missing_styles_calls += 1
                        for missing_style in missing_styles:
                            if (
                                missing_style
                                not in telemetry_fill_missing_styles_styles
                            ):
                                telemetry_fill_missing_styles_styles.append(
                                    missing_style
                                )

                        missing_labels = ", ".join(
                            f"[{style}]" for style in missing_styles
                        )
                        fill_instruction = (
                            "CRITICAL: The previous response was missing some style sections.\n"
                            f"Return ONLY the missing style sections: {missing_labels}\n"
                            "Keep the exact output format for each section:\n"
                            "[style]\nTranslation:\n<text>\n"
                            "Do not output any other style sections. Do not include explanations/notes."
                        )
                        fill_prompt = build_compare_prompt(fill_instruction)
                        fill_raw_result = translate_single_timed(
                            "fill_missing_styles",
                            text,
                            fill_prompt,
                            files_to_attach,
                            None,
                        )
                        fill_parsed_options = self._parse_style_comparison_result(
                            fill_raw_result
                        )
                        if not fill_parsed_options:
                            return

                        for option in fill_parsed_options:
                            style = option.style
                            if (
                                style
                                and style in missing_styles
                                and style not in base_options
                                and not _is_text_output_language_mismatch(
                                    option.text, "en"
                                )
                            ):
                                base_options[style] = option

                    prompt = build_compare_prompt()

                    logger.debug(
                        "Sending text to Copilot for style comparison (refs=%d)",
                        len(files_to_attach) if files_to_attach else 0,
                    )
                    raw_result = translate_single_timed(
                        "style_compare",
                        text,
                        prompt,
                        files_to_attach,
                        copilot_on_chunk,
                    )
                    parsed_options = self._parse_style_comparison_result(raw_result)
                    did_output_language_retry = False
                    needs_numeric_rule_retry = bool(parsed_options) and any(
                        _needs_to_en_numeric_rule_retry_copilot_after_auto_fix(
                            text, option.text
                        )
                        for option in parsed_options
                    )
                    if parsed_options and any(
                        _is_text_output_language_mismatch(option.text, "en")
                        for option in parsed_options
                    ):
                        did_output_language_retry = True
                        telemetry_output_language_retry_calls += 1
                        retry_parts = [_TEXT_TO_EN_OUTPUT_LANGUAGE_RETRY_INSTRUCTION]
                        if needs_numeric_rule_retry:
                            telemetry_numeric_rule_retry_calls += 1
                            retry_parts.append(_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION)
                        retry_prompt = build_compare_prompt("\n".join(retry_parts))
                        retry_raw_result = translate_single_timed(
                            "style_compare_output_language_retry",
                            text,
                            retry_prompt,
                            files_to_attach,
                            None,
                        )
                        retry_parsed_options = self._parse_style_comparison_result(
                            retry_raw_result
                        )
                        if retry_parsed_options and not any(
                            _is_text_output_language_mismatch(option.text, "en")
                            for option in retry_parsed_options
                        ):
                            parsed_options = retry_parsed_options
                            raw_result = retry_raw_result
                            if needs_numeric_rule_retry and any(
                                _needs_to_en_numeric_rule_retry_copilot_after_auto_fix(
                                    text, option.text
                                )
                                for option in retry_parsed_options
                            ):
                                telemetry_numeric_rule_retry_failed = True
                        else:
                            parsed_options = []
                            combined_error = (
                                combined_error
                                or "Style comparison output language mismatch"
                            )
                    if (
                        parsed_options
                        and not did_output_language_retry
                        and needs_numeric_rule_retry
                    ):
                        telemetry_numeric_rule_retry_calls += 1
                        retry_prompt = build_compare_prompt(
                            _TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION
                        )
                        retry_raw_result = translate_single_timed(
                            "style_compare_numeric_rule_retry",
                            text,
                            retry_prompt,
                            files_to_attach,
                            None,
                        )
                        retry_parsed_options = self._parse_style_comparison_result(
                            retry_raw_result
                        )
                        if (
                            retry_parsed_options
                            and not any(
                                _is_text_output_language_mismatch(option.text, "en")
                                for option in retry_parsed_options
                            )
                            and not any(
                                _needs_to_en_numeric_rule_retry_copilot_after_auto_fix(
                                    text, option.text
                                )
                                for option in retry_parsed_options
                            )
                        ):
                            parsed_options = retry_parsed_options
                            raw_result = retry_raw_result
                        else:
                            telemetry_numeric_rule_retry_failed = True

                    if not parsed_options:
                        parsed_single = self._parse_single_translation_result(
                            raw_result
                        )
                        if parsed_single:
                            option = parsed_single[0]
                            if _is_text_output_language_mismatch(option.text, "en"):
                                telemetry_output_language_retry_calls += 1
                                retry_prompt = build_compare_prompt(
                                    _TEXT_TO_EN_OUTPUT_LANGUAGE_RETRY_INSTRUCTION
                                )
                                retry_raw_result = translate_single_timed(
                                    "style_compare_output_language_retry",
                                    text,
                                    retry_prompt,
                                    files_to_attach,
                                    None,
                                )
                                retry_parsed_options = (
                                    self._parse_style_comparison_result(
                                        retry_raw_result
                                    )
                                )
                                if retry_parsed_options:
                                    base_options: dict[str, TranslationOption] = {}
                                    for retry_option in retry_parsed_options:
                                        if (
                                            retry_option.style
                                            and retry_option.style not in base_options
                                        ):
                                            base_options[retry_option.style] = (
                                                retry_option
                                            )

                                    missing_styles = [
                                        s for s in style_list if s not in base_options
                                    ]
                                    if missing_styles:
                                        logger.warning(
                                            "Style comparison missing styles: %s",
                                            ", ".join(missing_styles),
                                        )
                                        fill_missing_styles(
                                            base_options, missing_styles
                                        )
                                        missing_styles = [
                                            s
                                            for s in style_list
                                            if s not in base_options
                                        ]
                                        if missing_styles:
                                            logger.warning(
                                                "Style comparison still missing styles after fill: %s",
                                                ", ".join(missing_styles),
                                            )

                                    ordered_options = [
                                        base_options[s]
                                        for s in style_list
                                        if s in base_options
                                    ]
                                    if ordered_options and not any(
                                        _is_text_output_language_mismatch(
                                            option.text, "en"
                                        )
                                        for option in ordered_options
                                    ):
                                        result = TextTranslationResult(
                                            source_text=text,
                                            source_char_count=len(text),
                                            options=ordered_options,
                                            output_language=output_language,
                                            detected_language=detected_language,
                                        )
                                        telemetry_combined_succeeded = True
                                        result = ensure_style_options(result)
                                        result = apply_style_diff_guard(result)
                                        result = apply_numeric_unit_correction(result)
                                        return attach_style_comparison_telemetry(result)
                                    if ordered_options:
                                        combined_error = (
                                            combined_error
                                            or "Style comparison output language mismatch"
                                        )

                                retry_single = self._parse_single_translation_result(
                                    retry_raw_result
                                )
                                if retry_single:
                                    option = retry_single[0]
                            option.style = DEFAULT_TEXT_STYLE
                            if _is_text_output_language_mismatch(option.text, "en"):
                                combined_error = (
                                    combined_error
                                    or "Style comparison output language mismatch"
                                )
                            else:
                                result = TextTranslationResult(
                                    source_text=text,
                                    source_char_count=len(text),
                                    options=[option],
                                    output_language=output_language,
                                    detected_language=detected_language,
                                )
                                telemetry_combined_succeeded = True
                                result = ensure_style_options(result)
                                result = apply_style_diff_guard(result)
                                result = apply_numeric_unit_correction(result)
                                return attach_style_comparison_telemetry(result)
                        combined_error = (
                            combined_error or "Failed to parse style comparison result"
                        )
                    else:
                        base_options: dict[str, TranslationOption] = {}
                        for option in parsed_options:
                            if option.style and option.style not in base_options:
                                base_options[option.style] = option

                        missing_styles = [
                            s for s in style_list if s not in base_options
                        ]
                        if missing_styles:
                            logger.warning(
                                "Style comparison missing styles: %s",
                                ", ".join(missing_styles),
                            )
                            fill_missing_styles(base_options, missing_styles)
                            missing_styles = [
                                s for s in style_list if s not in base_options
                            ]
                            if missing_styles:
                                logger.warning(
                                    "Style comparison still missing styles after fill: %s",
                                    ", ".join(missing_styles),
                                )

                        ordered_options = [
                            base_options[s] for s in style_list if s in base_options
                        ]
                        if ordered_options and not any(
                            _is_text_output_language_mismatch(option.text, "en")
                            for option in ordered_options
                        ):
                            result = TextTranslationResult(
                                source_text=text,
                                source_char_count=len(text),
                                options=ordered_options,
                                output_language=output_language,
                                detected_language=detected_language,
                            )
                            telemetry_combined_succeeded = True
                            result = ensure_style_options(result)
                            result = apply_style_diff_guard(result)
                            result = apply_numeric_unit_correction(result)
                            return attach_style_comparison_telemetry(result)
                        if ordered_options:
                            combined_error = (
                                combined_error
                                or "Style comparison output language mismatch"
                            )

                        combined_error = (
                            combined_error or "Failed to parse style comparison result"
                        )
                except TranslationCancelledError:
                    logger.info("Style comparison translation cancelled")
                    return attach_style_comparison_telemetry(
                        TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message="翻訳がキャンセルされました",
                        )
                    )
                except OSError as e:
                    logger.warning("File I/O error during style comparison: %s", e)
                    combined_error = str(e)
                except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
                    logger.exception("Error during style comparison translation: %s", e)
                    combined_error = str(e)
            else:
                combined_error = "Missing style comparison template"

        options: list[TranslationOption] = []
        last_error: Optional[str] = combined_error

        telemetry_per_style_used = True
        with self._ui_window_sync_scope("translate_text_with_style_comparison"):
            for style in style_list:
                try:
                    style_phase = f"per_style:{style}"

                    def translate_single_for_style(
                        source_text: str,
                        prompt: str,
                        reference_files: Optional[list[Path]] = None,
                        on_chunk: "Callable[[str], None] | None" = None,
                        _phase: str = style_phase,
                    ) -> str:
                        return translate_single_timed(
                            _phase, source_text, prompt, reference_files, on_chunk
                        )

                    result = self._translate_text_with_options_on_copilot(
                        text=text,
                        reference_files=reference_files,
                        style=style,
                        detected_language=detected_language,
                        output_language=output_language,
                        on_chunk=copilot_on_chunk,
                        translate_single=translate_single_for_style,
                    )
                except TranslationCancelledError:
                    logger.info("Text translation with options cancelled")
                    result = TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳がキャンセルされました",
                    )
                except OSError as e:
                    logger.warning("File I/O error during translation: %s", e)
                    result = TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message=str(e),
                    )
                except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
                    logger.exception(
                        "Error during text translation with options: %s", e
                    )
                    result = TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message=str(e),
                    )
                if result.options:
                    for option in result.options:
                        if option.style is None:
                            option.style = style
                    options.extend(result.options)
                else:
                    last_error = result.error_message or last_error

        if options:
            result = TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                options=options,
                output_language=output_language,
                detected_language=detected_language,
            )
            result = ensure_style_options(result)
            result = apply_style_diff_guard(result)
            result = apply_numeric_unit_correction(result)
            return attach_style_comparison_telemetry(result)

        return attach_style_comparison_telemetry(
            TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language=output_language,
                detected_language=detected_language,
                error_message=last_error or "Unknown error",
            )
        )

    def extract_detection_sample(
        self, file_path: Path, max_blocks: int = 5
    ) -> Optional[str]:
        """Extract a lightweight text sample for language detection.

        Uses fast extraction methods that parse XML/binary directly from archives,
        avoiding the overhead of loading full documents with openpyxl/python-docx/etc.

        Args:
            file_path: File to inspect.
            max_blocks: Maximum number of text blocks to sample (used for fallback).

        Returns:
            Concatenated sample text (up to 500 chars) or None if nothing
            is readable.
        """
        processor = self._get_processor(file_path)

        # Try fast extraction path for all file types
        if hasattr(processor, "extract_sample_text_fast"):
            sample = processor.extract_sample_text_fast(file_path)
            if sample:
                logger.debug(
                    "%s language detection: fast extraction returned %d chars",
                    processor.file_type.value,
                    len(sample),
                )
                return sample
            # Fallback to standard extraction if fast path fails
            logger.debug(
                "%s language detection: fast path returned None, falling back to standard extraction",
                processor.file_type.value,
            )

        # Standard extraction fallback (for .xls, .doc, .ppt legacy formats or when fast path fails)
        # Use islice to stop extraction early after max_blocks (avoids loading entire document)
        # First pass: JP→EN extraction (default)
        blocks = list(
            islice(
                processor.extract_text_blocks(file_path, output_language="en"),
                max_blocks,
            )
        )

        # Retry with EN→JP extraction to capture English/Chinese-only files
        if not blocks:
            blocks = list(
                islice(
                    processor.extract_text_blocks(file_path, output_language="jp"),
                    max_blocks,
                )
            )

        if not blocks:
            return None

        return " ".join(block.text for block in blocks)[:500]

    def adjust_translation(
        self,
        text: str,
        adjust_type: str,
        source_text: Optional[str] = None,
        current_style: Optional[str] = None,
        reference_files: Optional[list[Path]] = None,
    ) -> Optional[TranslationOption]:
        """
        Adjust a translation based on user request.

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'detailed', 'alternatives', or custom instruction
                - 'shorter': Re-translate one step shorter (standard→concise→minimal)
                - 'detailed': Re-translate one step more detailed (minimal→concise→standard)
                - 'alternatives': Get alternative in same style
            source_text: Original source text (required for style changes and alternatives)
            current_style: Current translation style (for relative adjustment)
                           If None, uses DEFAULT_TEXT_STYLE
            reference_files: Optional list of reference file paths (glossary, style guide, etc.)

        Returns:
            TranslationOption with adjusted text, or None on failure (including at style limit)
        """
        # Style order: minimal < concise < standard
        STYLE_ORDER = ["minimal", "concise", "standard"]
        self._cancel_event.clear()

        try:
            # Determine current style (fallback to DEFAULT_TEXT_STYLE)
            if current_style is None:
                current_style = DEFAULT_TEXT_STYLE

            # Handle style-based adjustments (relative change)
            if adjust_type == "shorter" and source_text:
                # Get one step shorter style
                try:
                    current_idx = STYLE_ORDER.index(current_style)
                except ValueError:
                    current_idx = 1  # Default to concise if unknown
                if current_idx <= 0:
                    # Already at minimum - return None to indicate no change possible
                    logger.info("Already at minimal style, cannot go shorter")
                    return None
                new_style = STYLE_ORDER[current_idx - 1]
                result = self.translate_text_with_options(
                    source_text, reference_files, style=new_style
                )
                if result.options:
                    return result.options[0]
                return None

            if adjust_type == "detailed" and source_text:
                # Get one step more detailed style
                try:
                    current_idx = STYLE_ORDER.index(current_style)
                except ValueError:
                    current_idx = 1  # Default to concise if unknown
                if current_idx >= len(STYLE_ORDER) - 1:
                    # Already at maximum - return None to indicate no change possible
                    logger.info("Already at standard style, cannot go more detailed")
                    return None
                new_style = STYLE_ORDER[current_idx + 1]
                result = self.translate_text_with_options(
                    source_text, reference_files, style=new_style
                )
                if result.options:
                    return result.options[0]
                return None

            if adjust_type == "alternatives" and source_text:
                # Get alternative in same style
                return self._get_alternative_translation(
                    text, source_text, current_style, reference_files
                )

            # Custom instructions - use adjust_custom.txt with full context
            prompt_file = "adjust_custom.txt"
            prompt_path = (
                self.prompt_builder.prompts_dir / prompt_file
                if self.prompt_builder.prompts_dir
                else None
            )

            if prompt_path and prompt_path.exists():
                template = prompt_path.read_text(encoding="utf-8")
            else:
                # Simple fallback with full context
                template = """以下のリクエストに対応してください。

リクエスト: {user_instruction}

原文:
{source_text}

翻訳結果:
{input_text}

出力:
- 調整結果（本文）のみ（ラベル/解説/見出しは出力しない）。"""

            # Build prompt with full context (original text + translation)
            # Reload translation rules to pick up any user edits
            output_language = "en"
            if source_text:
                output_language = (
                    "en" if self.detect_language(source_text) == "日本語" else "jp"
                )
            elif text:
                output_language = (
                    "jp" if self.detect_language(text) == "日本語" else "en"
                )
            self.prompt_builder.reload_translation_rules_if_needed()
            translation_rules = self.prompt_builder.get_translation_rules(
                output_language
            )
            reference_section = (
                self.prompt_builder.build_reference_section(reference_files)
                if reference_files
                else ""
            )

            prompt = template.replace("{translation_rules}", translation_rules)
            prompt = prompt.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{user_instruction}", adjust_type)
            prompt = prompt.replace("{source_text}", source_text if source_text else "")
            prompt = prompt.replace("{input_text}", text)

            # Get adjusted translation
            raw_result = self._translate_single_with_cancel(
                text, prompt, reference_files
            )

            # Parse the result
            option = self._parse_single_option_result(raw_result)

            return option

        except TranslationCancelledError:
            logger.info("Translation adjustment cancelled")
            return None
        except OSError as e:
            logger.warning("File I/O error during translation adjustment: %s", e)
            return None
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during translation adjustment: %s", e)
            return None

    def _get_alternative_translation(
        self,
        current_translation: str,
        source_text: str,
        current_style: Optional[str] = None,
        reference_files: Optional[list[Path]] = None,
    ) -> Optional[TranslationOption]:
        """
        Get an alternative translation in the same style.

        Args:
            current_translation: The current translation to get alternative for
            source_text: Original source text
            current_style: Current translation style (if None, uses DEFAULT_TEXT_STYLE)
            reference_files: Optional list of reference file paths (glossary, style guide, etc.)

        Returns:
            TranslationOption with alternative translation, or None on failure
        """
        try:
            # Use provided style or fallback to DEFAULT_TEXT_STYLE
            style = current_style if current_style else (DEFAULT_TEXT_STYLE)

            # Load alternatives prompt
            prompt_file = "text_alternatives.txt"
            prompt_path = (
                self.prompt_builder.prompts_dir / prompt_file
                if self.prompt_builder.prompts_dir
                else None
            )

            if prompt_path and prompt_path.exists():
                template = prompt_path.read_text(encoding="utf-8")
            else:
                # Fallback template
                template = """以下の翻訳に対して、同じスタイルで別の言い方を提案してください。

現在の翻訳: {current_translation}
元の日本語: {source_text}
スタイル: {style}

出力:
- 別表現（本文）のみ（ラベル/解説/見出しは出力しない）。
{reference_section}"""

            # Build prompt
            # Reload translation rules to pick up any user edits
            output_language = "en"
            if source_text:
                output_language = (
                    "en" if self.detect_language(source_text) == "日本語" else "jp"
                )
            elif current_translation:
                output_language = (
                    "jp"
                    if self.detect_language(current_translation) == "日本語"
                    else "en"
                )
            self.prompt_builder.reload_translation_rules_if_needed()
            translation_rules = self.prompt_builder.get_translation_rules(
                output_language
            )
            reference_section = (
                self.prompt_builder.build_reference_section(reference_files)
                if reference_files
                else ""
            )

            prompt = template.replace("{translation_rules}", translation_rules)
            prompt = prompt.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{current_translation}", current_translation)
            prompt = prompt.replace("{source_text}", source_text)
            prompt = prompt.replace("{style}", style)

            # Get alternative translation
            raw_result = self._translate_single_with_cancel(
                source_text, prompt, reference_files
            )

            # Parse the result and set style
            option = self._parse_single_option_result(raw_result)
            if option:
                option.style = style
            return option

        except TranslationCancelledError:
            logger.info("Alternative translation cancelled")
            return None
        except OSError as e:
            logger.warning("File I/O error during alternative translation: %s", e)
            return None
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            logger.exception("Error during alternative translation: %s", e)
            return None

    def _parse_multi_option_result(self, raw_result: str) -> list[TranslationOption]:
        """Parse multi-option result from Copilot (for →en translation)."""
        options = []
        raw_result = _strip_input_markers(raw_result)

        # Use pre-compiled pattern for [1], [2], [3] sections
        matches = _RE_MULTI_OPTION.findall(raw_result)

        for num, text, explanation in matches:
            text = text.strip()
            explanation = explanation.strip()
            text = _strip_input_markers(text)
            explanation = _strip_input_markers(explanation)
            if text:
                options.append(
                    TranslationOption(
                        text=text,
                        explanation=explanation,
                    )
                )

        return options

    def _parse_style_comparison_result(
        self, raw_result: str
    ) -> list[TranslationOption]:
        """Parse a compare template result and return a single minimal option.

        Compatibility: accepts [standard]/[concise] headers, but always returns
        exactly one option with style="minimal".
        """
        matches = list(_RE_STYLE_SECTION.finditer(raw_result))
        if not matches:
            return []

        parsed_by_style: dict[str, TranslationOption] = {}
        for index, match in enumerate(matches):
            style = match.group(1).lower()
            start = match.end()
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(raw_result)
            )
            section = raw_result[start:end].strip()
            if not section:
                continue

            parsed = self._parse_single_translation_result(section)
            if not parsed:
                continue

            option = parsed[0]
            option.style = style
            option.explanation = ""
            parsed_by_style.setdefault(style, option)

        if not parsed_by_style:
            return []

        chosen = (
            parsed_by_style.get("minimal")
            or parsed_by_style.get("concise")
            or parsed_by_style.get("standard")
            or next(iter(parsed_by_style.values()))
        )
        chosen.style = "minimal"
        return [chosen]

    def _parse_single_translation_result(
        self, raw_result: str
    ) -> list[TranslationOption]:
        """Parse single translation result from Copilot (for →jp translation)."""
        raw_result = _strip_input_markers(raw_result).strip()
        if not raw_result:
            return []

        text_match = _RE_TRANSLATION_TEXT.search(raw_result)
        explanation_match = _RE_EXPLANATION.search(raw_result)

        if text_match:
            text = text_match.group(1).strip()
        elif explanation_match:
            text = raw_result[: explanation_match.start()].strip() or raw_result
        else:
            text = raw_result

        text = _RE_MARKDOWN_SEPARATOR.sub("", text).strip()
        text = _RE_TRANSLATION_LABEL.sub("", text).strip()
        text = _strip_input_markers(text)

        if text:
            return [TranslationOption(text=text, explanation="")]

        return []

    def _parse_single_option_result(
        self, raw_result: str
    ) -> Optional[TranslationOption]:
        """Parse single option result from adjustment (text-only)."""
        raw_result = _strip_input_markers(raw_result).strip()

        text_match = _RE_TRANSLATION_TEXT.search(raw_result)
        explanation_match = _RE_EXPLANATION.search(raw_result)

        if text_match:
            text = text_match.group(1).strip()
        elif explanation_match:
            text = raw_result[: explanation_match.start()].strip() or raw_result.strip()
        else:
            text = raw_result.strip()

        text = _RE_TRANSLATION_LABEL.sub("", text).strip()
        text = _strip_input_markers(text)

        if text:
            return TranslationOption(text=text, explanation="")

        return None

    def _filter_blocks_by_section(
        self,
        blocks: list[TextBlock],
        selected_sections: Optional[list[int]] = None,
    ) -> list[TextBlock]:
        """
        Filter text blocks to include only those from selected sections.

        Args:
            blocks: List of text blocks to filter
            selected_sections: List of section indices to include

        Returns:
            Filtered list of text blocks
        """
        if selected_sections is None:
            return blocks

        filtered = []
        for block in blocks:
            section_idx = self._get_block_section_index(block)
            if section_idx is None or section_idx in selected_sections:
                filtered.append(block)

        return filtered

    @staticmethod
    def _get_block_section_index(block: TextBlock) -> Optional[int]:
        metadata = block.metadata or {}
        for key in ("section_idx", "sheet_idx", "slide_idx", "page_idx"):
            value = metadata.get(key)
            if isinstance(value, int):
                return value
        return None

    def _summarize_batch_issues(
        self,
        blocks: list[TextBlock],
        issue_ids: list[str],
        limit: int = 24,
    ) -> tuple[list[str], dict[int, int]]:
        if not issue_ids:
            return [], {}

        issue_id_set = set(issue_ids)
        issue_locations: list[str] = []
        issue_section_counts: dict[int, int] = {}
        seen_locations = set()

        for block in blocks:
            if block.id not in issue_id_set:
                continue
            if block.location and block.location not in seen_locations:
                issue_locations.append(block.location)
                seen_locations.add(block.location)
            section_idx = self._get_block_section_index(block)
            if section_idx is not None:
                issue_section_counts[section_idx] = (
                    issue_section_counts.get(section_idx, 0) + 1
                )

        if limit and len(issue_locations) > limit:
            issue_locations = issue_locations[:limit]

        return issue_locations, issue_section_counts

    def translate_file(
        self,
        input_path: Path,
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
        selected_sections: Optional[list[int]] = None,
    ) -> TranslationResult:
        """
        Translate a file to specified output language.

        Args:
            input_path: Path to input file
            reference_files: Reference files to attach
            on_progress: Callback for progress updates
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output
            selected_sections: List of section indices to translate (None = all sections)

        Returns:
            TranslationResult with output_path
        """
        start_time = time.monotonic()
        self._cancel_event.clear()  # Reset cancellation at start

        # Reset PDF processor cancellation flag if applicable
        pdf_processor = self.processors.get(".pdf")
        if pdf_processor and hasattr(pdf_processor, "reset_cancel"):
            pdf_processor.reset_cancel()

        try:
            # Get processor
            processor = self._get_processor(input_path)

            # Use streaming processing for PDF files
            if input_path.suffix.lower() == ".pdf":
                with self._ui_window_sync_scope(f"translate_file:{input_path.name}"):
                    return self._translate_pdf_streaming(
                        input_path,
                        processor,
                        reference_files,
                        on_progress,
                        output_language,
                        start_time,
                        translation_style,
                        selected_sections,
                    )

            # Standard processing for other file types
            with self._ui_window_sync_scope(f"translate_file:{input_path.name}"):
                return self._translate_file_standard(
                    input_path,
                    processor,
                    reference_files,
                    on_progress,
                    output_language,
                    start_time,
                    translation_style,
                    selected_sections,
                )

        except MemoryError:
            # CRITICAL: Memory exhausted - provide clear error message
            logger.critical(
                "CRITICAL: Out of memory during file translation. "
                "For PDF files, try reducing DPI or processing fewer pages. "
                "For large files, consider splitting into smaller chunks."
            )
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=(
                    "メモリ不足エラーが発生しました。"
                    "PDFファイルの場合はDPIを下げるか、ページ数を減らしてください。"
                    "大きなファイルは分割して処理することをお勧めします。"
                ),
                duration_seconds=time.monotonic() - start_time,
            )

        except (
            OSError,
            RuntimeError,
            ValueError,
            ConnectionError,
            TimeoutError,
            BadZipFile,
            ImportError,
        ) as e:
            # Catch specific exceptions for graceful error handling
            logger.exception("Translation failed: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.monotonic() - start_time,
            )

    def _translate_file_standard(
        self,
        input_path: Path,
        processor: FileProcessor,
        reference_files: Optional[list[Path]],
        on_progress: Optional[ProgressCallback],
        output_language: str,
        start_time: float,
        translation_style: str = "concise",
        selected_sections: Optional[list[int]] = None,
    ) -> TranslationResult:
        """Standard translation flow for non-PDF files."""
        # Report progress
        if on_progress:
            on_progress(
                TranslationProgress(
                    current=0,
                    total=100,
                    status="Extracting text...",
                    phase=TranslationPhase.EXTRACTING,
                    phase_current=1,
                    phase_total=1,
                )
            )

        # Extract text blocks
        #
        # Excel: selected_sections が指定されている場合は、抽出段階から対象シートのみ処理する。
        # (従来は全シート抽出→後段でフィルタしており、抽出時間が無駄に伸びるケースがあった)
        if selected_sections is not None and processor.file_type == FileType.EXCEL:
            blocks = list(
                processor.extract_text_blocks(
                    input_path,
                    output_language,
                    selected_sections=selected_sections,
                )
            )
        else:
            blocks = list(processor.extract_text_blocks(input_path, output_language))

        # Filter blocks by selected sections if specified
        if selected_sections is not None:
            blocks = self._filter_blocks_by_section(blocks, selected_sections)

        total_blocks = len(blocks)

        if total_blocks == 0:
            warnings = ["No translatable text found in file"]
            warnings.extend(self._collect_processor_warnings(processor))
            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=input_path,
                blocks_translated=0,
                blocks_total=0,
                duration_seconds=time.monotonic() - start_time,
                warnings=warnings,
            )

        # Check for cancellation (thread-safe)
        if self._cancel_event.is_set():
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                duration_seconds=time.monotonic() - start_time,
            )

        # Report progress
        if on_progress:
            on_progress(
                TranslationProgress(
                    current=10,
                    total=100,
                    status=f"Translating {total_blocks} blocks...",
                    phase=TranslationPhase.TRANSLATING,
                )
            )

        # Excel cells often contain numbered lines; keep stable IDs to avoid list parsing drift.
        include_item_ids = processor.file_type == FileType.EXCEL

        translation_styles = (
            ["minimal"] if output_language == "en" else [translation_style]
        )
        primary_style = translation_styles[0]

        style_labels = {
            "minimal": "最簡潔",
        }

        batch_translator = self._get_active_batch_translator()
        batch_limit, batch_limit_source = self._get_local_file_batch_limit_info()

        translations_by_style: dict[str, dict[str, str]] = {}
        primary_batch_result = None

        translate_start = 10
        translate_end = 90
        translate_span = translate_end - translate_start
        style_total = max(1, len(translation_styles))

        for style_idx, style_key in enumerate(translation_styles):
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )

            seg_start = translate_start + int(translate_span * style_idx / style_total)
            seg_end = translate_start + int(
                translate_span * (style_idx + 1) / style_total
            )
            if seg_end <= seg_start:
                seg_end = seg_start + 1

            def batch_progress(
                progress: TranslationProgress,
                _seg_start: int = seg_start,
                _seg_end: int = seg_end,
                _style_label: str = style_labels.get(style_key, style_key),
            ):
                if on_progress:
                    on_progress(
                        scale_progress(
                            progress,
                            _seg_start,
                            _seg_end,
                            TranslationPhase.TRANSLATING,
                            phase_detail=f"{_style_label} {progress.current}/{progress.total}",
                        )
                    )

            batch_result = batch_translator.translate_blocks_with_result(
                blocks,
                reference_files,
                batch_progress if on_progress else None,
                output_language=output_language,
                translation_style=style_key,
                include_item_ids=include_item_ids,
                _max_chars_per_batch=batch_limit,
                _max_chars_per_batch_source=batch_limit_source,
            )

            if batch_result.cancelled or self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )

            translations_by_style[style_key] = batch_result.translations
            if style_key == primary_style:
                primary_batch_result = batch_result

        if primary_batch_result is None:
            primary_style = translation_styles[0]
            primary_batch_result = batch_result

        primary_translations = translations_by_style.get(primary_style, {})
        issue_locations, issue_section_counts = self._summarize_batch_issues(
            blocks, primary_batch_result.untranslated_block_ids
        )

        output_path = self._generate_output_path(input_path)
        extra_output_files: list[tuple[Path, str]] = []
        output_paths_by_style: dict[str, Path] = {primary_style: output_path}
        if output_language == "en":
            for style_key in translation_styles:
                if style_key == primary_style:
                    continue
                style_path = self._generate_style_variant_output_path(
                    output_path, style_key
                )
                output_paths_by_style[style_key] = style_path
                extra_output_files.append(
                    (
                        style_path,
                        f"翻訳ファイル（{style_labels.get(style_key, style_key)}）",
                    )
                )

        direction = "jp_to_en" if output_language == "en" else "en_to_jp"

        apply_total = (
            len(translation_styles)
            + (1 if self.config and self.config.bilingual_output else 0)
            + (1 if self.config and self.config.export_glossary else 0)
        )
        apply_step = 0
        bilingual_path = None
        glossary_path = None

        style_apply_order = [primary_style] + [
            s for s in translation_styles if s != primary_style
        ]
        for style_key in style_apply_order:
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )
            apply_step += 1
            if on_progress:
                progress_current = 90 + int(10 * (apply_step - 1) / max(apply_total, 1))
                style_label = style_labels.get(style_key, style_key)
                on_progress(
                    TranslationProgress(
                        current=progress_current,
                        total=100,
                        status=f"Applying translations ({style_label})...",
                        phase=TranslationPhase.APPLYING,
                        phase_current=apply_step,
                        phase_total=apply_total,
                    )
                )
            processor.apply_translations(
                input_path,
                output_paths_by_style[style_key],
                translations_by_style[style_key],
                direction,
                self.config,
                selected_sections=selected_sections,
                text_blocks=blocks,  # Pass extracted blocks for precise positioning
            )

        # Create bilingual output if enabled (primary style only)
        if self.config and self.config.bilingual_output:
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )
            apply_step += 1
            if on_progress:
                progress_current = 90 + int(10 * (apply_step - 1) / max(apply_total, 1))
                on_progress(
                    TranslationProgress(
                        current=progress_current,
                        total=100,
                        status="Creating bilingual file...",
                        phase=TranslationPhase.APPLYING,
                        phase_detail="Interleaving original and translated content",
                        phase_current=apply_step,
                        phase_total=apply_total,
                    )
                )

            bilingual_path = self._create_bilingual_output(
                input_path, output_path, processor
            )

        # Export glossary CSV if enabled (primary style only)
        if self.config and self.config.export_glossary:
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )
            apply_step += 1
            if on_progress:
                progress_current = 90 + int(10 * (apply_step - 1) / max(apply_total, 1))
                on_progress(
                    TranslationProgress(
                        current=progress_current,
                        total=100,
                        status="Exporting glossary CSV...",
                        phase=TranslationPhase.APPLYING,
                        phase_detail="Creating translation pairs",
                        phase_current=apply_step,
                        phase_total=apply_total,
                    )
                )

            glossary_path = output_path.parent / (
                output_path.stem.replace("_translated", "") + "_glossary.csv"
            )
            self._export_glossary_csv(blocks, primary_translations, glossary_path)

        # Report complete
        if on_progress:
            on_progress(
                TranslationProgress(
                    current=100,
                    total=100,
                    status="Complete",
                    phase=TranslationPhase.COMPLETE,
                )
            )

        warnings = self._collect_processor_warnings(processor)
        if self._use_local_backend() and reference_files:
            self._ensure_local_backend()
            if self._local_prompt_builder is not None:
                embedded_ref = self._local_prompt_builder.build_reference_embed(
                    reference_files
                )
                warnings.extend(embedded_ref.warnings)
        if primary_batch_result.untranslated_block_ids:
            warnings.append(
                f"未翻訳ブロック: {len(primary_batch_result.untranslated_block_ids)}"
            )
        if primary_batch_result.mismatched_batch_count:
            warnings.append(
                f"翻訳件数の不一致: {primary_batch_result.mismatched_batch_count}"
            )

        return TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_path=output_path,
            bilingual_path=bilingual_path,
            glossary_path=glossary_path,
            blocks_translated=len(primary_translations),
            blocks_total=total_blocks,
            duration_seconds=time.monotonic() - start_time,
            warnings=warnings if warnings else [],
            issue_block_ids=primary_batch_result.untranslated_block_ids,
            issue_block_locations=issue_locations,
            issue_section_counts=issue_section_counts,
            mismatched_batch_count=primary_batch_result.mismatched_batch_count,
            extra_output_files=extra_output_files,
        )

    def _translate_pdf_streaming(
        self,
        input_path: Path,
        processor: "PdfProcessor",
        reference_files: Optional[list[Path]],
        on_progress: Optional[ProgressCallback],
        output_language: str,
        start_time: float,
        translation_style: str = "concise",
        selected_sections: Optional[list[int]] = None,
    ) -> TranslationResult:
        """
        Streaming translation for PDF files.

        Uses hybrid approach: pdfminer for text + yomitoku for layout.
        Processes pages incrementally:
        1. Extract text (pdfminer) + analyze layout (yomitoku)
        2. Translate page blocks
        3. Repeat for all pages
        4. Apply all translations

        This provides better progress feedback for large PDFs.
        """
        # Get page count for progress estimation
        total_pages = processor.get_page_count(input_path)
        selected_page_indices = None
        selected_pages = None
        pages_for_progress = total_pages

        if selected_sections is not None:
            selected_page_indices = sorted(
                {
                    idx
                    for idx in selected_sections
                    if isinstance(idx, int) and 0 <= idx < total_pages
                }
            )
            selected_pages = [idx + 1 for idx in selected_page_indices]
            pages_for_progress = len(selected_page_indices)

        if on_progress:
            if selected_page_indices is not None:
                status = f"Processing PDF ({pages_for_progress}/{total_pages} pages selected)..."
                phase_detail = f"0/{pages_for_progress} pages"
                phase_total = pages_for_progress
            else:
                status = f"Processing PDF ({total_pages} pages)..."
                phase_detail = f"0/{total_pages} pages"
                phase_total = total_pages
            on_progress(
                TranslationProgress(
                    current=0,
                    total=100,
                    status=status,
                    phase=TranslationPhase.EXTRACTING,
                    phase_detail=phase_detail,
                    phase_current=0,
                    phase_total=phase_total,
                )
            )

        all_blocks = []
        pages_processed = 0

        # Get settings from config (if available)
        batch_size = self.config.ocr_batch_size if self.config else 5
        dpi = self.config.ocr_dpi if self.config else 300
        device = self.config.ocr_device if self.config else "auto"

        # Phase 1: Extract text with streaming progress (0-40%)
        # PDFMathTranslate compliant: page_cells is always None (TranslationCell removed)
        for page_blocks, _ in processor.extract_text_blocks_streaming(
            input_path,
            on_progress=self._make_extraction_progress_callback(
                on_progress, pages_for_progress
            ),
            device=device,
            batch_size=batch_size,
            dpi=dpi,
            output_language=output_language,
            pages=selected_page_indices,
        ):
            all_blocks.extend(page_blocks)
            pages_processed += 1

            # Check for cancellation between pages (thread-safe)
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )

        # Filter blocks by selected sections if specified
        if selected_sections is not None:
            all_blocks = self._filter_blocks_by_section(all_blocks, selected_sections)

        total_blocks = len(all_blocks)

        if total_blocks == 0:
            warnings = ["No translatable text found in PDF"]
            warnings.extend(self._collect_processor_warnings(processor))
            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=input_path,
                blocks_translated=0,
                blocks_total=0,
                duration_seconds=time.monotonic() - start_time,
                warnings=warnings,
            )

        # Phase 2: Translate blocks (40-90%)
        if on_progress:
            on_progress(
                TranslationProgress(
                    current=40,
                    total=100,
                    status=f"Translating {total_blocks} blocks...",
                    phase=TranslationPhase.TRANSLATING,
                )
            )

        translation_styles = (
            ["minimal"] if output_language == "en" else [translation_style]
        )
        primary_style = translation_styles[0]

        style_labels = {
            "minimal": "最簡潔",
        }

        translations_by_style: dict[str, dict[str, str]] = {}
        primary_batch_result = None

        batch_translator = self._get_active_batch_translator()
        batch_limit, batch_limit_source = self._get_local_file_batch_limit_info()

        translate_start = 40
        translate_end = 90
        translate_span = translate_end - translate_start
        style_total = max(1, len(translation_styles))

        for style_idx, style_key in enumerate(translation_styles):
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )

            seg_start = translate_start + int(translate_span * style_idx / style_total)
            seg_end = translate_start + int(
                translate_span * (style_idx + 1) / style_total
            )
            if seg_end <= seg_start:
                seg_end = seg_start + 1

            def batch_progress(
                progress: TranslationProgress,
                _seg_start: int = seg_start,
                _seg_end: int = seg_end,
                _style_label: str = style_labels.get(style_key, style_key),
            ):
                if on_progress:
                    on_progress(
                        scale_progress(
                            progress,
                            _seg_start,
                            _seg_end,
                            TranslationPhase.TRANSLATING,
                            phase_detail=f"{_style_label} {progress.current}/{progress.total}",
                        )
                    )

            batch_result = batch_translator.translate_blocks_with_result(
                all_blocks,
                reference_files,
                batch_progress if on_progress else None,
                output_language=output_language,
                translation_style=style_key,
                include_item_ids=True,
                _max_chars_per_batch=batch_limit,
                _max_chars_per_batch_source=batch_limit_source,
            )

            if batch_result.cancelled or self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )

            translations_by_style[style_key] = batch_result.translations
            if style_key == primary_style:
                primary_batch_result = batch_result

        if primary_batch_result is None:
            primary_style = translation_styles[0]
            primary_batch_result = batch_result

        primary_translations = translations_by_style.get(primary_style, {})
        issue_locations, issue_section_counts = self._summarize_batch_issues(
            all_blocks, primary_batch_result.untranslated_block_ids
        )

        output_path = self._generate_output_path(input_path)
        extra_output_files: list[tuple[Path, str]] = []
        output_paths_by_style: dict[str, Path] = {primary_style: output_path}
        if output_language == "en":
            for style_key in translation_styles:
                if style_key == primary_style:
                    continue
                style_path = self._generate_style_variant_output_path(
                    output_path, style_key
                )
                output_paths_by_style[style_key] = style_path
                extra_output_files.append(
                    (
                        style_path,
                        f"翻訳ファイル（{style_labels.get(style_key, style_key)}）",
                    )
                )

        direction = "jp_to_en" if output_language == "en" else "en_to_jp"

        apply_total = (
            len(translation_styles)
            + (1 if self.config and self.config.bilingual_output else 0)
            + (1 if self.config and self.config.export_glossary else 0)
        )
        apply_step = 0
        bilingual_path = None
        glossary_path = None

        style_apply_order = [primary_style] + [
            s for s in translation_styles if s != primary_style
        ]
        for style_key in style_apply_order:
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )
            apply_step += 1
            if on_progress:
                progress_current = 90 + int(10 * (apply_step - 1) / max(apply_total, 1))
                style_label = style_labels.get(style_key, style_key)
                on_progress(
                    TranslationProgress(
                        current=progress_current,
                        total=100,
                        status=f"Applying translations to PDF ({style_label})...",
                        phase=TranslationPhase.APPLYING,
                        phase_current=apply_step,
                        phase_total=apply_total,
                    )
                )

            processor.apply_translations(
                input_path,
                output_paths_by_style[style_key],
                translations_by_style[style_key],
                direction,
                self.config,
                pages=selected_pages,
                text_blocks=all_blocks,  # Pass extracted blocks for precise positioning
            )

        # Create bilingual PDF if enabled (primary style only)
        if self.config and self.config.bilingual_output:
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )
            apply_step += 1
            if on_progress:
                progress_current = 90 + int(10 * (apply_step - 1) / max(apply_total, 1))
                on_progress(
                    TranslationProgress(
                        current=progress_current,
                        total=100,
                        status="Creating bilingual PDF...",
                        phase=TranslationPhase.APPLYING,
                        phase_detail="Interleaving original and translated pages",
                        phase_current=apply_step,
                        phase_total=apply_total,
                    )
                )

            bilingual_path = output_path.parent / (
                output_path.stem.replace("_translated", "") + "_bilingual.pdf"
            )
            processor.create_bilingual_pdf(input_path, output_path, bilingual_path)

        # Export glossary CSV if enabled (primary style only)
        if self.config and self.config.export_glossary:
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )
            apply_step += 1
            if on_progress:
                progress_current = 90 + int(10 * (apply_step - 1) / max(apply_total, 1))
                on_progress(
                    TranslationProgress(
                        current=progress_current,
                        total=100,
                        status="Exporting glossary CSV...",
                        phase=TranslationPhase.APPLYING,
                        phase_detail="Creating translation pairs",
                        phase_current=apply_step,
                        phase_total=apply_total,
                    )
                )

            glossary_path = output_path.parent / (
                output_path.stem.replace("_translated", "") + "_glossary.csv"
            )
            self._export_glossary_csv(all_blocks, primary_translations, glossary_path)

        if on_progress:
            on_progress(
                TranslationProgress(
                    current=100,
                    total=100,
                    status="Complete",
                    phase=TranslationPhase.COMPLETE,
                )
            )

        # Collect warnings including OCR failures
        warnings = self._collect_processor_warnings(processor)
        if self._use_local_backend() and reference_files:
            self._ensure_local_backend()
            if self._local_prompt_builder is not None:
                embedded_ref = self._local_prompt_builder.build_reference_embed(
                    reference_files
                )
                warnings.extend(embedded_ref.warnings)
        if primary_batch_result.untranslated_block_ids:
            warnings.append(
                f"未翻訳ブロック: {len(primary_batch_result.untranslated_block_ids)}"
            )
        if primary_batch_result.mismatched_batch_count:
            warnings.append(
                f"翻訳件数の不一致: {primary_batch_result.mismatched_batch_count}"
            )

        return TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_path=output_path,
            bilingual_path=bilingual_path,
            glossary_path=glossary_path,
            blocks_translated=len(primary_translations),
            blocks_total=total_blocks,
            duration_seconds=time.monotonic() - start_time,
            warnings=warnings if warnings else [],
            issue_block_ids=primary_batch_result.untranslated_block_ids,
            issue_block_locations=issue_locations,
            issue_section_counts=issue_section_counts,
            mismatched_batch_count=primary_batch_result.mismatched_batch_count,
            extra_output_files=extra_output_files,
        )

    def _make_extraction_progress_callback(
        self,
        on_progress: Optional[ProgressCallback],
        total_pages: int,
    ) -> Optional[ProgressCallback]:
        """Create a progress callback for extraction phase (0-40%)."""
        if not on_progress:
            return None

        def callback(progress: TranslationProgress):
            # Scale page progress to 0-40% range
            page_percentage = progress.current / max(progress.total, 1)
            scaled = int(page_percentage * 40)
            on_progress(
                TranslationProgress(
                    current=scaled,
                    total=100,
                    status=progress.status,
                    phase=TranslationPhase.EXTRACTING,
                    phase_detail=progress.phase_detail,
                    phase_current=progress.current,
                    phase_total=progress.total,
                )
            )

        return callback

    def _collect_processor_warnings(self, processor: FileProcessor) -> list[str]:
        """Build user-facing warnings from processor failure metadata."""
        warnings: list[str] = []

        # Check for processor-level warnings (ExcelProcessor, etc.)
        # Use getattr with default to handle mock objects in tests
        processor_warnings = getattr(processor, "warnings", None)
        if processor_warnings and isinstance(processor_warnings, list):
            warnings.extend(processor_warnings)

        # Check for PP-DocLayout-L fallback (PDF processor only)
        if getattr(processor, "_layout_fallback_used", False):
            warnings.append(
                "レイアウト解析(PP-DocLayout-L)が未インストールのため、段落検出精度が低下している可能性があります"
            )

        if hasattr(processor, "failed_pages") and processor.failed_pages:
            failed_pages = processor.failed_pages
            reasons = getattr(processor, "failed_page_reasons", {}) or {}

            if len(failed_pages) == 1:
                page = failed_pages[0]
                reason = reasons.get(page)
                if reason:
                    warnings.append(f"Page {page} skipped: {reason}")
                else:
                    warnings.append(f"OCR failed for page {page}")
            else:
                if reasons:
                    details = ", ".join(
                        f"{page} ({reasons.get(page, 'processing failed')})"
                        for page in failed_pages
                    )
                    warnings.append(f"Pages skipped: {details}")
                else:
                    warnings.append(
                        f"OCR failed for {len(failed_pages)} pages: {failed_pages}"
                    )

        return warnings

    def _export_glossary_csv(
        self,
        blocks: list[TextBlock],
        translations: dict[str, str],
        output_path: Path,
    ) -> bool:
        """
        Export translation pairs as glossary CSV.

        Format:
            original,translated
            原文テキスト,Translation text
            ...

        Args:
            blocks: Original text blocks
            translations: Translation results (block_id -> translated_text)
            output_path: Output CSV file path

        Returns:
            True if export was successful, False otherwise
        """
        try:
            pair_count = 0
            with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["original", "translated"])

                for block in blocks:
                    if block.id in translations:
                        original = block.text.strip()
                        translated = translations[block.id].strip()
                        # Skip empty pairs
                        if original and translated:
                            writer.writerow([original, translated])
                            pair_count += 1

            logger.info("Exported glossary CSV: %s (%d pairs)", output_path, pair_count)
            return True
        except (OSError, IOError) as e:
            logger.error("Failed to export glossary CSV to %s: %s", output_path, e)
            # Clean up incomplete file
            try:
                if output_path.exists():
                    output_path.unlink()
            except OSError:
                pass
            return False

    def _create_bilingual_output(
        self,
        input_path: Path,
        translated_path: Path,
        processor: FileProcessor,
    ) -> Optional[Path]:
        """
        Create bilingual output file based on file type.

        Args:
            input_path: Original input file path
            translated_path: Translated output file path
            processor: File processor instance

        Returns:
            Path to bilingual output file, or None on failure
        """
        ext = input_path.suffix.lower()

        # Generate bilingual output path
        bilingual_path = translated_path.parent / (
            translated_path.stem.replace("_translated", "") + "_bilingual" + ext
        )

        try:
            if ext in (".xlsx", ".xls"):
                # Excel: interleaved sheets
                if hasattr(processor, "create_bilingual_workbook"):
                    processor.create_bilingual_workbook(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual Excel: %s", bilingual_path)
                    return bilingual_path

            elif ext == ".docx":
                # Word: interleaved pages
                if hasattr(processor, "create_bilingual_document"):
                    processor.create_bilingual_document(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual Word document: %s", bilingual_path)
                    return bilingual_path

            elif ext == ".pptx":
                # PowerPoint: interleaved slides
                if hasattr(processor, "create_bilingual_presentation"):
                    processor.create_bilingual_presentation(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual PowerPoint: %s", bilingual_path)
                    return bilingual_path

            elif ext == ".txt":
                # Text: interleaved paragraphs with separators
                if hasattr(processor, "create_bilingual_document"):
                    processor.create_bilingual_document(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual text file: %s", bilingual_path)
                    return bilingual_path

            else:
                logger.warning("Bilingual output not supported for file type: %s", ext)
                return None

        except Exception as e:
            # Catch all exceptions for graceful error handling
            logger.error(
                "Failed to create bilingual output for %s: %s", input_path.name, e
            )
            return None

        return None

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file information for UI display"""
        processor = self._get_processor(file_path)
        return processor.get_file_info(file_path)

    def cancel(self) -> None:
        """Request cancellation of current operation (thread-safe)"""
        self._cancel_event.set()
        self.batch_translator.cancel()
        if self._local_batch_translator is not None:
            self._local_batch_translator.cancel()

        # Also cancel PDF processor if it's running OCR
        # Use _processors (not processors property) to avoid lazy initialization on shutdown
        if self._processors is not None:
            pdf_processor = self._processors.get(".pdf")
            if pdf_processor and hasattr(pdf_processor, "cancel"):
                pdf_processor.cancel()

    def reset_cancel(self) -> None:
        """Reset cancellation flags (thread-safe)."""
        self._cancel_event.clear()
        self.batch_translator.reset_cancel()
        if self._local_batch_translator is not None:
            self._local_batch_translator.reset_cancel()

        # Reset PDF processor cancellation flag if already initialized
        # Use _processors (not processors property) to avoid lazy initialization.
        if self._processors is not None:
            pdf_processor = self._processors.get(".pdf")
            if pdf_processor and hasattr(pdf_processor, "reset_cancel"):
                pdf_processor.reset_cancel()

    def _get_processor(self, file_path: Path) -> FileProcessor:
        """Get appropriate processor for file type"""
        ext = file_path.suffix.lower()
        if ext not in self.processors:
            raise ValueError(f"Unsupported file type: {ext}")
        return self.processors[ext]

    def _generate_output_path(self, input_path: Path) -> Path:
        """
        Generate unique output path.
        Adds _translated suffix, with numbering if file exists.
        """
        suffix = "_translated"
        stem = _sanitize_output_stem(input_path.stem)
        ext = input_path.suffix

        # Get output directory
        output_dir = self.config.get_output_directory(input_path)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Failed to create output directory '%s': %s", output_dir, e)
            raise

        # Try base name first
        output_path = output_dir / f"{stem}{suffix}{ext}"
        if not output_path.exists():
            return output_path

        # Add number if file exists (with limit to prevent infinite loop)
        counter = 2
        max_attempts = 10000
        while counter <= max_attempts:
            output_path = output_dir / f"{stem}{suffix}_{counter}{ext}"
            if not output_path.exists():
                return output_path
            counter += 1

        # Fallback: use timestamp if too many files exist
        import time

        timestamp = int(time.monotonic())
        output_path = output_dir / f"{stem}{suffix}_{timestamp}{ext}"
        logger.warning(
            "Could not find available filename after %d attempts, using timestamp: %s",
            max_attempts,
            output_path.name,
        )
        return output_path

    def _generate_style_variant_output_path(
        self, output_path: Path, style: str
    ) -> Path:
        """Generate an additional output path with style suffix, ensuring uniqueness."""
        suffix = f"_{style}"
        candidate = output_path.with_name(
            f"{output_path.stem}{suffix}{output_path.suffix}"
        )
        if not candidate.exists():
            return candidate

        counter = 2
        max_attempts = 10000
        while counter <= max_attempts:
            candidate = output_path.with_name(
                f"{output_path.stem}{suffix}_{counter}{output_path.suffix}"
            )
            if not candidate.exists():
                return candidate
            counter += 1

        timestamp = int(time.monotonic())
        candidate = output_path.with_name(
            f"{output_path.stem}{suffix}_{timestamp}{output_path.suffix}"
        )
        logger.warning(
            "Could not find available style filename after %d attempts, using timestamp: %s",
            max_attempts,
            candidate.name,
        )
        return candidate

    def is_supported_file(self, file_path: Path) -> bool:
        """Check if file type is supported"""
        ext = file_path.suffix.lower()
        return ext in self.processors

    def get_supported_extensions(self) -> list[str]:
        """Get list of supported file extensions"""
        return list(self.processors.keys())
