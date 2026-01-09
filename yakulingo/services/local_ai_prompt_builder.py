# yakulingo/services/local_ai_prompt_builder.py
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from yakulingo.config.settings import AppSettings
from yakulingo.services.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


_SUPPORTED_REFERENCE_EXTENSIONS = {".csv", ".txt", ".md", ".json"}


@dataclass(frozen=True)
class EmbeddedReference:
    text: str
    warnings: list[str]
    truncated: bool


class LocalPromptBuilder:
    def __init__(
        self,
        prompts_dir: Optional[Path],
        *,
        base_prompt_builder: PromptBuilder,
        settings: AppSettings,
    ) -> None:
        self.prompts_dir = prompts_dir
        self._base = base_prompt_builder
        self._settings = settings
        self._template_cache: dict[str, str] = {}
        self._template_lock = threading.Lock()
        self._rules_lock = threading.Lock()
        self._reference_cache: Optional[tuple[tuple[tuple[str, int, int], ...], EmbeddedReference]] = None
        self._reference_lock = threading.Lock()

    def _get_translation_rules(self, output_language: str) -> str:
        with self._rules_lock:
            self._base.reload_translation_rules()
            return self._base.get_translation_rules(output_language)

    def _load_template(self, filename: str) -> str:
        with self._template_lock:
            cached = self._template_cache.get(filename)
            if cached is not None:
                return cached
            if not self.prompts_dir:
                raise FileNotFoundError(f"prompts_dir is not set (missing template: {filename})")
            path = self.prompts_dir / filename
            if not path.exists():
                raise FileNotFoundError(f"Missing local AI prompt template: {path}")
            text = path.read_text(encoding="utf-8")
            self._template_cache[filename] = text
            return text

    def build_reference_embed(self, reference_files: Optional[Sequence[Path]]) -> EmbeddedReference:
        if not reference_files:
            return EmbeddedReference(text="", warnings=[], truncated=False)

        key_items: list[tuple[str, int, int]] = []
        for path in reference_files:
            try:
                stat = path.stat()
                mtime_ns = getattr(stat, "st_mtime_ns", None)
                mtime_key = int(mtime_ns) if isinstance(mtime_ns, int) else int(stat.st_mtime)
                key_items.append((str(path), mtime_key, int(stat.st_size)))
            except OSError:
                key_items.append((str(path), 0, 0))
        cache_key = tuple(key_items)

        with self._reference_lock:
            if self._reference_cache and self._reference_cache[0] == cache_key:
                return self._reference_cache[1]

        max_total_chars = 4000
        max_file_chars = 2000

        warnings: list[str] = []
        truncated = False
        total = 0
        parts: list[str] = []

        for path in reference_files:
            suffix = path.suffix.lower()
            if suffix not in _SUPPORTED_REFERENCE_EXTENSIONS:
                warnings.append(f"未対応の参照ファイルをスキップしました: {path.name}")
                continue
            try:
                content = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                warnings.append(f"参照ファイルを読み込めませんでした: {path.name}")
                continue

            content = content.strip()
            if not content:
                continue

            if len(content) > max_file_chars:
                content = content[:max_file_chars]
                truncated = True
                warnings.append(f"参照ファイルを一部省略しました（上限 {max_file_chars} 文字）: {path.name}")

            remaining = max_total_chars - total
            if remaining <= 0:
                truncated = True
                warnings.append(f"参照ファイルを一部省略しました（合計上限 {max_total_chars} 文字）")
                break

            if len(content) > remaining:
                content = content[:remaining]
                truncated = True
                warnings.append(f"参照ファイルを一部省略しました（合計上限 {max_total_chars} 文字）")

            total += len(content)
            parts.append(f"[REFERENCE:file={path.name}]\n{content}\n[/REFERENCE]")

        if not parts:
            embedded = EmbeddedReference(text="", warnings=warnings, truncated=truncated)
            with self._reference_lock:
                self._reference_cache = (cache_key, embedded)
            return embedded

        header = (
            "### 参照（埋め込み）\n"
            "- 以下の参照を優先して翻訳してください（用語集・スタイルガイド等）。\n"
            "- 参照に一致する用語がある場合は、その訳語を優先してください。\n"
            "- 参照は一部省略されている可能性があります。\n"
        )
        embedded_text = header + "\n\n".join(parts)
        embedded = EmbeddedReference(text=embedded_text, warnings=warnings, truncated=truncated)
        with self._reference_lock:
            self._reference_cache = (cache_key, embedded)
        return embedded

    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        reference_files: Optional[Sequence[Path]] = None,
    ) -> str:
        if output_language not in ("en", "jp"):
            output_language = "en"

        filename = (
            "local_batch_translate_to_en_json.txt"
            if output_language == "en"
            else "local_batch_translate_to_jp_json.txt"
        )
        template = self._load_template(filename)
        translation_rules = self._get_translation_rules(output_language)

        embedded_ref = self.build_reference_embed(reference_files)
        reference_section = embedded_ref.text if (has_reference_files and embedded_ref.text) else ""

        items = [{"id": i + 1, "text": text} for i, text in enumerate(texts)]
        items_json = json.dumps({"items": items}, ensure_ascii=False)

        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{style}", translation_style)
        prompt = prompt.replace("{items_json}", items_json)
        prompt = prompt.replace("{output_language}", output_language)
        prompt = prompt.replace("{n_items}", str(len(items)))
        return prompt

    def build_text_to_en_3style(
        self,
        text: str,
        *,
        reference_files: Optional[Sequence[Path]] = None,
        detected_language: str = "日本語",
    ) -> str:
        template = self._load_template("local_text_translate_to_en_3style_json.txt")
        translation_rules = self._get_translation_rules("en")
        embedded_ref = self.build_reference_embed(reference_files)
        reference_section = embedded_ref.text if embedded_ref.text else ""
        prompt_input_text = self._base.normalize_input_text(text, "en")
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", prompt_input_text)
        prompt = prompt.replace("{detected_language}", detected_language)
        return prompt

    def build_text_to_en_single(
        self,
        text: str,
        *,
        style: str,
        reference_files: Optional[Sequence[Path]] = None,
        detected_language: str = "日本語",
    ) -> str:
        template = self._load_template("local_text_translate_to_en_single_json.txt")
        translation_rules = self._get_translation_rules("en")
        embedded_ref = self.build_reference_embed(reference_files)
        reference_section = embedded_ref.text if embedded_ref.text else ""
        prompt_input_text = self._base.normalize_input_text(text, "en")
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", prompt_input_text)
        prompt = prompt.replace("{style}", style)
        prompt = prompt.replace("{detected_language}", detected_language)
        return prompt

    def build_text_to_jp(
        self,
        text: str,
        *,
        reference_files: Optional[Sequence[Path]] = None,
        detected_language: str = "英語",
    ) -> str:
        template = self._load_template("local_text_translate_to_jp_json.txt")
        translation_rules = self._get_translation_rules("jp")
        embedded_ref = self.build_reference_embed(reference_files)
        reference_section = embedded_ref.text if embedded_ref.text else ""
        prompt_input_text = self._base.normalize_input_text(text, "jp")
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", prompt_input_text)
        prompt = prompt.replace("{detected_language}", detected_language)
        return prompt
