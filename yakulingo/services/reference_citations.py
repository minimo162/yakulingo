# yakulingo/services/reference_citations.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

_CITATION_TRAILING_PUNCTUATION = ".,;:!?。！？、)]}）】』」\"'”’"


def _reference_file_citation_labels(reference_files: Optional[list[Path]]) -> list[str]:
    """Return candidate citation labels shown by chat UIs for attached files."""
    if not reference_files:
        return []
    labels: set[str] = set()
    for file_path in reference_files:
        if not file_path:
            continue
        try:
            name = file_path.name.strip()
            stem = file_path.stem.strip()
        except Exception:
            continue
        if stem:
            labels.add(stem)
        if name:
            labels.add(name)
    return sorted(labels, key=len, reverse=True)


def _strip_reference_citations(text: str, reference_files: Optional[list[Path]]) -> str:
    """Strip citation labels (attached filenames) from extracted message text.

    Some chat UIs may render citations for attachments as inline UI elements
    (e.g., "glossary"). When we extract message text via innerHTML/textContent, those
    labels can be captured and end up mixed into translation results/explanations.
    This removes such labels conservatively (mainly line-end suffixes / standalone
    lines) based on the attached reference file names.
    """
    if not text or not reference_files:
        return text or ""

    labels = _reference_file_citation_labels(reference_files)
    if not labels:
        return text

    def _split_trailing_punct(line: str) -> tuple[str, str]:
        line = line.rstrip()
        idx = len(line)
        while idx > 0 and line[idx - 1] in _CITATION_TRAILING_PUNCTUATION:
            idx -= 1
        return line[:idx], line[idx:]

    def _strip_line(line: str) -> str:
        out = line
        for _ in range(10):
            working = out.rstrip()
            if not working:
                return working
            core, punct = _split_trailing_punct(working)
            core = core.rstrip()

            removed = False
            core_fold = core.casefold()
            for label in labels:
                if not label:
                    continue
                label_fold = label.casefold()
                if core_fold.endswith(label_fold):
                    core = core[: -len(label)]
                    out = f"{core}{punct}"
                    removed = True
                    break
            if not removed:
                return out.rstrip()
        return out.rstrip()

    original_lines = text.splitlines()
    cleaned_lines: list[str] = []

    for original in original_lines:
        cleaned = _strip_line(original)
        if original.strip() and not cleaned.strip():
            # Drop lines that became empty after stripping (likely citation-only).
            continue
        cleaned_lines.append(cleaned)

    while cleaned_lines and not cleaned_lines[0].strip():
        cleaned_lines.pop(0)
    while cleaned_lines and not cleaned_lines[-1].strip():
        cleaned_lines.pop()

    cleaned_text = "\n".join(cleaned_lines)
    if cleaned_text.strip():
        return cleaned_text
    return text
