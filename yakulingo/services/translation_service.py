# yakulingo/services/translation_service.py
"""
Main translation service.
Coordinates between UI, translation backend, and file processors.
Bidirectional translation: Japanese → English, Other → Japanese (auto-detected).
"""

# ruff: noqa: E402

import logging
import os
import threading
import time
from contextlib import contextmanager, nullcontext
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import Callable, Optional, Protocol, TYPE_CHECKING
from zipfile import BadZipFile
import unicodedata

import re

if TYPE_CHECKING:
    from yakulingo.services.local_llama_server import LocalAIServerRuntime


class BatchTranslationClient(Protocol):
    def set_cancel_callback(self, callback: Optional[Callable[[], bool]]) -> None: ...

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        skip_clear_wait: bool = False,
        timeout: int = 300,
        include_item_ids: bool = False,
    ) -> list[str]: ...


class SingleTranslationClient(Protocol):
    def set_cancel_callback(self, callback: Optional[Callable[[], bool]]) -> None: ...

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> str: ...


class BackendClient(BatchTranslationClient, SingleTranslationClient, Protocol): ...


# Module logger
logger = logging.getLogger(__name__)

_LOCAL_AI_TIMING_ENABLED = os.environ.get("YAKULINGO_LOCAL_AI_TIMING") == "1"

DEFAULT_TEXT_STYLE = "minimal"
TEXT_STYLE_ORDER: tuple[str, ...] = ("standard", "concise", "minimal")
_TEXT_TO_EN_LENGTH_RATIO_BY_STYLE: dict[str, float] = {
    "standard": 3.0,
    "concise": 2.5,
    "minimal": 2.0,
}
_TEXT_TO_EN_LENGTH_RETRY_TEMPLATE = (
    "CRITICAL: Enforce output length. "
    "The translation MUST be <= {max_chars} characters ({ratio}x of the Japanese source). "
    "Shorten aggressively to fit the limit. Output translation only."
)


def _normalize_text_style(style: str | None) -> str:
    style_key = (style or "").strip().lower()
    return style_key if style_key in TEXT_STYLE_ORDER else DEFAULT_TEXT_STYLE


_TEXT_TO_EN_OUTPUT_LANGUAGE_RETRY_INSTRUCTION = (
    "CRITICAL: English only (no Japanese/Chinese/Korean scripts; no Japanese punctuation). "
    "Keep the exact output format (Translation sections only; no explanations/notes)."
)
_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION = (
    "CRITICAL: Follow numeric conversion rules. "
    "Do not use 'billion', 'trillion', or 'bn'. Use 'oku' (and 'k') as specified. "
    "If numeric conversion hints are provided, use them verbatim."
)
_TEXT_TO_EN_NEGATIVE_RULE_INSTRUCTION = (
    "CRITICAL: Convert ▲ negative numbers to parentheses with the number only (e.g., ▲50 -> (50)). "
    "Do not output ▲ or a leading minus."
)

# Pre-compiled regex patterns for performance
# Support both half-width (:) and full-width (：) colons, and markdown bold (**訳文:**)
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
_RE_CODE_FENCE_LINE = re.compile(r"^\s*```(?:\w+)?\s*$", re.IGNORECASE)

# Pattern to remove translation label prefixes from parsed result
# These labels come from prompt template output format examples (e.g., "訳文: 英語翻訳")
# When the backend follows the format literally, these labels appear at the start of the translation
_RE_TRANSLATION_LABEL = re.compile(
    r"^(?:英語翻訳|日本語翻訳|English\s*Translation|Japanese\s*Translation)\s*",
    re.IGNORECASE,
)

# Pattern to remove trailing attached filename from explanation
# Chat UI/backends sometimes append the attached file name (e.g., "glossary", "glossary.csv") to the response
# This pattern matches common reference file names at the end of the explanation
_RE_TRAILING_FILENAME = re.compile(
    r"[\s。．.、,]*(glossary(?:_old)?|abbreviations|用語集|略語集)(?:\.[a-z]{2,4})?\s*$",
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
_INT_WITH_OPTIONAL_COMMAS_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_RE_EN_OKU = re.compile(r"\boku\b", re.IGNORECASE)
_RE_EN_OKU_YEN_AMOUNT = re.compile(
    rf"(?P<prefix>\(?[▲+\-−]?)"
    rf"(?P<number>{_INT_WITH_OPTIONAL_COMMAS_PATTERN}(?:\.\d+)?)"
    rf"(?P<suffix>\)?)"
    r"\s*"
    r"(?P<oku>oku)\b"
    r"(?:\s*(?P<yen>yen)(?![A-Za-z0-9]))?",
    re.IGNORECASE,
)
_RE_JP_LARGE_UNIT = re.compile(r"[兆億]")
_RE_JP_OKU_CHOU_YEN_AMOUNT = re.compile(
    rf"(?P<sign>[▲+\-−])?\s*(?:(?P<trillion>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})兆(?:(?P<oku>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})億)?|(?P<oku_only>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})億)(?P<yen>円)?"
)
_RE_JP_MAN_YEN_AMOUNT = re.compile(
    rf"(?P<sign>[▲+\-−])?\s*(?P<man>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})万円"
)
_RE_JP_YEN_AMOUNT = re.compile(
    rf"(?P<sign>[▲+\-−])?\s*(?P<yen>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})円"
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
        is_negative = sign_marker in {"▲", "-", "−"}

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

    This targets common model mistakes such as:
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


def _fix_to_jp_oku_numeric_unit_if_possible(
    translated_text: str,
) -> tuple[str, bool]:
    """Convert numeric `oku` units to Japanese `億`/`億円` safely."""
    if not translated_text:
        return translated_text, False
    if "oku" not in translated_text.lower():
        return translated_text, False

    def repl(match: re.Match[str]) -> str:
        prefix = match.group("prefix") or ""
        number = match.group("number") or ""
        suffix = match.group("suffix") or ""
        has_yen = bool(match.group("yen"))
        unit = "億円" if has_yen else "億"
        return f"{prefix}{number}{suffix}{unit}"

    fixed, count = _RE_EN_OKU_YEN_AMOUNT.subn(repl, translated_text)
    return fixed, bool(count) and fixed != translated_text


def _strip_code_fences(text: str) -> str:
    if "```" not in text:
        return text
    lines = [line for line in text.splitlines() if not _RE_CODE_FENCE_LINE.match(line)]
    return "\n".join(lines).strip()


def _normalize_local_plain_text_output(text: str) -> str:
    cleaned = _strip_code_fences(text or "").strip()
    if not cleaned:
        return ""
    lines = [
        line for line in cleaned.splitlines() if not _RE_INPUT_MARKER_LINE.match(line)
    ]
    return "\n".join(lines).strip()


def _format_k_amount(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value == value.to_integral():
        return f"{sign}{int(value):,}"
    text = format(value.normalize(), "f")
    int_part, _, frac_part = text.partition(".")
    int_part_with_commas = f"{int(int_part):,}"
    frac_part = frac_part.rstrip("0")
    if frac_part:
        return f"{sign}{int_part_with_commas}.{frac_part}"
    return f"{sign}{int_part_with_commas}"


def _parse_decimal(value: str) -> Optional[Decimal]:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def _fix_to_en_k_notation_if_possible(
    *,
    source_text: str,
    translated_text: str,
) -> tuple[str, bool]:
    """Try to fix `万/千` conversions to `k` for JP→EN when it is safe."""
    if not source_text or not translated_text:
        return translated_text, False
    if not (
        _RE_JP_MAN_AMOUNT.search(source_text) or _RE_JP_SEN_AMOUNT.search(source_text)
    ):
        return translated_text, False

    expected: dict[int, str] = {}

    def add_expected(*, k_value: Decimal) -> None:
        full_value = k_value * Decimal("1000")
        if full_value != full_value.to_integral():
            return
        full_int = int(full_value)
        if full_int in expected:
            return
        formatted_k = _format_k_amount(k_value).lstrip("-")
        expected[full_int] = f"{formatted_k}k"

    for match in _RE_JP_MAN_AMOUNT_WITH_UNIT.finditer(source_text):
        man_value = _parse_decimal(match.group("number") or "")
        if man_value is None:
            continue
        add_expected(k_value=man_value * Decimal("10"))

    for match in _RE_JP_SEN_AMOUNT_WITH_UNIT.finditer(source_text):
        sen_value = _parse_decimal(match.group("number") or "")
        if sen_value is None:
            continue
        add_expected(k_value=sen_value)

    if not expected:
        return translated_text, False

    def repl_int_token(match: re.Match[str]) -> str:
        raw_number = match.group("number") or ""
        try:
            value = int(raw_number.replace(",", ""))
        except ValueError:
            return match.group(0)
        replacement = expected.get(value)
        return replacement if replacement else match.group(0)

    def repl_man_sen_unit(match: re.Match[str]) -> str:
        number_value = _parse_decimal(match.group("number") or "")
        if number_value is None:
            return match.group(0)

        unit = (match.group("unit") or "").strip().lower()
        if unit == "man":
            k_value = number_value * Decimal("10")
        elif unit == "sen":
            k_value = number_value
        else:
            return match.group(0)

        full_value = k_value * Decimal("1000")
        if full_value != full_value.to_integral():
            return match.group(0)

        full_int = int(full_value)
        replacement = expected.get(full_int)
        return replacement if replacement else match.group(0)

    fixed = translated_text
    total = 0
    fixed, count = _RE_EN_NUMBER_WITH_MAN_SEN_UNIT.subn(repl_man_sen_unit, fixed)
    total += count
    fixed, count = _RE_EN_INT_TOKEN.subn(repl_int_token, fixed)
    total += count

    if total == 0 or fixed == translated_text:
        return translated_text, False
    return fixed, True


def _needs_to_en_numeric_rule_retry_conservative(
    source_text: str,
    translated_text: str,
) -> bool:
    """英訳の数値ルール違反を最小限でリトライする（保守的）。

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


def _needs_to_en_numeric_rule_retry_conservative_after_safe_fix(
    source_text: str,
    translated_text: str,
) -> bool:
    """安全なローカル補正後もNGが残る場合のみTrue（保守的リトライ判定）。"""
    if not _needs_to_en_numeric_rule_retry_conservative(source_text, translated_text):
        return False

    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
        source_text=source_text,
        translated_text=translated_text,
    )
    if fixed and not _needs_to_en_numeric_rule_retry_conservative(
        source_text, fixed_text
    ):
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


_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN = (
    rf"{_INT_WITH_OPTIONAL_COMMAS_PATTERN}(?:\.\d+)?"
)
_RE_JP_MAN_AMOUNT = re.compile(
    rf"{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN}\s*万"
)
_RE_JP_SEN_AMOUNT = re.compile(
    rf"{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN}\s*千"
)
_RE_JP_MAN_AMOUNT_WITH_UNIT = re.compile(
    rf"(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN})\s*万(?P<unit>円|台)?"
)
_RE_JP_SEN_AMOUNT_WITH_UNIT = re.compile(
    rf"(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN})\s*千(?P<unit>円|台)?"
)
_RE_JP_TRIANGLE_NEGATIVE_NUMBER = re.compile(r"▲\s*\d")
_RE_JP_MONTH_NUMBER = re.compile(r"(\d{1,2})月")
_RE_EN_NUMBER_WITH_K_UNIT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*k\b", re.IGNORECASE)
_RE_EN_NUMBER_WITH_MAN_SEN_UNIT = re.compile(
    rf"(?<![\w.])(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN})\s*(?P<unit>man|sen)(?!-)\b",
    re.IGNORECASE,
)
_RE_EN_PAREN_NUMBER_ONLY = re.compile(r"\(\s*\d[\d,]*(?:\.\d+)?\s*\)")
_RE_EN_NEGATIVE_SIGN_NUMBER = re.compile(r"(?<!\w)[-−]\s*\d")
_RE_EN_NEGATIVE_SIGNED_NUMBER = re.compile(
    rf"(?<![\w(])[-−]\s*(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN})"
)
_RE_EN_MINUS_PAREN_NUMBER = re.compile(
    rf"(?<!\w)[-−]\s*\(\s*(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN})\s*\)"
)
_RE_EN_PAREN_NEGATIVE_SIGN_NUMBER = re.compile(
    rf"\(\s*[-−]\s*(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN})\s*\)"
)
_RE_EN_TRIANGLE_SIGNED_NUMBER = re.compile(
    rf"▲\s*(?P<number>{_NUMBER_WITH_OPTIONAL_COMMAS_AND_DECIMALS_PATTERN})"
)
_RE_EN_INT_TOKEN = re.compile(
    rf"(?<![\w.])(?P<number>{_INT_WITH_OPTIONAL_COMMAS_PATTERN})(?![\w.])"
)
_TO_EN_MONTH_ABBREV_PATTERNS: dict[int, re.Pattern[str]] = {
    1: re.compile(r"(?i)(?<![a-z])jan\.(?![a-z])"),
    2: re.compile(r"(?i)(?<![a-z])feb\.(?![a-z])"),
    3: re.compile(r"(?i)(?<![a-z])mar\.(?![a-z])"),
    4: re.compile(r"(?i)(?<![a-z])apr\.(?![a-z])"),
    # May has no period (capitalized to avoid "may" modal false positives).
    5: re.compile(r"(?<![A-Za-z])May(?![A-Za-z])"),
    6: re.compile(r"(?i)(?<![a-z])jun\.(?![a-z])"),
    7: re.compile(r"(?i)(?<![a-z])jul\.(?![a-z])"),
    8: re.compile(r"(?i)(?<![a-z])aug\.(?![a-z])"),
    9: re.compile(r"(?i)(?<![a-z])sep\.(?![a-z])"),
    10: re.compile(r"(?i)(?<![a-z])oct\.(?![a-z])"),
    11: re.compile(r"(?i)(?<![a-z])nov\.(?![a-z])"),
    12: re.compile(r"(?i)(?<![a-z])dec\.(?![a-z])"),
}
_TO_EN_MONTH_ABBREV_CANONICAL: dict[int, str] = {
    1: "Jan.",
    2: "Feb.",
    3: "Mar.",
    4: "Apr.",
    5: "May",
    6: "Jun.",
    7: "Jul.",
    8: "Aug.",
    9: "Sep.",
    10: "Oct.",
    11: "Nov.",
    12: "Dec.",
}
_TO_EN_MONTH_FULLNAME_PATTERNS: dict[int, re.Pattern[str]] = {
    1: re.compile(r"(?i)(?<![a-z])january\.?(?![a-z])"),
    2: re.compile(r"(?i)(?<![a-z])february\.?(?![a-z])"),
    3: re.compile(r"(?<![A-Za-z])(?:March|MARCH)\.?(?![A-Za-z])"),
    4: re.compile(r"(?i)(?<![a-z])april\.?(?![a-z])"),
    5: re.compile(r"(?<![A-Za-z])(?:May|MAY)\.?(?![A-Za-z])"),
    6: re.compile(r"(?i)(?<![a-z])june\.?(?![a-z])"),
    7: re.compile(r"(?i)(?<![a-z])july\.?(?![a-z])"),
    8: re.compile(r"(?i)(?<![a-z])august\.?(?![a-z])"),
    9: re.compile(r"(?i)(?<![a-z])september\.?(?![a-z])"),
    10: re.compile(r"(?i)(?<![a-z])october\.?(?![a-z])"),
    11: re.compile(r"(?i)(?<![a-z])november\.?(?![a-z])"),
    12: re.compile(r"(?i)(?<![a-z])december\.?(?![a-z])"),
}
_TO_EN_MONTH_ABBREV_RELAXED_PATTERNS: dict[int, re.Pattern[str]] = {
    1: re.compile(r"(?i)(?<![a-z])jan\.?(?![a-z])"),
    2: re.compile(r"(?i)(?<![a-z])feb\.?(?![a-z])"),
    3: re.compile(r"(?<![A-Za-z])(?:Mar|MAR)\.?(?![A-Za-z])"),
    4: re.compile(r"(?i)(?<![a-z])apr\.?(?![a-z])"),
    5: re.compile(r"(?<![A-Za-z])(?:May|MAY)\.?(?![A-Za-z])"),
    6: re.compile(r"(?i)(?<![a-z])jun\.?(?![a-z])"),
    7: re.compile(r"(?i)(?<![a-z])jul\.?(?![a-z])"),
    8: re.compile(r"(?i)(?<![a-z])aug\.?(?![a-z])"),
    9: re.compile(r"(?i)(?<![a-z])sep(?:t)?\.?(?![a-z])"),
    10: re.compile(r"(?i)(?<![a-z])oct\.?(?![a-z])"),
    11: re.compile(r"(?i)(?<![a-z])nov\.?(?![a-z])"),
    12: re.compile(r"(?i)(?<![a-z])dec\.?(?![a-z])"),
}


def _extract_jp_month_numbers(text: str) -> set[int]:
    if not text:
        return set()
    months: set[int] = set()
    for match in _RE_JP_MONTH_NUMBER.finditer(text):
        try:
            month = int(match.group(1))
        except ValueError:
            continue
        if 1 <= month <= 12:
            months.add(month)
    return months


def _needs_to_en_k_rule_retry(source_text: str, translated_text: str) -> bool:
    if not source_text or not translated_text:
        return False
    if not (
        _RE_JP_MAN_AMOUNT.search(source_text) or _RE_JP_SEN_AMOUNT.search(source_text)
    ):
        return False
    return _RE_EN_NUMBER_WITH_K_UNIT.search(translated_text) is None


def _needs_to_en_negative_rule_retry(source_text: str, translated_text: str) -> bool:
    if not source_text or not translated_text:
        return False
    if not _RE_JP_TRIANGLE_NEGATIVE_NUMBER.search(source_text):
        return False
    if "▲" in translated_text:
        return True
    if _RE_EN_NEGATIVE_SIGN_NUMBER.search(translated_text):
        return True
    return _RE_EN_PAREN_NUMBER_ONLY.search(translated_text) is None


def _needs_to_en_month_abbrev_retry(source_text: str, translated_text: str) -> bool:
    if not source_text or not translated_text:
        return False
    months = _extract_jp_month_numbers(source_text)
    if not months:
        return False
    for month in months:
        pattern = _TO_EN_MONTH_ABBREV_PATTERNS.get(month)
        if pattern is None:
            continue
        if not pattern.search(translated_text):
            return True
    return False


def _collect_to_en_rule_retry_reasons(
    source_text: str, translated_text: str
) -> list[str]:
    reasons: list[str] = []
    if _needs_to_en_k_rule_retry(source_text, translated_text):
        reasons.append("k")
    if _needs_to_en_negative_rule_retry(source_text, translated_text):
        reasons.append("negative")
    if _needs_to_en_month_abbrev_retry(source_text, translated_text):
        reasons.append("month")
    return reasons


def _build_to_en_rule_retry_instruction(reasons: list[str]) -> str:
    if not reasons:
        return ""
    lines = ["CRITICAL: Fix the previous output to follow the Translation Rules."]
    if "k" in reasons:
        lines.append("- Use k notation for 万/千 (e.g., 22万円 -> 220k yen).")
    if "negative" in reasons:
        lines.append(
            "- Convert ▲ negative numbers to parentheses with the number only (e.g., ▲50 -> (50)). Do not output ▲ or a leading minus."
        )
    if "month" in reasons:
        lines.append(
            "- Use month abbreviations: Jan., Feb., Mar., Apr., May, Jun., Jul., Aug., Sep., Oct., Nov., Dec. Do not use full month names."
        )
    return "\n".join(lines)


def _get_to_en_length_limit(
    source_text: str, style: str
) -> tuple[int, float, int] | None:
    ratio = _TEXT_TO_EN_LENGTH_RATIO_BY_STYLE.get(style)
    if ratio is None:
        return None
    source_count = len((source_text or "").strip())
    if source_count <= 0:
        return None
    limit = max(1, int(source_count * ratio))
    return limit, ratio, source_count


def _needs_to_en_length_retry(
    source_text: str, translated_text: str, style: str
) -> tuple[bool, int, float, int, int]:
    limit_info = _get_to_en_length_limit(source_text, style)
    translation_count = len((translated_text or "").strip())
    if limit_info is None:
        return False, 0, 0.0, 0, translation_count
    limit, ratio, source_count = limit_info
    return translation_count > limit, limit, ratio, source_count, translation_count


def _build_to_en_length_retry_instruction(max_chars: int, ratio: float) -> str:
    return _TEXT_TO_EN_LENGTH_RETRY_TEMPLATE.format(
        max_chars=max_chars, ratio=f"{ratio:g}"
    )


def _fix_to_en_negative_parens_if_possible(
    *,
    source_text: str,
    translated_text: str,
) -> tuple[str, bool]:
    """Convert negative sign markers to `(number)` for JP→EN when it is safe.

    This is a last-resort safety net when a retry still violates the negative-number rule.
    """
    if not source_text or not translated_text:
        return translated_text, False
    if not _RE_JP_TRIANGLE_NEGATIVE_NUMBER.search(source_text):
        return translated_text, False

    fixed = translated_text
    total = 0

    fixed, count = _RE_EN_MINUS_PAREN_NUMBER.subn(
        lambda m: f"({m.group('number')})", fixed
    )
    total += count
    fixed, count = _RE_EN_PAREN_NEGATIVE_SIGN_NUMBER.subn(
        lambda m: f"({m.group('number')})", fixed
    )
    total += count
    fixed, count = _RE_EN_TRIANGLE_SIGNED_NUMBER.subn(
        lambda m: f"({m.group('number')})", fixed
    )
    total += count
    fixed, count = _RE_EN_NEGATIVE_SIGNED_NUMBER.subn(
        lambda m: f"({m.group('number')})", fixed
    )
    total += count

    if total == 0 or fixed == translated_text:
        return translated_text, False
    return fixed, True


def _fix_to_en_month_abbrev_if_possible(
    *,
    source_text: str,
    translated_text: str,
) -> tuple[str, bool]:
    """Convert full month names / common variants to canonical abbreviations for JP→EN when safe."""
    if not source_text or not translated_text:
        return translated_text, False

    months = _extract_jp_month_numbers(source_text)
    if not months:
        return translated_text, False

    fixed = translated_text
    total = 0
    for month in sorted(months):
        canonical_pattern = _TO_EN_MONTH_ABBREV_PATTERNS.get(month)
        if canonical_pattern is not None and canonical_pattern.search(fixed):
            continue

        canonical = _TO_EN_MONTH_ABBREV_CANONICAL.get(month)
        if not canonical:
            continue

        full_pattern = _TO_EN_MONTH_FULLNAME_PATTERNS.get(month)
        if full_pattern is not None:
            fixed, count = full_pattern.subn(canonical, fixed)
            total += count

        abbrev_pattern = _TO_EN_MONTH_ABBREV_RELAXED_PATTERNS.get(month)
        if abbrev_pattern is not None:
            fixed, count = abbrev_pattern.subn(canonical, fixed)
            total += count

    if total == 0 or fixed == translated_text:
        return translated_text, False
    return fixed, True


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


_RE_ELLIPSIS_ONLY = re.compile(r"^[.\u2026\u22ef]+$")
_RE_PLACEHOLDER_TOKEN = re.compile(r"^<\s*([^<>]+)\s*>$")
_RE_PLACEHOLDER_INNER = re.compile(r"^(?:translation|style|\.{3}|…)$", re.IGNORECASE)

_LOCAL_AI_ELLIPSIS_RETRY_INSTRUCTION = (
    '- Do not output ellipsis placeholders (e.g., "...", "…").\n'
    "- Output an actual translation; never output only dots.\n"
)
_LOCAL_AI_PLACEHOLDER_RETRY_INSTRUCTION = (
    "- Do not output placeholder tokens like <TRANSLATION> or <STYLE>.\n"
    "- Output actual translations, not placeholder markers.\n"
)


def _is_ellipsis_only_text(text: str | None) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return _RE_ELLIPSIS_ONLY.fullmatch(cleaned) is not None


def _is_placeholder_only_text(text: str | None) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    tokens = cleaned.split()
    if not tokens:
        return False
    for token in tokens:
        match = _RE_PLACEHOLDER_TOKEN.fullmatch(token)
        if not match:
            return False
        inner = match.group(1).strip()
        if not _RE_PLACEHOLDER_INNER.fullmatch(inner):
            return False
    return True


def _is_ellipsis_only_translation(source_text: str, translated_text: str) -> bool:
    if not _is_ellipsis_only_text(translated_text):
        return False
    return not _is_ellipsis_only_text(source_text)


def _is_placeholder_only_translation(source_text: str, translated_text: str) -> bool:
    if not _is_placeholder_only_text(translated_text):
        return False
    return not _is_placeholder_only_text(source_text)


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
    """Remove input marker lines accidentally echoed by the backend."""
    if not text:
        return text
    lines = [
        line for line in text.splitlines() if not _RE_INPUT_MARKER_LINE.match(line)
    ]
    return "\n".join(lines).strip()


def _strip_trailing_attachment_links(text: str) -> str:
    """Remove trailing attachment links like [file | Excel](...)."""
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
    *,
    expected_output_language: str | None = None,
    parse_json: bool = False,
    prompt: str | None = None,
) -> Optional[Callable[[str], None]]:
    if on_chunk is None:
        return None
    _ = expected_output_language, parse_json
    last_emitted = ""
    last_emit_time = 0.0
    raw_cached = ""
    raw_parts: list[str] = []
    throttle_seconds = 0.08
    strip_echo = None
    if prompt:
        from yakulingo.services.local_ai_client import strip_prompt_echo as strip_echo

    def _current_candidate() -> str:
        candidate = raw_cached
        if strip_echo is not None:
            candidate = strip_echo(candidate, prompt)
        return candidate

    def _handle(delta: str) -> None:
        nonlocal last_emitted, last_emit_time, raw_cached, raw_parts

        if not delta:
            return
        if raw_cached and delta.startswith(raw_cached):
            raw_cached = delta
            raw_parts.clear()
        else:
            raw_parts.append(delta)

        if raw_parts:
            raw_cached += "".join(raw_parts)
            raw_parts.clear()

        candidate = _current_candidate()
        if candidate == last_emitted:
            return
        now = time.monotonic()
        if (now - last_emit_time) < throttle_seconds and abs(
            len(candidate) - len(last_emitted)
        ) < 3:
            return
        last_emitted = candidate
        last_emit_time = now
        on_chunk(candidate)

    def flush() -> None:
        nonlocal last_emitted, last_emit_time
        candidate = _current_candidate()
        if not candidate:
            return
        if candidate != last_emitted:
            last_emitted = candidate
            last_emit_time = time.monotonic()
            on_chunk(candidate)
        downstream_flush = getattr(on_chunk, "flush", None)
        if callable(downstream_flush):
            try:
                downstream_flush()
            except Exception:
                pass

    setattr(_handle, "flush", flush)
    return _handle


# =============================================================================
# Language Detection
# =============================================================================


class LanguageDetector:
    """
    Language detection with local-only approach.

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
        Detect language locally.

        Detection priority:
        1. Hiragana/Katakana present → "日本語" (definite Japanese)
        2. Hangul present → "韓国語" (definite Korean)
        3. CJK with many non-JIS ideographs → "中国語" (conservative heuristic)
        4. Latin alphabet dominant → "英語" (assume English for speed)
        5. CJK only (no kana) → "日本語" (assume Japanese for target users)
        6. Other/mixed → "日本語" (default fallback)

        Note: This method always returns a language name (never None). Target
        users are Japanese, so Japanese is used as the default fallback.

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
from yakulingo.services.exceptions import TranslationCancelledError
from yakulingo.services.prompt_builder import (
    PromptBuilder,
    REFERENCE_INSTRUCTION,
    DEFAULT_TEXT_TO_JP_TEMPLATE,
)
from yakulingo.processors.base import FileProcessor

if TYPE_CHECKING:
    from yakulingo.processors.pdf_processor import PdfProcessor


_RE_LOCAL_TEXT_SEGMENT_NEWLINES = re.compile(r"(\r\n|\r|\n)")
_LOCAL_TEXT_SEGMENT_SENTENCE_END = frozenset("。.!?！？")
_LOCAL_TEXT_SEGMENT_CLAUSE_END = frozenset("、,;；:：")
_LOCAL_TEXT_SEGMENT_EDGE_WS = " \t"


def _split_long_text_core_for_local_translation(
    text: str, *, max_chars: int
) -> list[str]:
    if max_chars <= 0:
        return [text]
    normalized = text or ""
    if len(normalized) <= max_chars:
        return [normalized]

    parts: list[str] = []
    idx = 0
    n = len(normalized)
    min_soft_boundary = max(64, max_chars // 2)

    while idx < n:
        remaining = n - idx
        if remaining <= max_chars:
            parts.append(normalized[idx:])
            break

        window_end = idx + max_chars
        soft_start = min(n, idx + min_soft_boundary)
        split_at = None

        for ch_idx in range(window_end - 1, soft_start - 1, -1):
            if normalized[ch_idx] in _LOCAL_TEXT_SEGMENT_SENTENCE_END:
                split_at = ch_idx + 1
                break
        if split_at is None:
            for ch_idx in range(window_end - 1, soft_start - 1, -1):
                if normalized[ch_idx] in _LOCAL_TEXT_SEGMENT_CLAUSE_END:
                    split_at = ch_idx + 1
                    break
        if split_at is None:
            for ch_idx in range(window_end - 1, idx, -1):
                if normalized[ch_idx] in _LOCAL_TEXT_SEGMENT_EDGE_WS:
                    split_at = ch_idx + 1
                    break
        if split_at is None or split_at <= idx:
            split_at = window_end

        parts.append(normalized[idx:split_at])
        idx = split_at

    return [p for p in parts if p]


def _segment_long_text_for_local_text_translation(
    text: str, *, max_segment_chars: int
) -> list[tuple[str, bool]]:
    """Split text into (token, translate?) preserving newlines and edge whitespace."""
    normalized = text or ""
    if not normalized:
        return []

    tokens: list[tuple[str, bool]] = []
    for part in _RE_LOCAL_TEXT_SEGMENT_NEWLINES.split(normalized):
        if not part:
            continue
        if part in ("\n", "\r", "\r\n"):
            tokens.append((part, False))
            continue

        for segment in _split_long_text_core_for_local_translation(
            part, max_chars=max_segment_chars
        ):
            if not segment:
                continue
            lead_len = len(segment) - len(segment.lstrip(_LOCAL_TEXT_SEGMENT_EDGE_WS))
            if lead_len:
                tokens.append((segment[:lead_len], False))
                segment = segment[lead_len:]
            trail_len = len(segment) - len(segment.rstrip(_LOCAL_TEXT_SEGMENT_EDGE_WS))
            trailing = ""
            if trail_len:
                trailing = segment[-trail_len:]
                segment = segment[:-trail_len]
            if segment:
                tokens.append((segment, True))
            if trailing:
                tokens.append((trailing, False))

    return tokens


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
    DEFAULT_MAX_CHARS_PER_BATCH = 1000  # Characters per batch (prompt safety)
    DEFAULT_REQUEST_TIMEOUT = (
        600  # Default timeout for translation response (10 minutes)
    )
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
        client: BatchTranslationClient | None,
        prompt_builder: PromptBuilder,
        max_chars_per_batch: Optional[int] = None,
        request_timeout: Optional[int] = None,
        enable_cache: bool = True,
        client_lock: Optional[threading.Lock] = None,
    ):
        self.client = client
        self.prompt_builder = prompt_builder
        self._client_lock = client_lock
        # Thread-safe cancellation using Event instead of bool flag
        self._cancel_event = threading.Event()

        # Use provided values or defaults
        self.max_chars_per_batch = (
            max_chars_per_batch or self.DEFAULT_MAX_CHARS_PER_BATCH
        )
        self.request_timeout = request_timeout or self.DEFAULT_REQUEST_TIMEOUT

        # Translation cache for avoiding re-translation of identical text
        self._cache = TranslationCache() if enable_cache else None

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
        return isinstance(self.client, LocalAIClient)

    def _require_client(self) -> BatchTranslationClient:
        client = self.client
        if client is None:
            raise RuntimeError("Translation client not configured")
        return client

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
        reference_files = None
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
        _clear_cancel_event: Optional[bool] = None,
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
        reference_files = None
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
        fallback_original_batches = 0
        local_persisted_max_chars_per_batch: Optional[int] = None

        if _clear_cancel_event is None:
            _clear_cancel_event = _split_retry_depth == 0
        if _clear_cancel_event:
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
        if has_refs:
            ref_names: list[str] = []
            for path in reference_files or []:
                try:
                    ref_names.append(path.name)
                except Exception:
                    ref_names.append(str(path))
            shown = ", ".join(ref_names[:3])
            if len(ref_names) > 3:
                suffix = f"+{len(ref_names) - 3} more"
                shown = f"{shown}, {suffix}" if shown else suffix
            logger.debug(
                "Reference files provided: %d (%s)",
                len(ref_names),
                shown,
            )

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

            if (
                is_local_backend
                and local_persisted_max_chars_per_batch is not None
                and sum(len(block.text) for block in batch)
                > local_persisted_max_chars_per_batch
            ):
                retry_result = self.translate_blocks_with_result(
                    batch,
                    reference_files=reference_files,
                    on_progress=None,
                    output_language=output_language,
                    translation_style=translation_style,
                    include_item_ids=include_item_ids,
                    _max_chars_per_batch=local_persisted_max_chars_per_batch,
                    _max_chars_per_batch_source="local_adaptive_max_chars_per_batch",
                    _split_retry_depth=0,
                    _clear_cancel_event=False,
                )
                translations.update(retry_result.translations)
                untranslated_block_ids.extend(retry_result.untranslated_block_ids)
                mismatched_batch_count += retry_result.mismatched_batch_count
                if retry_result.cancelled:
                    cancelled = True
                    break
                continue

            unique_texts, original_to_unique_idx = batch_unique_data[i]
            prompt = prompts[i]  # Use pre-built prompt

            # Translate unique texts only
            # Skip clear wait for 2nd+ batches (we just finished getting a response)
            skip_clear_wait = i > 0
            try:
                client = self._require_client()
                lock = self._client_lock or nullcontext()
                with lock:
                    client.set_cancel_callback(lambda: self._cancel_event.is_set())
                    try:
                        unique_translations = client.translate_sync(
                            unique_texts,
                            prompt,
                            files_to_attach,
                            skip_clear_wait,
                            timeout=self.request_timeout,
                            include_item_ids=include_item_ids,
                        )
                    finally:
                        client.set_cancel_callback(None)
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
                    if is_local_backend:
                        local_persisted_max_chars_per_batch = (
                            reduced_limit
                            if local_persisted_max_chars_per_batch is None
                            else min(local_persisted_max_chars_per_batch, reduced_limit)
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
                        if is_local_backend:
                            local_persisted_max_chars_per_batch = (
                                reduced_limit
                                if local_persisted_max_chars_per_batch is None
                                else min(
                                    local_persisted_max_chars_per_batch, reduced_limit
                                )
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

            post_check_enabled = not is_local_backend
            cleaned_unique_translations = []
            hangul_indices: list[int] = []
            output_language_mismatch_indices: list[int] = []
            for idx, translated_text in enumerate(unique_translations):
                cleaned_text = self._clean_batch_translation(translated_text)
                if not cleaned_text or not cleaned_text.strip():
                    cleaned_unique_translations.append("")
                    continue
                if (
                    post_check_enabled
                    and output_language == "en"
                    and _RE_HANGUL.search(cleaned_text)
                ):
                    hangul_indices.append(idx)
                    cleaned_unique_translations.append("")
                    continue
                if post_check_enabled and self._is_output_language_mismatch(
                    cleaned_text, output_language
                ):
                    output_language_mismatch_indices.append(idx)
                    cleaned_unique_translations.append("")
                    continue
                if post_check_enabled and self._should_retry_translation(
                    unique_texts[idx], cleaned_text, output_language
                ):
                    preview = unique_texts[idx][:50].replace("\n", " ")
                    logger.debug("Scheduling retry for JP->EN text: '%s'", preview)
                    cleaned_unique_translations.append("")
                    continue
                cleaned_unique_translations.append(cleaned_text)

            if hangul_indices and output_language == "en":
                logger.warning(
                    "Batch %d: Hangul detected in %d English translations; using fallback",
                    i + 1,
                    len(hangul_indices),
                )

            if output_language_mismatch_indices and output_language in ("en", "jp"):
                logger.warning(
                    "Batch %d: Output language mismatch detected in %d translations (target=%s); using fallback",
                    i + 1,
                    len(output_language_mismatch_indices),
                    output_language,
                )

            if (
                (not is_local_backend)
                and output_language == "en"
                and not self._cancel_event.is_set()
            ):
                auto_fixed_numeric = 0
                for idx, translated_text in enumerate(cleaned_unique_translations):
                    if not translated_text or not translated_text.strip():
                        continue
                    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                        source_text=unique_texts[idx],
                        translated_text=translated_text,
                    )
                    if fixed:
                        cleaned_unique_translations[idx] = fixed_text
                        auto_fixed_numeric += 1
                if auto_fixed_numeric:
                    logger.debug(
                        "Batch %d: Auto-corrected numeric units for %d/%d items",
                        i + 1,
                        auto_fixed_numeric,
                        len(cleaned_unique_translations),
                    )

            if (
                (not is_local_backend)
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
                    logger.warning(
                        "Batch %d: Numeric rule violations remain in %d items; using fallback",
                        i + 1,
                        len(numeric_rule_violation_indices),
                    )
                    for idx in numeric_rule_violation_indices:
                        cleaned_unique_translations[idx] = ""

            if not is_local_backend:
                # Treat ellipsis-only outputs ("..." / "…") as invalid translations and fall back.
                ellipsis_only_indices = [
                    idx
                    for idx, trans in enumerate(cleaned_unique_translations)
                    if trans
                    and trans.strip()
                    and _is_ellipsis_only_translation(unique_texts[idx], trans)
                ]
                if ellipsis_only_indices:
                    logger.warning(
                        "Batch %d: %d ellipsis-only translations detected; using fallback for those blocks",
                        i + 1,
                        len(ellipsis_only_indices),
                    )
                    for idx in ellipsis_only_indices:
                        cleaned_unique_translations[idx] = ""

                placeholder_only_indices = [
                    idx
                    for idx, trans in enumerate(cleaned_unique_translations)
                    if trans
                    and trans.strip()
                    and _is_placeholder_only_translation(unique_texts[idx], trans)
                ]
                if placeholder_only_indices:
                    logger.warning(
                        "Batch %d: %d placeholder-only translations detected; using fallback for those blocks",
                        i + 1,
                        len(placeholder_only_indices),
                    )
                    for idx in placeholder_only_indices:
                        cleaned_unique_translations[idx] = ""

            # Detect empty translations (a backend may return empty strings for some items)
            empty_translation_indices = [
                idx
                for idx, trans in enumerate(cleaned_unique_translations)
                if not trans or not trans.strip()
            ]
            if (not is_local_backend) and empty_translation_indices:
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
                    if (
                        (not is_local_backend)
                        and (not translated_text or not translated_text.strip())
                    ):
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
            (not is_local_backend)
            and untranslated_block_ids
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
                "[TIMING] BatchTranslator.retries: prompt_too_long=%d local_error=%d fallback_original_batches=%d mismatched_batches=%d untranslated_blocks=%d",
                retry_prompt_too_long,
                retry_local_error,
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

    def translate_blocks_single_unit_with_result(
        self,
        blocks: list[TextBlock],
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        _clear_cancel_event: bool = True,
    ) -> BatchTranslationResult:
        """Translate blocks one-by-one (single unit) with per-call caching."""
        from yakulingo.models.types import BatchTranslationResult

        if _clear_cancel_event:
            self._cancel_event.clear()
        reference_files = None

        translations: dict[str, str] = {}
        untranslated_block_ids: list[str] = []
        mismatched_batch_count = 0
        cancelled = False

        # Phase 0: Skip formula blocks and non-translatable blocks (preserve original text)
        formula_skipped = 0
        skip_translation_count = 0
        translatable_blocks: list[TextBlock] = []

        for block in blocks:
            if block.metadata and block.metadata.get("is_formula"):
                translations[block.id] = block.text
                formula_skipped += 1
            elif block.metadata and block.metadata.get("skip_translation"):
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

        # Phase 1: Resolve cached translations and track uncached blocks.
        # Progress is block-based (uncached blocks), while backend calls are deduped by cache key.
        resolved_by_key: dict[str, tuple[str, bool]] = {}
        cache_hits = 0
        uncached_block_keys: dict[str, str] = {}

        for block in translatable_blocks:
            cache_key = self._build_cache_key(
                block.text,
                output_language=output_language,
                translation_style=translation_style,
            )
            if self._cache:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    translations[block.id] = cached
                    resolved_by_key[cache_key] = (cached, False)
                    cache_hits += 1
                    continue
            uncached_block_keys[block.id] = cache_key

        if cache_hits > 0:
            logger.debug(
                "Cache hits (single-unit): %d/%d blocks (%.1f%%)",
                cache_hits,
                len(translatable_blocks),
                cache_hits / len(translatable_blocks) * 100
                if translatable_blocks
                else 0,
            )

        has_refs = bool(reference_files)
        files_to_attach = reference_files if has_refs else None

        total_blocks = len(uncached_block_keys)
        processed_blocks = 0
        backend_calls = 0

        def translate_single(text: str, *, skip_clear_wait: bool):
            prompt = self.prompt_builder.build_batch(
                [text],
                has_reference_files=has_refs,
                output_language=output_language,
                translation_style=translation_style,
                include_item_ids=include_item_ids,
                reference_files=reference_files,
            )
            client = self._require_client()
            lock = self._client_lock or nullcontext()
            with lock:
                client.set_cancel_callback(lambda: self._cancel_event.is_set())
                try:
                    return client.translate_sync(
                        [text],
                        prompt,
                        files_to_attach,
                        skip_clear_wait,
                        timeout=self.request_timeout,
                        include_item_ids=include_item_ids,
                    )
                finally:
                    client.set_cancel_callback(None)

        # Phase 2: Translate missing texts one-by-one
        for block in translatable_blocks:
            if self._cancel_event.is_set():
                cancelled = True
                break

            cache_key = uncached_block_keys.get(block.id)
            if not cache_key:
                continue

            if cache_key in resolved_by_key:
                resolved, is_fallback = resolved_by_key[cache_key]
                translations[block.id] = resolved
                if is_fallback:
                    untranslated_block_ids.append(block.id)
                processed_blocks += 1
                if on_progress:
                    on_progress(
                        TranslationProgress(
                            current=processed_blocks,
                            total=total_blocks,
                            status=f"Block {processed_blocks} of {total_blocks}",
                            phase_current=processed_blocks,
                            phase_total=total_blocks,
                        )
                    )
                continue

            if self._cache:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    translations[block.id] = cached
                    resolved_by_key[cache_key] = (cached, False)
                    processed_blocks += 1
                    if on_progress:
                        on_progress(
                            TranslationProgress(
                                current=processed_blocks,
                                total=total_blocks,
                                status=f"Block {processed_blocks} of {total_blocks}",
                                phase_current=processed_blocks,
                                phase_total=total_blocks,
                            )
                        )
                    continue

            skip_clear_wait = backend_calls > 0
            try:
                raw_list = translate_single(block.text, skip_clear_wait=skip_clear_wait)
            except TranslationCancelledError:
                cancelled = True
                break
            except RuntimeError as e:
                logger.warning("Single-unit translation failed: %s", e)
                untranslated_block_ids.append(block.id)
                translations[block.id] = block.text
                resolved_by_key[cache_key] = (block.text, True)
                processed_blocks += 1
                if on_progress:
                    on_progress(
                        TranslationProgress(
                            current=processed_blocks,
                            total=total_blocks,
                            status=f"Block {processed_blocks} of {total_blocks}",
                            phase_current=processed_blocks,
                            phase_total=total_blocks,
                        )
                    )
                continue

            backend_calls += 1

            if not isinstance(raw_list, list) or len(raw_list) != 1:
                mismatched_batch_count += 1
                untranslated_block_ids.append(block.id)
                translations[block.id] = block.text
                resolved_by_key[cache_key] = (block.text, True)
                processed_blocks += 1
                if on_progress:
                    on_progress(
                        TranslationProgress(
                            current=processed_blocks,
                            total=total_blocks,
                            status=f"Block {processed_blocks} of {total_blocks}",
                            phase_current=processed_blocks,
                            phase_total=total_blocks,
                        )
                    )
                continue

            translated_text = self._clean_batch_translation(raw_list[0])

            if not translated_text or not translated_text.strip():
                untranslated_block_ids.append(block.id)
                translations[block.id] = block.text
                resolved_by_key[cache_key] = (block.text, True)
                processed_blocks += 1
                if on_progress:
                    on_progress(
                        TranslationProgress(
                            current=processed_blocks,
                            total=total_blocks,
                            status=f"Block {processed_blocks} of {total_blocks}",
                            phase_current=processed_blocks,
                            phase_total=total_blocks,
                        )
                    )
                continue

            translations[block.id] = translated_text
            resolved_by_key[cache_key] = (translated_text, False)
            if self._cache:
                self._cache.set(cache_key, translated_text)
            processed_blocks += 1
            if on_progress:
                on_progress(
                    TranslationProgress(
                        current=processed_blocks,
                        total=total_blocks,
                        status=f"Block {processed_blocks} of {total_blocks}",
                        phase_current=processed_blocks,
                        phase_total=total_blocks,
                    )
                )

        if on_progress:
            on_progress(
                TranslationProgress(
                    current=min(processed_blocks, total_blocks),
                    total=total_blocks,
                    status="Complete" if not cancelled else "Cancelled",
                    phase_current=min(processed_blocks, total_blocks),
                    phase_total=total_blocks,
                )
            )

        return BatchTranslationResult(
            translations=translations,
            untranslated_block_ids=untranslated_block_ids,
            mismatched_batch_count=mismatched_batch_count,
            total_blocks=len(blocks),
            translated_count=len(translations),
            cancelled=cancelled,
        )

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
    Coordinates between UI, translation backend, and file processors.
    """

    def __init__(
        self,
        config: AppSettings,
        prompts_dir: Optional[Path] = None,
        *,
        client: BackendClient | None = None,
        client_lock: Optional[threading.Lock] = None,
    ):
        self.config = config
        self._client = client
        self._client_lock = client_lock
        self.prompt_builder = PromptBuilder(prompts_dir)
        self.batch_translator = BatchTranslator(
            client,
            self.prompt_builder,
            max_chars_per_batch=config.max_chars_per_batch if config else None,
            request_timeout=config.request_timeout if config else None,
            client_lock=client_lock,
        )
        self._local_init_lock = threading.Lock()
        self._local_call_lock = threading.Lock()
        self._local_client = None
        self._local_prompt_builder = None
        self._local_batch_translator = None
        self._local_translate_single_supports_runtime: bool | None = None
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
                and getattr(self.config, "translation_backend", "local") == "local"
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

                prompts_dir = self.prompt_builder.prompts_dir
                if prompts_dir is None:
                    candidate = Path(__file__).resolve().parents[2] / "prompts"
                    if candidate.exists():
                        prompts_dir = candidate

                self._local_prompt_builder = LocalPromptBuilder(
                    prompts_dir,
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
                    client_lock=self._local_call_lock,
                )

    def _local_translate_single_supports_runtime_param(self) -> bool:
        cached = self._local_translate_single_supports_runtime
        if cached is not None:
            return cached
        try:
            import inspect

            cached = (
                "runtime"
                in inspect.signature(
                    self._translate_single_with_cancel_on_local
                ).parameters
            )
        except Exception:
            cached = False
        self._local_translate_single_supports_runtime = cached
        return cached

    def _get_active_client(self) -> SingleTranslationClient:
        if self._use_local_backend():
            self._ensure_local_backend()
            client = self._local_client
            if client is None:
                raise RuntimeError("Local AI client not initialized")
            return client
        client = self._client
        if client is None:
            raise RuntimeError("Translation client not configured")
        return client

    def _get_active_batch_translator(self) -> BatchTranslator:
        if self._use_local_backend():
            self._ensure_local_backend()
            translator = self._local_batch_translator
            if translator is None:
                raise RuntimeError("Local batch translator not initialized")
            return translator
        return self.batch_translator

    def _get_local_text_batch_limit(self) -> Optional[int]:
        if not self._use_local_backend() or self.config is None:
            return None
        limit = getattr(self.config, "local_ai_max_chars_per_batch", None)
        if isinstance(limit, int) and limit > 0:
            return limit
        return None

    def _get_local_file_batch_limit_info(self) -> tuple[Optional[int], str | None]:
        """ファイル翻訳（ローカルAIバッチ翻訳）の分割上限（初期値）を解決する。

        互換性のため `local_ai_max_chars_per_batch_file` を優先し、未設定なら
        `local_ai_max_chars_per_batch` をフォールバックとして使う。
        """
        if self.config is None:
            return None, None
        limit = getattr(self.config, "local_ai_max_chars_per_batch_file", None)
        if isinstance(limit, int) and limit > 0:
            return limit, "local_ai_max_chars_per_batch_file"
        fallback = getattr(self.config, "local_ai_max_chars_per_batch", None)
        if isinstance(fallback, int) and fallback > 0:
            return fallback, "local_ai_max_chars_per_batch"
        return None, None

    @staticmethod
    def _estimate_local_prompt_tokens(prompt: str) -> int:
        prompt = (prompt or "").strip()
        if not prompt:
            return 0
        ascii_chars = sum(1 for ch in prompt if ord(ch) < 128)
        non_ascii_chars = len(prompt) - ascii_chars
        ascii_tokens = (ascii_chars + 2) // 3
        return non_ascii_chars + ascii_tokens

    def _estimate_local_file_batch_char_limit(
        self,
        *,
        blocks: list["TextBlock"],
        reference_files: Optional[list[Path]],
        output_language: str,
        translation_style: str,
        include_item_ids: bool,
    ) -> tuple[Optional[int], str | None]:
        reference_files = None
        configured, configured_source = self._get_local_file_batch_limit_info()
        if configured is None or configured <= 0:
            return configured, configured_source
        if self.config is None:
            return configured, configured_source

        ctx_size = getattr(self.config, "local_ai_ctx_size", None)
        if not isinstance(ctx_size, int) or ctx_size <= 0:
            return configured, configured_source

        max_tokens_setting = getattr(self.config, "local_ai_max_tokens", None)
        max_tokens = (
            int(max_tokens_setting)
            if isinstance(max_tokens_setting, int) and max_tokens_setting > 0
            else min(1024, max(0, ctx_size // 2))
        )

        prompt_builder = self._local_prompt_builder
        if prompt_builder is None:
            return configured, configured_source

        min_limit = (
            configured
            if configured < BatchTranslator._MIN_SPLIT_BATCH_CHARS
            else BatchTranslator._MIN_SPLIT_BATCH_CHARS
        )
        candidate = int(configured)
        safety_total = 96

        def build_sample_texts(max_chars: int) -> list[str]:
            texts: list[str] = []
            total = 0
            for block in blocks:
                text = (block.text or "").strip()
                if not text:
                    continue
                text_len = len(text)
                if texts and total + text_len > max_chars:
                    break
                texts.append(text)
                total += text_len
                if total >= max_chars:
                    break
                if len(texts) >= 50:
                    break
            return texts

        for _ in range(6):
            sample_texts = build_sample_texts(candidate)
            if not sample_texts:
                return configured, configured_source
            try:
                prompt = prompt_builder.build_batch(
                    sample_texts,
                    output_language=output_language,
                    translation_style=translation_style,
                    include_item_ids=include_item_ids,
                    reference_files=reference_files,
                )
            except Exception:
                return configured, configured_source

            prompt_tokens = self._estimate_local_prompt_tokens(prompt)
            repeated_prompt_tokens = prompt_tokens * 2 + 2
            total_tokens = repeated_prompt_tokens + max_tokens

            if total_tokens + safety_total <= ctx_size:
                if candidate == configured:
                    return configured, configured_source
                source = (
                    f"{configured_source}+estimated_ctx_limit"
                    if configured_source
                    else "estimated_ctx_limit"
                )
                return candidate, source

            next_candidate = max(min_limit, candidate // 2)
            if next_candidate >= candidate:
                break
            candidate = next_candidate

        source = (
            f"{configured_source}+estimated_ctx_limit"
            if configured_source
            else "estimated_ctx_limit"
        )
        return candidate, source

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
        """翻訳中のみ、バックエンドのウィンドウをUIの背面に同期表示する（対応環境のみ）。"""
        client = self._client
        scope_factory = (
            getattr(client, "ui_window_sync_scope", None) if client else None
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
        reference_files = None
        client = self._get_active_client()
        ui_scope = (
            nullcontext()
            if self._use_local_backend()
            else self._ui_window_sync_scope("translate_single")
        )
        with ui_scope:
            with self._cancel_callback_scope():
                lock = (
                    self._local_call_lock
                    if self._use_local_backend()
                    else (self._client_lock or nullcontext())
                )
                with lock:
                    return client.translate_single(
                        text, prompt, reference_files, on_chunk
                    )

    def _translate_single_with_cancel_on_local(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
        runtime: "LocalAIServerRuntime | None" = None,
    ) -> str:
        """Force a LocalAI translate_single call regardless of translation_backend."""
        reference_files = None
        self._ensure_local_backend()
        client = self._local_client
        if client is None:
            raise RuntimeError("Local AI client not initialized")

        set_cb = getattr(client, "set_cancel_callback", None)
        lock = self._local_call_lock

        if callable(set_cb):
            try:
                set_cb(lambda: self._cancel_event.is_set())
            except Exception:
                set_cb = None

        try:
            with lock:
                if runtime is None:
                    return client.translate_single(
                        text, prompt, reference_files, on_chunk
                    )
                try:
                    return client.translate_single(
                        text,
                        prompt,
                        reference_files,
                        on_chunk,
                        runtime=runtime,
                    )
                except TypeError:
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
        reference_files = None

        try:
            # Build prompt (English-only legacy path)
            has_refs = bool(reference_files)
            prompt = self.prompt_builder.build(text, has_refs, output_language="en")

            # Translate
            result = self._translate_single_with_cancel_on_local(
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
            # Catch specific exceptions from backend calls
            logger.exception("Error during text translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.monotonic() - start_time,
            )

    def detect_language(self, text: str) -> str:
        """
        入力テキストの言語をローカル判定します。

        Priority:
        1. Hiragana/Katakana present → "日本語"
        2. Hangul present → "韓国語"
        3. Latin alphabet dominant → "英語"
        4. CJK only or other → "日本語" (default for Japanese users)

        Note: Language detection is local-only for fast response times.
        Japanese is used as the default fallback since target users are Japanese.

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
        force_simple_prompt: bool = False,
        raw_output: bool = False,
    ) -> TextTranslationResult:
        reference_files = None
        self._ensure_local_backend()
        from yakulingo.services.local_ai_client import strip_prompt_echo
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

        if output_language == "en":
            style = _normalize_text_style(style)

        metadata: dict = {"backend": "local"}
        prebuilt_prompt: str | None = None
        embedded_ref = None
        simple_prompt_mode = bool(force_simple_prompt)

        if simple_prompt_mode:
            prebuilt_prompt = self.prompt_builder.build_simple_prompt(
                text,
                output_language=output_language,
            )
        else:
            if output_language == "en":
                build_with_embed = getattr(
                    local_builder, "build_text_to_en_single_with_embed", None
                )
                if callable(build_with_embed):
                    prebuilt_prompt, embedded_ref = build_with_embed(
                        text,
                        style=style,
                        reference_files=reference_files,
                        detected_language=detected_language,
                    )
                else:
                    embedded_ref = local_builder.build_reference_embed(
                        reference_files, input_text=text
                    )
            else:
                build_with_embed = getattr(
                    local_builder, "build_text_to_jp_with_embed", None
                )
                if callable(build_with_embed):
                    prebuilt_prompt, embedded_ref = build_with_embed(
                        text,
                        reference_files=reference_files,
                        detected_language=detected_language,
                    )
                else:
                    embedded_ref = local_builder.build_reference_embed(
                        reference_files, input_text=text
                    )

            warnings = getattr(embedded_ref, "warnings", None) if embedded_ref else None
            if warnings:
                metadata["reference_warnings"] = warnings
            if bool(getattr(embedded_ref, "truncated", False)):
                metadata["reference_truncated"] = True

        try:
            local_batch_translator = self._local_batch_translator
            max_segment_chars = getattr(
                local_batch_translator, "max_chars_per_batch", None
            )
            runtime = None
            supports_runtime = self._local_translate_single_supports_runtime_param()
            local_translate_single_calls = 0
            skip_runtime_prefetch = False

            if supports_runtime:
                local_client = self._local_client
                if local_client is None:
                    raise RuntimeError("Local AI client not initialized")
                try:
                    from yakulingo.services.local_ai_client import LocalAIClient
                except Exception:
                    LocalAIClient = None
                is_local_ai_client = (
                    isinstance(local_client, LocalAIClient)
                    if LocalAIClient is not None
                    else False
                )
                translate_single_fn = getattr(local_client, "translate_single", None)
                if is_local_ai_client and callable(translate_single_fn):
                    module_name = getattr(translate_single_fn, "__module__", "")
                    if (
                        module_name
                        and module_name != "yakulingo.services.local_ai_client"
                    ):
                        skip_runtime_prefetch = True
                if not skip_runtime_prefetch:
                    ensure_ready = getattr(local_client, "ensure_ready", None)
                    runtime = ensure_ready() if callable(ensure_ready) else None

            def translate_single_local(
                *,
                prompt: str,
                on_chunk: "Callable[[str], None] | None",
                phase: str,
            ) -> str:
                nonlocal local_translate_single_calls
                local_translate_single_calls += 1
                metadata["local_translate_single_calls"] = local_translate_single_calls
                metadata["local_translate_single_phases"] = metadata.get(
                    "local_translate_single_phases", []
                ) + [phase]
                if supports_runtime and runtime is not None:
                    return self._translate_single_with_cancel_on_local(
                        text, prompt, None, on_chunk, runtime=runtime
                    )
                return self._translate_single_with_cancel_on_local(
                    text, prompt, None, on_chunk
                )

            def _translate_segmented_fallback(
                reason: str,
            ) -> TextTranslationResult | None:
                if not (
                    local_batch_translator is not None
                    and isinstance(max_segment_chars, int)
                    and max_segment_chars > 0
                    and len((text or "").strip()) > max_segment_chars
                ):
                    return None

                tokens = _segment_long_text_for_local_text_translation(
                    text, max_segment_chars=max_segment_chars
                )
                blocks: list[TextBlock] = []
                join_spec: list[tuple[str, str]] = []
                block_idx = 0
                for token, should_translate in tokens:
                    if not should_translate:
                        join_spec.append(("raw", token))
                        continue
                    if not token or not token.strip():
                        join_spec.append(("raw", token))
                        continue
                    block_idx += 1
                    block_id = f"text_seg_{block_idx:04d}"
                    blocks.append(
                        TextBlock(
                            id=block_id,
                            text=token,
                            location=f"local_text_segment:{block_idx}",
                        )
                    )
                    join_spec.append((block_id, token))

                metadata["segmented_input"] = True
                metadata["segment_reason"] = reason
                metadata["segment_max_chars"] = max_segment_chars
                metadata["segment_count"] = block_idx

                if blocks:
                    use_single_segment_prompt = simple_prompt_mode or raw_output
                    if use_single_segment_prompt:
                        translated_map: dict[str, str] = {}
                        segment_untranslated = 0
                        for block in blocks:
                            if self._cancel_event.is_set():
                                raise TranslationCancelledError(
                                    "Translation cancelled by user"
                                )
                            if simple_prompt_mode:
                                segment_prompt = (
                                    self.prompt_builder.build_simple_prompt(
                                        block.text,
                                        output_language=output_language,
                                    )
                                )
                            else:
                                if output_language == "en":
                                    segment_prompt = (
                                        local_builder.build_text_to_en_single(
                                            block.text,
                                            style=style,
                                            reference_files=reference_files,
                                            detected_language=detected_language,
                                        )
                                    )
                                else:
                                    segment_prompt = local_builder.build_text_to_jp(
                                        block.text,
                                        reference_files=reference_files,
                                        detected_language=detected_language,
                                    )
                            try:
                                if supports_runtime and runtime is not None:
                                    raw_segment = (
                                        self._translate_single_with_cancel_on_local(
                                            block.text,
                                            segment_prompt,
                                            None,
                                            None,
                                            runtime=runtime,
                                        )
                                    )
                                else:
                                    raw_segment = (
                                        self._translate_single_with_cancel_on_local(
                                            block.text,
                                            segment_prompt,
                                            None,
                                            None,
                                        )
                                    )
                            except TranslationCancelledError:
                                raise
                            except RuntimeError:
                                translated_map[block.id] = (
                                    "" if raw_output else block.text
                                )
                                segment_untranslated += 1
                                continue

                            if raw_output:
                                translated_map[block.id] = raw_segment
                                continue

                            raw_segment = strip_prompt_echo(raw_segment, segment_prompt)
                            translated_piece = _normalize_local_plain_text_output(
                                raw_segment
                            )
                            if not translated_piece or not translated_piece.strip():
                                translated_map[block.id] = block.text
                                segment_untranslated += 1
                                continue
                            translated_map[block.id] = translated_piece

                        metadata["segment_untranslated"] = segment_untranslated
                        metadata["segment_mismatched_batches"] = 0
                    else:
                        batch_result = (
                            local_batch_translator.translate_blocks_with_result(
                                blocks,
                                reference_files=reference_files,
                                on_progress=None,
                                output_language=output_language,
                                translation_style=style,
                                include_item_ids=False,
                            )
                        )
                        if batch_result.cancelled:
                            raise TranslationCancelledError(
                                "Translation cancelled by user"
                            )
                        metadata["segment_untranslated"] = len(
                            batch_result.untranslated_block_ids
                        )
                        metadata["segment_mismatched_batches"] = int(
                            batch_result.mismatched_batch_count
                        )
                        translated_map = batch_result.translations
                else:
                    translated_map = {}

                merged_parts: list[str] = []
                for key, original in join_spec:
                    if key == "raw":
                        merged_parts.append(original)
                        continue
                    merged_parts.append(translated_map.get(key, original))
                merged = "".join(merged_parts)

                if raw_output:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[
                            TranslationOption(
                                text=merged,
                                explanation="",
                                style=style if output_language == "en" else None,
                            )
                        ],
                        output_language=output_language,
                        detected_language=detected_language,
                        metadata=metadata,
                    )

                if output_language == "en":
                    if _is_text_output_language_mismatch(merged, "en"):
                        metadata["output_language_mismatch"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message="翻訳結果が英語ではありませんでした（出力言語ガード）",
                            metadata=metadata,
                        )
                    if _looks_incomplete_translation_to_en(text, merged):
                        metadata["incomplete_translation"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message="翻訳結果が不完全でした（短すぎます）。",
                            metadata=metadata,
                        )
                    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                        source_text=text,
                        translated_text=merged,
                    )
                    if fixed:
                        merged = fixed_text
                        metadata["to_en_numeric_unit_correction"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[
                            TranslationOption(text=merged, explanation="", style=style)
                        ],
                        output_language=output_language,
                        detected_language=detected_language,
                        metadata=metadata,
                    )

                if _is_text_output_language_mismatch(merged, "jp"):
                    metadata["output_language_mismatch"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳結果が日本語ではありませんでした（出力言語ガード）",
                        metadata=metadata,
                    )
                fixed_text, fixed = _fix_to_jp_oku_numeric_unit_if_possible(merged)
                if fixed:
                    merged = fixed_text
                    metadata["to_jp_oku_correction"] = True
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[TranslationOption(text=merged, explanation="")],
                    output_language=output_language,
                    detected_language=detected_language,
                    metadata=metadata,
                )

            if output_language == "en":
                prompt = prebuilt_prompt or local_builder.build_text_to_en_single(
                    text,
                    style=style,
                    reference_files=reference_files,
                    detected_language=detected_language,
                )
                stream_handler = _wrap_local_streaming_on_chunk(
                    on_chunk,
                    expected_output_language=output_language,
                    parse_json=False,
                    prompt=prompt,
                )
                try:
                    raw = translate_single_local(
                        prompt=prompt,
                        on_chunk=stream_handler,
                        phase="en_initial",
                    )
                except RuntimeError as e:
                    if str(e).startswith("LOCAL_PROMPT_TOO_LONG:"):
                        fallback = _translate_segmented_fallback(
                            "LOCAL_PROMPT_TOO_LONG"
                        )
                        if fallback is not None:
                            return fallback
                    raise
                raw = strip_prompt_echo(raw, prompt)
                if raw_output:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[
                            TranslationOption(
                                text=raw or "",
                                explanation="",
                                style=style,
                            )
                        ],
                        output_language=output_language,
                        detected_language=detected_language,
                        metadata=metadata,
                    )
                translation = _normalize_local_plain_text_output(raw)
                if not translation:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="ローカルAIの応答が空でした（プレーンテキスト）",
                        metadata=metadata,
                    )

                needs_output_language_retry = _is_text_output_language_mismatch(
                    translation, "en"
                )
                needs_ellipsis_retry = _is_ellipsis_only_translation(text, translation)
                needs_placeholder_retry = _is_placeholder_only_translation(
                    text, translation
                )
                if simple_prompt_mode:
                    if needs_output_language_retry:
                        metadata["output_language_mismatch"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message="翻訳結果が英語ではありませんでした（出力言語ガード）",
                            metadata=metadata,
                        )
                    if needs_ellipsis_retry:
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message=(
                                "ローカルAIの出力が「...」のみでした。モデル/設定を確認してください。"
                            ),
                            metadata=metadata,
                        )
                    if needs_placeholder_retry:
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message=(
                                "ローカルAIの出力がプレースホルダーのみでした。モデル/設定を確認してください。"
                            ),
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
                    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        translation = fixed_text
                        metadata["to_en_numeric_unit_correction"] = True
                    fixed_text, fixed = _fix_to_en_negative_parens_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        translation = fixed_text
                        metadata["to_en_negative_correction"] = True
                    fixed_text, fixed = _fix_to_en_k_notation_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        translation = fixed_text
                        metadata["to_en_k_correction"] = True
                    fixed_text, fixed = _fix_to_en_month_abbrev_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        translation = fixed_text
                        metadata["to_en_month_abbrev_correction"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[
                            TranslationOption(
                                text=translation,
                                explanation="",
                                style=style,
                            )
                        ],
                        output_language=output_language,
                        detected_language=detected_language,
                        metadata=metadata,
                    )
                if (
                    not needs_output_language_retry
                    and not needs_ellipsis_retry
                    and not needs_placeholder_retry
                    and _looks_incomplete_translation_to_en(text, translation)
                ):
                    metadata["incomplete_translation"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳結果が不完全でした（短すぎます）。",
                        metadata=metadata,
                    )

                if not needs_output_language_retry:
                    fixed_text, fixed = _fix_to_en_negative_parens_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        translation = fixed_text
                        metadata["to_en_negative_correction"] = True

                    fixed_text, fixed = _fix_to_en_k_notation_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        translation = fixed_text
                        metadata["to_en_k_correction"] = True

                    fixed_text, fixed = _fix_to_en_month_abbrev_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        translation = fixed_text
                        metadata["to_en_month_abbrev_correction"] = True

                needs_length_retry = False
                length_limit = 0
                length_ratio = 0.0
                length_source_count = len((text or "").strip())
                length_translation_count = len((translation or "").strip())
                if not needs_output_language_retry and detected_language == "日本語":
                    (
                        needs_length_retry,
                        length_limit,
                        length_ratio,
                        length_source_count,
                        length_translation_count,
                    ) = _needs_to_en_length_retry(text, translation, style)
                    if length_limit > 0:
                        metadata["to_en_length_limit"] = length_limit
                        metadata["to_en_length_ratio"] = length_ratio
                        metadata["to_en_length_source_chars"] = length_source_count
                        metadata["to_en_length_translation_chars"] = (
                            length_translation_count
                        )
                    if needs_length_retry:
                        metadata["to_en_length_violation"] = True

                needs_numeric_rule_retry = False
                needs_rule_retry = False
                rule_retry_reasons: list[str] = []

                if False:
                    if _LOCAL_AI_TIMING_ENABLED:
                        retry_reasons: list[str] = []
                        if needs_output_language_retry:
                            retry_reasons.append("output_language")
                        if needs_ellipsis_retry:
                            retry_reasons.append("ellipsis")
                        if needs_placeholder_retry:
                            retry_reasons.append("placeholder")
                        if needs_numeric_rule_retry:
                            retry_reasons.append("numeric_rule")
                        if needs_rule_retry:
                            if rule_retry_reasons:
                                retry_reasons.append(
                                    f"rule({','.join(rule_retry_reasons)})"
                                )
                            else:
                                retry_reasons.append("rule")
                        logger.info(
                            "[DIAG] LocalText retry scheduled: %s (output=%s style=%s chars=%d)",
                            "+".join(retry_reasons) if retry_reasons else "unknown",
                            output_language,
                            style,
                            len(text or ""),
                        )
                    retry_parts: list[str] = []
                    if needs_output_language_retry:
                        retry_parts.append(
                            BatchTranslator._EN_STRICT_OUTPUT_LANGUAGE_INSTRUCTION
                        )
                    if needs_ellipsis_retry:
                        retry_parts.append(_LOCAL_AI_ELLIPSIS_RETRY_INSTRUCTION)
                    if needs_placeholder_retry:
                        retry_parts.append(_LOCAL_AI_PLACEHOLDER_RETRY_INSTRUCTION)
                    if needs_numeric_rule_retry:
                        retry_parts.append(_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION)
                    if needs_rule_retry:
                        retry_parts.append(
                            _build_to_en_rule_retry_instruction(rule_retry_reasons)
                        )

                    retry_prompt = local_builder.build_text_to_en_single(
                        text,
                        style=style,
                        reference_files=reference_files,
                        detected_language=detected_language,
                        extra_instruction="\n".join(retry_parts).strip(),
                    )
                    try:
                        retry_raw = translate_single_local(
                            prompt=retry_prompt,
                            on_chunk=None,
                            phase="en_retry",
                        )
                    except RuntimeError as e:
                        if str(e).startswith("LOCAL_PROMPT_TOO_LONG:"):
                            fallback = _translate_segmented_fallback(
                                "LOCAL_PROMPT_TOO_LONG"
                            )
                            if fallback is not None:
                                return fallback
                        raise
                    retry_raw = strip_prompt_echo(retry_raw, retry_prompt)
                    retry_translation = _normalize_local_plain_text_output(retry_raw)
                    if not retry_translation:
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message="ローカルAIの応答が空でした（プレーンテキスト）",
                            metadata=metadata,
                        )
                    if _is_placeholder_only_translation(text, retry_translation):
                        if needs_placeholder_retry:
                            metadata["placeholder_retry"] = True
                        metadata["placeholder_retry_failed"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message=(
                                "ローカルAIの出力がプレースホルダーのみでした。モデル/設定を確認してください。"
                            ),
                            metadata=metadata,
                        )
                    if _is_ellipsis_only_translation(text, retry_translation):
                        if needs_ellipsis_retry:
                            metadata["ellipsis_retry"] = True
                        metadata["ellipsis_retry_failed"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message=(
                                "ローカルAIの出力が「...」のみでした。モデル/設定を確認してください。"
                            ),
                            metadata=metadata,
                        )
                    translation = retry_translation
                    if needs_output_language_retry:
                        metadata["output_language_retry"] = True
                    if needs_ellipsis_retry:
                        metadata["ellipsis_retry"] = True
                    if needs_placeholder_retry:
                        metadata["placeholder_retry"] = True
                    if needs_numeric_rule_retry:
                        metadata["to_en_numeric_rule_retry"] = True
                        metadata["to_en_numeric_rule_retry_styles"] = [style]
                    if needs_rule_retry:
                        metadata["to_en_rule_retry"] = True
                        metadata["to_en_rule_retry_reasons"] = list(rule_retry_reasons)
                    if detected_language == "日本語":
                        (
                            needs_length_retry_after,
                            length_limit_after,
                            length_ratio_after,
                            length_source_count_after,
                            length_translation_count_after,
                        ) = _needs_to_en_length_retry(text, translation, style)
                        if length_limit_after > 0:
                            metadata["to_en_length_limit"] = length_limit_after
                            metadata["to_en_length_ratio"] = length_ratio_after
                            metadata["to_en_length_source_chars"] = (
                                length_source_count_after
                            )
                            metadata["to_en_length_translation_chars"] = (
                                length_translation_count_after
                            )
                        length_violation_after = (
                            length_limit_after > 0
                            and length_translation_count_after > length_limit_after
                        )
                        if length_violation_after:
                            metadata["to_en_length_violation"] = True
                        needs_length_retry_after = False
                        if needs_length_retry_after:
                            metadata["to_en_length_violation"] = True
                            if needs_length_retry:
                                metadata["to_en_length_retry_failed"] = True
                            length_error = (
                                f"英訳が長さ制約を満たせませんでした（{length_translation_count_after}/{length_limit_after}文字）"
                                if length_limit_after > 0
                                else "英訳が長さ制約を満たせませんでした"
                            )
                            return TextTranslationResult(
                                source_text=text,
                                source_char_count=len(text),
                                output_language=output_language,
                                detected_language=detected_language,
                                error_message=length_error,
                                metadata=metadata,
                            )
                    if _LOCAL_AI_TIMING_ENABLED:
                        logger.info(
                            "[DIAG] LocalText retry response received (output=%s style=%s chars=%d)",
                            output_language,
                            style,
                            len(text or ""),
                        )

                if _is_text_output_language_mismatch(translation, "en"):
                    metadata["output_language_mismatch"] = True
                    if metadata.get("output_language_retry"):
                        metadata["output_language_retry_failed"] = True
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
                fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                    source_text=text,
                    translated_text=translation,
                )
                if fixed:
                    translation = fixed_text
                    metadata["to_en_numeric_unit_correction"] = True

                fixed_text, fixed = _fix_to_en_negative_parens_if_possible(
                    source_text=text,
                    translated_text=translation,
                )
                if fixed:
                    translation = fixed_text
                    metadata["to_en_negative_correction"] = True

                fixed_text, fixed = _fix_to_en_k_notation_if_possible(
                    source_text=text,
                    translated_text=translation,
                )
                if fixed:
                    translation = fixed_text
                    metadata["to_en_k_correction"] = True

                fixed_text, fixed = _fix_to_en_month_abbrev_if_possible(
                    source_text=text,
                    translated_text=translation,
                )
                if fixed:
                    translation = fixed_text
                    metadata["to_en_month_abbrev_correction"] = True

                if metadata.get("to_en_rule_retry"):
                    remaining = _collect_to_en_rule_retry_reasons(text, translation)
                    if remaining:
                        metadata["to_en_rule_retry_failed"] = True
                        metadata["to_en_rule_retry_failed_reasons"] = remaining
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message="翻訳結果が翻訳ルールに従っていませんでした（k/負数/月略称）",
                            metadata=metadata,
                        )
                if detected_language == "日本語":
                    (
                        needs_length_retry_final,
                        length_limit_final,
                        length_ratio_final,
                        length_source_count_final,
                        length_translation_count_final,
                    ) = _needs_to_en_length_retry(text, translation, style)
                    if length_limit_final > 0:
                        metadata["to_en_length_limit"] = length_limit_final
                        metadata["to_en_length_ratio"] = length_ratio_final
                        metadata["to_en_length_source_chars"] = (
                            length_source_count_final
                        )
                        metadata["to_en_length_translation_chars"] = (
                            length_translation_count_final
                        )
                    length_violation_final = (
                        length_limit_final > 0
                        and length_translation_count_final > length_limit_final
                    )
                    if length_violation_final:
                        metadata["to_en_length_violation"] = True
                    needs_length_retry_final = False
                    if needs_length_retry_final:
                        metadata["to_en_length_violation"] = True
                        if metadata.get("to_en_length_retry"):
                            metadata["to_en_length_retry_failed"] = True
                        length_error = (
                            f"英訳が長さ制約を満たせませんでした（{length_translation_count_final}/{length_limit_final}文字）"
                            if length_limit_final > 0
                            else "英訳が長さ制約を満たせませんでした"
                        )
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message=length_error,
                            metadata=metadata,
                        )
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[
                        TranslationOption(text=translation, explanation="", style=style)
                    ],
                    output_language=output_language,
                    detected_language=detected_language,
                    metadata=metadata,
                )

            prompt = prebuilt_prompt or local_builder.build_text_to_jp(
                text,
                reference_files=reference_files,
                detected_language=detected_language,
            )
            stream_handler = _wrap_local_streaming_on_chunk(
                on_chunk,
                expected_output_language=output_language,
                parse_json=False,
                prompt=prompt,
            )
            try:
                raw = translate_single_local(
                    prompt=prompt,
                    on_chunk=stream_handler,
                    phase="jp_initial",
                )
            except RuntimeError as e:
                if str(e).startswith("LOCAL_PROMPT_TOO_LONG:"):
                    fallback = _translate_segmented_fallback("LOCAL_PROMPT_TOO_LONG")
                    if fallback is not None:
                        return fallback
                raise
            raw = strip_prompt_echo(raw, prompt)
            if raw_output:
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[TranslationOption(text=raw or "", explanation="")],
                    output_language=output_language,
                    detected_language=detected_language,
                    metadata=metadata,
                )
            translation = _normalize_local_plain_text_output(raw)
            if not translation:
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message="ローカルAIの応答が空でした（プレーンテキスト）",
                    metadata=metadata,
                )
            needs_ellipsis_retry = _is_ellipsis_only_translation(text, translation)
            needs_placeholder_retry = _is_placeholder_only_translation(
                text, translation
            )
            needs_output_language_retry = _is_text_output_language_mismatch(
                translation, "jp"
            )
            if simple_prompt_mode:
                if needs_output_language_retry:
                    metadata["output_language_mismatch"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳結果が日本語ではありませんでした（出力言語ガード）",
                        metadata=metadata,
                    )
                if needs_ellipsis_retry:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message=(
                            "ローカルAIの出力が「...」のみでした。モデル/設定を確認してください。"
                        ),
                        metadata=metadata,
                    )
                if needs_placeholder_retry:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message=(
                            "ローカルAIの出力がプレースホルダーのみでした。モデル/設定を確認してください。"
                        ),
                        metadata=metadata,
                    )
                fixed_text, fixed = _fix_to_jp_oku_numeric_unit_if_possible(translation)
                if fixed:
                    translation = fixed_text
                    metadata["to_jp_oku_correction"] = True
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[TranslationOption(text=translation, explanation="")],
                    output_language=output_language,
                    detected_language=detected_language,
                    metadata=metadata,
                )
            if False:
                if _LOCAL_AI_TIMING_ENABLED:
                    reasons: list[str] = []
                    if needs_output_language_retry:
                        reasons.append("output_language")
                    if needs_ellipsis_retry:
                        reasons.append("ellipsis")
                    if needs_placeholder_retry:
                        reasons.append("placeholder")
                    logger.info(
                        "[DIAG] LocalText retry scheduled: %s (output=%s chars=%d)",
                        "+".join(reasons) if reasons else "unknown",
                        output_language,
                        len(text or ""),
                    )
                retry_parts: list[str] = []
                if needs_output_language_retry:
                    retry_parts.append(
                        BatchTranslator._JP_STRICT_OUTPUT_LANGUAGE_INSTRUCTION
                    )
                if needs_ellipsis_retry:
                    retry_parts.append(_LOCAL_AI_ELLIPSIS_RETRY_INSTRUCTION)
                if needs_placeholder_retry:
                    retry_parts.append(_LOCAL_AI_PLACEHOLDER_RETRY_INSTRUCTION)
                retry_prompt = _insert_extra_instruction(
                    prompt, "\n".join(retry_parts).strip()
                )
                try:
                    retry_raw = translate_single_local(
                        prompt=retry_prompt,
                        on_chunk=None,
                        phase="jp_retry",
                    )
                except RuntimeError as e:
                    if str(e).startswith("LOCAL_PROMPT_TOO_LONG:"):
                        fallback = _translate_segmented_fallback(
                            "LOCAL_PROMPT_TOO_LONG"
                        )
                        if fallback is not None:
                            return fallback
                    raise
                retry_raw = strip_prompt_echo(retry_raw, retry_prompt)
                retry_translation = _normalize_local_plain_text_output(retry_raw)
                if (
                    retry_translation
                    and not _is_text_output_language_mismatch(retry_translation, "jp")
                    and not _is_ellipsis_only_translation(text, retry_translation)
                    and not _is_placeholder_only_translation(text, retry_translation)
                ):
                    translation = retry_translation
                    if needs_output_language_retry:
                        metadata["output_language_retry"] = True
                    if needs_ellipsis_retry:
                        metadata["ellipsis_retry"] = True
                    if needs_placeholder_retry:
                        metadata["placeholder_retry"] = True
                else:
                    if retry_translation and _is_placeholder_only_translation(
                        text, retry_translation
                    ):
                        if needs_placeholder_retry:
                            metadata["placeholder_retry"] = True
                        metadata["placeholder_retry_failed"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message=(
                                "ローカルAIの出力がプレースホルダーのみでした。モデル/設定を確認してください。"
                            ),
                            metadata=metadata,
                        )
                    if retry_translation and _is_ellipsis_only_translation(
                        text, retry_translation
                    ):
                        if needs_ellipsis_retry:
                            metadata["ellipsis_retry"] = True
                        metadata["ellipsis_retry_failed"] = True
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            output_language=output_language,
                            detected_language=detected_language,
                            error_message=(
                                "ローカルAIの出力が「...」のみでした。モデル/設定を確認してください。"
                            ),
                            metadata=metadata,
                        )
                    metadata["output_language_mismatch"] = True
                    if needs_output_language_retry:
                        metadata["output_language_retry_failed"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳結果が日本語ではありませんでした（出力言語ガード）",
                        metadata=metadata,
                    )
            fixed_text, fixed = _fix_to_jp_oku_numeric_unit_if_possible(translation)
            if fixed:
                translation = fixed_text
                metadata["to_jp_oku_correction"] = True
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
        reference_files = None
        self._ensure_local_backend()
        from yakulingo.services.local_ai_client import (
            is_truncated_json,
            parse_text_single_translation,
            parse_text_to_en_3style,
            parse_text_to_en_style_subset,
            strip_prompt_echo,
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

        desired_styles = [s for s in TEXT_STYLE_ORDER if s in styles] if styles else []
        if not desired_styles:
            desired_styles = list(TEXT_STYLE_ORDER)

        metadata: dict = {"backend": "local"}
        runtime = None
        supports_runtime = self._local_translate_single_supports_runtime_param()
        local_translate_single_calls = 0
        skip_runtime_prefetch = False

        if supports_runtime:
            local_client = self._local_client
            if local_client is None:
                raise RuntimeError("Local AI client not initialized")
            try:
                from yakulingo.services.local_ai_client import LocalAIClient
            except Exception:
                LocalAIClient = None
            is_local_ai_client = (
                isinstance(local_client, LocalAIClient)
                if LocalAIClient is not None
                else False
            )
            translate_single_fn = getattr(local_client, "translate_single", None)
            if is_local_ai_client and callable(translate_single_fn):
                module_name = getattr(translate_single_fn, "__module__", "")
                if module_name and module_name != "yakulingo.services.local_ai_client":
                    skip_runtime_prefetch = True
            if not skip_runtime_prefetch:
                ensure_ready = getattr(local_client, "ensure_ready", None)
                runtime = ensure_ready() if callable(ensure_ready) else None

        def _mark_style_list(key: str, style: str) -> None:
            style_list = metadata.setdefault(key, [])
            if style not in style_list:
                style_list.append(style)

        def translate_single_local(
            *,
            prompt: str,
            on_chunk_local: "Callable[[str], None] | None",
            phase: str,
        ) -> str:
            nonlocal local_translate_single_calls
            local_translate_single_calls += 1
            metadata["local_translate_single_calls"] = local_translate_single_calls
            metadata["local_translate_single_phases"] = metadata.get(
                "local_translate_single_phases", []
            ) + [phase]
            if supports_runtime and runtime is not None:
                return self._translate_single_with_cancel_on_local(
                    text, prompt, None, on_chunk_local, runtime=runtime
                )
            return self._translate_single_with_cancel_on_local(
                text, prompt, None, on_chunk_local
            )

        def _parse_styles(
            raw_result: str,
            requested_styles: list[str],
        ) -> dict[str, tuple[str, str]]:
            parsed = parse_text_to_en_3style(raw_result)
            has_style_sections = bool(_RE_STYLE_SECTION.search(raw_result))
            if (not parsed or len(parsed) < 2) and has_style_sections:
                parsed_options = self._parse_style_comparison_result(raw_result)
                parsed = {
                    opt.style: (opt.text, opt.explanation or "")
                    for opt in parsed_options
                    if opt.style
                }
            if not parsed:
                translation, explanation = parse_text_single_translation(raw_result)
                if translation:
                    fallback_style = (
                        requested_styles[0] if requested_styles else "minimal"
                    )
                    parsed = {fallback_style: (translation, explanation or "")}
            return parsed

        def _apply_safe_fixes(style: str, translation: str) -> str:
            if _is_text_output_language_mismatch(translation, "en"):
                return translation

            fixed_text, fixed = _fix_to_en_negative_parens_if_possible(
                source_text=text,
                translated_text=translation,
            )
            if fixed:
                translation = fixed_text
                metadata["to_en_negative_correction"] = True
                _mark_style_list("to_en_negative_correction_styles", style)

            fixed_text, fixed = _fix_to_en_k_notation_if_possible(
                source_text=text,
                translated_text=translation,
            )
            if fixed:
                translation = fixed_text
                metadata["to_en_k_correction"] = True
                _mark_style_list("to_en_k_correction_styles", style)

            fixed_text, fixed = _fix_to_en_month_abbrev_if_possible(
                source_text=text,
                translated_text=translation,
            )
            if fixed:
                translation = fixed_text
                metadata["to_en_month_abbrev_correction"] = True
                _mark_style_list("to_en_month_abbrev_correction_styles", style)

            return translation

        def _finalize_styles(
            translations: dict[str, str],
            explanations: dict[str, str],
            *,
            numeric_retry_styles: set[str],
        ) -> TextTranslationResult:
            for style, current in list(translations.items()):
                fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                    source_text=text,
                    translated_text=current,
                )
                if fixed:
                    translations[style] = fixed_text
                    metadata["to_en_numeric_unit_correction"] = True
                    _mark_style_list("to_en_numeric_unit_correction_styles", style)

            for style, current in list(translations.items()):
                translations[style] = _apply_safe_fixes(style, current)

            mismatch_styles = {
                style
                for style, current in translations.items()
                if _is_text_output_language_mismatch(current, "en")
            }
            if mismatch_styles:
                metadata["output_language_mismatch"] = True
                metadata["output_language_mismatch_styles"] = sorted(mismatch_styles)
                if metadata.get("output_language_retry"):
                    metadata["output_language_retry_failed"] = True
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language="en",
                    detected_language=detected_language,
                    error_message="翻訳結果が英語ではありませんでした（出力言語ガード）",
                    metadata=metadata,
                )

            incomplete_styles = {
                style
                for style, current in translations.items()
                if _looks_incomplete_translation_to_en(text, current)
            }
            if incomplete_styles:
                metadata["incomplete_translation"] = True
                metadata["incomplete_translation_styles"] = sorted(incomplete_styles)
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language="en",
                    detected_language=detected_language,
                    error_message="翻訳結果が不完全でした（短すぎます）。",
                    metadata=metadata,
                )

            if numeric_retry_styles:
                remaining_numeric = {
                    style
                    for style in numeric_retry_styles
                    if style in translations
                    and _needs_to_en_numeric_rule_retry_conservative(
                        text, translations[style]
                    )
                }
                if remaining_numeric:
                    metadata["to_en_numeric_rule_retry_failed"] = True
                    metadata["to_en_numeric_rule_retry_failed_styles"] = sorted(
                        remaining_numeric
                    )

            if metadata.get("to_en_rule_retry"):
                remaining_reasons: set[str] = set()
                for current in translations.values():
                    remaining_reasons.update(
                        _collect_to_en_rule_retry_reasons(text, current)
                    )
                if remaining_reasons:
                    metadata["to_en_rule_retry_failed"] = True
                    metadata["to_en_rule_retry_failed_reasons"] = sorted(
                        remaining_reasons
                    )
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language="en",
                        detected_language=detected_language,
                        error_message="翻訳結果が翻訳ルールに従っていませんでした（k/負数/月略称）",
                        metadata=metadata,
                    )

            options: list[TranslationOption] = []
            for style in desired_styles:
                current = translations.get(style)
                if not current:
                    continue
                options.append(
                    TranslationOption(
                        text=current,
                        explanation=explanations.get(style, ""),
                        style=style,
                    )
                )

            if not options:
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language="en",
                    detected_language=detected_language,
                    error_message="ローカルAIの応答(JSON)を解析できませんでした（詳細はログを確認してください）",
                    metadata=metadata,
                )

            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                options=options,
                output_language="en",
                detected_language=detected_language,
                metadata=metadata,
            )

        try:
            prompt = local_builder.build_text_to_en_3style(
                text,
                reference_files=reference_files,
                detected_language=detected_language,
            )
            stream_handler = _wrap_local_streaming_on_chunk(
                on_chunk,
                expected_output_language="en",
                parse_json=True,
                prompt=prompt,
            )
            try:
                raw_result = translate_single_local(
                    prompt=prompt,
                    on_chunk_local=stream_handler,
                    phase="en_initial",
                )
            except RuntimeError as e:
                if str(e).startswith("LOCAL_PROMPT_TOO_LONG:"):
                    return self._translate_text_with_options_local(
                        text=text,
                        reference_files=reference_files,
                        style="minimal",
                        detected_language=detected_language,
                        output_language="en",
                        on_chunk=on_chunk,
                    )
                raise

            raw_result = strip_prompt_echo(raw_result, prompt)
            parsed = _parse_styles(raw_result, desired_styles)
            if not parsed:
                error_message = "ローカルAIの応答(JSON)を解析できませんでした（詳細はログを確認してください）"
                if is_truncated_json(raw_result):
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

            translations = {
                style: value[0] for style, value in parsed.items() if value[0]
            }
            explanations = {style: (value[1] or "") for style, value in parsed.items()}

            options_hint = '"options"' in raw_result

            mismatch_styles = {
                style
                for style, current in translations.items()
                if _is_text_output_language_mismatch(current, "en")
            }
            ellipsis_styles = {
                style
                for style, current in translations.items()
                if _is_ellipsis_only_translation(text, current)
            }
            placeholder_styles = {
                style
                for style, current in translations.items()
                if _is_placeholder_only_translation(text, current)
            }

            numeric_rule_retry_styles: set[str] = set()
            rule_retry_reasons: set[str] = set()
            for style, current in list(translations.items()):
                if style in mismatch_styles:
                    continue
                translations[style] = _apply_safe_fixes(style, current)

            incomplete_styles = {
                style
                for style, current in translations.items()
                if _looks_incomplete_translation_to_en(text, current)
            }
            if (
                incomplete_styles
                and incomplete_styles == set(translations.keys())
                and not mismatch_styles
                and not ellipsis_styles
                and not placeholder_styles
            ):
                metadata["incomplete_translation"] = True
                metadata["incomplete_translation_styles"] = sorted(incomplete_styles)
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language="en",
                    detected_language=detected_language,
                    error_message="翻訳結果が不完全でした（短すぎます）。",
                    metadata=metadata,
                )

            for style, current in translations.items():
                if style in mismatch_styles:
                    continue
                if _needs_to_en_numeric_rule_retry_conservative_after_safe_fix(
                    text, current
                ):
                    numeric_rule_retry_styles.add(style)
                for reason in _collect_to_en_rule_retry_reasons(text, current):
                    rule_retry_reasons.add(reason)
                    _mark_style_list("to_en_rule_retry_styles", style)

            needs_retry = bool(
                mismatch_styles
                or ellipsis_styles
                or placeholder_styles
                or numeric_rule_retry_styles
                or rule_retry_reasons
            )

            if not needs_retry:
                incomplete_styles = {
                    style
                    for style, current in translations.items()
                    if _looks_incomplete_translation_to_en(text, current)
                }
                if incomplete_styles:
                    metadata["incomplete_translation"] = True
                    metadata["incomplete_translation_styles"] = sorted(
                        incomplete_styles
                    )
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language="en",
                        detected_language=detected_language,
                        error_message="翻訳結果が不完全でした（短すぎます）。",
                        metadata=metadata,
                    )

            if False:
                retry_parts: list[str] = []
                if mismatch_styles:
                    retry_parts.append(
                        BatchTranslator._EN_STRICT_OUTPUT_LANGUAGE_INSTRUCTION
                    )
                    metadata["output_language_retry"] = True
                    metadata["output_language_retry_styles"] = sorted(mismatch_styles)
                if ellipsis_styles:
                    retry_parts.append(_LOCAL_AI_ELLIPSIS_RETRY_INSTRUCTION)
                    metadata["ellipsis_retry"] = True
                    metadata["ellipsis_retry_styles"] = sorted(ellipsis_styles)
                if placeholder_styles:
                    retry_parts.append(_LOCAL_AI_PLACEHOLDER_RETRY_INSTRUCTION)
                    metadata["placeholder_retry"] = True
                    metadata["placeholder_retry_styles"] = sorted(placeholder_styles)
                if numeric_rule_retry_styles:
                    retry_parts.append(_TEXT_TO_EN_NUMERIC_RULE_INSTRUCTION)
                    metadata["to_en_numeric_rule_retry"] = True
                    metadata["to_en_numeric_rule_retry_styles"] = sorted(
                        numeric_rule_retry_styles
                    )
                if rule_retry_reasons:
                    retry_parts.append(
                        _build_to_en_rule_retry_instruction(sorted(rule_retry_reasons))
                    )
                    metadata["to_en_rule_retry"] = True
                    metadata["to_en_rule_retry_reasons"] = sorted(rule_retry_reasons)

                retry_prompt = local_builder.build_text_to_en_3style(
                    text,
                    reference_files=reference_files,
                    detected_language=detected_language,
                    extra_instruction="\n".join(retry_parts).strip(),
                )
                try:
                    retry_raw = translate_single_local(
                        prompt=retry_prompt,
                        on_chunk_local=None,
                        phase="en_retry",
                    )
                except RuntimeError as e:
                    if str(e).startswith("LOCAL_PROMPT_TOO_LONG:"):
                        return self._translate_text_with_options_local(
                            text=text,
                            reference_files=reference_files,
                            style="minimal",
                            detected_language=detected_language,
                            output_language="en",
                            on_chunk=on_chunk,
                        )
                    raise
                retry_raw = strip_prompt_echo(retry_raw, retry_prompt)
                raw_result = retry_raw
                options_hint = options_hint or '"options"' in raw_result
                parsed_retry = _parse_styles(retry_raw, desired_styles)
                if not parsed_retry:
                    error_message = "ローカルAIの応答(JSON)を解析できませんでした（詳細はログを確認してください）"
                    if is_truncated_json(retry_raw):
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

                translations = {
                    style: value[0] for style, value in parsed_retry.items() if value[0]
                }
                explanations = {
                    style: (value[1] or "") for style, value in parsed_retry.items()
                }

                mismatch_styles = {
                    style
                    for style, current in translations.items()
                    if _is_text_output_language_mismatch(current, "en")
                }
                placeholder_styles = {
                    style
                    for style, current in translations.items()
                    if _is_placeholder_only_translation(text, current)
                }
                if placeholder_styles:
                    metadata["placeholder_retry_failed"] = True
                    metadata["placeholder_retry_failed_styles"] = sorted(
                        placeholder_styles
                    )
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language="en",
                        detected_language=detected_language,
                        error_message="ローカルAIの出力がプレースホルダーのみでした。モデル/設定を確認してください。",
                        metadata=metadata,
                    )
                ellipsis_styles = {
                    style
                    for style, current in translations.items()
                    if _is_ellipsis_only_translation(text, current)
                }
                if ellipsis_styles:
                    metadata["ellipsis_retry_failed"] = True
                    metadata["ellipsis_retry_failed_styles"] = sorted(ellipsis_styles)
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language="en",
                        detected_language=detected_language,
                        error_message="ローカルAIの出力が「...」のみでした。モデル/設定を確認してください。",
                        metadata=metadata,
                    )
                if mismatch_styles:
                    metadata["output_language_mismatch"] = True
                    metadata["output_language_mismatch_styles"] = sorted(
                        mismatch_styles
                    )
                    if metadata.get("output_language_retry"):
                        metadata["output_language_retry_failed"] = True
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language="en",
                        detected_language=detected_language,
                        error_message="翻訳結果が英語ではありませんでした（出力言語ガード）",
                        metadata=metadata,
                    )

                for style, current in list(translations.items()):
                    translations[style] = _apply_safe_fixes(style, current)

            missing_styles = [s for s in desired_styles if s not in translations]
            if options_hint and missing_styles:
                missing_prompt = local_builder.build_text_to_en_missing_styles(
                    text,
                    styles=missing_styles,
                    reference_files=reference_files,
                    detected_language=detected_language,
                )
                try:
                    missing_raw = translate_single_local(
                        prompt=missing_prompt,
                        on_chunk_local=None,
                        phase="en_missing_styles",
                    )
                except RuntimeError as e:
                    if not str(e).startswith("LOCAL_PROMPT_TOO_LONG:"):
                        raise
                    missing_raw = ""
                if missing_raw:
                    missing_raw = strip_prompt_echo(missing_raw, missing_prompt)
                if missing_raw:
                    parsed_missing = _parse_styles(missing_raw, missing_styles)
                    subset = parse_text_to_en_style_subset(missing_raw, missing_styles)
                    if subset:
                        parsed_missing.update(subset)
                    for style, value in parsed_missing.items():
                        translation_value = value[0]
                        if not translation_value:
                            continue
                        translation_value = _apply_safe_fixes(style, translation_value)
                        if _is_text_output_language_mismatch(translation_value, "en"):
                            continue
                        if _is_placeholder_only_translation(text, translation_value):
                            continue
                        if _is_ellipsis_only_translation(text, translation_value):
                            continue
                        translations[style] = translation_value
                        explanations[style] = value[1] or ""

            return _finalize_styles(
                translations,
                explanations,
                numeric_retry_styles=numeric_rule_retry_styles,
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

    def _translate_text_with_options_via_prompt_builder(
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
        reference_files = None
        backend_call_count = 0
        backend_call_phases: list[str] = []

        def translate_single_tracked(
            phase: str,
            source_text: str,
            prompt: str,
            reference_files: Optional[list[Path]] = None,
            on_chunk: "Callable[[str], None] | None" = None,
        ) -> str:
            nonlocal backend_call_count
            backend_call_count += 1
            backend_call_phases.append(phase)
            return translate_single(source_text, prompt, reference_files, on_chunk)

        def attach_backend_telemetry(
            result: TextTranslationResult,
        ) -> TextTranslationResult:
            metadata = dict(result.metadata) if result.metadata else {}
            metadata.setdefault("backend", "local")
            metadata["backend_call_count"] = backend_call_count
            metadata["backend_call_phases"] = list(backend_call_phases)
            result.metadata = metadata
            return result

        if output_language == "en":
            template = self.prompt_builder.get_text_template(
                output_language="en",
                translation_style=style,
            )
            if not template:
                return attach_backend_telemetry(
                    TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="Missing text template",
                    )
                )

            if reference_files:
                reference_section = REFERENCE_INSTRUCTION
                files_to_attach = reference_files
            else:
                reference_section = ""
                files_to_attach = None

            def build_compare_prompt() -> str:
                return self.prompt_builder._apply_placeholders(
                    template=template,
                    reference_section=reference_section,
                    input_text=text,
                    output_language="en",
                    translation_style=style,
                )

            def parse_compare_result(
                raw_result: str,
            ) -> Optional[TextTranslationResult]:
                parsed_single = self._parse_single_translation_result(raw_result)
                if parsed_single:
                    option = parsed_single[0]
                    option.explanation = ""
                    option.style = None
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[option],
                        translation_text=option.text,
                        output_language=output_language,
                        detected_language=detected_language,
                    )

                if raw_result.strip():
                    stripped = raw_result.strip()
                    option = TranslationOption(
                        text=stripped,
                        explanation="",
                    )
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[option],
                        translation_text=option.text,
                        output_language=output_language,
                        detected_language=detected_language,
                    )

                return None

            prompt = build_compare_prompt()
            logger.debug(
                "Sending text to backend (compare fallback, streaming=%s, refs=%d)",
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
                and _needs_to_en_numeric_rule_retry_conservative_after_safe_fix(
                    text, result.options[0].text
                )
            )
            if False:
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
                retry_prompt = build_compare_prompt()
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
                        metadata.setdefault("backend", "local")
                        metadata["to_en_numeric_unit_correction"] = True
                        retry_result.metadata = metadata
                        retry_text = fixed_retry_text
                    if not _is_text_output_language_mismatch(
                        retry_text, "en"
                    ) and not _needs_to_en_numeric_rule_retry_conservative(
                        text, retry_text
                    ):
                        if needs_numeric_rule_retry:
                            metadata = (
                                dict(retry_result.metadata)
                                if retry_result.metadata
                                else {}
                            )
                            metadata.setdefault("backend", "local")
                            metadata["to_en_numeric_rule_retry"] = True
                            metadata["to_en_numeric_rule_retry_styles"] = [style]
                            retry_result.metadata = metadata
                        return attach_backend_telemetry(retry_result)

                if needs_output_language_retry:
                    metadata = {
                        "backend": "local",
                        "output_language_mismatch": True,
                        "output_language_retry_failed": True,
                    }
                    if needs_numeric_rule_retry:
                        metadata["to_en_numeric_rule_retry"] = True
                        metadata["to_en_numeric_rule_retry_styles"] = [style]
                        metadata["to_en_numeric_rule_retry_failed"] = True
                        metadata["to_en_numeric_rule_retry_failed_styles"] = [style]
                    return attach_backend_telemetry(
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
                    metadata.setdefault("backend", "local")
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
                        metadata.setdefault("backend", "local")
                        metadata["to_en_numeric_rule_retry"] = True
                        metadata["to_en_numeric_rule_retry_styles"] = [style]
                        metadata["to_en_numeric_rule_retry_failed"] = True
                        metadata["to_en_numeric_rule_retry_failed_styles"] = [style]
                        retry_result.metadata = metadata
                    return attach_backend_telemetry(retry_result)

            if result:
                if result.output_language == "en" and result.options:
                    translation = result.options[0].text
                    fixed_text, fixed = _fix_to_en_oku_numeric_unit_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        metadata = dict(result.metadata) if result.metadata else {}
                        metadata.setdefault("backend", "local")
                        metadata["to_en_numeric_unit_correction"] = True
                        result.metadata = metadata
                        translation = fixed_text

                    fixed_text, fixed = _fix_to_en_negative_parens_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        metadata = dict(result.metadata) if result.metadata else {}
                        metadata.setdefault("backend", "local")
                        metadata["to_en_negative_correction"] = True
                        result.metadata = metadata
                        translation = fixed_text

                    fixed_text, fixed = _fix_to_en_k_notation_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        metadata = dict(result.metadata) if result.metadata else {}
                        metadata.setdefault("backend", "local")
                        metadata["to_en_k_correction"] = True
                        result.metadata = metadata
                        translation = fixed_text

                    fixed_text, fixed = _fix_to_en_month_abbrev_if_possible(
                        source_text=text,
                        translated_text=translation,
                    )
                    if fixed:
                        metadata = dict(result.metadata) if result.metadata else {}
                        metadata.setdefault("backend", "local")
                        metadata["to_en_month_abbrev_correction"] = True
                        result.metadata = metadata
                        translation = fixed_text

                    if translation != result.options[0].text:
                        result.options[0].text = translation
                        result.options[0].explanation = ""
                return attach_backend_telemetry(result)

            logger.warning("Empty response received from backend")
            return attach_backend_telemetry(
                TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message="翻訳エンジンから応答がありませんでした。ローカルAIの状態を確認してください。",
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

        prompt = template.replace("{reference_section}", reference_section)
        prompt_input_text = self.prompt_builder.normalize_input_text(
            text, output_language
        )
        prompt = prompt.replace("{input_text}", prompt_input_text)
        if output_language == "en":
            prompt = prompt.replace("{style}", style)

        logger.debug(
            "Sending text to backend (streaming=%s, refs=%d)",
            bool(on_chunk),
            len(files_to_attach) if files_to_attach else 0,
        )
        raw_result = translate_single_tracked(
            "initial", text, prompt, files_to_attach, on_chunk
        )
        options = self._parse_single_translation_result(raw_result)
        for opt in options:
            opt.explanation = ""
            opt.style = None

        if False:
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
                opt.explanation = ""
                opt.style = None
            if retry_options and not _is_text_output_language_mismatch(
                retry_options[0].text, "jp"
            ):
                return attach_backend_telemetry(
                    TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=retry_options,
                        translation_text=retry_options[0].text,
                        output_language=output_language,
                        detected_language=detected_language,
                    )
                )

            metadata = {
                "backend": "local",
                "output_language_mismatch": True,
                "output_language_retry_failed": True,
            }
            return attach_backend_telemetry(
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
            return attach_backend_telemetry(
                TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=options,
                    translation_text=options[0].text,
                    output_language=output_language,
                    detected_language=detected_language,
                )
            )
        if raw_result.strip():
            stripped = raw_result.strip()
            option = TranslationOption(
                text=stripped,
                explanation="",
            )
            return attach_backend_telemetry(
                TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[option],
                    translation_text=option.text,
                    output_language=output_language,
                    detected_language=detected_language,
                )
            )

        logger.warning("Empty response received from backend")
        return attach_backend_telemetry(
            TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language=output_language,
                detected_language=detected_language,
                error_message="翻訳エンジンから応答がありませんでした。ローカルAIの状態を確認してください。",
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
        reference_files = None
        try:
            # 事前判定があればそれを使用、なければローカル判定する
            if pre_detected_language:
                detected_language = pre_detected_language
                logger.info("Using pre-detected language: %s", detected_language)
            else:
                detected_language = self.detect_language(text)
                logger.info("Detected language: %s", detected_language)

            # Determine output language based on detection
            is_japanese = detected_language == "日本語"
            output_language = "en" if is_japanese else "jp"

            style = _normalize_text_style(style)

            return self._translate_text_with_options_local(
                text=text,
                reference_files=reference_files,
                style=style,
                detected_language=detected_language,
                output_language=output_language,
                on_chunk=on_chunk,
                raw_output=True,
                force_simple_prompt=True,
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
            # Catch specific exceptions from backend calls
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
        """Translate text with style comparison for JP→EN."""
        reference_files = None
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
        selected_style: str | None = None
        if styles:
            for style_name in styles:
                style_key = (style_name or "").strip().lower()
                if style_key in TEXT_STYLE_ORDER:
                    selected_style = style_key
                    break
        return self.translate_text_with_options(
            text=text,
            reference_files=reference_files,
            style=_normalize_text_style(selected_style),
            pre_detected_language=detected_language,
            on_chunk=on_chunk,
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
        reference_files = None

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
            reference_section = (
                self.prompt_builder.build_reference_section(reference_files)
                if reference_files
                else ""
            )

            prompt = template.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{user_instruction}", adjust_type)
            prompt = prompt.replace("{source_text}", source_text if source_text else "")
            prompt = prompt.replace("{input_text}", text)

            # Get adjusted translation
            raw_result = self._translate_single_with_cancel_on_local(
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
            # Catch specific exceptions from backend calls
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
        reference_files = None
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
            reference_section = (
                self.prompt_builder.build_reference_section(reference_files)
                if reference_files
                else ""
            )

            prompt = template.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{current_translation}", current_translation)
            prompt = prompt.replace("{source_text}", source_text)
            prompt = prompt.replace("{style}", style)

            # Get alternative translation
            raw_result = self._translate_single_with_cancel_on_local(
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

    def _parse_style_comparison_result(
        self, raw_result: str
    ) -> list[TranslationOption]:
        """Parse compare-style output into ordered style options."""
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

        ordered: list[TranslationOption] = []
        for style in TEXT_STYLE_ORDER:
            option = parsed_by_style.get(style)
            if option is not None:
                ordered.append(option)

        ordered_ids = {id(option) for option in ordered}
        for option in parsed_by_style.values():
            if id(option) not in ordered_ids:
                ordered.append(option)

        return ordered

    def _parse_single_translation_result(
        self, raw_result: str
    ) -> list[TranslationOption]:
        """Parse single translation result (for →jp translation)."""
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
        reference_files = None

        # File-scoped cache: clear at start and end to prevent cross-file contamination.
        self.clear_translation_cache()

        # Reset PDF processor cancellation flag if applicable
        pdf_processor = self.processors.get(".pdf")
        if pdf_processor and hasattr(pdf_processor, "reset_cancel"):
            pdf_processor.reset_cancel()

        try:
            # Get processor
            processor = self._get_processor(input_path)

            # Use streaming processing for PDF files
            if input_path.suffix.lower() == ".pdf":
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
        finally:
            # Ensure cache does not survive this file translation attempt (success/failure/cancel).
            self.clear_translation_cache()

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

        primary_style = (
            _normalize_text_style(translation_style) if output_language == "en" else ""
        )
        if output_language == "en" and primary_style not in TEXT_STYLE_ORDER:
            primary_style = DEFAULT_TEXT_STYLE

        style_labels = {
            "standard": "標準",
            "concise": "簡潔",
            "minimal": "最簡潔",
        }
        style_label = (
            style_labels.get(primary_style, "英訳")
            if output_language == "en"
            else "和訳"
        )

        translate_start = 10
        translate_end = 90

        def _normalize_cache_text(text: str) -> str:
            return (text or "").strip()

        def _build_cache_key(text: str) -> str:
            normalized = _normalize_cache_text(text)
            if output_language == "en":
                return f"{output_language}|{primary_style}|{normalized}"
            return f"{output_language}|{normalized}"

        file_translation_cache: dict[str, str] = {}
        cache_hits = 0
        cache_misses = 0
        untranslated_block_ids: list[str] = []
        primary_translations: dict[str, str] = {}

        effective_reference_files = None
        self._ensure_local_backend()

        try:
            total_for_progress = max(1, total_blocks)
            style_for_translate = (
                primary_style if output_language == "en" else DEFAULT_TEXT_STYLE
            )
            for idx, block in enumerate(blocks, start=1):
                if self._cancel_event.is_set():
                    return TranslationResult(
                        status=TranslationStatus.CANCELLED,
                        duration_seconds=time.monotonic() - start_time,
                    )

                cache_key = _build_cache_key(block.text)
                cached_translation = file_translation_cache.get(cache_key)
                if cached_translation is not None:
                    translated_text = cached_translation
                    cache_hits += 1
                else:
                    detected_language = (
                        self.detect_language(block.text)
                        if block.text
                        else ("日本語" if output_language == "en" else "英語")
                    )
                    result = self._translate_text_with_options_local(
                        text=block.text,
                        reference_files=effective_reference_files,
                        style=style_for_translate,
                        detected_language=detected_language,
                        output_language=output_language,
                        on_chunk=None,
                        force_simple_prompt=True,
                    )
                    translated_text = ""
                    if result.options:
                        translated_text = result.options[0].text or ""
                    if result.error_message or not translated_text.strip():
                        translated_text = block.text
                        untranslated_block_ids.append(block.id)
                    file_translation_cache[cache_key] = translated_text
                    cache_misses += 1

                primary_translations[block.id] = translated_text

                if on_progress:
                    phase_detail = (
                        f"{style_label} {idx}/{total_for_progress} "
                        f"(cache {cache_hits} hit / {cache_misses} miss)"
                    )
                    progress = TranslationProgress(
                        current=idx,
                        total=total_for_progress,
                        status=f"Translating blocks {idx}/{total_for_progress}...",
                        phase=TranslationPhase.TRANSLATING,
                        phase_current=idx,
                        phase_total=total_for_progress,
                    )
                    on_progress(
                        scale_progress(
                            progress,
                            translate_start,
                            translate_end,
                            TranslationPhase.TRANSLATING,
                            phase_detail=phase_detail,
                        )
                    )
        finally:
            # File-scoped cache must not survive beyond this translation attempt.
            file_translation_cache.clear()

        issue_locations, issue_section_counts = self._summarize_batch_issues(
            blocks, untranslated_block_ids
        )

        output_path = self._generate_output_path(input_path)
        extra_output_files: list[tuple[Path, str]] = []

        direction = "jp_to_en" if output_language == "en" else "en_to_jp"

        apply_total = 1 + (1 if self.config and self.config.bilingual_output else 0)
        apply_step = 0
        bilingual_path = None

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
                    status=f"Applying translations ({style_label})...",
                    phase=TranslationPhase.APPLYING,
                    phase_current=apply_step,
                    phase_total=apply_total,
                )
            )
        processor.apply_translations(
            input_path,
            output_path,
            primary_translations,
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
        if self._use_local_backend() and effective_reference_files:
            self._ensure_local_backend()
            if self._local_prompt_builder is not None:
                embedded_ref = self._local_prompt_builder.build_reference_embed(
                    effective_reference_files
                )
                warnings.extend(embedded_ref.warnings)
        if untranslated_block_ids:
            warnings.append(f"未翻訳ブロック: {len(untranslated_block_ids)}")

        translated_count = max(0, total_blocks - len(untranslated_block_ids))

        return TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_path=output_path,
            bilingual_path=bilingual_path,
            blocks_translated=translated_count,
            blocks_total=total_blocks,
            duration_seconds=time.monotonic() - start_time,
            warnings=warnings if warnings else [],
            issue_block_ids=untranslated_block_ids,
            issue_block_locations=issue_locations,
            issue_section_counts=issue_section_counts,
            mismatched_batch_count=0,
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

        primary_style = (
            _normalize_text_style(translation_style) if output_language == "en" else ""
        )
        if output_language == "en" and primary_style not in TEXT_STYLE_ORDER:
            primary_style = DEFAULT_TEXT_STYLE

        style_labels = {
            "standard": "標準",
            "concise": "簡潔",
            "minimal": "最簡潔",
        }
        style_label = (
            style_labels.get(primary_style, "英訳")
            if output_language == "en"
            else "和訳"
        )

        translate_start = 40
        translate_end = 90

        def _normalize_cache_text(text: str) -> str:
            return (text or "").strip()

        def _build_cache_key(text: str) -> str:
            normalized = _normalize_cache_text(text)
            if output_language == "en":
                return f"{output_language}|{primary_style}|{normalized}"
            return f"{output_language}|{normalized}"

        file_translation_cache: dict[str, str] = {}
        cache_hits = 0
        cache_misses = 0
        untranslated_block_ids: list[str] = []
        primary_translations: dict[str, str] = {}

        effective_reference_files = None
        self._ensure_local_backend()

        try:
            total_for_progress = max(1, total_blocks)
            style_for_translate = (
                primary_style if output_language == "en" else DEFAULT_TEXT_STYLE
            )
            progress_step = max(1, total_for_progress // 200)
            last_scaled_progress = -1

            for idx, block in enumerate(all_blocks, start=1):
                if self._cancel_event.is_set():
                    return TranslationResult(
                        status=TranslationStatus.CANCELLED,
                        duration_seconds=time.monotonic() - start_time,
                    )

                cache_key = _build_cache_key(block.text)
                cached_translation = file_translation_cache.get(cache_key)
                if cached_translation is not None:
                    translated_text = cached_translation
                    cache_hits += 1
                else:
                    detected_language = (
                        self.detect_language(block.text)
                        if block.text
                        else ("日本語" if output_language == "en" else "英語")
                    )
                    result = self._translate_text_with_options_local(
                        text=block.text,
                        reference_files=effective_reference_files,
                        style=style_for_translate,
                        detected_language=detected_language,
                        output_language=output_language,
                        on_chunk=None,
                        force_simple_prompt=True,
                    )
                    translated_text = ""
                    if result.options:
                        translated_text = result.options[0].text or ""
                    if result.error_message or not translated_text.strip():
                        translated_text = block.text
                        untranslated_block_ids.append(block.id)
                    file_translation_cache[cache_key] = translated_text
                    cache_misses += 1

                primary_translations[block.id] = translated_text

                if on_progress and (
                    idx == total_for_progress or idx % progress_step == 0
                ):
                    phase_detail = (
                        f"{style_label} {idx}/{total_for_progress} "
                        f"(cache {cache_hits} hit / {cache_misses} miss)"
                    )
                    progress = TranslationProgress(
                        current=idx,
                        total=total_for_progress,
                        status=f"Translating {idx}/{total_for_progress} blocks...",
                        phase=TranslationPhase.TRANSLATING,
                        phase_current=idx,
                        phase_total=total_for_progress,
                    )
                    scaled_progress = scale_progress(
                        progress,
                        translate_start,
                        translate_end,
                        TranslationPhase.TRANSLATING,
                        phase_detail=phase_detail,
                    )
                    if scaled_progress.current != last_scaled_progress:
                        last_scaled_progress = scaled_progress.current
                        on_progress(scaled_progress)
        finally:
            # File-scoped cache must not survive beyond this translation attempt.
            file_translation_cache.clear()

        issue_locations, issue_section_counts = self._summarize_batch_issues(
            all_blocks, untranslated_block_ids
        )

        output_path = self._generate_output_path(input_path)
        extra_output_files: list[tuple[Path, str]] = []

        direction = "jp_to_en" if output_language == "en" else "en_to_jp"

        apply_total = 1 + (1 if self.config and self.config.bilingual_output else 0)
        apply_step = 0
        bilingual_path = None

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
                    status=f"Applying translations to PDF ({style_label})...",
                    phase=TranslationPhase.APPLYING,
                    phase_current=apply_step,
                    phase_total=apply_total,
                )
            )

        processor.apply_translations(
            input_path,
            output_path,
            primary_translations,
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
        if self._use_local_backend() and effective_reference_files:
            self._ensure_local_backend()
            if self._local_prompt_builder is not None:
                embedded_ref = self._local_prompt_builder.build_reference_embed(
                    effective_reference_files
                )
                warnings.extend(embedded_ref.warnings)
        if untranslated_block_ids:
            warnings.append(f"未翻訳ブロック: {len(untranslated_block_ids)}")

        translated_count = max(0, total_blocks - len(untranslated_block_ids))

        return TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_path=output_path,
            bilingual_path=bilingual_path,
            blocks_translated=translated_count,
            blocks_total=total_blocks,
            duration_seconds=time.monotonic() - start_time,
            warnings=warnings if warnings else [],
            issue_block_ids=untranslated_block_ids,
            issue_block_locations=issue_locations,
            issue_section_counts=issue_section_counts,
            mismatched_batch_count=0,
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
