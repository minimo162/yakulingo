#!/usr/bin/env python3
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

UPSTREAM_BASE_URL = os.getenv("UPSTREAM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss-swallow-120b-iq4xs")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "600"))
HTTP_TIMEOUT = httpx.Timeout(REQUEST_TIMEOUT, connect=30.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        app.state.http_client = client
        yield


app = FastAPI(lifespan=lifespan)


def _safe_json_from_response(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except Exception:
        return {"error": {"message": "upstream returned non-json", "raw": response.text[:2000]}}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _extract_text_chunks(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            chunks.extend(_extract_text_chunks(item))
        return chunks
    if isinstance(value, dict):
        dict_chunks: list[str] = []
        value_type = value.get("type")
        if value_type == "input_text" and "text" in value:
            dict_chunks.append(str(value.get("text", "")))
        if isinstance(value.get("content"), str):
            dict_chunks.append(value["content"])
        if isinstance(value.get("content"), (list, dict)):
            dict_chunks.extend(_extract_text_chunks(value["content"]))
        if "text" in value and value_type != "input_text":
            dict_chunks.append(str(value.get("text", "")))
        if "input" in value:
            dict_chunks.extend(_extract_text_chunks(value.get("input")))
        return dict_chunks
    return [str(value)]


def to_input_text(value: Any) -> str:
    return "\n".join([chunk for chunk in _extract_text_chunks(value) if chunk])


def to_chat_messages(input_field: Any, instructions: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if instructions:
        messages.append({"role": "system", "content": str(instructions)})

    if isinstance(input_field, list):
        for item in input_field:
            if isinstance(item, dict) and "role" in item:
                role = str(item.get("role", "user")).lower()
                if role == "developer":
                    role = "system"
                if role not in {"system", "user", "assistant"}:
                    role = "user"
                content = to_input_text(item.get("content", item.get("input", "")))
                if content:
                    messages.append({"role": role, "content": content})
            else:
                text = to_input_text(item)
                if text:
                    messages.append({"role": "user", "content": text})
    else:
        text = to_input_text(input_field)
        if text:
            messages.append({"role": "user", "content": text})

    if not any(m["role"] == "user" for m in messages):
        fallback = to_input_text(input_field)
        if fallback:
            messages.append({"role": "user", "content": fallback})
    return messages


def upstream_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if UPSTREAM_API_KEY:
        headers["x-api-key"] = UPSTREAM_API_KEY
    return headers


def to_chat_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    model = payload.get("model", DEFAULT_MODEL)
    instructions = payload.get("instructions", "")
    messages = to_chat_messages(payload.get("input", ""), str(instructions))
    max_tokens = payload.get("max_output_tokens", payload.get("max_tokens", 512))

    chat_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": bool(payload.get("stream", False)),
    }
    for key in ("temperature", "top_p", "frequency_penalty", "presence_penalty", "stop", "seed"):
        if key in payload:
            chat_payload[key] = payload[key]
    return model, chat_payload


def _sse_line(obj: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@app.get("/v1/models")
async def passthrough_models(request: Request):
    client = get_client(request)
    r = await client.get(
        f"{UPSTREAM_BASE_URL}/models",
        headers=upstream_headers(),
    )
    return JSONResponse(status_code=r.status_code, content=_safe_json_from_response(r))


@app.post("/v1/responses")
async def responses_to_chat(request: Request):
    payload = await request.json()
    model, chat_payload = to_chat_payload(payload)
    stream_requested = bool(chat_payload.get("stream", False))
    client = get_client(request)

    if not stream_requested:
        r = await client.post(
            f"{UPSTREAM_BASE_URL}/chat/completions",
            headers=upstream_headers(),
            json=chat_payload,
        )

        body = _safe_json_from_response(r)
        if r.status_code >= 400:
            return JSONResponse(status_code=r.status_code, content=body)

        choices = body.get("choices", [])
        output_text = ""
        if choices:
            output_text = str(choices[0].get("message", {}).get("content", ""))

        usage = body.get("usage", {})
        response_body = {
            "id": body.get("id", f"resp_{uuid.uuid4().hex}"),
            "object": "response",
            "created_at": body.get("created", int(time.time())),
            "model": body.get("model", model),
            "output_text": output_text,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": output_text}],
                }
            ],
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }
        return JSONResponse(status_code=200, content=response_body)

    upstream = client.build_request(
        "POST",
        f"{UPSTREAM_BASE_URL}/chat/completions",
        headers=upstream_headers(),
        json=chat_payload,
    )
    stream = await client.send(upstream, stream=True)

    if stream.status_code >= 400:
        body = await stream.aread()
        await stream.aclose()
        try:
            parsed = json.loads(body.decode("utf-8", errors="ignore"))
        except Exception:
            parsed = {"error": {"message": "upstream error", "raw": body.decode('utf-8', errors='ignore')[:2000]}}
        return JSONResponse(status_code=stream.status_code, content=parsed)

    response_id = f"resp_{uuid.uuid4().hex}"
    created_at = int(time.time())

    async def event_generator():
        output_parts: list[str] = []
        usage: dict[str, Any] = {}

        yield _sse_line(
            {
                "type": "response.created",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "created_at": created_at,
                    "model": model,
                },
            }
        )

        try:
            async for line in stream.aiter_lines():
                if await request.is_disconnected():
                    break
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                if not isinstance(chunk, dict):
                    continue

                choice0 = (chunk.get("choices") or [{}])[0]
                delta = (choice0.get("delta") or {}).get("content", "")
                if delta:
                    output_parts.append(str(delta))
                    yield _sse_line({"type": "response.output_text.delta", "delta": str(delta)})

                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
        finally:
            await stream.aclose()

        output_text = "".join(output_parts)
        yield _sse_line({"type": "response.output_text.done", "text": output_text})
        yield _sse_line(
            {
                "type": "response.completed",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "created_at": created_at,
                    "model": model,
                    "output_text": output_text,
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": output_text}],
                        }
                    ],
                    "usage": {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                },
            }
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
