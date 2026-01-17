# yakulingo/services/local_ai_prompt_builder.py
from __future__ import annotations

import csv
import heapq
import io
import json
import logging
import re
import threading
import unicodedata
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, cast

from yakulingo.config.settings import AppSettings
from yakulingo.services.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


_SUPPORTED_REFERENCE_EXTENSIONS = {
    ".csv",
    ".txt",
    ".md",
    ".json",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
}
_BUNDLED_GLOSSARY_FILENAMES = {"glossary.csv", "glossary_old.csv"}
_RE_GLOSSARY_MATCH_SEPARATORS = re.compile(r"[\s_/\\-]+")
_RE_GLOSSARY_ASCII_WORD = re.compile(r"^[a-z0-9]+$")
_RE_JP_YEN_AMOUNT = re.compile(
    r"(?P<sign>[▲+-])?\s*(?:(?P<trillion>\d[\d,]*(?:\.\d+)?)兆(?:(?P<oku>\d[\d,]*(?:\.\d+)?)億)?|(?P<oku_only>\d[\d,]*(?:\.\d+)?)億)(?P<yen>円)?"
)


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
        self._reference_cache: Optional[
            tuple[
                tuple[tuple[str, int, int], ...],
                Optional[tuple[int, str, str]],
                EmbeddedReference,
            ]
        ] = None
        self._reference_lock = threading.Lock()
        self._reference_file_cache: dict[tuple[str, int, int], tuple[str, bool]] = {}
        self._reference_file_lock = threading.Lock()
        self._glossary_cache: dict[
            tuple[str, int, int], list[tuple[str, str, str, str, str, str]]
        ] = {}
        self._glossary_lock = threading.Lock()

    def _get_translation_rules(self, output_language: str) -> str:
        with self._rules_lock:
            rules = self._base.get_translation_rules(output_language)
            return rules.strip()

    def _get_effective_reference_files(
        self,
        reference_files: Optional[Sequence[Path]],
        *,
        input_text: Optional[str],
    ) -> list[Path]:
        files: list[Path] = list(reference_files) if reference_files else []
        if not self._settings.use_bundled_glossary:
            return files
        if not input_text or not input_text.strip():
            return files
        if not self.prompts_dir:
            return files

        glossary_path = self.prompts_dir.parent / "glossary.csv"
        if glossary_path.exists() and glossary_path not in files:
            files.insert(0, glossary_path)
        return files

    @staticmethod
    def _input_fingerprint(text: Optional[str]) -> Optional[tuple[int, str, str]]:
        if not text:
            return None
        normalized = text.strip()
        if not normalized:
            return None
        if len(normalized) <= 128:
            return (len(normalized), normalized, normalized)
        return (len(normalized), normalized[:64], normalized[-64:])

    @staticmethod
    def _file_cache_key(path: Path) -> tuple[str, int, int]:
        try:
            stat = path.stat()
            mtime_ns = getattr(stat, "st_mtime_ns", None)
            mtime_key = (
                int(mtime_ns) if isinstance(mtime_ns, int) else int(stat.st_mtime)
            )
            return (str(path), mtime_key, int(stat.st_size))
        except OSError:
            return (str(path), 0, 0)

    def _load_glossary_pairs(
        self, path: Path, file_key: tuple[str, int, int]
    ) -> list[tuple[str, str, str, str, str, str]]:
        with self._glossary_lock:
            cached = self._glossary_cache.get(file_key)
            if cached is not None:
                return cached

        try:
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            pairs: list[tuple[str, str, str, str, str, str]] = []
        else:
            pairs = []
            for row in csv.reader(io.StringIO(raw)):
                if not row:
                    continue
                first = (row[0] or "").strip()
                if not first or first.startswith("#"):
                    continue
                second = (row[1] or "").strip() if len(row) > 1 else ""
                source_folded = self._normalize_for_glossary_match(first)
                target_folded = self._normalize_for_glossary_match(second) if second else ""
                source_compact = self._compact_for_glossary_match(source_folded)
                target_compact = self._compact_for_glossary_match(target_folded)
                pairs.append(
                    (
                        first,
                        second,
                        source_folded,
                        target_folded,
                        source_compact,
                        target_compact,
                    )
                )

        with self._glossary_lock:
            self._glossary_cache[file_key] = pairs
        return pairs

    @staticmethod
    def _normalize_for_glossary_match(text: str) -> str:
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKC", text)
        normalized = normalized.replace("\u3000", " ")
        return normalized.casefold()

    @staticmethod
    def _compact_for_glossary_match(text_folded: str) -> str:
        if not text_folded:
            return ""
        return _RE_GLOSSARY_MATCH_SEPARATORS.sub("", text_folded)

    @staticmethod
    def _matches_glossary_term(
        *,
        text_folded: str,
        text_compact: str,
        term_folded: str,
        term_compact: str,
    ) -> bool:
        term_folded = (term_folded or "").strip()
        if not term_folded:
            return False

        if term_folded.isascii() and _RE_GLOSSARY_ASCII_WORD.match(term_folded):
            pattern = rf"\b{re.escape(term_folded)}\b"
            if re.search(pattern, text_folded):
                return True
        else:
            if term_folded in text_folded:
                return True

        term_compact = (term_compact or "").strip()
        if not term_compact:
            return False
        if len(term_compact) < 4:
            return False
        return term_compact in text_compact

    @staticmethod
    def _filter_glossary_pairs(
        pairs: list[tuple[str, str, str, str, str, str]],
        input_text: str,
        *,
        max_lines: int,
    ) -> tuple[list[tuple[str, str]], bool]:
        text = (input_text or "").strip()
        if not text:
            return [], False

        text_folded = LocalPromptBuilder._normalize_for_glossary_match(text)
        text_compact = LocalPromptBuilder._compact_for_glossary_match(text_folded)

        seen: set[str] = set()
        heap: list[tuple[int, int, str, str]] = []
        matched_count = 0
        for idx, (source, target, source_folded, target_folded, source_compact, target_compact) in enumerate(pairs):
            source = (source or "").strip()
            if not source:
                continue
            if source in seen:
                continue

            matched = LocalPromptBuilder._matches_glossary_term(
                text_folded=text_folded,
                text_compact=text_compact,
                term_folded=source_folded,
                term_compact=source_compact,
            )
            if not matched and target:
                matched = LocalPromptBuilder._matches_glossary_term(
                    text_folded=text_folded,
                    text_compact=text_compact,
                    term_folded=target_folded,
                    term_compact=target_compact,
                )
            if not matched:
                continue

            seen.add(source)
            matched_count += 1
            key = max(len(source_folded or source), len(target_folded or target))
            item = (key, -idx, source, target)
            if len(heap) < max_lines:
                heapq.heappush(heap, item)
            else:
                if item > heap[0]:
                    heapq.heapreplace(heap, item)

        if not heap:
            return [], False

        selected = sorted(heap, key=lambda x: (-x[0], -x[1]))
        return [(source, target) for _, _, source, target in selected], (
            matched_count > max_lines
        )

    @staticmethod
    def _join_lines_with_limit(
        lines: Sequence[str], *, max_chars: int
    ) -> tuple[str, bool]:
        if max_chars <= 0:
            return "", True
        kept: list[str] = []
        total = 0
        for line in lines:
            if not line:
                continue
            separator_len = 0 if not kept else 1  # newline
            needed = separator_len + len(line)
            if total + needed > max_chars:
                return "\n".join(kept), True
            kept.append(line)
            total += needed
        return "\n".join(kept), False


    def _get_translation_rules_for_text(self, output_language: str, text: str) -> str:
        if not text or not text.strip():
            return ""
        return self._get_translation_rules(output_language)

    @staticmethod
    def _format_oku_amount(value: Decimal) -> str:
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

    @staticmethod
    def _parse_decimal(value: str) -> Optional[Decimal]:
        if not value:
            return None
        try:
            return Decimal(value.replace(",", ""))
        except InvalidOperation:
            return None

    def _build_to_en_numeric_hints(self, text: str) -> str:
        if not text:
            return ""
        conversions: list[tuple[str, str]] = []
        max_lines = 12
        seen: set[str] = set()
        for match in _RE_JP_YEN_AMOUNT.finditer(text):
            raw = (match.group(0) or "").strip()
            if not raw or raw in seen:
                continue
            seen.add(raw)
            sign_marker = match.group("sign") or ""
            sign = -1 if sign_marker in {"▲", "-", "−"} else 1
            trillion = self._parse_decimal(match.group("trillion") or "")
            oku_part = self._parse_decimal(match.group("oku") or "")
            oku_only = self._parse_decimal(match.group("oku_only") or "")
            if trillion is not None:
                oku_value = trillion * Decimal("10000")
                if oku_part is not None:
                    oku_value += oku_part
            elif oku_only is not None:
                oku_value = oku_only
            else:
                continue
            oku_value *= sign
            formatted = self._format_oku_amount(oku_value)
            if sign < 0:
                formatted = f"({formatted.lstrip('-')})"
            unit = "oku yen" if match.group("yen") else "oku"
            conversions.append((raw, f"{formatted} {unit}".strip()))
            if len(conversions) >= max_lines:
                break

        if not conversions:
            return ""

        lines = ["### 数値変換ヒント（必ず使用）"]
        for raw, converted in conversions:
            lines.append(f"- {raw} -> {converted}")
        return "\n".join(lines) + "\n"

    def _get_cached_reference_text(
        self,
        path: Path,
        *,
        file_key: tuple[str, int, int],
        max_chars: int,
    ) -> tuple[Optional[str], bool]:
        with self._reference_file_lock:
            cached = self._reference_file_cache.get(file_key)
        if cached is not None:
            return cached

        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return None, False

        content = content.strip()
        truncated = False
        if content and len(content) > max_chars:
            content = content[:max_chars]
            truncated = True

        with self._reference_file_lock:
            self._reference_file_cache[file_key] = (content, truncated)
        return content, truncated

    def _get_cached_binary_reference_text(
        self,
        path: Path,
        *,
        file_key: tuple[str, int, int],
        suffix: str,
        max_chars: int,
    ) -> tuple[Optional[str], bool]:
        with self._reference_file_lock:
            cached = self._reference_file_cache.get(file_key)
        if cached is not None:
            return cached

        content = self._extract_binary_reference_text(
            path,
            suffix=suffix,
            max_chars=max_chars,
        )
        if content is None:
            return None, False

        truncated = False
        with self._reference_file_lock:
            self._reference_file_cache[file_key] = (content, truncated)
        return content, truncated

    def _load_template(self, filename: str) -> str:
        with self._template_lock:
            cached = self._template_cache.get(filename)
            if cached is not None:
                return cached
            if not self.prompts_dir:
                raise FileNotFoundError(
                    f"prompts_dir is not set (missing template: {filename})"
                )
            path = self.prompts_dir / filename
            if not path.exists():
                raise FileNotFoundError(f"Missing local AI prompt template: {path}")
            text = path.read_text(encoding="utf-8")
            self._template_cache[filename] = text
            return text

    @staticmethod
    def _append_limited_text(
        chunks: list[str],
        text: str,
        *,
        max_chars: int,
        total: int,
    ) -> tuple[int, bool]:
        if not text:
            return total, False
        remaining = max_chars - total
        if remaining <= 0:
            return total, True
        if len(text) > remaining:
            chunks.append(text[:remaining])
            return max_chars, True
        chunks.append(text)
        return total + len(text), False

    @staticmethod
    def _extract_binary_reference_text(
        path: Path,
        *,
        suffix: str,
        max_chars: int,
    ) -> Optional[str]:
        def add_chunk(chunks: list[str], raw: str, total: int) -> tuple[int, bool]:
            text = (raw or "").strip()
            if not text:
                return total, False
            return LocalPromptBuilder._append_limited_text(
                chunks,
                f"{text}\n",
                max_chars=max_chars,
                total=total,
            )

        try:
            if suffix == ".pdf":
                import fitz

                doc = fitz.open(path)
                try:
                    chunks: list[str] = []
                    total = 0
                    for page in doc:
                        total, truncated = add_chunk(
                            chunks, cast(str, page.get_text("text")), total
                        )
                        if truncated:
                            break
                    return "".join(chunks).strip()
                finally:
                    doc.close()

            if suffix == ".docx":
                from docx import Document

                doc = Document(str(path))
                chunks = []
                total = 0
                for para in doc.paragraphs:
                    total, truncated = add_chunk(chunks, para.text, total)
                    if truncated:
                        break
                if total < max_chars:
                    for table in doc.tables:
                        if total >= max_chars:
                            break
                        for row in table.rows:
                            if total >= max_chars:
                                break
                            cells = [
                                cell.text
                                for cell in row.cells
                                if cell.text and cell.text.strip()
                            ]
                            if not cells:
                                continue
                            total, truncated = add_chunk(
                                chunks, "\t".join(cells), total
                            )
                            if truncated:
                                break
                return "".join(chunks).strip()

            if suffix == ".xlsx":
                import openpyxl

                wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                try:
                    chunks = []
                    total = 0
                    for sheet in wb.worksheets:
                        if total >= max_chars:
                            break
                        total, truncated = add_chunk(
                            chunks, f"[Sheet] {sheet.title}", total
                        )
                        if truncated:
                            break
                        for row in sheet.iter_rows(values_only=True):
                            if total >= max_chars:
                                break
                            row_values = [
                                str(value).strip()
                                for value in row
                                if value is not None and str(value).strip()
                            ]
                            if not row_values:
                                continue
                            total, truncated = add_chunk(
                                chunks, "\t".join(row_values), total
                            )
                            if truncated:
                                break
                    return "".join(chunks).strip()
                finally:
                    wb.close()

            if suffix == ".pptx":
                from pptx import Presentation

                pres = Presentation(str(path))
                chunks = []
                total = 0
                for slide in pres.slides:
                    if total >= max_chars:
                        break
                    for shape in slide.shapes:
                        if total >= max_chars:
                            break
                        if getattr(shape, "has_text_frame", False):
                            total, truncated = add_chunk(
                                chunks, cast(Any, shape).text, total
                            )
                            if truncated:
                                break
                return "".join(chunks).strip()
        except Exception:
            return None
        return None

    def build_reference_embed(
        self,
        reference_files: Optional[Sequence[Path]],
        *,
        input_text: Optional[str] = None,
    ) -> EmbeddedReference:
        reference_files = self._get_effective_reference_files(
            reference_files, input_text=input_text
        )
        if not reference_files:
            return EmbeddedReference(text="", warnings=[], truncated=False)

        key_items: list[tuple[str, int, int]] = []
        file_keys: dict[Path, tuple[str, int, int]] = {}
        for path in reference_files:
            file_key = self._file_cache_key(path)
            file_keys[path] = file_key
            key_items.append(file_key)
        cache_key = tuple(key_items)
        text_key = self._input_fingerprint(input_text)

        with self._reference_lock:
            if (
                self._reference_cache
                and self._reference_cache[0] == cache_key
                and self._reference_cache[1] == text_key
            ):
                return self._reference_cache[2]

        max_total_chars = 4000
        max_file_chars = 2000
        glossary_max_lines = 80

        warnings: list[str] = []
        truncated = False
        total = 0
        parts: list[str] = []

        for path in reference_files:
            file_key = file_keys.get(path) or self._file_cache_key(path)
            suffix = path.suffix.lower()
            if suffix not in _SUPPORTED_REFERENCE_EXTENSIONS:
                warnings.append(f"未対応の参照ファイルをスキップしました: {path.name}")
                continue

            is_bundled_glossary = (
                suffix == ".csv" and path.name.casefold() in _BUNDLED_GLOSSARY_FILENAMES
            )
            if is_bundled_glossary:
                if not input_text or not input_text.strip():
                    continue
                pairs = self._load_glossary_pairs(path, file_key)
                matched, glossary_truncated = self._filter_glossary_pairs(
                    pairs, input_text or "", max_lines=glossary_max_lines
                )
                if not matched:
                    continue
                lines = [
                    f"{source} 翻译成 {target}" for source, target in matched if target
                ]
                if not lines:
                    continue
                remaining_total = max_total_chars - total
                max_glossary_chars = min(max_file_chars, max(0, remaining_total))
                content, was_truncated = self._join_lines_with_limit(
                    lines, max_chars=max_glossary_chars
                )
                was_truncated = was_truncated or glossary_truncated
                if not content:
                    continue
            elif suffix in {".txt", ".md", ".json", ".csv"}:
                content, was_truncated = self._get_cached_reference_text(
                    path,
                    file_key=file_key,
                    max_chars=max_file_chars,
                )
                if content is None:
                    warnings.append(f"参照ファイルを読み込めませんでした: {path.name}")
                    continue
                if not content:
                    continue
            else:
                content, was_truncated = self._get_cached_binary_reference_text(
                    path,
                    suffix=suffix,
                    file_key=file_key,
                    max_chars=max_file_chars,
                )
                if not content:
                    warnings.append(f"参照ファイルを読み込めませんでした: {path.name}")
                    continue

            if was_truncated or len(content) > max_file_chars:
                if len(content) > max_file_chars:
                    content = content[:max_file_chars]
                truncated = True
                if not is_bundled_glossary:
                    warnings.append(
                        f"参照ファイルを一部省略しました（上限 {max_file_chars} 文字）: {path.name}"
                    )

            remaining = max_total_chars - total
            if remaining <= 0:
                truncated = True
                if not is_bundled_glossary:
                    warnings.append(
                        f"参照ファイルを一部省略しました（合計上限 {max_total_chars} 文字）"
                    )
                break

            if len(content) > remaining:
                content = content[:remaining]
                truncated = True
                if not is_bundled_glossary:
                    warnings.append(
                        f"参照ファイルを一部省略しました（合計上限 {max_total_chars} 文字）"
                    )

            total += len(content)
            parts.append(f"[REFERENCE:file={path.name}]\n{content}\n[/REFERENCE]")

        if not parts:
            embedded = EmbeddedReference(
                text="", warnings=warnings, truncated=truncated
            )
            with self._reference_lock:
                self._reference_cache = (cache_key, text_key, embedded)
            return embedded

        header = (
            "### 参照（埋め込み）\n"
            "以下の参照を優先して翻訳してください（必要に応じて省略されています）。\n"
        )
        embedded_text = header + "\n\n".join(parts)
        embedded = EmbeddedReference(
            text=embedded_text, warnings=warnings, truncated=truncated
        )
        with self._reference_lock:
            self._reference_cache = (cache_key, text_key, embedded)
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

        max_context_chars = 3000
        context_parts: list[str] = []
        total_chars = 0
        for item in texts:
            if not item:
                continue
            if total_chars >= max_context_chars:
                break
            remaining = max_context_chars - total_chars
            if len(item) > remaining:
                context_parts.append(item[:remaining])
                total_chars = max_context_chars
                break
            context_parts.append(item)
            total_chars += len(item) + 1
        context_text = "\n".join(context_parts)
        embedded_ref = self.build_reference_embed(
            reference_files, input_text=context_text
        )
        reference_section = embedded_ref.text if embedded_ref.text else ""

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
        extra_instruction: str | None = None,
    ) -> str:
        template = self._load_template("local_text_translate_to_en_3style_json.txt")
        embedded_ref = self.build_reference_embed(reference_files, input_text=text)
        translation_rules = self._get_translation_rules_for_text("en", text)
        numeric_hints = self._build_to_en_numeric_hints(text)
        reference_section = embedded_ref.text if embedded_ref.text else ""
        prompt_input_text = self._base.normalize_input_text(text, "en")
        extra_instruction = extra_instruction.strip() if extra_instruction else ""
        if extra_instruction:
            extra_instruction = f"{extra_instruction}\n"
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{numeric_hints}", numeric_hints)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{extra_instruction}", extra_instruction)
        prompt = prompt.replace("{input_text}", prompt_input_text)
        prompt = prompt.replace("{detected_language}", detected_language)
        return prompt

    def build_text_to_en_missing_styles(
        self,
        text: str,
        *,
        styles: Sequence[str],
        reference_files: Optional[Sequence[Path]] = None,
        detected_language: str = "日本語",
        extra_instruction: str | None = None,
    ) -> str:
        template = self._load_template(
            "local_text_translate_to_en_missing_styles_json.txt"
        )
        embedded_ref = self.build_reference_embed(reference_files, input_text=text)
        translation_rules = self._get_translation_rules_for_text("en", text)
        numeric_hints = self._build_to_en_numeric_hints(text)
        reference_section = embedded_ref.text if embedded_ref.text else ""
        prompt_input_text = self._base.normalize_input_text(text, "en")
        extra_instruction = extra_instruction.strip() if extra_instruction else ""
        if extra_instruction:
            extra_instruction = f"{extra_instruction}\n"
        style_list: list[str] = []
        seen: set[str] = set()
        for style in styles:
            if not style or style in seen:
                continue
            seen.add(style)
            style_list.append(style)
        styles_json = json.dumps(style_list, ensure_ascii=False)
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{numeric_hints}", numeric_hints)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{extra_instruction}", extra_instruction)
        prompt = prompt.replace("{input_text}", prompt_input_text)
        prompt = prompt.replace("{detected_language}", detected_language)
        prompt = prompt.replace("{styles_json}", styles_json)
        prompt = prompt.replace("{n_styles}", str(len(style_list)))
        return prompt

    def build_text_to_en_single(
        self,
        text: str,
        *,
        style: str,
        reference_files: Optional[Sequence[Path]] = None,
        detected_language: str = "日本語",
        extra_instruction: str | None = None,
    ) -> str:
        template = self._load_template("local_text_translate_to_en_single_json.txt")
        embedded_ref = self.build_reference_embed(reference_files, input_text=text)
        translation_rules = self._get_translation_rules_for_text("en", text)
        numeric_hints = self._build_to_en_numeric_hints(text)
        reference_section = embedded_ref.text if embedded_ref.text else ""
        prompt_input_text = self._base.normalize_input_text(text, "en")
        extra_instruction = extra_instruction.strip() if extra_instruction else ""
        if extra_instruction:
            extra_instruction = f"{extra_instruction}\n"
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{numeric_hints}", numeric_hints)
        prompt = prompt.replace("{extra_instruction}", extra_instruction)
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
        embedded_ref = self.build_reference_embed(reference_files, input_text=text)
        translation_rules = self._get_translation_rules_for_text("jp", text)
        reference_section = embedded_ref.text if embedded_ref.text else ""
        prompt_input_text = self._base.normalize_input_text(text, "jp")
        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", prompt_input_text)
        prompt = prompt.replace("{detected_language}", detected_language)
        return prompt
