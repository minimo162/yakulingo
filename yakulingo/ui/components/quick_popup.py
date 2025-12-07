# yakulingo/ui/components/quick_popup.py
"""
Quick translation popup window using Tkinter.

Displays translation results in a lightweight popup that:
- Appears near the cursor position
- Shows source text (collapsible) and translation
- Has copy button
- Closes on Esc or click outside
"""

import logging
import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
import ctypes

logger = logging.getLogger(__name__)

# Windows DPI awareness for proper scaling
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    pass


class QuickTranslatePopup:
    """
    Lightweight translation popup using Tkinter.

    Shows translation results in a small window near the cursor,
    with copy functionality and easy dismissal.
    """

    # Popup dimensions
    WIDTH = 500
    MAX_HEIGHT = 400

    # Colors (Material Design inspired)
    BG_COLOR = "#FFFFFF"
    BORDER_COLOR = "#E0E0E0"
    TEXT_COLOR = "#1F1F1F"
    SECONDARY_TEXT_COLOR = "#5F6368"
    ACCENT_COLOR = "#4355B9"
    BUTTON_BG = "#F1F3F4"
    BUTTON_HOVER = "#E8EAED"
    ERROR_COLOR = "#D93025"

    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._is_visible = False
        self._on_close_callback: Optional[Callable[[], None]] = None

    def show(
        self,
        source_text: str,
        translated_text: str,
        explanation: Optional[str] = None,
        is_error: bool = False,
        on_close: Optional[Callable[[], None]] = None,
    ):
        """
        Show translation popup.

        Args:
            source_text: Original text
            translated_text: Translated text (or error message if is_error=True)
            explanation: Optional explanation text
            is_error: If True, show as error message
            on_close: Callback when popup is closed
        """
        self._on_close_callback = on_close

        # Run in main thread if called from another thread
        if threading.current_thread() is not threading.main_thread():
            # Schedule on main thread
            self._show_impl(source_text, translated_text, explanation, is_error)
        else:
            self._show_impl(source_text, translated_text, explanation, is_error)

    def _show_impl(
        self,
        source_text: str,
        translated_text: str,
        explanation: Optional[str],
        is_error: bool,
    ):
        """Implementation of show popup."""
        # Close existing popup if any
        self.hide()

        # Create new window
        self._root = tk.Tk()
        self._root.title("YakuLingo")

        # Remove window decorations
        self._root.overrideredirect(True)

        # Set background
        self._root.configure(bg=self.BG_COLOR)

        # Make topmost
        self._root.attributes('-topmost', True)

        # Add border effect
        self._root.configure(highlightbackground=self.BORDER_COLOR, highlightthickness=1)

        # Create content
        self._create_content(source_text, translated_text, explanation, is_error)

        # Position near cursor
        self._position_near_cursor()

        # Bind events
        self._root.bind('<Escape>', lambda e: self.hide())
        self._root.bind('<FocusOut>', self._on_focus_out)

        # Focus the window
        self._root.focus_force()

        self._is_visible = True

        # Start event loop
        self._root.mainloop()

    def _create_content(
        self,
        source_text: str,
        translated_text: str,
        explanation: Optional[str],
        is_error: bool,
    ):
        """Create popup content."""
        # Main container with padding
        container = tk.Frame(self._root, bg=self.BG_COLOR, padx=16, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        if is_error:
            # Error message
            error_label = tk.Label(
                container,
                text=translated_text,
                font=("Yu Gothic UI", 11),
                fg=self.ERROR_COLOR,
                bg=self.BG_COLOR,
                wraplength=self.WIDTH - 40,
                justify=tk.LEFT,
            )
            error_label.pack(anchor=tk.W, pady=(0, 8))
        else:
            # Source text (collapsible)
            if source_text:
                source_frame = tk.Frame(container, bg=self.BG_COLOR)
                source_frame.pack(fill=tk.X, pady=(0, 8))

                source_label = tk.Label(
                    source_frame,
                    text="原文:",
                    font=("Yu Gothic UI", 9),
                    fg=self.SECONDARY_TEXT_COLOR,
                    bg=self.BG_COLOR,
                )
                source_label.pack(anchor=tk.W)

                # Truncate long source text
                display_source = source_text[:200] + "..." if len(source_text) > 200 else source_text
                source_text_label = tk.Label(
                    source_frame,
                    text=display_source,
                    font=("Yu Gothic UI", 10),
                    fg=self.TEXT_COLOR,
                    bg=self.BG_COLOR,
                    wraplength=self.WIDTH - 40,
                    justify=tk.LEFT,
                )
                source_text_label.pack(anchor=tk.W)

                # Separator
                separator = tk.Frame(container, height=1, bg=self.BORDER_COLOR)
                separator.pack(fill=tk.X, pady=8)

            # Translation result
            translation_label = tk.Label(
                container,
                text="翻訳:",
                font=("Yu Gothic UI", 9),
                fg=self.SECONDARY_TEXT_COLOR,
                bg=self.BG_COLOR,
            )
            translation_label.pack(anchor=tk.W)

            translation_text = tk.Label(
                container,
                text=translated_text,
                font=("Yu Gothic UI", 12),
                fg=self.TEXT_COLOR,
                bg=self.BG_COLOR,
                wraplength=self.WIDTH - 40,
                justify=tk.LEFT,
            )
            translation_text.pack(anchor=tk.W, pady=(4, 0))

            # Explanation (if any)
            if explanation:
                explanation_frame = tk.Frame(container, bg="#F8F9FA", padx=8, pady=6)
                explanation_frame.pack(fill=tk.X, pady=(12, 0))

                explanation_label = tk.Label(
                    explanation_frame,
                    text=explanation,
                    font=("Yu Gothic UI", 10),
                    fg=self.SECONDARY_TEXT_COLOR,
                    bg="#F8F9FA",
                    wraplength=self.WIDTH - 56,
                    justify=tk.LEFT,
                )
                explanation_label.pack(anchor=tk.W)

        # Button frame
        button_frame = tk.Frame(container, bg=self.BG_COLOR)
        button_frame.pack(fill=tk.X, pady=(12, 0))

        # Copy button (if not error)
        if not is_error and translated_text:
            copy_btn = tk.Button(
                button_frame,
                text="コピー",
                font=("Yu Gothic UI", 10),
                bg=self.BUTTON_BG,
                fg=self.TEXT_COLOR,
                relief=tk.FLAT,
                padx=12,
                pady=4,
                cursor="hand2",
                command=lambda: self._copy_to_clipboard(translated_text),
            )
            copy_btn.pack(side=tk.LEFT)

            # Hover effect
            copy_btn.bind('<Enter>', lambda e: copy_btn.configure(bg=self.BUTTON_HOVER))
            copy_btn.bind('<Leave>', lambda e: copy_btn.configure(bg=self.BUTTON_BG))

        # Close button
        close_btn = tk.Button(
            button_frame,
            text="閉じる",
            font=("Yu Gothic UI", 10),
            bg=self.BUTTON_BG,
            fg=self.TEXT_COLOR,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.hide,
        )
        close_btn.pack(side=tk.RIGHT)

        # Hover effect
        close_btn.bind('<Enter>', lambda e: close_btn.configure(bg=self.BUTTON_HOVER))
        close_btn.bind('<Leave>', lambda e: close_btn.configure(bg=self.BUTTON_BG))

    def _position_near_cursor(self):
        """Position popup near the cursor."""
        # Get cursor position
        try:
            cursor_x, cursor_y = self._root.winfo_pointerxy()
        except Exception:
            cursor_x, cursor_y = 100, 100

        # Update window to calculate size
        self._root.update_idletasks()

        # Get window size
        width = self._root.winfo_reqwidth()
        height = min(self._root.winfo_reqheight(), self.MAX_HEIGHT)

        # Get screen size
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()

        # Calculate position (offset from cursor)
        x = cursor_x + 10
        y = cursor_y + 10

        # Adjust if would go off screen
        if x + width > screen_width:
            x = cursor_x - width - 10
        if y + height > screen_height:
            y = cursor_y - height - 10

        # Ensure not negative
        x = max(0, x)
        y = max(0, y)

        self._root.geometry(f"{width}x{height}+{x}+{y}")

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard."""
        try:
            self._root.clipboard_clear()
            self._root.clipboard_append(text)
            self._root.update()  # Required for clipboard to work
            logger.debug("Copied to clipboard")
        except Exception as e:
            logger.error(f"Failed to copy to clipboard: {e}")

    def _on_focus_out(self, event):
        """Handle focus out event."""
        # Small delay to allow click on buttons
        if self._root:
            self._root.after(100, self._check_focus)

    def _check_focus(self):
        """Check if focus is still on popup."""
        if self._root and not self._root.focus_get():
            self.hide()

    def hide(self):
        """Hide and destroy the popup."""
        if self._root:
            try:
                self._root.quit()
                self._root.destroy()
            except Exception:
                pass
            self._root = None
            self._is_visible = False

            if self._on_close_callback:
                try:
                    self._on_close_callback()
                except Exception:
                    pass

    @property
    def is_visible(self) -> bool:
        """Check if popup is currently visible."""
        return self._is_visible


class QuickTranslateController:
    """
    Controller for quick translation popup.

    Handles the translation logic and shows results in popup.
    """

    def __init__(self, translation_service, copilot_handler):
        """
        Initialize controller.

        Args:
            translation_service: TranslationService instance
            copilot_handler: CopilotHandler instance
        """
        self.translation_service = translation_service
        self.copilot = copilot_handler
        self._popup: Optional[QuickTranslatePopup] = None
        self._translating = False

    def translate_and_show(self, content: bytes | str):
        """
        Translate content and show result in popup.

        Args:
            content: Either text (str) or image data (bytes)
        """
        if self._translating:
            logger.warning("Translation already in progress")
            return

        if not content:
            self._show_error("テキストを選択するか、スクリーンショットをコピーしてください")
            return

        self._translating = True

        # Run translation in background thread
        thread = threading.Thread(
            target=self._translate_impl,
            args=(content,),
            daemon=True
        )
        thread.start()

    def _translate_impl(self, content: bytes | str):
        """Implementation of translation (runs in background thread)."""
        try:
            if isinstance(content, bytes):
                # Image - run OCR first
                text = self._ocr_image(content)
                if not text:
                    self._show_error("画像からテキストを抽出できませんでした")
                    return
            else:
                text = content

            # Check if Copilot is connected
            if not self.copilot or not self.copilot.is_connected:
                self._show_error("Copilotに接続されていません。YakuLingoでCopilotに接続してください。")
                return

            # Translate
            result = self.translation_service.translate_text_with_options(text)

            if result and result.options:
                option = result.options[0]
                self._show_popup(
                    source_text=text,
                    translated_text=option.text,
                    explanation=option.explanation,
                )
            else:
                self._show_error("翻訳に失敗しました")

        except Exception as e:
            logger.error(f"Translation error: {e}", exc_info=True)
            self._show_error(f"翻訳エラー: {str(e)}")
        finally:
            self._translating = False

    def _ocr_image(self, image_data: bytes) -> Optional[str]:
        """Extract text from image using OCR."""
        try:
            from PIL import Image
            from io import BytesIO

            # Load image
            image = Image.open(BytesIO(image_data))

            # Try PaddleOCR
            try:
                from paddleocr import PaddleOCR

                # Initialize OCR (Japanese + English)
                ocr = PaddleOCR(use_angle_cls=True, lang='japan')

                # Convert to numpy array
                import numpy as np
                img_array = np.array(image)

                # Run OCR
                result = ocr.ocr(img_array, cls=True)

                if result and result[0]:
                    # Extract text from results
                    texts = []
                    for line in result[0]:
                        if line and len(line) >= 2:
                            text = line[1][0]  # (text, confidence)
                            texts.append(text)
                    return '\n'.join(texts)

            except ImportError:
                logger.warning("PaddleOCR not available")
                return None

        except Exception as e:
            logger.error(f"OCR error: {e}", exc_info=True)
            return None

    def _show_popup(
        self,
        source_text: str,
        translated_text: str,
        explanation: Optional[str] = None,
    ):
        """Show translation result popup."""
        self._popup = QuickTranslatePopup()
        self._popup.show(
            source_text=source_text,
            translated_text=translated_text,
            explanation=explanation,
        )

    def _show_error(self, message: str):
        """Show error popup."""
        self._popup = QuickTranslatePopup()
        self._popup.show(
            source_text="",
            translated_text=message,
            is_error=True,
        )
