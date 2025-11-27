"""
Excel Japanese to English Translation Tool
Uses M365 Copilot (GPT-5) to translate Japanese cells in Excel.
"""

import os
import sys
import re
import time
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Windows COM
import win32com.client
import pythoncom

# Playwright
from playwright.sync_api import sync_playwright, Page, BrowserContext


# =============================================================================
# Configuration
# =============================================================================
@dataclass
class Config:
    """Configuration"""
    # Paths (relative to script directory)
    script_dir: Path = None
    prompt_file: Path = None

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
        """Get selection info"""
        selection = self.app.Selection
        self.original_sheet = self.app.ActiveSheet
        return {
            "sheet_name": self.original_sheet.Name,
            "first_row": selection.Row,
            "first_col": selection.Column,
            "last_row": selection.Row + selection.Rows.Count - 1,
            "last_col": selection.Column + selection.Columns.Count - 1,
            "rows_count": selection.Rows.Count,
            "cols_count": selection.Columns.Count,
        }
    
    def extract_japanese_cells(self, info: dict) -> list[dict]:
        """Extract cells containing Japanese"""
        japanese_cells = []
        sheet = self.original_sheet
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
        return japanese_cells
    
    def write_translations(self, translations: dict[str, str], info: dict):
        """Write translations back to sheet"""
        sheet = self.original_sheet
        for address, translated in translations.items():
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
                capture_output=True, text=True, timeout=5, cwd=local_cwd
            )
            for line in result.stdout.split("\n"):
                if f":{self.cdp_port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        subprocess.run([taskkill_path, "/F", "/PID", pid],
                                      capture_output=True, timeout=5, cwd=local_cwd)
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
    
    def launch(self) -> bool:
        """Launch dedicated Edge and open Copilot"""
        try:
            if not self._start_translator_edge():
                show_message("Error", "Failed to start Edge.", "error")
                return False
            
            print("  Connecting...", end="", flush=True)
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
            print("  Opening Copilot...", end="", flush=True)
            self.page.goto(CONFIG.copilot_url, wait_until="networkidle", timeout=60000)
            print(" done")
            
            # Bring browser to front
            self.page.bring_to_front()
            
            # Wait for input field
            print("  Waiting for Copilot...", end="", flush=True)
            try:
                self.page.wait_for_selector(CONFIG.selector_input, state="visible", timeout=30000)
                print(" ready")
            except TimeoutError:
                print(" login required")
                show_message("Login Required", "Please login to M365 Copilot.\nClick OK after logging in.")
                self.page.wait_for_selector(CONFIG.selector_input, state="visible", timeout=300000)
            
            # Enable GPT-5 if not already enabled
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
    
    def attach_image(self, image_path: Path) -> bool:
        """Attach an image to the chat"""
        try:
            # Look for file input element (hidden)
            file_input = self.page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(str(image_path))
                time.sleep(1)
                print("  Image attached via file input")
                return True

            # Alternative: Click attach button and use file chooser
            attach_button = self.page.query_selector('button[aria-label*="添付"], button[aria-label*="Attach"], button[data-testid*="attach"]')
            if attach_button:
                with self.page.expect_file_chooser() as fc_info:
                    attach_button.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(image_path))
                time.sleep(1)
                print("  Image attached via button")
                return True

            print("  Warning: Could not find attach mechanism")
            return False

        except Exception as e:
            print(f"  Warning: Image attach failed: {e}")
            return False

    def send_prompt(self, prompt: str, image_path: Optional[Path] = None) -> bool:
        """Send prompt with optional image attachment"""
        try:
            # Bring browser to front so user can see progress
            self.page.bring_to_front()

            # Attach image first if provided
            if image_path and image_path.exists():
                self.attach_image(image_path)

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

    def start_translation(self):
        """Start translation in background thread"""
        import threading
        self.cancel_requested = False
        thread = threading.Thread(target=self._run_translation, daemon=True)
        thread.start()

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

            # Step 1: Load prompt
            self._update_ui(self.app.show_connecting)
            prompt_header = load_prompt()

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                return

            # Step 2: Connect to Excel
            self.excel = ExcelHandler()
            if not self.excel.connect():
                self._update_ui(self.app.show_error, "Failed to connect to Excel")
                return

            # Step 3: Get selection
            selection_info = self.excel.get_selection_info()
            japanese_cells = self.excel.extract_japanese_cells(selection_info)

            if not japanese_cells:
                self._update_ui(self.app.show_error, "No Japanese text found in selection")
                self.excel.cleanup()
                return

            total_cells = len(japanese_cells)

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                self.excel.cleanup()
                return

            # Step 4: Capture screenshot for context
            screenshot_path = self.excel.capture_selection_screenshot()

            # Step 5: Launch Copilot
            self.copilot = CopilotHandler()
            if not self.copilot.launch():
                self._update_ui(self.app.show_error, "Failed to launch browser")
                self.excel.cleanup()
                return

            if self.cancel_requested:
                self._update_ui(self.app.show_cancelled)
                self._cleanup()
                return

            # Step 6: Translate
            self._update_ui(self.app.show_translating, 0, total_cells)

            cells_tsv = format_cells_for_copilot(japanese_cells)
            full_prompt = f"{prompt_header}\n{cells_tsv}"

            if not self.copilot.send_prompt(full_prompt, image_path=screenshot_path):
                self._update_ui(self.app.show_error, "Failed to send prompt")
                self._cleanup()
                return

            response = self.copilot.wait_and_copy_response()
            if not response:
                self._update_ui(self.app.show_error, "Failed to get response")
                self._cleanup()
                return

            translations = parse_copilot_response(response)

            # Retry if count mismatch
            if len(translations) != len(japanese_cells):
                response = self.copilot.wait_and_copy_response()
                if response:
                    translations = parse_copilot_response(response)

            # Close browser
            self.copilot.close()

            # Write to Excel
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

            # Show completion with translation log
            self._update_ui(self.app.show_complete, len(translations), translation_pairs)

        except Exception as e:
            self._update_ui(self.app.show_error, str(e))
            self._cleanup()

    def _cleanup(self):
        """Cleanup resources"""
        if self.copilot:
            try:
                self.copilot.close()
            except Exception:
                pass
        if self.excel:
            try:
                self.excel.cleanup()
            except Exception:
                pass


# =============================================================================
# Main Entry Point
# =============================================================================
def main():
    """Main entry point - launches UI with global hotkey"""
    import customtkinter as ctk
    import keyboard
    from ui import TranslatorApp

    # Configure appearance
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    # Create app
    app = TranslatorApp()

    # Create controller
    controller = TranslatorController(app)

    # Connect callbacks
    app.set_on_start(controller.start_translation)
    app.set_on_cancel(controller.request_cancel)

    # Global hotkey handler
    def on_hotkey():
        """Handle Ctrl+Shift+E hotkey"""
        # Bring app to front and start translation
        app.after(0, lambda: _trigger_translation(app, controller))

    def _trigger_translation(app, controller):
        """Trigger translation from hotkey (runs in main thread)"""
        try:
            # Bring window to front
            app.deiconify()
            app.lift()
            app.focus_force()
            # Start translation if not already running
            if not app.is_translating:
                controller.start_translation()
        except Exception:
            pass

    # Register global hotkey (Ctrl+Shift+E)
    keyboard.add_hotkey('ctrl+shift+e', on_hotkey, suppress=False)

    # Show hotkey hint on startup
    print("Global hotkey: Ctrl+Shift+E")

    try:
        # Run
        app.mainloop()
    finally:
        # Cleanup hotkey on exit
        keyboard.unhook_all()


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


if __name__ == "__main__":
    # Check for --cli flag
    if "--cli" in sys.argv:
        main_cli()
    else:
        main()
