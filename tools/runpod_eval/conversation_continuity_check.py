#!/usr/bin/env python3
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import error, request

MODEL_ID = "gpt-oss-swallow-120b-iq4xs"


def post_json(url: str, api_key: str, payload: dict, timeout: float) -> tuple[int, dict]:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw) if raw else {}
            return int(resp.status), parsed if isinstance(parsed, dict) else {"data": parsed}
    except error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"_raw": raw[:2000]}
        return int(e.code), parsed if isinstance(parsed, dict) else {"data": parsed}
    except Exception as e:
        return 0, {"_error": str(e)}


def extract_chat_text(body: dict) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return str(msg.get("content") or "").strip()


def extract_response_text(body: dict) -> str:
    if isinstance(body.get("output_text"), str) and body.get("output_text"):
        return str(body.get("output_text")).strip()
    output = body.get("output") or []
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = str(content.get("text") or "").strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def run_conversation_chat(base_url: str, api_key: str, timeout: float, conv_id: int, user_id: int) -> dict:
    keyword = f"KEY-{conv_id:03d}-AOIRINGO"
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    messages: list[dict[str, str]] = []

    turn1_user = f"この会話の合言葉は「{keyword}」です。合言葉だけを1語で返してください。"
    messages.append({"role": "user", "content": turn1_user})
    payload1 = {"model": MODEL_ID, "messages": messages, "max_tokens": 64}
    http1, body1 = post_json(url, api_key, payload1, timeout)
    turn1_text = extract_chat_text(body1)
    messages.append({"role": "assistant", "content": turn1_text})

    turn2_user = "もう一度、同じ合言葉だけを返してください。"
    messages.append({"role": "user", "content": turn2_user})
    payload2 = {"model": MODEL_ID, "messages": messages, "max_tokens": 64}
    http2, body2 = post_json(url, api_key, payload2, timeout)
    turn2_text = extract_chat_text(body2)
    messages.append({"role": "assistant", "content": turn2_text})

    turn3_user = "合言葉を含む短い日本語文を1文だけ返してください。"
    messages.append({"role": "user", "content": turn3_user})
    payload3 = {"model": MODEL_ID, "messages": messages, "max_tokens": 64}
    http3, body3 = post_json(url, api_key, payload3, timeout)
    turn3_text = extract_chat_text(body3)

    all_2xx = all(200 <= code < 300 for code in (http1, http2, http3))
    turn2_ok = keyword in turn2_text
    turn3_ok = keyword in turn3_text
    continued = bool(all_2xx and turn2_ok and turn3_ok)

    return {
        "api_mode": "chat",
        "user_id": user_id,
        "conv_id": conv_id,
        "keyword": keyword,
        "http1": http1,
        "http2": http2,
        "http3": http3,
        "state_id_chain_ok": 1,
        "turn2_ok": int(turn2_ok),
        "turn3_ok": int(turn3_ok),
        "continued": int(continued),
        "turn2_text": turn2_text[:200],
        "turn3_text": turn3_text[:200],
    }


def run_conversation_responses(base_url: str, api_key: str, timeout: float, conv_id: int, user_id: int) -> dict:
    keyword = f"KEY-{conv_id:03d}-AOIRINGO"
    url = f"{base_url.rstrip('/')}/v1/responses"

    turn1_payload = {
        "model": MODEL_ID,
        "input": f"この会話の合言葉は「{keyword}」です。合言葉だけを1語で返してください。",
        "stream": False,
        "max_output_tokens": 64,
    }
    http1, body1 = post_json(url, api_key, turn1_payload, timeout)
    turn1_text = extract_response_text(body1)
    resp_id_1 = str(body1.get("id") or "")

    turn2_text = ""
    turn3_text = ""
    http2 = 0
    http3 = 0
    resp_id_2 = ""
    resp_id_3 = ""

    if resp_id_1:
        turn2_payload = {
            "model": MODEL_ID,
            "input": "もう一度、同じ合言葉だけを返してください。",
            "previous_response_id": resp_id_1,
            "stream": False,
            "max_output_tokens": 64,
        }
        http2, body2 = post_json(url, api_key, turn2_payload, timeout)
        turn2_text = extract_response_text(body2)
        resp_id_2 = str(body2.get("id") or "")

        if resp_id_2:
            turn3_payload = {
                "model": MODEL_ID,
                "input": "合言葉を含む短い日本語文を1文だけ返してください。",
                "previous_response_id": resp_id_2,
                "stream": False,
                "max_output_tokens": 64,
            }
            http3, body3 = post_json(url, api_key, turn3_payload, timeout)
            turn3_text = extract_response_text(body3)
            resp_id_3 = str(body3.get("id") or "")

    all_2xx = all(200 <= code < 300 for code in (http1, http2, http3))
    turn2_ok = keyword in turn2_text
    turn3_ok = keyword in turn3_text
    state_id_chain_ok = bool(resp_id_1 and resp_id_2 and resp_id_3)
    continued = bool(all_2xx and state_id_chain_ok and turn2_ok and turn3_ok)

    return {
        "api_mode": "responses",
        "user_id": user_id,
        "conv_id": conv_id,
        "keyword": keyword,
        "http1": http1,
        "http2": http2,
        "http3": http3,
        "state_id_chain_ok": int(state_id_chain_ok),
        "turn2_ok": int(turn2_ok),
        "turn3_ok": int(turn3_ok),
        "continued": int(continued),
        "turn2_text": turn2_text[:200],
        "turn3_text": turn3_text[:200],
        "turn1_id": resp_id_1[:80],
        "turn2_id": resp_id_2[:80],
        "turn3_id": resp_id_3[:80],
        "turn1_text": turn1_text[:200],
    }


def run_conversation(api_mode: str, base_url: str, api_key: str, timeout: float, conv_id: int, user_id: int) -> dict:
    if api_mode == "responses":
        return run_conversation_responses(base_url, api_key, timeout, conv_id, user_id)
    return run_conversation_chat(base_url, api_key, timeout, conv_id, user_id)


def run_user_batch(api_mode: str, base_url: str, api_key: str, timeout: float, user_id: int, conv_start: int, conv_count: int) -> list[dict]:
    rows: list[dict] = []
    for conv_id in range(conv_start, conv_start + conv_count):
        rows.append(run_conversation(api_mode, base_url, api_key, timeout, conv_id, user_id))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--csv-log", required=True)
    parser.add_argument("--summary-log", required=True)
    parser.add_argument("--users", type=int, default=2)
    parser.add_argument("--conversations-per-user", type=int, default=15)
    parser.add_argument("--conversations", type=int, default=0, help="0の場合は users * conversations-per-user")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--api-mode", choices=["chat", "responses"], default="chat")
    args = parser.parse_args()

    if args.users < 1:
        raise ValueError("--users は1以上を指定してください")
    if args.conversations_per_user < 1 and args.conversations <= 0:
        raise ValueError("--conversations-per-user は1以上を指定してください（--conversations指定時を除く）")

    total_conversations = args.conversations if args.conversations > 0 else args.users * args.conversations_per_user
    if total_conversations < 1:
        raise ValueError("総会話数が0です。--conversations または --conversations-per-user を見直してください")

    base = total_conversations // args.users
    extra = total_conversations % args.users
    plans: list[tuple[int, int, int]] = []
    conv_cursor = 1
    for user_id in range(1, args.users + 1):
        conv_count = base + (1 if user_id <= extra else 0)
        plans.append((user_id, conv_cursor, conv_count))
        conv_cursor += conv_count

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.users) as ex:
        futures = [
            ex.submit(run_user_batch, args.api_mode, args.base_url, args.api_key, args.timeout, user_id, conv_start, conv_count)
            for (user_id, conv_start, conv_count) in plans
            if conv_count > 0
        ]
        for f in as_completed(futures):
            rows.extend(f.result())
    rows.sort(key=lambda r: r["conv_id"])

    csv_path = Path(args.csv_log)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["api_mode", "user_id", "conv_id", "keyword", "http1", "http2", "http3", "state_id_chain_ok", "turn2_ok", "turn3_ok", "continued", "turn2_text", "turn3_text"]
        )
        for r in rows:
            writer.writerow(
                [
                    r["api_mode"],
                    r["user_id"],
                    r["conv_id"],
                    r["keyword"],
                    r["http1"],
                    r["http2"],
                    r["http3"],
                    r.get("state_id_chain_ok", 0),
                    r["turn2_ok"],
                    r["turn3_ok"],
                    r["continued"],
                    r["turn2_text"],
                    r["turn3_text"],
                ]
            )

    total = len(rows)
    passed = sum(r["continued"] for r in rows)
    rate = (passed / total * 100) if total else 0.0
    state_chain_ok = sum(r.get("state_id_chain_ok", 0) for r in rows)
    summary = (
        f"api_mode={args.api_mode}\n"
        f"users={args.users}\n"
        f"conversations_per_user_target={args.conversations_per_user}\n"
        f"conversations={total}\n"
        f"continued={passed}\n"
        f"state_id_chain_ok={state_chain_ok}\n"
        f"continuity_rate={rate:.2f}%\n"
        "definition=ユーザー並行実行。3ターン連続2xxかつturn2/turn3で合言葉維持（responsesはresponse_id連鎖も必須）\n"
    )

    summary_path = Path(args.summary_log)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")
    print(summary.strip())
    print(f"raw_csv: {csv_path}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
