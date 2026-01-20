from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextBlock, TranslationStatus
from yakulingo.services.prompt_builder import REFERENCE_INSTRUCTION, PromptBuilder
from yakulingo.services.translation_service import BatchTranslator, TranslationService


_REFERENCE_SENTINEL = (
    "用語集がある場合は、記載されている用語は必ずその訳語を使用してください。"
)


def test_prompt_builder_build_includes_reference_instruction_when_enabled() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    builder = PromptBuilder(prompts_dir)

    prompt = builder.build(
        "sample",
        has_reference_files=True,
        output_language="en",
        translation_style="concise",
    )
    assert _REFERENCE_SENTINEL in REFERENCE_INSTRUCTION
    assert _REFERENCE_SENTINEL in prompt


def test_prompt_builder_build_omits_reference_instruction_when_disabled() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    builder = PromptBuilder(prompts_dir)

    prompt = builder.build(
        "sample",
        has_reference_files=False,
        output_language="en",
        translation_style="concise",
    )
    assert _REFERENCE_SENTINEL not in prompt


def test_prompt_builder_build_batch_includes_reference_instruction_when_enabled() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    builder = PromptBuilder(prompts_dir)

    prompt = builder.build_batch(
        ["alpha", "beta"],
        has_reference_files=True,
        output_language="en",
        translation_style="concise",
        include_item_ids=False,
        reference_files=None,
    )
    assert _REFERENCE_SENTINEL in prompt


class _RecordingCopilot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk=None,
    ) -> str:
        self.calls.append(
            {
                "text": text,
                "prompt": prompt,
                "reference_files": reference_files,
            }
        )
        return "OK"


def test_translation_service_passes_reference_files_to_copilot_translate_single(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"

    copilot = _RecordingCopilot()
    service = TranslationService(
        copilot=copilot,  # type: ignore[arg-type]
        config=AppSettings(translation_backend="copilot"),
        prompts_dir=prompts_dir,
    )
    ref_path = tmp_path / "ref.txt"
    ref_path.write_text("ref", encoding="utf-8")
    reference_files = [ref_path]

    result = service.translate_text("hello", reference_files=reference_files)

    assert result.status == TranslationStatus.COMPLETED
    assert copilot.calls
    assert copilot.calls[0]["reference_files"] == reference_files
    assert _REFERENCE_SENTINEL in str(copilot.calls[0]["prompt"])


class _RecordingPromptBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        reference_files: list[Path] | None = None,
    ) -> str:
        self.calls.append(
            {
                "texts": list(texts),
                "has_reference_files": has_reference_files,
                "reference_files": reference_files,
            }
        )
        return "PROMPT"


class _RecordingCopilotSync:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def set_cancel_callback(self, callback) -> None:
        _ = callback

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: list[Path] | None,
        skip_clear_wait: bool,
        timeout: int | None = None,
        include_item_ids: bool = False,
    ) -> list[str]:
        _ = (prompt, skip_clear_wait, timeout, include_item_ids)
        self.calls.append({"texts": list(texts), "reference_files": reference_files})
        return [f"EN:{text}" for text in texts]


def test_batch_translator_passes_reference_files_to_backend_translate_sync(
    tmp_path: Path,
) -> None:
    prompt_builder = _RecordingPromptBuilder()
    copilot = _RecordingCopilotSync()
    translator = BatchTranslator(
        copilot=copilot,  # type: ignore[arg-type]
        prompt_builder=prompt_builder,  # type: ignore[arg-type]
        enable_cache=False,
    )

    ref_path = tmp_path / "glossary.csv"
    ref_path.write_text("a,b\n", encoding="utf-8")
    reference_files = [ref_path]
    blocks = [TextBlock(id="b1", text="A", location="Sheet1")]

    result = translator.translate_blocks_with_result(
        blocks,
        reference_files=reference_files,
        output_language="en",
    )

    assert result.translations["b1"] == "EN:A"
    assert copilot.calls and copilot.calls[0]["reference_files"] == reference_files
    assert prompt_builder.calls and prompt_builder.calls[0]["has_reference_files"] is True
