# yakulingo/services/local_ai_client.py
from __future__ import annotations

import ast
import json
import logging
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_llama_server import (
    LocalAIError,
    LocalAIServerRuntime,
    get_local_llama_server_manager,
)
from yakulingo.services.copilot_handler import TranslationCancelledError

logger = logging.getLogger(__name__)


_RE_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*$", re.IGNORECASE)
_RE_TRAILING_COMMAS = re.compile(r",(\s*[}\]])")
_RE_ID_MARKER_BLOCK = re.compile(r"\[\[ID:(\d+)\]\]\s*(.+?)(?=\[\[ID:\d+\]\]|$)", re.DOTALL)
_RE_NUMBERED_LINE = re.compile(r"^\s*(\d+)\.\s*(.+)\s*$")


def _strip_code_fences(text: str) -> str:
    if "```" not in text:
        return text
    lines = []
    for line in text.splitlines():
        if _RE_CODE_FENCE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


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


def parse_batch_translations(raw_content: str, expected_count: int) -> list[str]:
    obj = loads_json_loose(raw_content)
    parsed = _parse_batch_items_json(obj, expected_count) if obj is not None else None
    if parsed is not None:
        return parsed

    fallback = _parse_batch_items_fallback(raw_content, expected_count)
    if fallback is not None:
        return fallback

    raise RuntimeError("ローカルAIの応答(JSON)を解析できませんでした")


def parse_text_to_en_3style(raw_content: str) -> dict[str, tuple[str, str]]:
    obj = loads_json_loose(raw_content)
    if not isinstance(obj, dict):
        return {}
    options = obj.get("options")
    if not isinstance(options, list):
        return {}

    by_style: dict[str, tuple[str, str]] = {}
    for opt in options:
        if not isinstance(opt, dict):
            continue
        style = opt.get("style")
        translation = opt.get("translation")
        explanation = opt.get("explanation")
        if not isinstance(style, str) or style not in ("standard", "concise", "minimal"):
            continue
        if not isinstance(translation, str):
            continue
        by_style[style] = (translation, explanation if isinstance(explanation, str) else "")
    return by_style


def parse_text_single_translation(raw_content: str) -> tuple[Optional[str], Optional[str]]:
    obj = loads_json_loose(raw_content)
    if not isinstance(obj, dict):
        return None, None
    translation = obj.get("translation")
    explanation = obj.get("explanation")
    if not isinstance(translation, str):
        return None, None
    return translation, explanation if isinstance(explanation, str) else ""


@dataclass(frozen=True)
class LocalAIRequestResult:
    content: str
    model_id: Optional[str]


class LocalAIClient:
    def __init__(
        self,
        settings: AppSettings,
    ) -> None:
        self._settings = settings
        self._manager = get_local_llama_server_manager()
        self._cancel_check: Optional[Callable[[], bool]] = None

    def set_cancel_callback(self, callback: Optional[Callable[[], bool]]) -> None:
        self._cancel_check = callback

    def _should_cancel(self) -> bool:
        cb = self._cancel_check
        try:
            return bool(cb and cb())
        except Exception:
            return False

    def ensure_ready(self) -> LocalAIServerRuntime:
        return self._manager.ensure_ready(self._settings)

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        timeout: Optional[int] = None,
    ) -> str:
        _ = text
        _ = reference_files
        _ = on_chunk
        runtime = self.ensure_ready()
        result = self._chat_completions(runtime, prompt, timeout=timeout)
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
    ) -> list[str]:
        _ = reference_files
        _ = skip_clear_wait
        _ = include_item_ids
        _ = max_retries

        runtime = self.ensure_ready()
        result = self._chat_completions(runtime, prompt, timeout=timeout)
        return parse_batch_translations(result.content, expected_count=len(texts))

    def _chat_completions(
        self,
        runtime: LocalAIServerRuntime,
        prompt: str,
        *,
        timeout: Optional[int],
    ) -> LocalAIRequestResult:
        if self._should_cancel():
            raise TranslationCancelledError("Translation cancelled by user")

        timeout_s = float(timeout if timeout is not None else self._settings.request_timeout)
        payload: dict[str, object] = {
            "model": runtime.model_id or runtime.model_path.name,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "temperature": float(self._settings.local_ai_temperature),
        }
        if self._settings.local_ai_max_tokens is not None:
            payload["max_tokens"] = int(self._settings.local_ai_max_tokens)

        response = self._http_json_cancellable(
            host=runtime.host,
            port=runtime.port,
            path="/v1/chat/completions",
            payload=payload,
            timeout_s=timeout_s,
        )

        content = _parse_openai_chat_content(response)
        return LocalAIRequestResult(content=content, model_id=runtime.model_id)

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
                    token in lowered for token in ("context", "ctx", "token", "too long", "exceed")
                ):
                    raise RuntimeError(f"LOCAL_PROMPT_TOO_LONG: {body_text[:200]}")
                raise RuntimeError(f"ローカルAIサーバエラー（HTTP {status_code}）: {body_text[:200]}")

            try:
                return json.loads(body_bytes.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise RuntimeError(f"ローカルAIサーバのJSON応答を解析できませんでした: {e}") from e
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _parse_http_response(raw: bytes) -> tuple[int, dict[str, str], bytes]:
        header_end = raw.find(b"\r\n\r\n")
        if header_end == -1:
            raise LocalAIError("HTTP応答のヘッダが見つかりませんでした")

        header_bytes = raw[:header_end]
        body = raw[header_end + 4 :]

        header_text = header_bytes.decode("iso-8859-1", errors="replace")
        lines = header_text.split("\r\n")
        if not lines:
            raise LocalAIError("HTTP応答が空です")

        status_line = lines[0]
        try:
            status_code = int(status_line.split(" ")[1])
        except Exception as e:
            raise LocalAIError(f"HTTPステータス行を解析できませんでした: {status_line}") from e

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

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
