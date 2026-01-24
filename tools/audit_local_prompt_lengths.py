from __future__ import annotations

import argparse
import sys
from pathlib import Path


_LOCAL_TEMPLATES: tuple[str, ...] = (
    "local_text_translate_to_en_single_json.txt",
    "local_text_translate_to_jp_json.txt",
    "local_batch_translate_to_en_json.txt",
    "local_batch_translate_to_jp_json.txt",
    "local_text_translate_to_en_3style_json.txt",
    "local_text_translate_to_en_missing_styles_json.txt",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _format_len(label: str, text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return f"- {label}: chars={len(normalized)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt length audit (Local AI)")
    parser.add_argument(
        "--sample-text",
        default="売上高は2兆2,385億円(前年同期比1,554億円減)となりました。",
    )
    parser.add_argument(
        "--sample-text-short",
        default="上期の実績について説明します。",
    )
    parser.add_argument("--batch-items", type=int, default=12)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write output to file (UTF-8).",
    )
    parser.add_argument(
        "--show-head",
        type=int,
        default=0,
        help="Show the first N lines of each built prompt (0 disables).",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    prompts_dir = repo_root / "prompts"

    out_path: Path | None = args.out
    output_lines: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        if out_path is not None:
            output_lines.append(line)

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from yakulingo.config.settings import AppSettings
    from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
    from yakulingo.services.prompt_builder import PromptBuilder

    settings = AppSettings()
    settings.use_bundled_glossary = False
    base = PromptBuilder(prompts_dir)
    builder = LocalPromptBuilder(
        prompts_dir, base_prompt_builder=base, settings=settings
    )

    emit("== Files ==")
    rules_path = prompts_dir / "translation_rules.txt"
    emit(
        _format_len(
            "prompts/translation_rules.txt (raw)",
            rules_path.read_text(encoding="utf-8"),
        )
    )
    emit(
        _format_len(
            "translation_rules (common)", base.get_translation_rules("common").strip()
        )
    )
    emit(
        _format_len(
            "translation_rules (to_en)", base.get_translation_rules("en").strip()
        )
    )
    emit(
        _format_len(
            "translation_rules (to_jp)", base.get_translation_rules("jp").strip()
        )
    )

    for name in _LOCAL_TEMPLATES:
        path = prompts_dir / name
        emit(_format_len(f"prompts/{name}", path.read_text(encoding="utf-8")))

    emit("")
    emit("== Built prompts (no reference files) ==")
    sample_text = str(args.sample_text)
    sample_text_short = str(args.sample_text_short)
    prompt_en_single = builder.build_text_to_en_single(
        sample_text,
        style="minimal",
        reference_files=None,
        detected_language="日本語",
    )
    emit(_format_len("LocalPromptBuilder.build_text_to_en_single", prompt_en_single))

    prompt_jp_single = builder.build_text_to_jp(
        "Revenue was 220k yen.",
        reference_files=None,
        detected_language="英語",
    )
    emit(_format_len("LocalPromptBuilder.build_text_to_jp", prompt_jp_single))

    batch_items = max(1, int(args.batch_items))
    batch_texts = [f"{sample_text} [{idx + 1}]" for idx in range(batch_items)]
    prompt_batch = builder.build_batch(
        batch_texts,
        has_reference_files=False,
        output_language="en",
        translation_style="minimal",
        include_item_ids=True,
        reference_files=None,
    )
    emit(_format_len("LocalPromptBuilder.build_batch (to_en)", prompt_batch))

    emit(
        _format_len(
            "translation_rules (to_en, filtered short)",
            builder._get_translation_rules_for_text("en", sample_text_short).strip(),
        )
    )
    batch_short_texts = [
        f"{sample_text_short} [{idx + 1}]" for idx in range(batch_items)
    ]
    prompt_batch_short = builder.build_batch(
        batch_short_texts,
        has_reference_files=False,
        output_language="en",
        translation_style="minimal",
        include_item_ids=True,
        reference_files=None,
    )
    emit(
        _format_len("LocalPromptBuilder.build_batch (to_en, short)", prompt_batch_short)
    )

    if args.show_head:
        head = max(1, int(args.show_head))
        emit("")
        emit("== Prompt heads ==")
        for label, prompt in (
            ("en_single", prompt_en_single),
            ("jp_single", prompt_jp_single),
            ("batch_to_en", prompt_batch),
            ("batch_to_en_short", prompt_batch_short),
        ):
            lines = prompt.replace("\r\n", "\n").replace("\r", "\n").splitlines()
            emit(f"-- {label} (first {head} lines) --")
            for line in lines[:head]:
                emit(line)
            emit("")

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
        print(f"out: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
