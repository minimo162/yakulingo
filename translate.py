"""
Universal Translator
Translates text from anywhere - Excel, browser, Outlook, or any application.
Uses M365 Copilot (GPT-5) for high-quality translations.

Features:
- Excel cell translation (Japanese ↔ English, optimized for cells)
- Universal text translation (Japanese ↔ English)
- Clipboard integration for any application
- Output to Notepad for easy copying
- Global hotkeys for instant access
- System tray integration (minimize to tray)
- Glossary support via local CSV file
"""

import os
import sys
import re
import time
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum, auto

# Windows COM
import win32com.client
import pythoncom

# Playwright
from playwright.sync_api import sync_playwright, Page, BrowserContext


# =============================================================================
# Translation Mode
# =============================================================================
class TranslationMode(Enum):
    """Translation mode"""
    EXCEL_JP_TO_EN = "excel_jp_to_en"  # Excel cells: Japanese → English (compressed)
    EXCEL_EN_TO_JP = "excel_en_to_jp"  # Excel cells: English → Japanese
    TEXT_JP_TO_EN = "text_jp_to_en"    # General text: Japanese → English
    TEXT_EN_TO_JP = "text_en_to_jp"    # General text: English → Japanese


def _is_our_app_window(title: str) -> bool:
    """Check if window title belongs to our app (TranslatorApp or console)"""
    if not title:
        return False
    title_lower = title.lower()
    # Skip our app windows
    our_app_patterns = [
        "python",           # Python console
        "cmd.exe",          # Command prompt
        "powershell",       # PowerShell
        "windows powershell",
        "translate.py",     # Script name in title
        "run.bat",          # Batch file
        "★run",             # Our batch file
    ]
    for pattern in our_app_patterns:
        if pattern in title_lower:
            return True
    return False


def is_excel_active() -> bool:
    """Check if Excel was the active window before TranslatorApp"""
    try:
        import win32gui
        import win32con

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)

        # If current foreground is Excel, return True
        if "Excel" in title or "EXCEL" in title:
            return True

        # If current foreground is TranslatorApp, check the window below
        # (the window that was active before clicking the button)
        if hwnd:
            # Get the next window in Z-order (the one behind current)
            next_hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)

            # Find the first visible window with a title below (skip our app windows)
            while next_hwnd:
                if win32gui.IsWindowVisible(next_hwnd):
                    next_title = win32gui.GetWindowText(next_hwnd)
                    if next_title and not _is_our_app_window(next_title):
                        if "Excel" in next_title or "EXCEL" in next_title:
                            return True
                        # Found a visible window with title, stop searching
                        break
                next_hwnd = win32gui.GetWindow(next_hwnd, win32con.GW_HWNDNEXT)

        return False
    except Exception:
        return False


# =============================================================================
# Configuration
# =============================================================================
@dataclass
class Config:
    """Configuration"""
    # Paths (relative to script directory)
    script_dir: Path = None
    prompt_file: Path = None  # Excel JP→EN (compressed)
    prompt_file_excel_en_to_jp: Path = None  # Excel EN→JP
    prompt_file_jp_to_en: Path = None  # General JP→EN
    prompt_file_en_to_jp: Path = None  # EN→JP

    # M365 Copilot URL
    copilot_url: str = "https://m365.cloud.microsoft/chat/?auth=2"

    # CSS Selectors
    selector_input: str = "#m365-chat-editor-target-element > p"
    selector_new_chat: str = "#new-chat-button"
    selector_send: str = 'button[aria-label="送信"]'
    selector_copy: str = 'button[data-testid="CopyButtonTestId"]'

    def __post_init__(self):
        self.script_dir = Path(__file__).parent
        self.prompt_file = self.script_dir / "prompt.txt"
        self.prompt_file_excel_en_to_jp = self.script_dir / "prompt_excel_en_to_jp.txt"
        self.prompt_file_jp_to_en = self.script_dir / "prompt_jp_to_en.txt"
        self.prompt_file_en_to_jp = self.script_dir / "prompt_en_to_jp.txt"

    def get_prompt_file(self, mode: TranslationMode) -> Path:
        """Get prompt file for translation mode"""
        if mode == TranslationMode.EXCEL_JP_TO_EN:
            return self.prompt_file
        elif mode == TranslationMode.EXCEL_EN_TO_JP:
            return self.prompt_file_excel_en_to_jp
        elif mode == TranslationMode.TEXT_JP_TO_EN:
            return self.prompt_file_jp_to_en
        elif mode == TranslationMode.TEXT_EN_TO_JP:
            return self.prompt_file_en_to_jp
        return self.prompt_file


CONFIG = Config()


# =============================================================================
# Utility Functions
# =============================================================================
def has_japanese(text: str) -> bool:
    """Check if text contains Japanese characters"""
    for char in text:
        code = ord(char)
        if (0x3040 <= code <= 0x309F or
            0x30A0 <= code <= 0x30FF or
            0x4E00 <= code <= 0x9FFF):
            return True
    return False


def clean_cell_text(text: str) -> str:
    """Clean cell text"""
    if not text:
        return ""
    text = str(text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return text.strip()


def clean_copilot_response(text: str) -> str:
    """Remove markdown escapes from Copilot response"""
    replacements = [
        (r"\&", "&"), (r"\#", "#"), (r"\*", "*"), (r"\_", "_"),
        (r"\|", "|"), (r"\[", "["), (r"\]", "]"), (r"\(", "("), (r"\)", ")"),
    ]
    result = text.strip()
    for old, new in replacements:
        result = result.replace(old, new)
    result = re.sub(r"(?m)^-\s+", "'- ", result)
    result = re.sub(r"\t- ", "\t'- ", result)
    return result


# =============================================================================
# World-Class Translation Engine
# =============================================================================
class TranslationStatus(Enum):
    """Translation result status"""
    SUCCESS = auto()
    PARTIAL = auto()
    RETRY_NEEDED = auto()
    FAILED = auto()


@dataclass
class TranslationResult:
    """Result of a translation attempt"""
    status: TranslationStatus
    translations: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    missing_cells: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_response: str = ""


@dataclass
class QualityMetrics:
    """Translation quality metrics"""
    completeness: float = 0.0  # % of cells translated
    format_preserved: float = 0.0  # % with format intact
    no_japanese_remnants: float = 0.0  # % without leftover Japanese
    length_reasonable: float = 0.0  # % with reasonable length ratio
    overall_confidence: float = 0.0


class TranslationValidator:
    """Validates translation quality"""

    # Reasonable translation length ratios (Japanese is compact)
    MIN_LENGTH_RATIO = 0.3  # English shouldn't be less than 30% of Japanese
    MAX_LENGTH_RATIO = 5.0  # English shouldn't be more than 5x Japanese

    @staticmethod
    def has_japanese_remnants(text: str) -> bool:
        """Check if text still contains Japanese characters"""
        for char in text:
            code = ord(char)
            # Hiragana, Katakana, CJK (but allow some CJK punctuation)
            if (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF or  # Katakana
                0x4E00 <= code <= 0x9FFF):   # CJK Unified
                return True
        return False

    @staticmethod
    def check_format_preserved(original: str, translated: str) -> bool:
        """Check if special formatting is preserved"""
        # Check for common format patterns
        patterns = [
            r'\{[^}]+\}',      # Placeholders like {name}
            r'\[[^\]]+\]',     # Square brackets
            r'<[^>]+>',        # HTML-like tags
            r'\$\w+',          # Variables like $var
            r'%[sd]',          # Format specifiers
        ]
        for pattern in patterns:
            orig_matches = set(re.findall(pattern, original))
            trans_matches = set(re.findall(pattern, translated))
            # All original patterns should be in translation
            if orig_matches and not orig_matches.issubset(trans_matches):
                return False
        return True

    @staticmethod
    def check_length_reasonable(original: str, translated: str) -> bool:
        """Check if translation length is reasonable"""
        if not original or not translated:
            return False
        ratio = len(translated) / len(original)
        return TranslationValidator.MIN_LENGTH_RATIO <= ratio <= TranslationValidator.MAX_LENGTH_RATIO

    @classmethod
    def validate_single(cls, original: str, translated: str) -> tuple[bool, float, list[str]]:
        """
        Validate a single translation.
        Returns: (is_valid, confidence, warnings)
        """
        warnings = []
        scores = []

        # Check 1: No Japanese remnants
        if cls.has_japanese_remnants(translated):
            warnings.append("Translation contains Japanese characters")
            scores.append(0.0)
        else:
            scores.append(1.0)

        # Check 2: Format preserved
        if not cls.check_format_preserved(original, translated):
            warnings.append("Format placeholders may be missing")
            scores.append(0.5)
        else:
            scores.append(1.0)

        # Check 3: Reasonable length
        if not cls.check_length_reasonable(original, translated):
            warnings.append("Translation length seems unusual")
            scores.append(0.7)
        else:
            scores.append(1.0)

        # Calculate confidence
        confidence = sum(scores) / len(scores) if scores else 0.0
        is_valid = confidence >= 0.5 and not cls.has_japanese_remnants(translated)

        return is_valid, confidence, warnings

    @classmethod
    def validate_batch(cls, originals: dict[str, str], translations: dict[str, str]) -> QualityMetrics:
        """Validate a batch of translations"""
        if not originals:
            return QualityMetrics()

        total = len(originals)
        translated_count = 0
        format_ok_count = 0
        no_japanese_count = 0
        length_ok_count = 0
        confidence_sum = 0.0

        for address, original in originals.items():
            if address not in translations:
                continue

            translated = translations[address]
            translated_count += 1

            # Check each metric
            if not cls.has_japanese_remnants(translated):
                no_japanese_count += 1
            if cls.check_format_preserved(original, translated):
                format_ok_count += 1
            if cls.check_length_reasonable(original, translated):
                length_ok_count += 1

            _, conf, _ = cls.validate_single(original, translated)
            confidence_sum += conf

        metrics = QualityMetrics(
            completeness=translated_count / total if total > 0 else 0,
            format_preserved=format_ok_count / translated_count if translated_count > 0 else 0,
            no_japanese_remnants=no_japanese_count / translated_count if translated_count > 0 else 0,
            length_reasonable=length_ok_count / translated_count if translated_count > 0 else 0,
            overall_confidence=confidence_sum / translated_count if translated_count > 0 else 0,
        )

        return metrics


class SmartRetryStrategy:
    """Intelligent retry with exponential backoff"""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.attempt = 0

    def should_retry(self, result: TranslationResult) -> bool:
        """Determine if we should retry based on result"""
        if self.attempt >= self.max_retries:
            return False

        # Always retry on partial success (missing translations)
        if result.status == TranslationStatus.RETRY_NEEDED:
            return True

        # Retry on low confidence
        if result.status == TranslationStatus.PARTIAL and result.confidence < 0.8:
            return True

        return False

    def get_delay(self) -> float:
        """Get delay before next retry (exponential backoff)"""
        return self.base_delay * (2 ** self.attempt)

    def next_attempt(self):
        """Move to next attempt"""
        self.attempt += 1

    def reset(self):
        """Reset retry counter"""
        self.attempt = 0


class IntelligentResponseParser:
    """Advanced response parsing with multiple strategies"""

    @staticmethod
    def parse_tsv(response: str) -> dict[str, str]:
        """Parse TSV format (primary strategy)"""
        result = {}
        cleaned = clean_copilot_response(response)

        for line in cleaned.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Try tab separator first
            parts = line.split("\t", 1)
            if len(parts) == 2:
                address, translated = parts[0].strip(), parts[1].strip()
                if re.match(r"R\d+C\d+", address):
                    result[address] = translated
                    continue

            # Try multiple spaces as fallback
            parts = re.split(r'\s{2,}', line, maxsplit=1)
            if len(parts) == 2:
                address, translated = parts[0].strip(), parts[1].strip()
                if re.match(r"R\d+C\d+", address):
                    result[address] = translated

        return result

    @staticmethod
    def parse_markdown_table(response: str) -> dict[str, str]:
        """Parse markdown table format"""
        result = {}
        lines = response.split("\n")

        for line in lines:
            # Skip header/separator lines
            if '---' in line or 'Address' in line or 'セル' in line:
                continue

            # Parse pipe-separated values
            if '|' in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 2:
                    address = parts[0].strip()
                    translated = parts[-1].strip()  # Last column is usually translation
                    if re.match(r"R\d+C\d+", address):
                        result[address] = clean_copilot_response(translated)

        return result

    @staticmethod
    def parse_numbered_list(response: str, expected_addresses: list[str]) -> dict[str, str]:
        """Parse numbered list format, matching with expected addresses"""
        result = {}
        lines = response.split("\n")
        translations = []

        for line in lines:
            line = line.strip()
            # Match "1. translation" or "1) translation" format
            match = re.match(r'^\d+[.)]\s*(.+)$', line)
            if match:
                translations.append(clean_copilot_response(match.group(1)))

        # Map to addresses
        for i, addr in enumerate(expected_addresses):
            if i < len(translations):
                result[addr] = translations[i]

        return result

    @classmethod
    def parse(cls, response: str, expected_addresses: list[str] = None) -> dict[str, str]:
        """Parse response using best strategy"""
        # Strategy 1: TSV (preferred)
        result = cls.parse_tsv(response)
        if result:
            return result

        # Strategy 2: Markdown table
        result = cls.parse_markdown_table(response)
        if result:
            return result

        # Strategy 3: Numbered list (needs expected addresses)
        if expected_addresses:
            result = cls.parse_numbered_list(response, expected_addresses)
            if result:
                return result

        return {}


class TranslationEngine:
    """World-class translation engine"""

    def __init__(
        self,
        copilot: 'CopilotHandler',
        on_progress: Callable[[int, int, str], None] = None,
        on_cell_translated: Callable[[str, str, str], None] = None,
    ):
        self.copilot = copilot
        self.on_progress = on_progress  # (current, total, status_message)
        self.on_cell_translated = on_cell_translated  # (address, original, translated)
        self.validator = TranslationValidator()
        self.retry_strategy = SmartRetryStrategy(max_retries=3)
        self.parser = IntelligentResponseParser()

    def _report_progress(self, current: int, total: int, message: str):
        """Report progress to UI"""
        if self.on_progress:
            self.on_progress(current, total, message)

    def _build_retry_prompt(self, prompt_header: str, missing_cells: list[dict], attempt: int) -> str:
        """Build increasingly specific prompt for retries"""
        cells_tsv = format_cells_for_copilot(missing_cells)

        if attempt == 1:
            # First retry: add emphasis
            extra = "\n\n[IMPORTANT: Output MUST be in TSV format: ADDRESS<tab>TRANSLATION]\n"
        elif attempt >= 2:
            # Later retries: be very explicit
            extra = f"""

[CRITICAL INSTRUCTIONS]
- Output format: R#C#<tab>English translation
- Translate ALL {len(missing_cells)} cells
- One cell per line, tab-separated
- NO markdown, NO explanations, JUST translations
"""
        else:
            extra = ""

        return f"{prompt_header}{extra}\n{cells_tsv}"

    def translate(
        self,
        prompt_header: str,
        japanese_cells: list[dict],
        screenshot_path: Path = None,
        glossary_path: Path = None,
    ) -> TranslationResult:
        """
        Perform translation with smart retry and validation.
        Returns comprehensive TranslationResult.
        """
        total_cells = len(japanese_cells)
        all_translations: dict[str, str] = {}
        remaining_cells = japanese_cells.copy()
        all_warnings: list[str] = []

        self.retry_strategy.reset()

        # Build address -> original text mapping for validation
        originals = {cell['address']: cell['text'] for cell in japanese_cells}
        expected_addresses = [cell['address'] for cell in japanese_cells]

        while remaining_cells:
            attempt = self.retry_strategy.attempt

            # Progress update
            translated_count = len(all_translations)
            self._report_progress(
                translated_count, total_cells,
                f"Translating... ({translated_count}/{total_cells})"
                + (f" [Retry {attempt}]" if attempt > 0 else "")
            )

            # Build prompt
            prompt = self._build_retry_prompt(prompt_header, remaining_cells, attempt)

            # Send to Copilot
            use_screenshot = screenshot_path and attempt == 0  # Only use screenshot on first try
            use_glossary = glossary_path and attempt == 0  # Only attach glossary on first try
            if not self.copilot.send_prompt(
                prompt,
                image_path=screenshot_path if use_screenshot else None,
                glossary_path=glossary_path if use_glossary else None,
            ):
                return TranslationResult(
                    status=TranslationStatus.FAILED,
                    translations=all_translations,
                    warnings=["Failed to send prompt to Copilot"],
                )

            # Get response
            response = self.copilot.wait_and_copy_response()
            if not response:
                # Try once more to get response
                time.sleep(1)
                response = self.copilot.wait_and_copy_response()
                if not response:
                    return TranslationResult(
                        status=TranslationStatus.FAILED,
                        translations=all_translations,
                        warnings=["Failed to get response from Copilot"],
                    )

            # Parse response
            new_translations = self.parser.parse(response, expected_addresses)

            # Validate and merge translations
            for address, translated in new_translations.items():
                if address in originals and address not in all_translations:
                    original = originals[address]
                    is_valid, confidence, warnings = self.validator.validate_single(original, translated)

                    if is_valid or confidence >= 0.5:
                        all_translations[address] = translated
                        all_warnings.extend(warnings)

                        # Report individual translation
                        if self.on_cell_translated:
                            self.on_cell_translated(address, original, translated)

            # Check what's still missing
            remaining_cells = [
                cell for cell in remaining_cells
                if cell['address'] not in all_translations
            ]

            # If we got all translations, we're done
            if not remaining_cells:
                break

            # Check if we should retry
            partial_result = TranslationResult(
                status=TranslationStatus.RETRY_NEEDED,
                translations=all_translations,
                missing_cells=[c['address'] for c in remaining_cells],
            )

            if not self.retry_strategy.should_retry(partial_result):
                break

            # Wait before retry
            delay = self.retry_strategy.get_delay()
            time.sleep(delay)
            self.retry_strategy.next_attempt()

            # Start new chat for retry (clean context)
            self.copilot.new_chat()

        # Final validation
        metrics = self.validator.validate_batch(originals, all_translations)

        # Determine final status
        if len(all_translations) == total_cells and metrics.overall_confidence >= 0.8:
            status = TranslationStatus.SUCCESS
        elif len(all_translations) == total_cells:
            status = TranslationStatus.PARTIAL  # All translated but with warnings
        elif len(all_translations) > 0:
            status = TranslationStatus.PARTIAL
        else:
            status = TranslationStatus.FAILED

        return TranslationResult(
            status=status,
            translations=all_translations,
            confidence=metrics.overall_confidence,
            missing_cells=[c['address'] for c in remaining_cells],
            warnings=all_warnings,
            raw_response=response or "",
        )


def show_message(title: str, message: str, icon: str = "info", yes_no: bool = False) -> Optional[str]:
    """Show message dialog"""
    import ctypes
    MB_OK, MB_YESNO, MB_ICONINFO, MB_ICONERROR = 0x0, 0x4, 0x40, 0x10
    
    flags = MB_OK | (MB_ICONERROR if icon == "error" else MB_ICONINFO)
    
    if yes_no:
        flags = MB_YESNO | MB_ICONINFO
        result = ctypes.windll.user32.MessageBoxW(0, message, title, flags)
        return "Yes" if result == 6 else "No"
    
    ctypes.windll.user32.MessageBoxW(0, message, title, flags)
    return None


# =============================================================================
# Load Prompt
# =============================================================================
def load_prompt() -> str:
    """Load prompt from network"""
    try:
        return CONFIG.prompt_file.read_text(encoding="utf-8")
    except Exception as e:
        show_message("Error", f"Failed to load prompt file.\n{e}", "error")
        sys.exit(1)


# =============================================================================
# Excel Operations (via COM)
# =============================================================================
class ExcelHandler:
    """Excel COM operations"""
    
    def __init__(self):
        pythoncom.CoInitialize()
        self.app = None
        self.workbook = None
        self.original_sheet = None
    
    def connect(self) -> bool:
        """Connect to active Excel"""
        try:
            self.app = win32com.client.GetActiveObject("Excel.Application")
            self.workbook = self.app.ActiveWorkbook
            if not self.workbook:
                show_message("Error", "No Excel file is open.", "error")
                return False
            return True
        except Exception as e:
            show_message("Error", f"Failed to connect to Excel.\n{e}", "error")
            return False
    
    def get_selection_info(self) -> dict:
        """Get selection info - supports both cells and shapes"""
        selection = self.app.Selection
        self.original_sheet = self.app.ActiveSheet

        # Check if selection is a shape/drawing object
        selection_type = "cells"
        shape_names = []

        try:
            # Try to access ShapeRange (exists when shapes are selected)
            shape_range = selection.ShapeRange
            if shape_range.Count > 0:
                selection_type = "shapes"
                for i in range(1, shape_range.Count + 1):
                    shape_names.append(shape_range.Item(i).Name)
        except Exception:
            # Not a shape selection, it's cells
            pass

        if selection_type == "shapes":
            return {
                "sheet_name": self.original_sheet.Name,
                "selection_type": "shapes",
                "shape_names": shape_names,
            }
        else:
            return {
                "sheet_name": self.original_sheet.Name,
                "selection_type": "cells",
                "first_row": selection.Row,
                "first_col": selection.Column,
                "last_row": selection.Row + selection.Rows.Count - 1,
                "last_col": selection.Column + selection.Columns.Count - 1,
                "rows_count": selection.Rows.Count,
                "cols_count": selection.Columns.Count,
            }
    
    def _get_shapes_in_range(self, info: dict) -> list[str]:
        """Get shape names that fall within the selected cell range"""
        shapes_in_range = []
        sheet = self.original_sheet

        try:
            # Iterate through all shapes on the sheet
            for i in range(1, sheet.Shapes.Count + 1):
                try:
                    shape = sheet.Shapes.Item(i)
                    # Check if shape has text
                    if not shape.HasTextFrame:
                        continue

                    # Get shape's position using TopLeftCell
                    top_left_cell = shape.TopLeftCell
                    shape_row = top_left_cell.Row
                    shape_col = top_left_cell.Column

                    # Check if shape's top-left corner is within the selected range
                    if (info["first_row"] <= shape_row <= info["last_row"] and
                        info["first_col"] <= shape_col <= info["last_col"]):
                        shapes_in_range.append(shape.Name)
                except Exception:
                    # Skip shapes that can't be accessed
                    continue
        except Exception as e:
            print(f"  Warning: Could not enumerate shapes: {e}")

        return shapes_in_range

    def extract_japanese_cells(self, info: dict) -> list[dict]:
        """Extract cells or shapes containing Japanese"""
        japanese_cells = []
        sheet = self.original_sheet

        if info.get("selection_type") == "shapes":
            # Extract text from selected shapes
            for shape_name in info.get("shape_names", []):
                try:
                    shape = sheet.Shapes(shape_name)
                    if shape.HasTextFrame:
                        text_frame = shape.TextFrame2
                        if text_frame.HasText:
                            text = text_frame.TextRange.Text
                            text = clean_cell_text(str(text))
                            if text and has_japanese(text):
                                japanese_cells.append({
                                    "shape_name": shape_name,
                                    "address": f"SHAPE:{shape_name}",
                                    "text": text,
                                })
                except Exception as e:
                    print(f"  Warning: Could not read shape {shape_name}: {e}")
        else:
            # Extract text from cells
            for row in range(info["first_row"], info["last_row"] + 1):
                for col in range(info["first_col"], info["last_col"] + 1):
                    cell = sheet.Cells(row, col)
                    value = cell.Value
                    if value is None:
                        continue
                    text = clean_cell_text(str(value))
                    if text and has_japanese(text):
                        japanese_cells.append({
                            "row": row, "col": col,
                            "address": f"R{row}C{col}", "text": text,
                        })

            # Also extract text from shapes within the selected range
            shapes_in_range = self._get_shapes_in_range(info)
            for shape_name in shapes_in_range:
                try:
                    shape = sheet.Shapes(shape_name)
                    if shape.HasTextFrame:
                        text_frame = shape.TextFrame2
                        if text_frame.HasText:
                            text = text_frame.TextRange.Text
                            text = clean_cell_text(str(text))
                            if text and has_japanese(text):
                                japanese_cells.append({
                                    "shape_name": shape_name,
                                    "address": f"SHAPE:{shape_name}",
                                    "text": text,
                                })
                except Exception as e:
                    print(f"  Warning: Could not read shape {shape_name}: {e}")

        return japanese_cells

    def extract_english_cells(self, info: dict) -> list[dict]:
        """Extract cells or shapes containing English (non-Japanese text)"""
        english_cells = []
        sheet = self.original_sheet

        if info.get("selection_type") == "shapes":
            # Extract text from selected shapes
            for shape_name in info.get("shape_names", []):
                try:
                    shape = sheet.Shapes(shape_name)
                    if shape.HasTextFrame:
                        text_frame = shape.TextFrame2
                        if text_frame.HasText:
                            text = text_frame.TextRange.Text
                            text = clean_cell_text(str(text))
                            # Non-empty text that does NOT contain Japanese
                            if text and not has_japanese(text):
                                english_cells.append({
                                    "shape_name": shape_name,
                                    "address": f"SHAPE:{shape_name}",
                                    "text": text,
                                })
                except Exception as e:
                    print(f"  Warning: Could not read shape {shape_name}: {e}")
        else:
            # Extract text from cells
            for row in range(info["first_row"], info["last_row"] + 1):
                for col in range(info["first_col"], info["last_col"] + 1):
                    cell = sheet.Cells(row, col)
                    value = cell.Value
                    if value is None:
                        continue
                    text = clean_cell_text(str(value))
                    # Non-empty text that does NOT contain Japanese
                    if text and not has_japanese(text):
                        english_cells.append({
                            "row": row, "col": col,
                            "address": f"R{row}C{col}", "text": text,
                        })

            # Also extract text from shapes within the selected range
            shapes_in_range = self._get_shapes_in_range(info)
            for shape_name in shapes_in_range:
                try:
                    shape = sheet.Shapes(shape_name)
                    if shape.HasTextFrame:
                        text_frame = shape.TextFrame2
                        if text_frame.HasText:
                            text = text_frame.TextRange.Text
                            text = clean_cell_text(str(text))
                            # Non-empty text that does NOT contain Japanese
                            if text and not has_japanese(text):
                                english_cells.append({
                                    "shape_name": shape_name,
                                    "address": f"SHAPE:{shape_name}",
                                    "text": text,
                                })
                except Exception as e:
                    print(f"  Warning: Could not read shape {shape_name}: {e}")

        return english_cells
    
    def write_translations(self, translations: dict[str, str], info: dict):
        """Write translations back to sheet (cells or shapes)"""
        sheet = self.original_sheet
        for address, translated in translations.items():
            if address.startswith("SHAPE:"):
                # Write to shape
                shape_name = address[6:]  # Remove "SHAPE:" prefix
                try:
                    shape = sheet.Shapes(shape_name)
                    if shape.HasTextFrame:
                        shape.TextFrame2.TextRange.Text = translated
                except Exception as e:
                    print(f"  Warning: Could not write to shape {shape_name}: {e}")
            else:
                # Write to cell
                match = re.match(r"R(\d+)C(\d+)", address)
                if match:
                    row, col = int(match.group(1)), int(match.group(2))
                    sheet.Cells(row, col).Value = translated

    def capture_selection_screenshot(self) -> Optional[Path]:
        """Capture screenshot of current selection and save to temp file"""
        try:
            from PIL import ImageGrab
            import tempfile

            selection = self.app.Selection

            # Copy selection as picture to clipboard
            # xlScreen=1, xlBitmap=2
            selection.CopyPicture(Appearance=1, Format=2)

            # Small delay for clipboard
            time.sleep(0.3)

            # Grab image from clipboard
            img = ImageGrab.grabclipboard()
            if img is None:
                print("  Warning: Could not capture screenshot from clipboard")
                return None

            # Save to temp file
            temp_dir = Path(tempfile.gettempdir()) / "excel_translator"
            temp_dir.mkdir(exist_ok=True)
            screenshot_path = temp_dir / f"selection_{int(time.time())}.png"
            img.save(screenshot_path, "PNG")

            print(f"  Screenshot saved: {screenshot_path.name}")
            return screenshot_path

        except Exception as e:
            print(f"  Warning: Screenshot capture failed: {e}")
            return None

    def cleanup(self):
        """Cleanup"""
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass  # CoUninitialize may fail if not initialized


# =============================================================================
# Copilot Operations (Playwright with CDP)
# =============================================================================
class CopilotHandler:
    """M365 Copilot operations - connects to existing Edge"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.cdp_port = 9333  # Dedicated port for translator (not common 9222)
        self.profile_dir = None
        self.edge_process = None  # Track our Edge process
    
    def _find_edge_exe(self) -> Optional[str]:
        """Find Edge executable"""
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in edge_paths:
            if Path(path).exists():
                return path
        return None
    
    def _is_port_in_use(self) -> bool:
        """Check if our CDP port is in use"""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', self.cdp_port))
            sock.close()
            return result == 0
        except (socket.error, OSError):
            return False
    
    def _kill_existing_translator_edge(self):
        """Kill any Edge using our dedicated port/profile"""
        # Use netstat to find process using our port (use full path, local cwd)
        try:
            netstat_path = r"C:\Windows\System32\netstat.exe"
            taskkill_path = r"C:\Windows\System32\taskkill.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
            
            result = subprocess.run(
                [netstat_path, "-ano"],
                capture_output=True, text=True, timeout=5, cwd=local_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.split("\n"):
                if f":{self.cdp_port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        subprocess.run([taskkill_path, "/F", "/PID", pid],
                                      capture_output=True, timeout=5, cwd=local_cwd,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                        time.sleep(1)
                        break
        except (subprocess.SubprocessError, OSError, TimeoutError) as e:
            print(f"  Warning: Failed to kill existing Edge: {e}")
    
    def _start_translator_edge(self) -> bool:
        """Start dedicated Edge instance for translation"""
        edge_exe = self._find_edge_exe()
        if not edge_exe:
            show_message("Error", "Microsoft Edge not found.", "error")
            return False
        
        # Use user-local profile directory
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            self.profile_dir = Path(local_app_data) / "ExcelTranslator" / "EdgeProfile"
        else:
            self.profile_dir = Path.home() / ".excel-translator" / "edge-profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        
        # Kill any existing process on our port
        if self._is_port_in_use():
            print("  Closing previous translator Edge...", end="", flush=True)
            self._kill_existing_translator_edge()
            time.sleep(1)
            print(" done")
        
        # Start new Edge with our dedicated port and profile
        print("  Starting translator Edge...", end="", flush=True)
        try:
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
            self.edge_process = subprocess.Popen([
                edge_exe,
                f"--remote-debugging-port={self.cdp_port}",
                f"--user-data-dir={self.profile_dir}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=local_cwd)
            
            # Wait for Edge to start
            for i in range(20):
                time.sleep(0.3)
                if self._is_port_in_use():
                    print(" done")
                    return True
                if i % 3 == 0:
                    print(".", end="", flush=True)
            
            print(" timeout")
            return False
        except Exception as e:
            print(f" error: {e}")
            return False
    
    def launch(self, on_progress: Optional[Callable[[int, str], None]] = None) -> bool:
        """Launch dedicated Edge and open Copilot

        Args:
            on_progress: Optional callback (step, message) for progress updates
        """
        def progress(step: int, message: str):
            print(f"  {message}", end="", flush=True)
            if on_progress:
                on_progress(step, message)

        try:
            progress(1, "Starting Edge...")
            if not self._start_translator_edge():
                show_message("Error", "Failed to start Edge.", "error")
                return False
            print(" done")

            progress(2, "Connecting to browser...")
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.cdp_port}"
            )
            print(" done")

            # Get existing context
            contexts = self.browser.contexts
            self.context = contexts[0] if contexts else self.browser.new_context()

            # Use first existing page, close others
            pages = self.context.pages
            if pages:
                self.page = pages[0]
                # Close extra tabs (keep first one)
                for page in pages[1:]:
                    try:
                        page.close()
                    except Exception:
                        pass  # Ignore errors when closing extra tabs
            else:
                self.page = self.context.new_page()

            # Navigate to Copilot and wait for full page load
            progress(3, "Opening M365 Copilot...")
            self.page.goto(CONFIG.copilot_url, wait_until="networkidle", timeout=60000)
            print(" done")

            # Bring browser to front
            self.page.bring_to_front()

            # Wait for input field
            progress(4, "Waiting for Copilot to load...")
            try:
                self.page.wait_for_selector(CONFIG.selector_input, state="visible", timeout=30000)
                print(" ready")
            except TimeoutError:
                print(" login required")
                show_message("Login Required", "Please login to M365 Copilot.\nClick OK after logging in.")
                self.page.wait_for_selector(CONFIG.selector_input, state="visible", timeout=300000)

            # Enable GPT-5 if not already enabled
            progress(5, "Enabling GPT-5...")
            self._enable_gpt5()

            return True

        except Exception as e:
            show_message("Error", f"Failed to connect to browser.\n{e}", "error")
            return False
    
    def _enable_gpt5(self):
        """Enable GPT-5 if not already enabled"""
        try:
            # Wait for GPT-5 button to appear
            gpt5_button = self.page.wait_for_selector(
                'button.fui-ToggleButton[aria-pressed]',
                state="visible",
                timeout=10000
            )

            if gpt5_button:
                is_pressed = gpt5_button.get_attribute("aria-pressed")
                if is_pressed == "false":
                    print("  Enabling GPT-5...", end="", flush=True)
                    gpt5_button.click()
                    time.sleep(0.5)
                    print(" done")
                else:
                    print("  GPT-5 already enabled")
        except TimeoutError:
            print("  GPT-5 button not found (timeout)")
        except Exception as e:
            print(f"  GPT-5 button error: {e}")
    
    def new_chat(self):
        """Start new chat"""
        try:
            self.page.wait_for_selector(CONFIG.selector_new_chat, state="visible", timeout=10000)
            self.page.click(CONFIG.selector_new_chat)
            time.sleep(0.5)
            self.page.wait_for_selector(CONFIG.selector_input, state="visible", timeout=10000)
        except Exception as e:
            print(f"New chat error: {e}")
    
    def attach_file(self, file_path: Path) -> bool:
        """Attach a file (image, CSV, etc.) to the chat"""
        try:
            # Look for file input element (hidden)
            file_input = self.page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(str(file_path))
                time.sleep(1)
                print(f"  File attached via file input: {file_path.name}")
                return True

            # Alternative: Click attach button and use file chooser
            attach_button = self.page.query_selector('button[aria-label*="添付"], button[aria-label*="Attach"], button[data-testid*="attach"]')
            if attach_button:
                with self.page.expect_file_chooser() as fc_info:
                    attach_button.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(file_path))
                time.sleep(1)
                print(f"  File attached via button: {file_path.name}")
                return True

            print("  Warning: Could not find attach mechanism")
            return False

        except Exception as e:
            print(f"  Warning: File attach failed: {e}")
            return False

    def send_prompt(self, prompt: str, image_path: Optional[Path] = None, glossary_path: Optional[Path] = None) -> bool:
        """Send prompt with optional file attachments (image, glossary)"""
        try:
            # Bring browser to front so user can see progress
            self.page.bring_to_front()

            # Attach glossary file first if provided
            if glossary_path and glossary_path.exists():
                self.attach_file(glossary_path)

            # Attach image if provided
            if image_path and image_path.exists():
                self.attach_file(image_path)

            self.page.click(CONFIG.selector_input)
            time.sleep(0.3)
            self.page.evaluate(f"navigator.clipboard.writeText({repr(prompt)})")
            self.page.keyboard.press("Control+v")
            time.sleep(1)

            input_text = self.page.inner_text(CONFIG.selector_input)
            if not input_text.strip():
                show_message("Error", "Paste failed.\nPlease allow clipboard access in browser.", "error")
                self.page.click(CONFIG.selector_input)
                self.page.keyboard.press("Control+v")
                time.sleep(1)
                input_text = self.page.inner_text(CONFIG.selector_input)
                if not input_text.strip():
                    return False

            self.page.wait_for_selector(CONFIG.selector_send, state="visible", timeout=5000)
            self.page.click(CONFIG.selector_send)
            return True
        except Exception as e:
            print(f"Send error: {e}")
            return False
    
    def wait_and_copy_response(self) -> Optional[str]:
        """Wait for response and copy"""
        try:
            self.page.wait_for_selector(CONFIG.selector_copy, state="visible", timeout=180000)
            time.sleep(0.5)
            self.page.click(CONFIG.selector_copy)
            time.sleep(0.3)
            return self.page.evaluate("navigator.clipboard.readText()")
        except Exception as e:
            print(f"Response error: {e}")
            return None
    
    def close(self):
        """Close browser gracefully to save profile"""
        try:
            # Close the page first
            if self.page:
                try:
                    self.page.close()
                except Exception:
                    pass  # Page may already be closed

            # Close browser context
            if self.context:
                try:
                    self.context.close()
                except Exception:
                    pass  # Context may already be closed

            # Disconnect from browser (don't close it yet)
            if self.browser:
                try:
                    self.browser.close()
                except Exception:
                    pass  # Browser may already be disconnected

            # Stop playwright
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass  # Playwright may already be stopped

            # Give Edge time to save profile
            time.sleep(1)

            # Close Edge gracefully using window close (not kill)
            if self.edge_process:
                try:
                    # Send close signal and wait
                    self.edge_process.terminate()
                    self.edge_process.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    # If still running, wait more for profile save
                    time.sleep(2)
                    try:
                        self.edge_process.kill()
                    except OSError:
                        pass  # Process may have already exited

            # Final cleanup if port still in use
            time.sleep(0.5)
            if self._is_port_in_use():
                self._kill_existing_translator_edge()

        except Exception as e:
            print(f"  Close error: {e}")


# =============================================================================
# Shared Copilot Connection Manager
# =============================================================================
import threading as _threading
_shared_copilot_lock = _threading.Lock()  # Module-level lock to avoid race condition


class SharedCopilotManager:
    """
    Manages a shared CopilotHandler instance across translations.
    Keeps the browser open between translations for faster performance.
    """
    _instance: Optional[CopilotHandler] = None

    @classmethod
    def _is_connection_valid(cls) -> bool:
        """Check if the current connection is still valid and working"""
        if cls._instance is None:
            return False
        try:
            # Check if browser and page objects exist
            if cls._instance.browser is None or cls._instance.page is None:
                return False
            # Try to verify the page is still responsive
            if not cls._instance.browser.is_connected():
                return False
            # Page might be closed or crashed
            if cls._instance.page.is_closed():
                return False
            return True
        except Exception:
            return False

    @classmethod
    def get_copilot(cls, on_progress: Optional[Callable[[int, str], None]] = None) -> Optional[CopilotHandler]:
        """Get the shared CopilotHandler, launching if needed

        Args:
            on_progress: Optional callback (step, message) for progress updates during initial connection
        """
        with _shared_copilot_lock:
            # Check if existing connection is still valid
            if cls._instance is not None:
                if cls._is_connection_valid():
                    return cls._instance
                else:
                    # Connection is invalid, clean up and create new one
                    print("  Previous connection invalid, reconnecting...")
                    if on_progress:
                        on_progress(0, "Reconnecting...")
                    try:
                        cls._instance.close()
                    except Exception:
                        pass
                    cls._instance = None

            # Create new instance
            cls._instance = CopilotHandler()
            if not cls._instance.launch(on_progress=on_progress):
                cls._instance = None
                return None
            return cls._instance

    @classmethod
    def is_connected(cls) -> bool:
        """Check if Copilot is already connected and valid"""
        return cls._is_connection_valid()

    @classmethod
    def new_chat(cls):
        """Start a new chat in the existing connection"""
        if cls._instance:
            cls._instance.new_chat()

    @classmethod
    def close(cls):
        """Close the shared Copilot (called on app exit)"""
        with _shared_copilot_lock:
            if cls._instance:
                cls._instance.close()
                cls._instance = None


# =============================================================================
# Universal Text Translation (Clipboard-based)
# =============================================================================
class UniversalTranslator:
    """
    Translates text from clipboard and outputs to Notepad.
    Works with any application - just select text and use hotkey.
    """

    def __init__(self, mode: TranslationMode = TranslationMode.TEXT_JP_TO_EN):
        self.mode = mode
        self.copilot: Optional[CopilotHandler] = None

    def get_clipboard_text(self) -> Optional[str]:
        """Get text from clipboard"""
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                    return text.strip() if text else None
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            print(f"Clipboard error: {e}")
        return None

    def get_clipboard_image(self) -> Optional[Path]:
        """Get image from clipboard and save to temp file"""
        try:
            from PIL import ImageGrab
            import tempfile

            img = ImageGrab.grabclipboard()
            if img is None:
                return None

            # Save to temp file
            temp_dir = Path(tempfile.gettempdir()) / "excel_translator"
            temp_dir.mkdir(exist_ok=True)
            image_path = temp_dir / f"clipboard_{int(time.time())}.png"
            img.save(image_path, "PNG")
            print(f"  Clipboard image saved: {image_path.name}")
            return image_path
        except Exception as e:
            print(f"Clipboard image error: {e}")
        return None

    def translate_image(self, image_path: Path, on_progress: Optional[Callable[[int, str], None]] = None) -> Optional[str]:
        """Translate image using Copilot (OCR + translation)

        Args:
            image_path: Path to image file
            on_progress: Optional callback (step, message) for connection progress updates
        """
        if not image_path or not image_path.exists():
            return None

        # Build prompt for image translation
        if self.mode == TranslationMode.TEXT_JP_TO_EN:
            prompt = "Please extract any Japanese text from this image and translate it to English. Output only the translation."
        else:
            prompt = "Please extract any English text from this image and translate it to Japanese. Output only the translation."

        # Get or launch shared Copilot
        already_connected = SharedCopilotManager.is_connected()
        self.copilot = SharedCopilotManager.get_copilot(
            on_progress=on_progress if not already_connected else None
        )
        if not self.copilot:
            return None

        # Start new chat if reusing connection
        if already_connected:
            print("  Reusing existing Copilot connection...")
            SharedCopilotManager.new_chat()

        # Send prompt with image
        if not self.copilot.send_prompt(prompt, image_path=image_path):
            return None

        # Get response
        response = self.copilot.wait_and_copy_response()
        if response:
            return clean_copilot_response(response)

        return None

    def set_clipboard_text(self, text: str):
        """Set text to clipboard"""
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            print(f"Clipboard set error: {e}")

    def copy_selected_text(self):
        """Send Ctrl+C to copy selected text from the previous window"""
        try:
            import keyboard
            import win32gui
            import win32con

            # Get current foreground window (TranslatorApp)
            current_hwnd = win32gui.GetForegroundWindow()

            # Find the previous window (the one with the text to copy)
            # Skip our app windows (console, etc.)
            prev_hwnd = win32gui.GetWindow(current_hwnd, win32con.GW_HWNDNEXT)
            while prev_hwnd:
                if win32gui.IsWindowVisible(prev_hwnd):
                    title = win32gui.GetWindowText(prev_hwnd)
                    # Skip windows without title and our app windows
                    if title and not _is_our_app_window(title):
                        break
                prev_hwnd = win32gui.GetWindow(prev_hwnd, win32con.GW_HWNDNEXT)

            # Give focus to the previous window
            if prev_hwnd:
                win32gui.SetForegroundWindow(prev_hwnd)
                time.sleep(0.1)

            # Send Ctrl+C to copy
            keyboard.send('ctrl+c')
            time.sleep(0.3)

            # Return focus to our app (optional, may not be needed)
            if current_hwnd:
                try:
                    win32gui.SetForegroundWindow(current_hwnd)
                except Exception:
                    pass

        except Exception as e:
            print(f"Copy error: {e}")

    def open_notepad_with_text(self, original: str, translated: str):
        """Open Notepad and paste the translation result"""
        try:
            import win32gui
            import win32con
            import win32clipboard
            import keyboard
            import win32process

            # Format output
            output = f"""=== Original ===
{original}

=== Translation ({self._get_direction_label()}) ===
{translated}
"""
            # Get list of existing Notepad windows BEFORE opening new one
            existing_notepad_hwnds = set()
            def find_existing_notepad(hwnd, hwnds):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if "メモ帳" in title or "Notepad" in title or "無題" in title or "Untitled" in title:
                        hwnds.add(hwnd)
                return True
            win32gui.EnumWindows(find_existing_notepad, existing_notepad_hwnds)

            # Open NEW Notepad
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
            notepad_path = os.path.join(local_cwd, "notepad.exe")
            proc = subprocess.Popen([notepad_path], cwd=local_cwd)
            new_pid = proc.pid

            # Wait for NEW Notepad window (not in existing list)
            notepad_hwnd = None
            for _ in range(50):  # Try for up to 5 seconds
                time.sleep(0.1)
                def find_new_notepad(hwnd, result):
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if "メモ帳" in title or "Notepad" in title or "無題" in title or "Untitled" in title:
                            # Check if this is NOT an existing window
                            if hwnd not in existing_notepad_hwnds:
                                # Verify it's our process
                                try:
                                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                                    if pid == new_pid:
                                        result.append(hwnd)
                                except Exception:
                                    # If can't get PID, still use it if not in existing
                                    result.append(hwnd)
                    return True
                result = []
                win32gui.EnumWindows(find_new_notepad, result)
                if result:
                    notepad_hwnd = result[0]
                    break

            if not notepad_hwnd:
                print("  Warning: Failed to find new Notepad window")
                return

            # Activate Notepad window and paste
            for attempt in range(10):  # Try up to 10 times
                try:
                    # Restore if minimized
                    if win32gui.IsIconic(notepad_hwnd):
                        win32gui.ShowWindow(notepad_hwnd, win32con.SW_RESTORE)
                        time.sleep(0.2)

                    # Bring to front and activate
                    win32gui.ShowWindow(notepad_hwnd, win32con.SW_SHOW)

                    # Use Alt key trick to allow SetForegroundWindow
                    keyboard.press('alt')
                    time.sleep(0.05)
                    win32gui.SetForegroundWindow(notepad_hwnd)
                    keyboard.release('alt')
                    time.sleep(0.3)

                    # Verify Notepad is in foreground
                    current_fg = win32gui.GetForegroundWindow()
                    if current_fg != notepad_hwnd:
                        print(f"  Notepad not in foreground (attempt {attempt + 1}), retrying...")
                        time.sleep(0.3)
                        continue

                    # Notepad is active - NOW copy to clipboard and paste immediately
                    win32clipboard.OpenClipboard()
                    try:
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, output)
                    finally:
                        win32clipboard.CloseClipboard()

                    # Paste immediately after copying
                    time.sleep(0.1)
                    keyboard.send('ctrl+v')
                    time.sleep(0.3)

                    print("  Translation pasted to Notepad")
                    break

                except Exception as e:
                    print(f"  Paste attempt {attempt + 1} failed: {e}")
                    time.sleep(0.3)
                    continue

        except Exception as e:
            print(f"  Notepad error: {e}")

    def _get_direction_label(self) -> str:
        """Get human-readable direction label"""
        if self.mode == TranslationMode.TEXT_JP_TO_EN:
            return "Japanese → English"
        elif self.mode == TranslationMode.TEXT_EN_TO_JP:
            return "English → Japanese"
        return "Translation"

    def load_prompt(self) -> str:
        """Load prompt for current mode with glossary reference"""
        prompt_file = CONFIG.get_prompt_file(self.mode)
        try:
            prompt = prompt_file.read_text(encoding="utf-8")
            # Add glossary reference if configured
            from config_manager import get_config
            glossary_addition = get_config().get_glossary_prompt_addition()
            if glossary_addition:
                prompt = prompt + glossary_addition
            return prompt
        except Exception as e:
            show_message("Error", f"Failed to load prompt file.\n{e}", "error")
            return ""

    def translate_text(self, text: str, on_progress: Optional[Callable[[int, str], None]] = None) -> Optional[str]:
        """Translate text using Copilot

        Args:
            text: Text to translate
            on_progress: Optional callback (step, message) for connection progress updates
        """
        if not text:
            return None

        # Load prompt
        prompt_header = self.load_prompt()
        if not prompt_header:
            return None

        # Get glossary file path
        from config_manager import get_config
        glossary_path = get_config().get_glossary_file_path()

        # Build full prompt
        full_prompt = f"{prompt_header}\n{text}"

        # Get or launch shared Copilot (reuse existing connection)
        already_connected = SharedCopilotManager.is_connected()
        self.copilot = SharedCopilotManager.get_copilot(
            on_progress=on_progress if not already_connected else None
        )
        if not self.copilot:
            return None

        # Start new chat if reusing connection
        if already_connected:
            print("  Reusing existing Copilot connection...")
            SharedCopilotManager.new_chat()

        # Send prompt with glossary attachment
        if not self.copilot.send_prompt(full_prompt, glossary_path=glossary_path):
            return None

        # Get response
        response = self.copilot.wait_and_copy_response()
        if response:
            return clean_copilot_response(response)

        return None

    def close(self):
        """Don't close shared Copilot - keep connection for next translation"""
        # Shared Copilot is managed by SharedCopilotManager
        pass


def open_notepad_with_excel_log(translation_pairs: list, direction: str = "JP → EN"):
    """Open Notepad with Excel translation log (original and translated text) with verification

    Args:
        translation_pairs: List of (original, translated) tuples
        direction: Translation direction label
    """
    try:
        import win32gui
        import win32con
        import win32clipboard
        import keyboard
        import win32process

        # Format output with both original and translated text
        lines = [f"=== Excel Translation Log ({direction}) ===", ""]
        for i, (original, translated) in enumerate(translation_pairs, 1):
            lines.append(f"[{i}] Original:")
            lines.append(f"    {original}")
            lines.append(f"    → {translated}")
            lines.append("")

        lines.append(f"=== {len(translation_pairs)} cells translated ===")
        output = "\n".join(lines)

        # Get list of existing Notepad windows BEFORE opening new one
        existing_notepad_hwnds = set()
        def find_existing_notepad(hwnd, hwnds):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "メモ帳" in title or "Notepad" in title or "無題" in title or "Untitled" in title:
                    hwnds.add(hwnd)
            return True
        win32gui.EnumWindows(find_existing_notepad, existing_notepad_hwnds)

        # Open NEW Notepad
        local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
        notepad_path = os.path.join(local_cwd, "notepad.exe")
        proc = subprocess.Popen([notepad_path], cwd=local_cwd)
        new_pid = proc.pid

        # Wait for NEW Notepad window (not in existing list)
        notepad_hwnd = None
        for _ in range(50):  # Try for up to 5 seconds
            time.sleep(0.1)
            def find_new_notepad(hwnd, result):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if "メモ帳" in title or "Notepad" in title or "無題" in title or "Untitled" in title:
                        # Check if this is NOT an existing window
                        if hwnd not in existing_notepad_hwnds:
                            # Verify it's our process
                            try:
                                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                                if pid == new_pid:
                                    result.append(hwnd)
                            except Exception:
                                # If can't get PID, still use it if not in existing
                                result.append(hwnd)
                return True
            result = []
            win32gui.EnumWindows(find_new_notepad, result)
            if result:
                notepad_hwnd = result[0]
                break

        if not notepad_hwnd:
            print("  Warning: Could not find new Notepad window")
            return

        # Activate Notepad window and paste
        for attempt in range(10):  # Try up to 10 times
            try:
                # Restore if minimized
                if win32gui.IsIconic(notepad_hwnd):
                    win32gui.ShowWindow(notepad_hwnd, win32con.SW_RESTORE)
                    time.sleep(0.2)

                # Bring to front and activate
                win32gui.ShowWindow(notepad_hwnd, win32con.SW_SHOW)

                # Use Alt key trick to allow SetForegroundWindow
                keyboard.press('alt')
                time.sleep(0.05)
                win32gui.SetForegroundWindow(notepad_hwnd)
                keyboard.release('alt')
                time.sleep(0.3)

                # Verify Notepad is in foreground
                current_fg = win32gui.GetForegroundWindow()
                if current_fg != notepad_hwnd:
                    print(f"  Notepad not in foreground (attempt {attempt + 1}), retrying...")
                    time.sleep(0.3)
                    continue

                # Notepad is active - NOW copy to clipboard and paste immediately
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, output)
                finally:
                    win32clipboard.CloseClipboard()

                # Paste immediately after copying
                time.sleep(0.1)
                keyboard.send('ctrl+v')
                time.sleep(0.3)

                print("  Translation log pasted to Notepad")
                break

            except Exception as e:
                print(f"  Paste attempt {attempt + 1} failed: {e}")
                time.sleep(0.3)
                continue

    except Exception as e:
        print(f"  Warning: Notepad log error: {e}")


# =============================================================================
# Universal Translation Controller
# =============================================================================
class UniversalTranslatorController:
    """Controls universal text translation with UI integration"""

    def __init__(self, app):
        self.app = app
        self.translator: Optional[UniversalTranslator] = None
        self.cancel_requested = False

    def translate_clipboard(self, mode: TranslationMode):
        """Translate text from clipboard"""
        import threading
        self.cancel_requested = False
        thread = threading.Thread(
            target=self._run_clipboard_translation,
            args=(mode,),
            daemon=True
        )
        thread.start()

    def request_cancel(self):
        """Request cancellation"""
        self.cancel_requested = True

    def _update_ui(self, method, *args, **kwargs):
        """Thread-safe UI update"""
        self.app.after(0, lambda: method(*args, **kwargs))

    def _run_clipboard_translation(self, mode: TranslationMode):
        """Run clipboard translation in background (text or image)"""
        try:
            # Initialize COM for this thread
            pythoncom.CoInitialize()

            self.translator = UniversalTranslator(mode)

            # Update UI - initial connecting state
            direction = "JP→EN" if mode == TranslationMode.TEXT_JP_TO_EN else "EN→JP"
            self._update_ui(self.app.show_connecting, 0, "Preparing...")

            # Copy selected content (text or image)
            self.translator.copy_selected_text()

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                return

            # Get text from clipboard
            text = self.translator.get_clipboard_text()

            # If no text, check for image
            image_path = None
            is_image_translation = False
            if not text:
                image_path = self.translator.get_clipboard_image()
                if image_path:
                    is_image_translation = True
                    print(f"  Image detected in clipboard, translating image...")
                else:
                    self._update_ui(self.app.show_error, "No text or image in clipboard. Select content first.")
                    return

            # Validate text for translation direction (skip for image)
            if not is_image_translation:
                if mode == TranslationMode.TEXT_JP_TO_EN and not has_japanese(text):
                    self._update_ui(self.app.show_error, "Selected text does not contain Japanese.")
                    return

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                return

            # Progress callback for connection status
            def on_connection_progress(step: int, message: str):
                self._update_ui(self.app.show_connecting, step, message)

            # Translate (text or image)
            if is_image_translation:
                translated = self.translator.translate_image(image_path, on_progress=on_connection_progress)
                original_display = "[Image]"
            else:
                translated = self.translator.translate_text(text, on_progress=on_connection_progress)
                original_display = text

            # Update UI - translating done
            self._update_ui(self.app.show_translating, 1, 1)

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                self._cleanup()
                return

            if not translated:
                self._update_ui(self.app.show_error, "Translation failed")
                self._cleanup()
                return

            # Open Notepad with result
            self.translator.open_notepad_with_text(original_display, translated)

            # Close Copilot
            self.translator.close()

            # Show completion
            self._update_ui(
                self.app.show_complete,
                1,
                [(original_display[:50] + "..." if len(original_display) > 50 else original_display,
                  translated[:50] + "..." if len(translated) > 50 else translated)],
                95,
            )

        except Exception as e:
            self._update_ui(self.app.show_error, str(e))
            self._cleanup()

    def _cleanup(self):
        """Cleanup resources"""
        if self.translator:
            try:
                self.translator.close()
            except Exception:
                pass


# =============================================================================
# Helper Functions
# =============================================================================
def format_cells_for_copilot(cells: list[dict]) -> str:
    """Format batch as TSV for Copilot"""
    return "\n".join(f"{cell['address']}\t{cell['text']}" for cell in cells)


def parse_copilot_response(response: str) -> dict[str, str]:
    """Parse Copilot response"""
    result = {}
    cleaned = clean_copilot_response(response)
    for line in cleaned.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            address, translated = parts[0].strip(), parts[1].strip()
            if re.match(r"R\d+C\d+", address):
                result[address] = translated
    return result


def bring_excel_to_front():
    """Bring Excel window to front"""
    try:
        import win32gui
        def enum_callback(hwnd, hwnds):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "Excel" in title:
                    hwnds.append(hwnd)
            return True
        hwnds = []
        win32gui.EnumWindows(enum_callback, hwnds)
        if hwnds:
            win32gui.SetForegroundWindow(hwnds[0])
    except Exception:
        pass


# =============================================================================
# Translation Controller (connects UI with translation logic)
# =============================================================================
class TranslatorController:
    """Controls the translation process with UI integration"""

    def __init__(self, app):
        self.app = app
        self.cancel_requested = False
        self.excel: Optional[ExcelHandler] = None
        self.copilot: Optional[CopilotHandler] = None
        self.translation_mode: TranslationMode = TranslationMode.EXCEL_JP_TO_EN

    def start_translation(self, mode: TranslationMode = TranslationMode.EXCEL_JP_TO_EN):
        """Start translation in background thread"""
        import threading
        self.cancel_requested = False
        self.translation_mode = mode
        thread = threading.Thread(target=self._run_translation, daemon=True)
        thread.start()

    def start_jp_to_en(self):
        """Start JP→EN Excel translation"""
        self.start_translation(TranslationMode.EXCEL_JP_TO_EN)

    def start_en_to_jp(self):
        """Start EN→JP Excel translation"""
        self.start_translation(TranslationMode.EXCEL_EN_TO_JP)

    def request_cancel(self):
        """Request cancellation"""
        self.cancel_requested = True

    def _update_ui(self, method, *args, **kwargs):
        """Thread-safe UI update"""
        self.app.after(0, lambda: method(*args, **kwargs))

    def _run_translation(self):
        """Main translation process (runs in background thread)"""
        try:
            # Initialize COM for this thread
            pythoncom.CoInitialize()

            # Step 1: Load prompt based on mode
            self._update_ui(self.app.show_connecting)
            prompt_file = CONFIG.get_prompt_file(self.translation_mode)
            try:
                prompt_header = prompt_file.read_text(encoding="utf-8")
                # Add glossary reference if configured
                from config_manager import get_config
                config = get_config()
                glossary_addition = config.get_glossary_prompt_addition()
                glossary_path = config.get_glossary_file_path()
                if glossary_addition:
                    prompt_header = prompt_header + glossary_addition
            except Exception as e:
                self._update_ui(self.app.show_error, f"Failed to load prompt: {e}")
                return

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                return

            # Step 2: Connect to Excel
            self.excel = ExcelHandler()
            if not self.excel.connect():
                self._update_ui(self.app.show_error, "Failed to connect to Excel")
                return

            # Step 3: Get selection and extract cells based on direction
            selection_info = self.excel.get_selection_info()

            if self.translation_mode == TranslationMode.EXCEL_EN_TO_JP:
                # EN→JP: Extract English cells
                cells_to_translate = self.excel.extract_english_cells(selection_info)
                error_msg = "No English text found in selection"
            else:
                # JP→EN: Extract Japanese cells
                cells_to_translate = self.excel.extract_japanese_cells(selection_info)
                error_msg = "No Japanese text found in selection"

            if not cells_to_translate:
                self._update_ui(self.app.show_error, error_msg)
                self.excel.cleanup()
                return

            total_cells = len(cells_to_translate)
            # Use cells_to_translate instead of japanese_cells below
            japanese_cells = cells_to_translate  # Alias for compatibility

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                self.excel.cleanup()
                return

            # Step 4: Capture screenshot for context
            screenshot_path = self.excel.capture_selection_screenshot()

            # Step 5: Get or launch Copilot (reuse existing connection)
            already_connected = SharedCopilotManager.is_connected()

            # Progress callback for connection status
            def on_connection_progress(step: int, message: str):
                self._update_ui(self.app.show_connecting, step, message)

            self.copilot = SharedCopilotManager.get_copilot(
                on_progress=on_connection_progress if not already_connected else None
            )
            if not self.copilot:
                self._update_ui(self.app.show_error, "Failed to launch browser")
                self.excel.cleanup()
                return

            # Start new chat if reusing connection
            if already_connected:
                print("  Reusing existing Copilot connection...")
                SharedCopilotManager.new_chat()

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                self._cleanup()
                return

            # Step 6: Translate using world-class engine
            self._update_ui(self.app.show_translating, 0, total_cells)

            # Progress callback for real-time UI updates
            def on_progress(current: int, total: int, message: str):
                if not self.cancel_requested:
                    self._update_ui(self.app.show_translating, current, total)

            # Cell translated callback for live updates
            translated_pairs: list[tuple[str, str]] = []
            def on_cell_translated(address: str, original: str, translated: str):
                translated_pairs.append((original, translated))

            # Create world-class translation engine
            engine = TranslationEngine(
                copilot=self.copilot,
                on_progress=on_progress,
                on_cell_translated=on_cell_translated,
            )

            # Execute translation with smart retry and validation
            result = engine.translate(
                prompt_header=prompt_header,
                japanese_cells=japanese_cells,
                screenshot_path=screenshot_path,
                glossary_path=glossary_path,
            )

            # Don't close browser - keep connection for next translation

            # Handle result based on status
            if result.status == TranslationStatus.FAILED:
                error_msg = "Translation failed"
                if result.warnings:
                    error_msg += f": {result.warnings[0]}"
                self._update_ui(self.app.show_error, error_msg)
                self._cleanup()
                return

            translations = result.translations

            # Write to Excel (even partial results)
            if translations:
                bring_excel_to_front()
                self.excel.write_translations(translations, selection_info)

                # Select first cell
                time.sleep(0.5)
                try:
                    first_cell = japanese_cells[0]
                    self.excel.app.ActiveWorkbook.Sheets(selection_info['sheet_name']).Cells(
                        first_cell['row'], first_cell['col']
                    ).Select()
                except Exception:
                    pass

            self.excel.cleanup()

            # Build translation pairs for display
            translation_pairs = []
            for cell in japanese_cells:
                address = cell['address']
                if address in translations:
                    translation_pairs.append((cell['text'], translations[address]))

            # Add quality indicator to completion
            confidence_pct = int(result.confidence * 100)

            # Open Notepad with translation log (original + translated)
            if translation_pairs:
                direction = "JP → EN" if self.translation_mode == TranslationMode.EXCEL_JP_TO_EN else "EN → JP"
                open_notepad_with_excel_log(translation_pairs, direction)

            # Show completion with translation log and quality info
            self._update_ui(
                self.app.show_complete,
                len(translations),
                translation_pairs,
                confidence_pct,  # Pass confidence to UI
            )

        except Exception as e:
            self._update_ui(self.app.show_error, str(e))
            self._cleanup()

    def _cleanup(self):
        """Cleanup resources (but keep Copilot connection open)"""
        # Don't close shared Copilot - keep connection for next translation
        if self.excel:
            try:
                self.excel.cleanup()
            except Exception:
                pass


# =============================================================================
# Main Entry Point
# =============================================================================
def main():
    """Main entry point - launches UI with global hotkeys and system tray"""
    import customtkinter as ctk
    import keyboard
    from ui import TranslatorApp
    from config_manager import get_config
    from system_tray import SystemTrayManager, setup_minimize_to_tray

    # Load configuration
    config = get_config()

    # Configure appearance
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    # Create app
    app = TranslatorApp()

    # Create controllers
    excel_controller = TranslatorController(app)
    universal_controller = UniversalTranslatorController(app)

    # Connect callbacks for all modes
    app.set_on_start(excel_controller.start_translation)  # Excel mode (legacy)
    app.set_on_jp_to_en(lambda: _smart_translate(app, excel_controller, universal_controller, "jp_to_en"))
    app.set_on_en_to_jp(lambda: _smart_translate(app, excel_controller, universal_controller, "en_to_jp"))
    app.set_on_cancel(lambda: (excel_controller.request_cancel(), universal_controller.request_cancel()))

    def _smart_translate(app, excel_ctrl, universal_ctrl, direction: str):
        """Smart translation: auto-detect Excel or use clipboard"""
        if app.is_translating:
            return

        # Auto-detect if Excel is active
        if is_excel_active():
            # Use Excel translation
            if direction == "jp_to_en":
                excel_ctrl.start_jp_to_en()
            else:
                excel_ctrl.start_en_to_jp()
        else:
            # Use clipboard translation
            if direction == "jp_to_en":
                universal_ctrl.translate_clipboard(TranslationMode.TEXT_JP_TO_EN)
            else:
                universal_ctrl.translate_clipboard(TranslationMode.TEXT_EN_TO_JP)

    # Global hotkey handlers (only 2 hotkeys now)
    def on_hotkey_jp_to_en():
        """Handle Ctrl+Shift+E hotkey - Japanese to English (auto-detect Excel)"""
        app.after(0, lambda: _trigger_smart_translation(app, excel_controller, universal_controller, "jp_to_en"))

    def on_hotkey_en_to_jp():
        """Handle Ctrl+Shift+J hotkey - English to Japanese (auto-detect Excel)"""
        app.after(0, lambda: _trigger_smart_translation(app, excel_controller, universal_controller, "en_to_jp"))

    def _trigger_smart_translation(app, excel_ctrl, universal_ctrl, direction: str):
        """Trigger smart translation from hotkey"""
        try:
            app.deiconify()
            app.lift()
            app.focus_force()
            if not app.is_translating:
                _smart_translate(app, excel_ctrl, universal_ctrl, direction)
        except Exception:
            pass

    # Register global hotkeys
    keyboard.add_hotkey(config.config.hotkeys.jp_to_en, on_hotkey_jp_to_en, suppress=False)
    keyboard.add_hotkey(config.config.hotkeys.en_to_jp, on_hotkey_en_to_jp, suppress=False)

    # Setup system tray
    tray_manager = None
    if config.minimize_to_tray:
        def show_window():
            app.deiconify()
            app.lift()
            app.focus_force()

        def quit_app():
            app.destroy()

        tray_manager = SystemTrayManager(
            app,
            on_show=show_window,
            on_quit=quit_app,
            on_jp_to_en=lambda: _trigger_smart_translation(app, excel_controller, universal_controller, "jp_to_en"),
            on_en_to_jp=lambda: _trigger_smart_translation(app, excel_controller, universal_controller, "en_to_jp"),
        )
        setup_minimize_to_tray(app, tray_manager)

        # Start minimized if configured
        if config.start_minimized:
            app.withdraw()

    # Show hotkey hints and config status
    print("=" * 50)
    print("Universal Translator - Global Hotkeys")
    print("=" * 50)
    print(f"  {config.config.hotkeys.jp_to_en.upper()} : Japanese → English")
    print(f"  {config.config.hotkeys.en_to_jp.upper()} : English → Japanese")
    print("  (Excel is auto-detected)")
    print("-" * 50)
    if config.glossary_enabled:
        print(f"  Glossary: {config.config.glossary.file}")
    else:
        print("  Glossary: Disabled (edit config.json to enable)")
    if config.minimize_to_tray:
        print("  System Tray: Enabled (close to minimize)")
    print("=" * 50)

    try:
        # Run
        app.mainloop()
    finally:
        # Cleanup
        keyboard.unhook_all()
        if tray_manager:
            tray_manager.stop()
        # Close shared Copilot connection
        SharedCopilotManager.close()


def main_cli():
    """CLI mode (legacy) - for debugging"""
    print("=" * 60)
    print("Excel Japanese to English Translation Tool")
    print("=" * 60)

    # Step 1: Load prompt
    print("\n[1/5] Loading prompt...")
    prompt_header = load_prompt()
    print("  OK")

    # Step 2: Connect to Excel
    print("\n[2/5] Connecting to Excel...")
    excel = ExcelHandler()
    if not excel.connect():
        return
    print("  OK")

    # Step 3: Get selection
    print("\n[3/5] Reading selection...")
    selection_info = excel.get_selection_info()
    print(f"  Sheet: {selection_info['sheet_name']}")
    print(f"  Range: R{selection_info['first_row']}C{selection_info['first_col']}:"
          f"R{selection_info['last_row']}C{selection_info['last_col']}")

    japanese_cells = excel.extract_japanese_cells(selection_info)
    if not japanese_cells:
        show_message("Error", "No Japanese text found in selection.", "error")
        excel.cleanup()
        return
    print(f"  Japanese cells: {len(japanese_cells)}")

    # Step 4: Capture screenshot
    print("\n[4/5] Capturing screenshot...")
    screenshot_path = excel.capture_selection_screenshot()

    # Step 5: Launch Copilot and translate
    print("\n[5/5] Launching Copilot...")
    copilot = CopilotHandler()
    if not copilot.launch():
        excel.cleanup()
        return

    print("  Translating...")
    cells_tsv = format_cells_for_copilot(japanese_cells)
    full_prompt = f"{prompt_header}\n{cells_tsv}"

    if not copilot.send_prompt(full_prompt, image_path=screenshot_path):
        show_message("Error", "Failed to send prompt.", "error")
        copilot.close()
        excel.cleanup()
        return

    print("  Waiting for Copilot...")
    response = copilot.wait_and_copy_response()
    if not response:
        show_message("Error", "Failed to get response.", "error")
        copilot.close()
        excel.cleanup()
        return

    translations = parse_copilot_response(response)

    if len(translations) != len(japanese_cells):
        print(f"  Warning: input {len(japanese_cells)} rows -> output {len(translations)} rows")
        response = copilot.wait_and_copy_response()
        if response:
            translations = parse_copilot_response(response)

    # Close Copilot tab
    copilot.close()

    # Bring Excel to front
    print("\n  Writing to Excel...")
    bring_excel_to_front()

    # Write translations
    excel.write_translations(translations, selection_info)

    # Brief pause then select first translated cell
    time.sleep(0.5)
    try:
        first_cell = japanese_cells[0]
        excel.app.ActiveWorkbook.Sheets(selection_info['sheet_name']).Cells(
            first_cell['row'], first_cell['col']
        ).Select()
    except Exception:
        pass

    excel.cleanup()

    print(f"\n  Complete! {len(translations)} cells translated.")
    print("\n" + "=" * 60)


def main_context_menu(direction: str):
    """Entry point for context menu - quick translation without UI"""
    import keyboard

    # Get text from clipboard
    translator = UniversalTranslator(
        mode=TranslationMode.TEXT_JP_TO_EN if direction == "jp_to_en" else TranslationMode.TEXT_EN_TO_JP
    )

    # Copy selected text first (send Ctrl+C)
    keyboard.send('ctrl+c')
    time.sleep(0.3)

    text = translator.get_clipboard_text()
    if not text:
        show_message("Error", "No text selected or in clipboard.", "error")
        return

    print(f"Translating: {text[:50]}...")

    # Initialize Copilot and translate
    translated = translator.translate_text(text)

    if translated:
        # Open Notepad with result
        translator.open_notepad_with_text(text, translated)
        print("Translation complete!")
    else:
        show_message("Error", "Translation failed.", "error")

    translator.close()


if __name__ == "__main__":
    # Check for command-line arguments
    if "--cli" in sys.argv:
        main_cli()
    elif "--context-menu" in sys.argv:
        # Context menu mode - quick translation
        if "--jp-to-en" in sys.argv:
            main_context_menu("jp_to_en")
        elif "--en-to-jp" in sys.argv:
            main_context_menu("en_to_jp")
        else:
            print("Usage: --context-menu --jp-to-en | --en-to-jp")
    else:
        main()
