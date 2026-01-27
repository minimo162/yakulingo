# yakulingo/services/local_ai_client.py
from __future__ import annotations

import ast
import json
import os
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal, Optional, Sequence

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_llama_server import (
    LocalAIError,
    LocalAIServerRuntime,
    get_local_llama_server_manager,
)
from yakulingo.services.exceptions import TranslationCancelledError

logger = logging.getLogger(__name__)

_TIMING_ENABLED = os.environ.get("YAKULINGO_LOCAL_AI_TIMING") == "1"

_DIAGNOSTIC_SNIPPET_CHARS = 200
_SSE_DELTA_COALESCE_MIN_CHARS = 256
_SSE_DELTA_COALESCE_MAX_INTERVAL_SEC = 0.18

_SYSTEM_TRANSLATION_PROMPT_EN = (
    "You are a translation engine.\n"
    "Reply in English only (no CJK/Hangul).\n"
    "Follow the user's prompt exactly.\n"
    "- Do not copy example placeholders.\n"
    "- Do not repeat the input unless explicitly asked.\n"
    "- Output only in the requested format (e.g., JSON only).\n"
)
_SYSTEM_TRANSLATION_PROMPT_JP = (
    "You are a translation engine.\n"
    "Reply in Japanese only.\n"
    "Follow the user's prompt exactly.\n"
    "- Do not copy example placeholders.\n"
    "- Do not repeat the input unless explicitly asked.\n"
    "- Output only in the requested format (e.g., JSON only).\n"
)

_PROMPT_REPEAT_SEPARATOR = "\n\n"


def _repeat_prompt_twice(prompt: str) -> str:
    if not prompt:
        return ""
    return f"{prompt}{_PROMPT_REPEAT_SEPARATOR}{prompt}"


def _repeat_prompt_twice_len(prompt: str | None) -> int:
    """Return the character length of `_repeat_prompt_twice(prompt)` without allocating it."""
    if not prompt:
        return 0
    return len(prompt) * 2 + len(_PROMPT_REPEAT_SEPARATOR)


def _sent_prompt(prompt: str | None, *, repeat: bool) -> str:
    base = prompt or ""
    return _repeat_prompt_twice(base) if repeat else base


def _sent_prompt_len(prompt: str | None, *, repeat: bool) -> int:
    return _repeat_prompt_twice_len(prompt) if repeat else len(prompt or "")


def _select_system_prompt(prompt: str) -> str:
    return (
        _SYSTEM_TRANSLATION_PROMPT_JP
        if "EN->JP" in (prompt or "")
        else _SYSTEM_TRANSLATION_PROMPT_EN
    )


def _is_hy_mt_model(runtime: LocalAIServerRuntime) -> bool:
    """Detect Tencent HY-MT models which are trained without a default system prompt."""

    candidates = [runtime.model_id, runtime.model_path.name]
    for candidate in candidates:
        if not candidate:
            continue
        lowered = str(candidate).strip().lower()
        if not lowered:
            continue
        if "hy-mt" in lowered or "hy_mt" in lowered:
            return True
    return False


_RE_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*$", re.IGNORECASE)
_RE_TRAILING_COMMAS = re.compile(r",(\s*[}\]])")
_RE_ID_MARKER_BLOCK = re.compile(
    r"\[\[ID:(\d+)\]\]\s*(.+?)(?=\[\[ID:\d+\]\]|$)", re.DOTALL
)
_RE_NUMBERED_LINE = re.compile(r"^\s*(\d+)\s*[\.\):]\s*(.+)\s*$")
_RE_TARGET_TAG = re.compile(
    r"<target(?:\s+[^>]*)?>(?P<text>.*?)</target>",
    re.IGNORECASE | re.DOTALL,
)
_RE_TARGET_TAG_OPEN = re.compile(r"<target(?:\s+[^>]*)?>", re.IGNORECASE)
_RE_SINGLE_SECTION_COLON = re.compile(
    r"^\s*(?:#+\s*)?(?P<label>訳文|解説|説明|translation|explanation)\s*[:：]\s*(?P<rest>.*)\s*$",
    re.IGNORECASE,
)
_RE_SINGLE_SECTION_LINE = re.compile(
    r"^\s*(?:#+\s*)?(?P<label>訳文|解説|説明|translation|explanation)\s*$",
    re.IGNORECASE,
)
_JSON_STOP_SEQUENCES = ["</s>", "<|end|>"]
_RESPONSE_FORMAT_CACHE_TTL_S = 600.0
_SAMPLING_PARAMS_CACHE_TTL_S = 600.0
_ResponseFormatMode = Literal["schema", "json_object", "none"]
_PARSED_JSON_MISSING: object = object()
_HY_MT_RECOMMENDED_TOP_P = 0.6
_HY_MT_RECOMMENDED_TOP_K = 20
_HY_MT_DEFAULT_TOP_P = 0.95
_HY_MT_DEFAULT_TOP_K = 64
_RESPONSE_FORMAT_SINGLE_SCHEMA: dict[str, object] = {
    "name": "yakulingo_single_translation_response",
    "schema": {
        "type": "object",
        "required": ["translation"],
        "properties": {
            "translation": {"type": "string", "minLength": 1},
            "explanation": {"type": "string"},
        },
        "additionalProperties": True,
    },
    "strict": True,
}
_RESPONSE_FORMAT_ITEMS_SCHEMA: dict[str, object] = {
    "name": "yakulingo_batch_translation_response",
    "schema": {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "translation"],
                    "properties": {
                        "id": {
                            "oneOf": [
                                {"type": "integer", "minimum": 1},
                                {"type": "string"},
                            ]
                        },
                        "translation": {"type": "string", "minLength": 1},
                    },
                    "additionalProperties": True,
                },
            }
        },
        "additionalProperties": True,
    },
    "strict": True,
}
_RESPONSE_FORMAT_OPTIONS_SCHEMA: dict[str, object] = {
    "name": "yakulingo_text_style_options_response",
    "schema": {
        "type": "object",
        "required": ["options"],
        "properties": {
            "options": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["translation"],
                    "properties": {
                        "style": {"type": "string"},
                        "translation": {"type": "string", "minLength": 1},
                        "explanation": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            }
        },
        "additionalProperties": True,
    },
    "strict": True,
}
_RESPONSE_FORMAT_OPTIONS_3STYLE_SCHEMA: dict[str, object] = {
    "name": "yakulingo_text_style_options_3style_response",
    "schema": {
        "type": "object",
        "required": ["options"],
        "properties": {
            "options": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "required": ["style", "translation"],
                    "properties": {
                        "style": {
                            "type": "string",
                            "enum": ["standard", "concise", "minimal"],
                        },
                        "translation": {"type": "string", "minLength": 1},
                        "explanation": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            }
        },
        "additionalProperties": True,
    },
    "strict": True,
}
_RESPONSE_FORMAT_JSON_OBJECT_PAYLOAD: dict[str, object] = {"type": "json_object"}


def _select_json_schema(prompt: str) -> dict[str, object]:
    lowered = (prompt or "").lower()
    if "items_json" in lowered:
        return _RESPONSE_FORMAT_ITEMS_SCHEMA
    if "options must contain exactly these 3 styles" in lowered:
        return _RESPONSE_FORMAT_OPTIONS_3STYLE_SCHEMA
    if '"options"' in lowered or "options" in lowered:
        return _RESPONSE_FORMAT_OPTIONS_SCHEMA
    return _RESPONSE_FORMAT_SINGLE_SCHEMA


def _build_response_format_payload(
    prompt: str, response_format: str | None
) -> dict[str, object]:
    if response_format == "json_object":
        return _RESPONSE_FORMAT_JSON_OBJECT_PAYLOAD
    return {
        "type": "json_schema",
        "json_schema": _select_json_schema(prompt),
    }


def _expected_json_root_key(prompt: str) -> str | None:
    lowered = (prompt or "").casefold()
    if '{"items"' in lowered or "items_json" in lowered:
        return "items"
    if (
        '{"options"' in lowered
        or "options must contain exactly these 3 styles" in lowered
    ):
        return "options"
    if '{"translation"' in lowered:
        return "translation"
    if "return json only" in lowered:
        return "translation"
    return None


def _should_enforce_json_response(prompt: str) -> bool:
    return _expected_json_root_key(prompt) is not None


def _strip_code_fences(text: str) -> str:
    if "```" not in text:
        return text
    lines = []
    for line in text.splitlines():
        if _RE_CODE_FENCE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _make_diagnostic_snippet(
    raw_content: str, *, limit: int = _DIAGNOSTIC_SNIPPET_CHARS
) -> str:
    cleaned = _strip_code_fences(raw_content)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("\0", "")
    cleaned = cleaned.replace("\t", "\\t").replace("\n", "\\n")
    cleaned = "".join(ch if ch.isprintable() else "?" for ch in cleaned)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "..."
    return cleaned


def _log_parse_failure(
    *,
    kind: str,
    raw_content: str,
    reason: str,
    obj: object | None,
    expected_count: Optional[int] = None,
) -> None:
    cleaned = _strip_code_fences(raw_content)
    has_json_substring = _extract_json_substring(cleaned) is not None
    has_code_fence = "```" in raw_content
    obj_type = type(obj).__name__ if obj is not None else "none"
    snippet = _make_diagnostic_snippet(raw_content)
    logger.warning(
        "LocalAI parse failure: kind=%s reason=%s obj=%s raw_chars=%d has_code_fence=%s has_json_substring=%s expected_count=%s snippet=%s",
        kind,
        reason,
        obj_type,
        len(raw_content),
        has_code_fence,
        has_json_substring,
        expected_count,
        snippet,
    )


def _extract_json_substring(text: str) -> Optional[str]:
    text = text.strip()
    if not text:
        return None

    start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not start_candidates:
        return None
    start = min(start_candidates)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    end = text.rfind(closer)
    if end == -1 or end <= start:
        return None
    return text[start : end + 1].strip()


def loads_json_loose(text: str) -> Optional[object]:
    cleaned = _strip_code_fences(text)
    candidate = _extract_json_substring(cleaned) or cleaned.strip()
    if not candidate:
        return None

    for attempt in range(3):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            if attempt == 0:
                candidate = _RE_TRAILING_COMMAS.sub(r"\1", candidate)
                continue
            break

    try:
        obj = ast.literal_eval(candidate)
        if isinstance(obj, (dict, list)):
            return obj
    except Exception:
        return None
    return None


def _should_retry_with_repeated_prompt(
    prompt: str,
    content: str,
    *,
    parsed_json: object = _PARSED_JSON_MISSING,
    require_json: bool = False,
) -> bool:
    expected_key = _expected_json_root_key(prompt)
    if expected_key is None:
        return False

    cleaned = _strip_code_fences(content).strip()
    if not cleaned:
        return True
    if is_truncated_json(content):
        return True

    has_json_substring = _extract_json_substring(cleaned) is not None
    obj = (
        loads_json_loose(cleaned)
        if parsed_json is _PARSED_JSON_MISSING and has_json_substring
        else parsed_json
    )

    if isinstance(obj, dict):
        if expected_key == "translation":
            translation = obj.get("translation")
            return not isinstance(translation, str) or not translation.strip()
        if expected_key == "items":
            items = obj.get("items")
            return not isinstance(items, list) or not items
        if expected_key == "options":
            options = obj.get("options")
            return not isinstance(options, list) or not options
        return True

    if expected_key == "translation":
        translation, _ = _parse_text_single_translation_fallback(cleaned)
        if isinstance(translation, str) and translation.strip():
            return False

    if not has_json_substring:
        return require_json
    return True


def _is_empty_json_object_reply(
    content: str,
    parsed_json: object = _PARSED_JSON_MISSING,
) -> bool:
    cleaned = _strip_code_fences(content).strip()
    if not cleaned:
        return True
    obj = (
        loads_json_loose(cleaned)
        if parsed_json is _PARSED_JSON_MISSING
        else parsed_json
    )
    if not isinstance(obj, dict):
        return False
    if not obj:
        return True
    if "translation" in obj:
        translation = obj.get("translation")
        if not isinstance(translation, str) or not translation.strip():
            return True
    return False


def is_truncated_json(text: str) -> bool:
    cleaned = _strip_code_fences(text).strip()
    if not cleaned:
        return False

    start_candidates = [
        idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx != -1
    ]
    if not start_candidates:
        return False

    start = min(start_candidates)
    segment = cleaned[start:]
    stack: list[str] = []
    in_string = False
    escape = False

    for ch in segment:
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("{")
        elif ch == "[":
            stack.append("[")
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
            else:
                return False
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
            else:
                return False

    if in_string:
        return True
    return bool(stack)


def _parse_openai_chat_content(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("ローカルAIの応答形式が不正です（choices がありません）")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("ローカルAIの応答形式が不正です（choices[0]）")
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    if isinstance(text, str):
        return text
    raise RuntimeError("ローカルAIの応答形式が不正です（content がありません）")


def _parse_openai_stream_delta(payload: dict) -> Optional[str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    if isinstance(text, str):
        return text
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return None


def _parse_batch_items_json(obj: object, expected_count: int) -> Optional[list[str]]:
    if not isinstance(obj, dict):
        return None
    items = obj.get("items")
    if not isinstance(items, list):
        return None

    by_id: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        item_id: Optional[int] = None
        if isinstance(raw_id, int):
            item_id = raw_id
        elif isinstance(raw_id, str) and raw_id.strip().isdigit():
            try:
                item_id = int(raw_id.strip())
            except ValueError:
                item_id = None
        if item_id is None or item_id <= 0:
            continue
        translation = item.get("translation")
        if not isinstance(translation, str):
            translation = ""
        by_id[item_id] = translation

    if not by_id:
        return None

    return [by_id.get(i + 1, "") for i in range(expected_count)]


def _parse_batch_items_fallback(text: str, expected_count: int) -> Optional[list[str]]:
    matches = list(_RE_ID_MARKER_BLOCK.finditer(text))
    if matches:
        by_id: dict[int, str] = {}
        for m in matches:
            try:
                item_id = int(m.group(1))
            except ValueError:
                continue
            by_id[item_id] = m.group(2).strip()
        if by_id:
            return [by_id.get(i + 1, "") for i in range(expected_count)]

    lines = []
    for line in text.splitlines():
        m = _RE_NUMBERED_LINE.match(line)
        if not m:
            continue
        lines.append(m.group(2).strip())
    if lines:
        while len(lines) < expected_count:
            lines.append("")
        return lines[:expected_count]
    return None


def _classify_parse_failure(raw_content: str, obj: object | None) -> tuple[str, bool]:
    cleaned = _strip_code_fences(raw_content).strip()
    has_json_substring = _extract_json_substring(cleaned) is not None
    truncated = is_truncated_json(raw_content)
    if not cleaned:
        return "empty", truncated
    if truncated:
        return "truncated_json", truncated
    if obj is None:
        return ("invalid_json" if has_json_substring else "no_json"), truncated
    if isinstance(obj, dict):
        if not obj:
            return "empty_json_object", truncated
        return "json_schema_mismatch", truncated
    return f"json_type_{type(obj).__name__}", truncated


def parse_batch_translations(
    raw_content: str,
    expected_count: int,
    *,
    parsed_json: object = _PARSED_JSON_MISSING,
) -> list[str]:
    obj = (
        loads_json_loose(raw_content)
        if parsed_json is _PARSED_JSON_MISSING
        else parsed_json
    )
    parsed = _parse_batch_items_json(obj, expected_count) if obj is not None else None
    if parsed is not None:
        return parsed

    fallback = _parse_batch_items_fallback(raw_content, expected_count)
    if fallback is not None:
        return fallback

    reason, truncated = _classify_parse_failure(raw_content, obj)
    _log_parse_failure(
        kind="batch",
        raw_content=raw_content,
        reason=reason,
        obj=obj,
        expected_count=expected_count,
    )

    if truncated:
        raise RuntimeError(
            "ローカルAIの応答が途中で終了しました（JSONが閉じていません）。\n"
            "max_tokens / ctx_size を見直してください。"
        )

    raise RuntimeError(
        "ローカルAIの応答(JSON)を解析できませんでした（詳細はログを確認してください）"
    )


_TEXT_STYLE_ORDER = ("standard", "concise", "minimal")


def _normalize_text_style(style: Optional[str]) -> Optional[str]:
    if not isinstance(style, str):
        return None
    cleaned = style.strip().casefold()
    if not cleaned:
        return None
    if cleaned in _TEXT_STYLE_ORDER:
        return cleaned
    if any(token in cleaned for token in ("standard", "std", "normal", "default")):
        return "standard"
    if any(token in cleaned for token in ("concise", "brief", "short", "compact")):
        return "concise"
    if any(token in cleaned for token in ("minimal", "minimum", "min", "mini")):
        return "minimal"
    if "標準" in style or "通常" in style:
        return "standard"
    if "簡潔" in style or "短" in style:
        return "concise"
    if "最簡潔" in style or "最小" in style or "極小" in style:
        return "minimal"
    return None


def _parse_text_style_options(
    raw_content: str,
) -> list[tuple[Optional[str], str, str]]:
    obj = loads_json_loose(raw_content)
    if not isinstance(obj, dict):
        return []
    options = obj.get("options")
    if not isinstance(options, list):
        return []

    items: list[tuple[Optional[str], str, str]] = []
    for opt in options:
        if not isinstance(opt, dict):
            continue
        translation = opt.get("translation")
        if not isinstance(translation, str):
            continue
        style = _normalize_text_style(opt.get("style"))
        explanation = opt.get("explanation")
        items.append((style, translation, explanation if isinstance(explanation, str) else ""))
    return items


def parse_text_to_en_3style(raw_content: str) -> dict[str, tuple[str, str]]:
    items = _parse_text_style_options(raw_content)
    if not items:
        translation, explanation = parse_text_single_translation(raw_content)
        if not translation:
            return {}
        return {"minimal": (translation, explanation or "")}

    by_style: dict[str, tuple[str, str]] = {}
    used_indexes: set[int] = set()
    for idx, (style, translation, explanation) in enumerate(items):
        if style in _TEXT_STYLE_ORDER and style not in by_style:
            by_style[style] = (translation, explanation)
            used_indexes.add(idx)

    remaining_styles = [s for s in _TEXT_STYLE_ORDER if s not in by_style]
    if remaining_styles:
        for idx, (style, translation, explanation) in enumerate(items):
            if idx in used_indexes:
                continue
            if not remaining_styles:
                break
            next_style = remaining_styles.pop(0)
            by_style[next_style] = (translation, explanation)
            used_indexes.add(idx)

    return by_style


def parse_text_to_en_style_subset(
    raw_content: str,
    styles: Sequence[str],
) -> dict[str, tuple[str, str]]:
    allowed = [s for s in styles if s in _TEXT_STYLE_ORDER]
    if not allowed:
        return {}

    items = _parse_text_style_options(raw_content)
    if not items:
        translation, explanation = parse_text_single_translation(raw_content)
        if not translation:
            return {}
        target_style = "minimal" if "minimal" in allowed else allowed[0]
        return {target_style: (translation, explanation or "")}

    by_style: dict[str, tuple[str, str]] = {}
    used_indexes: set[int] = set()
    for idx, (style, translation, explanation) in enumerate(items):
        if style in allowed and style not in by_style:
            by_style[style] = (translation, explanation)
            used_indexes.add(idx)

    remaining_styles = [s for s in allowed if s not in by_style]
    if remaining_styles:
        for idx, (style, translation, explanation) in enumerate(items):
            if idx in used_indexes:
                continue
            if not remaining_styles:
                break
            next_style = remaining_styles.pop(0)
            by_style[next_style] = (translation, explanation)
            used_indexes.add(idx)

    return by_style


def parse_text_single_translation(
    raw_content: str,
) -> tuple[Optional[str], Optional[str]]:
    obj = loads_json_loose(raw_content)
    if isinstance(obj, dict):
        translation = obj.get("translation")
        explanation = obj.get("explanation")
        if isinstance(translation, str):
            return translation, explanation if isinstance(explanation, str) else ""

    translation, explanation = _parse_text_single_translation_fallback(raw_content)
    if not translation:
        reason, _ = _classify_parse_failure(raw_content, obj)
        _log_parse_failure(
            kind="single",
            raw_content=raw_content,
            reason=reason,
            obj=obj,
            expected_count=None,
        )
    return translation, explanation


def _extract_target_tag(text: str) -> Optional[str]:
    if "<target" not in text.casefold():
        return None

    match = _RE_TARGET_TAG.search(text)
    if match is not None:
        extracted = (match.group("text") or "").strip()
        return extracted or None

    match_open = _RE_TARGET_TAG_OPEN.search(text)
    if match_open is None:
        return None
    extracted = text[match_open.end() :].strip()
    return extracted or None


def _select_sampling_param_hy_mt_default(
    value: float | int | None,
    *,
    default: float | int,
    recommended: float | int,
) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int) and isinstance(default, int) and value == default:
        return recommended
    if isinstance(value, float) and isinstance(default, float) and value == default:
        return recommended
    return value


def _parse_text_single_translation_fallback(
    raw_content: str,
) -> tuple[Optional[str], Optional[str]]:
    cleaned = _strip_code_fences(raw_content).strip()
    if not cleaned:
        return None, None

    target = _extract_target_tag(cleaned)
    if target:
        return target, ""

    translation_lines: list[str] = []
    explanation_lines: list[str] = []
    current: Optional[str] = None

    for line in cleaned.splitlines():
        match = _RE_SINGLE_SECTION_COLON.match(line)
        rest: str = ""
        if match is None:
            match = _RE_SINGLE_SECTION_LINE.match(line)
        else:
            rest = (match.group("rest") or "").strip()

        if match is not None:
            label = (match.group("label") or "").strip().casefold()
            if label in ("訳文", "translation"):
                current = "translation"
                if rest:
                    translation_lines.append(rest)
                continue
            if label in ("解説", "説明", "explanation"):
                current = "explanation"
                if rest:
                    explanation_lines.append(rest)
                continue

        if current == "translation":
            translation_lines.append(line)
        elif current == "explanation":
            explanation_lines.append(line)

    translation = "\n".join(translation_lines).strip()
    if not translation:
        return None, None
    explanation = "\n".join(explanation_lines).strip()
    return translation, explanation


@dataclass(frozen=True)
class LocalAIRequestResult:
    content: str
    model_id: Optional[str]
    parsed_json: object = _PARSED_JSON_MISSING


class LocalAIClient:
    def __init__(
        self,
        settings: AppSettings,
    ) -> None:
        self._settings = settings
        self._manager = get_local_llama_server_manager()
        self._cancel_check: Optional[Callable[[], bool]] = None
        self._response_format_support: dict[str, tuple[_ResponseFormatMode, float]] = {}
        self._response_format_lock = threading.Lock()
        self._sampling_params_support: dict[str, tuple[bool, float]] = {}
        self._sampling_params_lock = threading.Lock()

    def set_cancel_callback(self, callback: Optional[Callable[[], bool]]) -> None:
        self._cancel_check = callback

    def _should_cancel(self) -> bool:
        cb = self._cancel_check
        try:
            return bool(cb and cb())
        except Exception:
            return False

    def _build_chat_payload(
        self,
        runtime: LocalAIServerRuntime,
        prompt: str,
        *,
        stream: bool,
        enforce_json: bool,
        response_format: str | None = None,
        include_sampling_params: bool = True,
        repeat_prompt: bool = False,
    ) -> dict[str, object]:
        original_prompt = prompt or ""
        user_prompt = _sent_prompt(original_prompt, repeat=repeat_prompt)
        messages: list[dict[str, str]] = [{"role": "user", "content": user_prompt}]
        if not _is_hy_mt_model(runtime):
            messages.insert(
                0,
                {"role": "system", "content": _select_system_prompt(original_prompt)},
            )
        payload: dict[str, object] = {
            "model": runtime.model_id or runtime.model_path.name,
            "messages": messages,
            "stream": stream,
            "temperature": float(self._settings.local_ai_temperature),
        }
        if include_sampling_params:
            top_p = self._settings.local_ai_top_p
            top_k = self._settings.local_ai_top_k
            if _is_hy_mt_model(runtime):
                top_p = _select_sampling_param_hy_mt_default(
                    top_p,
                    default=_HY_MT_DEFAULT_TOP_P,
                    recommended=_HY_MT_RECOMMENDED_TOP_P,
                )
                top_k = _select_sampling_param_hy_mt_default(
                    top_k,
                    default=_HY_MT_DEFAULT_TOP_K,
                    recommended=_HY_MT_RECOMMENDED_TOP_K,
                )
            if top_p is not None:
                payload["top_p"] = float(top_p)
            if top_k is not None:
                payload["top_k"] = int(top_k)
            if self._settings.local_ai_min_p is not None:
                payload["min_p"] = float(self._settings.local_ai_min_p)
            if self._settings.local_ai_repeat_penalty is not None:
                payload["repeat_penalty"] = float(
                    self._settings.local_ai_repeat_penalty
                )
        if self._settings.local_ai_max_tokens is not None:
            payload["max_tokens"] = int(self._settings.local_ai_max_tokens)
        if enforce_json:
            payload["response_format"] = _build_response_format_payload(
                original_prompt, response_format
            )
        if _JSON_STOP_SEQUENCES:
            payload["stop"] = _JSON_STOP_SEQUENCES
        return payload

    @staticmethod
    def _should_retry_without_response_format(error: Exception) -> bool:
        message = str(error).lower()
        return any(
            token in message
            for token in ("response_format", "json_schema", "json schema")
        )

    @staticmethod
    def _should_retry_with_json_object(error: Exception) -> bool:
        message = str(error).lower()
        return "json_schema" in message or "json schema" in message

    @staticmethod
    def _should_retry_without_sampling_params(error: Exception) -> bool:
        message = str(error).lower()
        if "local_prompt_too_long" in message:
            return False
        if any(
            token in message
            for token in ("response_format", "json_schema", "json schema")
        ):
            return False
        return any(
            token in message
            for token in (
                "unknown field",
                "unsupported",
                "unrecognized",
                "top_p",
                "top_k",
                "min_p",
                "repeat_penalty",
                "repeat penalty",
                "repeat-penalty",
            )
        )

    @staticmethod
    def _should_cache_sampling_params_unsupported(error: Exception) -> bool:
        message = str(error).lower()
        return any(
            token in message
            for token in (
                "top_p",
                "top_k",
                "min_p",
                "repeat_penalty",
                "repeat penalty",
                "repeat-penalty",
            )
        )

    @staticmethod
    def _response_format_cache_key(runtime: LocalAIServerRuntime) -> str:
        return f"{runtime.host}:{runtime.port}"

    @staticmethod
    def _sampling_params_cache_key(runtime: LocalAIServerRuntime) -> str:
        return f"{runtime.host}:{runtime.port}"

    def _get_response_format_support(
        self, runtime: LocalAIServerRuntime
    ) -> Optional[_ResponseFormatMode]:
        key = self._response_format_cache_key(runtime)
        with self._response_format_lock:
            cached = self._response_format_support.get(key)
        if not cached:
            return None
        supported, checked_at = cached
        if time.monotonic() - checked_at > _RESPONSE_FORMAT_CACHE_TTL_S:
            with self._response_format_lock:
                self._response_format_support.pop(key, None)
            return None
        return supported

    def _set_response_format_support(
        self, runtime: LocalAIServerRuntime, supported: _ResponseFormatMode
    ) -> None:
        key = self._response_format_cache_key(runtime)
        with self._response_format_lock:
            self._response_format_support[key] = (supported, time.monotonic())

    def _get_sampling_params_support(
        self, runtime: LocalAIServerRuntime
    ) -> Optional[bool]:
        key = self._sampling_params_cache_key(runtime)
        with self._sampling_params_lock:
            cached = self._sampling_params_support.get(key)
        if not cached:
            return None
        supported, checked_at = cached
        if time.monotonic() - checked_at > _SAMPLING_PARAMS_CACHE_TTL_S:
            with self._sampling_params_lock:
                self._sampling_params_support.pop(key, None)
            return None
        return supported

    def _set_sampling_params_support(
        self, runtime: LocalAIServerRuntime, supported: bool
    ) -> None:
        key = self._sampling_params_cache_key(runtime)
        with self._sampling_params_lock:
            self._sampling_params_support[key] = (supported, time.monotonic())

    def ensure_ready(self) -> LocalAIServerRuntime:
        return self._manager.ensure_ready(self._settings)

    def warmup(
        self,
        runtime: Optional[LocalAIServerRuntime] = None,
        *,
        timeout: Optional[int] = None,
        max_tokens: int = 1,
    ) -> None:
        prompt = "ping"
        runtime = runtime or self.ensure_ready()
        payload = self._build_chat_payload(
            runtime, prompt, stream=False, enforce_json=False
        )
        payload["max_tokens"] = max(1, int(max_tokens))
        payload["temperature"] = 0.0
        timeout_s = float(
            timeout if timeout is not None else self._settings.request_timeout
        )
        if timeout_s <= 0:
            timeout_s = 10.0
        timeout_s = min(timeout_s, 10.0)
        t0 = time.perf_counter()
        self._http_json_cancellable(
            host=runtime.host,
            port=runtime.port,
            path="/v1/chat/completions",
            payload=payload,
            timeout_s=timeout_s,
        )
        t_req = time.perf_counter() - t0
        logger.debug(
            "[TIMING] LocalAI warmup: %.2fs (prompt_chars=%d)",
            t_req,
            _sent_prompt_len(prompt, repeat=False),
        )

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        timeout: Optional[int] = None,
        runtime: Optional[LocalAIServerRuntime] = None,
    ) -> str:
        _ = text
        _ = reference_files
        if runtime is None:
            t0 = time.perf_counter()
            runtime = self.ensure_ready()
            t_ready = time.perf_counter() - t0
            logger.debug(
                "[TIMING] LocalAI ensure_ready: %.2fs (host=%s port=%d model=%s)",
                t_ready,
                runtime.host,
                runtime.port,
                runtime.model_id or runtime.model_path.name,
            )

        t1 = time.perf_counter()
        repeat_used = False
        if on_chunk is None:
            result = self._chat_completions(
                runtime, prompt, timeout=timeout, repeat_prompt=False
            )
        else:
            result = self._chat_completions_streaming(
                runtime, prompt, on_chunk, timeout=timeout, repeat_prompt=False
            )

        if _should_retry_with_repeated_prompt(
            prompt,
            result.content,
            parsed_json=result.parsed_json,
            require_json=_should_enforce_json_response(prompt),
        ):
            repeat_used = True
            logger.debug("LocalAI retrying with repeated prompt (single)")
            result = self._chat_completions(
                runtime, prompt, timeout=timeout, repeat_prompt=True
            )

        t_req = time.perf_counter() - t1
        logger.debug(
            "[TIMING] LocalAI chat_completions%s: %.2fs (prompt_chars=%d repeated=%s)",
            "" if on_chunk is None else "_streaming",
            t_req,
            _sent_prompt_len(prompt, repeat=repeat_used),
            repeat_used,
        )
        return result.content

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        skip_clear_wait: bool = False,
        timeout: int = 300,
        include_item_ids: bool = False,
        max_retries: int = 0,
        runtime: Optional[LocalAIServerRuntime] = None,
    ) -> list[str]:
        _ = reference_files
        _ = skip_clear_wait
        _ = include_item_ids
        _ = max_retries

        if runtime is None:
            t0 = time.perf_counter()
            runtime = self.ensure_ready()
            t_ready = time.perf_counter() - t0
            logger.debug(
                "[TIMING] LocalAI ensure_ready: %.2fs (host=%s port=%d model=%s)",
                t_ready,
                runtime.host,
                runtime.port,
                runtime.model_id or runtime.model_path.name,
            )

        t1 = time.perf_counter()
        repeat_used = False
        result = self._chat_completions(
            runtime, prompt, timeout=timeout, repeat_prompt=False
        )
        try:
            parsed = parse_batch_translations(
                result.content,
                expected_count=len(texts),
                parsed_json=result.parsed_json,
            )
        except RuntimeError:
            if _should_retry_with_repeated_prompt(
                prompt,
                result.content,
                parsed_json=result.parsed_json,
                require_json=True,
            ):
                repeat_used = True
                logger.debug("LocalAI retrying with repeated prompt (batch)")
                result = self._chat_completions(
                    runtime, prompt, timeout=timeout, repeat_prompt=True
                )
                parsed = parse_batch_translations(
                    result.content,
                    expected_count=len(texts),
                    parsed_json=result.parsed_json,
                )
            else:
                raise

        t_req = time.perf_counter() - t1
        logger.debug(
            "[TIMING] LocalAI chat_completions: %.2fs (prompt_chars=%d repeated=%s items=%d)",
            t_req,
            _sent_prompt_len(prompt, repeat=repeat_used),
            repeat_used,
            len(texts),
        )
        return parsed

    def _chat_completions(
        self,
        runtime: LocalAIServerRuntime,
        prompt: str,
        *,
        timeout: Optional[int],
        force_response_format: Optional[bool] = None,
        repeat_prompt: bool = False,
    ) -> LocalAIRequestResult:
        if self._should_cancel():
            raise TranslationCancelledError("Translation cancelled by user")

        timeout_s = float(
            timeout if timeout is not None else self._settings.request_timeout
        )
        should_enforce_json = _should_enforce_json_response(prompt)
        cached_support = (
            self._get_response_format_support(runtime) if should_enforce_json else None
        )
        if force_response_format is None:
            response_format_mode: _ResponseFormatMode = (
                cached_support or ("schema" if should_enforce_json else "none")
            )
        else:
            response_format_mode = "schema" if force_response_format else "none"
        cached_sampling_support = self._get_sampling_params_support(runtime)
        include_sampling_params = cached_sampling_support is not False
        tried: set[tuple[_ResponseFormatMode, bool]] = set()
        while True:
            if self._should_cancel():
                raise TranslationCancelledError("Translation cancelled by user")
            key = (response_format_mode, include_sampling_params)
            if key in tried:
                raise RuntimeError("ローカルAIの応答形式の再試行に失敗しました")
            tried.add(key)

            enforce_json = response_format_mode != "none"
            response_format = (
                "json_object" if response_format_mode == "json_object" else None
            )
            payload = self._build_chat_payload(
                runtime,
                prompt,
                stream=False,
                enforce_json=enforce_json,
                response_format=response_format,
                include_sampling_params=include_sampling_params,
                repeat_prompt=repeat_prompt,
            )
            try:
                response = self._http_json_cancellable(
                    host=runtime.host,
                    port=runtime.port,
                    path="/v1/chat/completions",
                    payload=payload,
                    timeout_s=timeout_s,
                )
            except RuntimeError as exc:
                if (
                    include_sampling_params
                    and self._should_retry_without_sampling_params(exc)
                ):
                    if self._should_cache_sampling_params_unsupported(exc):
                        self._set_sampling_params_support(runtime, False)
                    include_sampling_params = False
                    logger.debug(
                        "LocalAI sampling params unsupported; retrying without them (%s)",
                        exc,
                    )
                    continue
                if enforce_json and self._should_retry_without_response_format(exc):
                    if (
                        response_format_mode == "schema"
                        and self._should_retry_with_json_object(exc)
                    ):
                        response_format_mode = "json_object"
                        logger.debug(
                            "LocalAI json_schema unsupported; retrying with json_object response_format (%s)",
                            exc,
                        )
                        continue
                    self._set_response_format_support(runtime, "none")
                    response_format_mode = "none"
                    logger.debug(
                        "LocalAI response_format unsupported; retrying without it (%s)",
                        exc,
                    )
                    continue
                raise

            content = _parse_openai_chat_content(response)
            parsed_json: object = _PARSED_JSON_MISSING
            empty_json_object_reply = False
            if enforce_json:
                parsed_json = loads_json_loose(content)
                empty_json_object_reply = _is_empty_json_object_reply(
                    content, parsed_json
                )
            if enforce_json and empty_json_object_reply:
                logger.debug(
                    "LocalAI response_format returned empty JSON object; retrying without it"
                )
                self._set_response_format_support(runtime, "none")
                response_format_mode = "none"
                continue

            if enforce_json and not empty_json_object_reply:
                self._set_response_format_support(runtime, response_format_mode)
            if include_sampling_params and any(
                key in payload for key in ("top_p", "top_k", "min_p", "repeat_penalty")
            ):
                self._set_sampling_params_support(runtime, True)
            self._manager.note_server_ok(runtime)
            return LocalAIRequestResult(
                content=content,
                model_id=runtime.model_id,
                parsed_json=parsed_json,
            )

    def _chat_completions_streaming(
        self,
        runtime: LocalAIServerRuntime,
        prompt: str,
        on_chunk: Callable[[str], None],
        *,
        timeout: Optional[int],
        repeat_prompt: bool = False,
    ) -> LocalAIRequestResult:
        should_enforce_json = _should_enforce_json_response(prompt)
        cached_support = (
            self._get_response_format_support(runtime) if should_enforce_json else None
        )
        response_format_mode: _ResponseFormatMode = (
            cached_support or ("schema" if should_enforce_json else "none")
        )
        cached_sampling_support = self._get_sampling_params_support(runtime)
        include_sampling_params = cached_sampling_support is not False
        tried: set[tuple[_ResponseFormatMode, bool]] = set()
        while True:
            if self._should_cancel():
                raise TranslationCancelledError("Translation cancelled by user")
            key = (response_format_mode, include_sampling_params)
            if key in tried:
                raise RuntimeError("ローカルAIの応答形式の再試行に失敗しました")
            tried.add(key)

            enforce_json = response_format_mode != "none"
            response_format = (
                "json_object" if response_format_mode == "json_object" else None
            )
            payload = self._build_chat_payload(
                runtime,
                prompt,
                stream=True,
                enforce_json=enforce_json,
                response_format=response_format,
                include_sampling_params=include_sampling_params,
                repeat_prompt=repeat_prompt,
            )
            try:
                result = self._chat_completions_streaming_with_payload(
                    runtime, payload, on_chunk, timeout=timeout
                )
            except RuntimeError as exc:
                if (
                    include_sampling_params
                    and self._should_retry_without_sampling_params(exc)
                ):
                    if self._should_cache_sampling_params_unsupported(exc):
                        self._set_sampling_params_support(runtime, False)
                    include_sampling_params = False
                    logger.debug(
                        "LocalAI sampling params unsupported; retrying streaming without them (%s)",
                        exc,
                    )
                    continue
                if enforce_json and self._should_retry_without_response_format(exc):
                    if (
                        response_format_mode == "schema"
                        and self._should_retry_with_json_object(exc)
                    ):
                        response_format_mode = "json_object"
                        logger.debug(
                            "LocalAI json_schema unsupported; retrying streaming with json_object response_format (%s)",
                            exc,
                        )
                        continue
                    self._set_response_format_support(runtime, "none")
                    response_format_mode = "none"
                    logger.debug(
                        "LocalAI response_format unsupported; retrying streaming without it (%s)",
                        exc,
                    )
                    continue
                raise

            if include_sampling_params and any(
                key in payload for key in ("top_p", "top_k", "min_p", "repeat_penalty")
            ):
                self._set_sampling_params_support(runtime, True)
            break

        empty_json_object_reply = enforce_json and _is_empty_json_object_reply(
            result.content
        )
        if empty_json_object_reply:
            logger.debug(
                "LocalAI response_format returned empty JSON object (streaming); retrying without it"
            )
            try:
                retry = self._chat_completions(
                    runtime,
                    prompt,
                    timeout=timeout,
                    force_response_format=False,
                    repeat_prompt=repeat_prompt,
                )
            except Exception as exc:
                logger.debug(
                    "LocalAI retry without response_format failed after empty JSON object (streaming) (%s)",
                    exc,
                )
            else:
                retry_empty_json_object_reply = _is_empty_json_object_reply(
                    retry.content
                )
                if not retry_empty_json_object_reply:
                    self._set_response_format_support(runtime, "none")
                    return retry

        if enforce_json and not empty_json_object_reply:
            self._set_response_format_support(runtime, response_format_mode)
        return result

    def _chat_completions_streaming_with_payload(
        self,
        runtime: LocalAIServerRuntime,
        payload: dict[str, object],
        on_chunk: Callable[[str], None],
        *,
        timeout: Optional[int],
    ) -> LocalAIRequestResult:
        if self._should_cancel():
            raise TranslationCancelledError("Translation cancelled by user")

        timeout_s = float(
            timeout if timeout is not None else self._settings.request_timeout
        )
        sock = self._open_http_stream(
            host=runtime.host,
            port=runtime.port,
            path="/v1/chat/completions",
            payload=payload,
            timeout_s=timeout_s,
        )

        start = time.monotonic()
        try:
            status_code, response_headers, initial_body = self._read_http_headers(
                sock, timeout_s, start
            )
            if status_code != 200:
                body_bytes = self._read_full_body(
                    sock, response_headers, initial_body, timeout_s, start
                )
                body_text = body_bytes.decode("utf-8", errors="replace")
                lowered = body_text.lower()
                if status_code == 400 and any(
                    token in lowered
                    for token in ("context", "ctx", "token", "too long", "exceed")
                ):
                    raise RuntimeError(f"LOCAL_PROMPT_TOO_LONG: {body_text[:200]}")
                raise RuntimeError(
                    f"ローカルAIサーバエラー（HTTP {status_code}）: {body_text[:200]}"
                )

            chunks = self._iter_body_bytes(
                sock, response_headers, initial_body, timeout_s, start
            )
            content, model_id = self._consume_sse_stream(chunks, on_chunk, start=start)
            self._manager.note_server_ok(runtime)
            return LocalAIRequestResult(
                content=content, model_id=model_id or runtime.model_id
            )
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _open_http_stream(
        self,
        *,
        host: str,
        port: int,
        path: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> socket.socket:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Host": f"{host}:{port}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Connection": "close",
            "Content-Length": str(len(body)),
        }
        request_lines = [f"POST {path} HTTP/1.1"]
        for k, v in headers.items():
            request_lines.append(f"{k}: {v}")
        request_lines.append("")
        request_lines.append("")
        request_bytes = "\r\n".join(request_lines).encode("utf-8") + body

        connect_timeout = min(5.0, timeout_s)
        try:
            sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as e:
            raise ConnectionError(f"ローカルAIサーバに接続できませんでした: {e}") from e

        sock.settimeout(0.25)
        sock.sendall(request_bytes)
        return sock

    def _recv_socket_chunk(
        self,
        sock: socket.socket,
        timeout_s: float,
        start: float,
    ) -> Optional[bytes]:
        if self._should_cancel():
            raise TranslationCancelledError("Translation cancelled by user")
        if time.monotonic() - start > timeout_s:
            raise TimeoutError("ローカルAIの応答がタイムアウトしました")
        try:
            return sock.recv(64 * 1024)
        except socket.timeout:
            return None

    def _read_http_headers(
        self,
        sock: socket.socket,
        timeout_s: float,
        start: float,
    ) -> tuple[int, dict[str, str], bytes]:
        buffer = bytearray()
        while True:
            header_end = buffer.find(b"\r\n\r\n")
            if header_end != -1:
                header_bytes = bytes(buffer[:header_end])
                body = bytes(buffer[header_end + 4 :])
                status_code, headers = self._parse_http_headers(header_bytes)
                return status_code, headers, body

            chunk = self._recv_socket_chunk(sock, timeout_s, start)
            if chunk is None:
                continue
            if not chunk:
                raise LocalAIError("HTTP応答のヘッダが見つかりませんでした")
            buffer.extend(chunk)

    def _iter_body_bytes(
        self,
        sock: socket.socket,
        headers: dict[str, str],
        initial_body: bytes,
        timeout_s: float,
        start: float,
    ) -> Iterable[bytes]:
        if headers.get("transfer-encoding", "").lower().startswith("chunked"):
            yield from self._iter_chunked_body(sock, initial_body, timeout_s, start)
            return

        content_length = headers.get("content-length")
        if content_length and content_length.isdigit():
            remaining = int(content_length) - len(initial_body)
            if initial_body:
                yield initial_body
            while remaining > 0:
                chunk = self._recv_socket_chunk(sock, timeout_s, start)
                if chunk is None:
                    continue
                if not chunk:
                    break
                if len(chunk) > remaining:
                    yield chunk[:remaining]
                    remaining = 0
                else:
                    yield chunk
                    remaining -= len(chunk)
            return

        if initial_body:
            yield initial_body
        while True:
            chunk = self._recv_socket_chunk(sock, timeout_s, start)
            if chunk is None:
                continue
            if not chunk:
                break
            yield chunk

    def _iter_chunked_body(
        self,
        sock: socket.socket,
        initial_body: bytes,
        timeout_s: float,
        start: float,
    ) -> Iterable[bytes]:
        buffer = bytearray(initial_body)
        while True:
            while True:
                line_end = buffer.find(b"\r\n")
                if line_end != -1:
                    size_line = (
                        buffer[:line_end].decode("ascii", errors="replace").strip()
                    )
                    del buffer[: line_end + 2]
                    if not size_line:
                        continue
                    try:
                        size = int(size_line.split(";", 1)[0], 16)
                    except ValueError as e:
                        raise LocalAIError(
                            "チャンクサイズを解析できませんでした"
                        ) from e
                    break
                chunk = self._recv_socket_chunk(sock, timeout_s, start)
                if chunk is None:
                    continue
                if not chunk:
                    return
                buffer.extend(chunk)

            if size == 0:
                return

            while len(buffer) < size + 2:
                chunk = self._recv_socket_chunk(sock, timeout_s, start)
                if chunk is None:
                    continue
                if not chunk:
                    return
                buffer.extend(chunk)

            if len(buffer) < size:
                return

            data = bytes(buffer[:size])
            yield data
            del buffer[:size]
            if buffer.startswith(b"\r\n"):
                del buffer[:2]

    def _consume_sse_stream(
        self,
        chunks: Iterable[bytes],
        on_chunk: Callable[[str], None],
        *,
        start: float | None = None,
    ) -> tuple[str, Optional[str]]:
        start_time = start if start is not None else time.monotonic()
        buffer = bytearray()
        pieces: list[str] = []
        model_id: Optional[str] = None
        delta_buffer: list[str] = []
        delta_buffer_len = 0
        last_flush_time = 0.0
        first_delta_emitted = False

        def _flush_delta_buffer() -> None:
            nonlocal delta_buffer_len, last_flush_time, first_delta_emitted
            if not delta_buffer:
                return
            combined = "".join(delta_buffer)
            if not combined:
                delta_buffer.clear()
                delta_buffer_len = 0
                return
            if (
                not first_delta_emitted
                and _TIMING_ENABLED
                and logger.isEnabledFor(logging.DEBUG)
            ):
                logger.debug(
                    "[TIMING] LocalAI ttft_streaming: %.3fs",
                    time.monotonic() - start_time,
                )
            delta_buffer.clear()
            delta_buffer_len = 0
            pieces.append(combined)
            on_chunk(combined)
            first_delta_emitted = True
            last_flush_time = time.monotonic()
            if self._should_cancel():
                raise TranslationCancelledError("Translation cancelled by user")

        def _process_line(line: bytes) -> Optional[bool]:
            nonlocal model_id
            if not line.startswith(b"data:"):
                return None
            payload = line[5:].strip()
            if not payload:
                return None
            if payload == b"[DONE]":
                return True
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                return None
            if model_id is None:
                candidate = obj.get("model")
                if isinstance(candidate, str):
                    model_id = candidate
            delta = _parse_openai_stream_delta(obj)
            if delta:
                nonlocal delta_buffer_len
                delta_buffer.append(delta)
                delta_buffer_len += len(delta)
                now = time.monotonic()
                if not first_delta_emitted:
                    _flush_delta_buffer()
                elif (
                    delta_buffer_len >= _SSE_DELTA_COALESCE_MIN_CHARS
                    or (now - last_flush_time) >= _SSE_DELTA_COALESCE_MAX_INTERVAL_SEC
                ):
                    _flush_delta_buffer()
                if self._should_cancel():
                    _flush_delta_buffer()
                    raise TranslationCancelledError("Translation cancelled by user")
            return None

        for chunk in chunks:
            if self._should_cancel():
                raise TranslationCancelledError("Translation cancelled by user")
            if not chunk:
                continue
            buffer.extend(chunk)
            while True:
                line_end = buffer.find(b"\n")
                if line_end == -1:
                    break
                line = bytes(buffer[:line_end]).rstrip(b"\r")
                del buffer[: line_end + 1]
                if not line:
                    continue
                done = _process_line(line)
                if done:
                    _flush_delta_buffer()
                    return "".join(pieces), model_id

        tail = bytes(buffer).strip()
        if tail:
            _process_line(tail)
        _flush_delta_buffer()
        return "".join(pieces), model_id

    def _read_full_body(
        self,
        sock: socket.socket,
        headers: dict[str, str],
        initial_body: bytes,
        timeout_s: float,
        start: float,
    ) -> bytes:
        return b"".join(
            self._iter_body_bytes(sock, headers, initial_body, timeout_s, start)
        )

    def _http_json_cancellable(
        self,
        *,
        host: str,
        port: int,
        path: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Host": f"{host}:{port}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Connection": "close",
            "Content-Length": str(len(body)),
        }
        request_lines = [f"POST {path} HTTP/1.1"]
        for k, v in headers.items():
            request_lines.append(f"{k}: {v}")
        request_lines.append("")
        request_lines.append("")
        request_bytes = "\r\n".join(request_lines).encode("utf-8") + body

        start = time.monotonic()
        connect_timeout = min(5.0, timeout_s)
        try:
            sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as e:
            raise ConnectionError(f"ローカルAIサーバに接続できませんでした: {e}") from e

        try:
            sock.settimeout(0.25)
            sock.sendall(request_bytes)

            chunks: list[bytes] = []
            while True:
                if self._should_cancel():
                    raise TranslationCancelledError("Translation cancelled by user")
                if time.monotonic() - start > timeout_s:
                    raise TimeoutError("ローカルAIの応答がタイムアウトしました")
                try:
                    chunk = sock.recv(64 * 1024)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                chunks.append(chunk)

            raw = b"".join(chunks)
            status_code, response_headers, body_bytes = self._parse_http_response(raw)
            if status_code != 200:
                body_text = body_bytes.decode("utf-8", errors="replace")
                lowered = body_text.lower()
                if status_code == 400 and any(
                    token in lowered
                    for token in ("context", "ctx", "token", "too long", "exceed")
                ):
                    raise RuntimeError(f"LOCAL_PROMPT_TOO_LONG: {body_text[:200]}")
                raise RuntimeError(
                    f"ローカルAIサーバエラー（HTTP {status_code}）: {body_text[:200]}"
                )

            try:
                return json.loads(body_bytes.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"ローカルAIサーバのJSON応答を解析できませんでした: {e}"
                ) from e
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _parse_http_headers(header_bytes: bytes) -> tuple[int, dict[str, str]]:
        header_text = header_bytes.decode("iso-8859-1", errors="replace")
        lines = header_text.split("\r\n")
        if not lines:
            raise LocalAIError("HTTP応答が空です")

        status_line = lines[0]
        try:
            status_code = int(status_line.split(" ")[1])
        except Exception as e:
            raise LocalAIError(
                f"HTTPステータス行を解析できませんでした: {status_line}"
            ) from e

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
        return status_code, headers

    @staticmethod
    def _parse_http_response(raw: bytes) -> tuple[int, dict[str, str], bytes]:
        header_end = raw.find(b"\r\n\r\n")
        if header_end == -1:
            raise LocalAIError("HTTP応答のヘッダが見つかりませんでした")

        header_bytes = raw[:header_end]
        body = raw[header_end + 4 :]

        status_code, headers = LocalAIClient._parse_http_headers(header_bytes)

        if headers.get("transfer-encoding", "").lower().startswith("chunked"):
            return status_code, headers, LocalAIClient._decode_chunked_body(body)

        content_length = headers.get("content-length")
        if content_length and content_length.isdigit():
            length = int(content_length)
            return status_code, headers, body[:length]

        return status_code, headers, body

    @staticmethod
    def _decode_chunked_body(body: bytes) -> bytes:
        out = bytearray()
        i = 0
        while True:
            j = body.find(b"\r\n", i)
            if j == -1:
                break
            size_line = body[i:j].decode("ascii", errors="replace").strip()
            if not size_line:
                break
            try:
                size = int(size_line.split(";", 1)[0], 16)
            except ValueError:
                break
            i = j + 2
            if size == 0:
                break
            out.extend(body[i : i + size])
            i = i + size + 2
        return bytes(out)
