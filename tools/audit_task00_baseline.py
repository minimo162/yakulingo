from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except ValueError:
                pass


def _normalize_newlines(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _print_len(label: str, text: str) -> None:
    normalized = _normalize_newlines(text)
    print(f"- {label}: chars={len(normalized)}")


def _repeat_prompt_twice(prompt: str) -> str:
    if not prompt:
        return ""
    return f"{prompt}\n\n{prompt}"


class SequencedLocalClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.translate_single_calls = 0
        self.prompts: list[str] = []

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Any = None,
    ) -> str:
        _ = text
        _ = reference_files
        _ = on_chunk
        self.translate_single_calls += 1
        self.prompts.append(prompt)
        index = min(self.translate_single_calls - 1, len(self._responses) - 1)
        return self._responses[index]


def _make_local_prompt_builder():
    repo_root = _repo_root()
    prompts_dir = repo_root / "prompts"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from yakulingo.config.settings import AppSettings
    from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
    from yakulingo.services.prompt_builder import PromptBuilder

    settings = AppSettings()
    settings.use_bundled_glossary = False
    base = PromptBuilder(prompts_dir)
    builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=base,
        settings=settings,
    )
    return builder


def _make_service(local: SequencedLocalClient):
    repo_root = _repo_root()
    prompts_dir = repo_root / "prompts"

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from yakulingo.config.settings import AppSettings
    from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
    from yakulingo.services.translation_service import TranslationService

    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        config=settings,
        prompts_dir=prompts_dir,
    )
    service._local_client = local
    service._local_prompt_builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=service.prompt_builder,
        settings=settings,
    )
    service._local_batch_translator = object()
    return service


@dataclass(frozen=True)
class Scenario:
    name: str
    input_text: str
    responses: list[str]


def _summarize_result_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    keys = (
        "backend",
        "output_language_retry",
        "output_language_retry_failed",
        "to_en_numeric_rule_retry",
        "to_en_numeric_rule_retry_failed",
        "to_en_numeric_unit_correction",
        "to_en_rule_retry",
        "to_en_rule_retry_failed",
        "to_en_rule_retry_reasons",
        "to_en_rule_retry_failed_reasons",
        "to_en_negative_correction",
        "to_en_month_abbrev_correction",
    )
    return {key: metadata.get(key) for key in keys if key in metadata}


def _classify_followups(call_count: int, metadata: dict[str, Any]) -> str:
    has_retry = call_count >= 2
    has_auto_fix = any(
        metadata.get(key) is True
        for key in (
            "to_en_numeric_unit_correction",
            "to_en_negative_correction",
            "to_en_month_abbrev_correction",
        )
    )
    if has_retry and has_auto_fix:
        return "リトライ + 自動補正"
    if has_retry:
        return "リトライ"
    if has_auto_fix:
        return "自動補正（再呼び出しなし）"
    return "追加処理なし"


def main() -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="task-00 baseline audit (no server)")
    parser.add_argument(
        "--show-prompts",
        action="store_true",
        help="Print built prompt heads (first 25 lines).",
    )
    args = parser.parse_args()

    builder = _make_local_prompt_builder()

    print("== Representative inputs (prompt build) ==")
    samples = [
        "初任給は22万円です。",
        "前年差は▲50です。",
        "1月の売上",
        "A > B",
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。",
    ]
    for text in samples:
        prompt = builder.build_text_to_en_single(
            text,
            style="minimal",
            reference_files=None,
            detected_language="日本語",
        )
        repeated = _repeat_prompt_twice(prompt)

        print("")
        print(f"-- input: {text}")
        _print_len("prompt (build_text_to_en_single)", prompt)
        _print_len("prompt (sent approx; repeated twice)", repeated)

        if args.show_prompts:
            lines = _normalize_newlines(prompt).splitlines()
            head = lines[:25]
            print("prompt head:")
            for line in head:
                print(line)

    print("")
    print("== Follow-up mechanisms (retry vs auto-fix) ==")
    scenarios: list[Scenario] = [
        Scenario(
            name="output_language_mismatch_retry",
            input_text="これはテストです。",
            responses=[
                json.dumps(
                    {"translation": "一方、この人事部長の会社の初任給は22万円だ。"}
                ),
                json.dumps(
                    {"translation": "Meanwhile, the starting salary is 220k yen."}
                ),
            ],
        ),
        Scenario(
            name="k_rule_retry",
            input_text="初任給は22万円です。",
            responses=[
                json.dumps({"translation": "The starting salary is 220,000 yen."}),
                json.dumps({"translation": "The starting salary is 220k yen."}),
            ],
        ),
        Scenario(
            name="negative_triangle_retry",
            input_text="前年差は▲50です。",
            responses=[
                json.dumps({"translation": "YoY change was ▲50."}),
                json.dumps({"translation": "YoY change was (50)."}),
            ],
        ),
        Scenario(
            name="month_abbrev_retry",
            input_text="1月の売上",
            responses=[
                json.dumps({"translation": "Sales in January."}),
                json.dumps({"translation": "Sales in Jan."}),
            ],
        ),
        Scenario(
            name="oku_unit_auto_fix_no_retry",
            input_text="売上高は2兆2,385億円となりました。",
            responses=[
                json.dumps({"translation": "Net sales were 22,385 billion yen."}),
            ],
        ),
        Scenario(
            name="oku_numeric_retry_when_not_auto_fixable",
            input_text="当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。",
            responses=[
                json.dumps({"translation": "Net sales were 22,384 billion yen."}),
                json.dumps({"translation": "Net sales were 22,385 oku yen."}),
            ],
        ),
        Scenario(
            name="negative_auto_fix_after_retry_still_violates",
            input_text="前年差は▲496億円です。",
            responses=[
                json.dumps({"translation": "YoY change was -496 oku yen."}),
                json.dumps({"translation": "YoY change was -496 oku yen."}),
            ],
        ),
        Scenario(
            name="month_abbrev_auto_fix_after_retry_still_violates",
            input_text="1月の売上",
            responses=[
                json.dumps({"translation": "Sales in January."}),
                json.dumps({"translation": "Sales in January."}),
            ],
        ),
    ]

    for scenario in scenarios:
        local = SequencedLocalClient(scenario.responses)
        service = _make_service(local)
        result = service.translate_text_with_style_comparison(
            scenario.input_text,
            pre_detected_language="日本語",
        )

        metadata = _summarize_result_metadata(result.metadata)
        classification = _classify_followups(local.translate_single_calls, metadata)

        print("")
        print(f"-- scenario: {scenario.name}")
        print(f"input: {scenario.input_text}")
        print(f"translate_single_calls: {local.translate_single_calls}")
        print(f"classification: {classification}")
        print(f"error_message: {result.error_message!r}")
        if result.options:
            print(f"output[minimal]: {result.options[0].text}")
        if metadata:
            print("metadata:")
            print(json.dumps(metadata, ensure_ascii=False, indent=2))

    print("")
    print("== Notes ==")
    print("- Local AI 実送信は prompt を2回反復（sent approx はその前提の概算）")
    print("- このスクリプトはサーバ不要（翻訳はテスト同様にモック応答で分岐を観測）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
