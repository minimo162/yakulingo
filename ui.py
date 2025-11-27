"""
Excel Translator - Premium UI
A world-class interface inspired by Apple's design philosophy.
"""

import customtkinter as ctk
import threading
import time
from typing import Callable, Optional
from dataclasses import dataclass


# =============================================================================
# Design System
# =============================================================================
@dataclass
class Theme:
    """Design tokens - Inspired by Apple's Human Interface Guidelines"""
    # Colors
    bg_primary: str = "#0a0a0a"
    bg_secondary: str = "#1a1a1a"
    bg_tertiary: str = "#2a2a2a"

    text_primary: str = "#ffffff"
    text_secondary: str = "#888888"
    text_tertiary: str = "#555555"

    accent: str = "#00d4aa"
    accent_dim: str = "#007a5e"

    error: str = "#ff4757"
    warning: str = "#ffa502"

    # Typography
    font_family: str = "Yu Gothic UI"
    font_family_en: str = "Segoe UI"

    # Spacing
    padding_xl: int = 48
    padding_lg: int = 32
    padding_md: int = 24
    padding_sm: int = 16
    padding_xs: int = 8

    # Animation
    animation_duration: float = 0.3


THEME = Theme()


# =============================================================================
# Custom Components
# =============================================================================
class BreathingDot(ctk.CTkCanvas):
    """A dot that breathes - indicates active processing"""

    def __init__(self, parent, size: int = 12, color: str = THEME.accent, **kwargs):
        super().__init__(
            parent,
            width=size * 3,
            height=size * 3,
            bg=THEME.bg_primary,
            highlightthickness=0,
            **kwargs
        )
        self.size = size
        self.color = color
        self.base_color = color
        self.is_breathing = False
        self.breath_phase = 0
        self.center = size * 1.5

        self._draw_dot(1.0)

    def _draw_dot(self, scale: float):
        self.delete("dot")
        radius = (self.size / 2) * scale
        self.create_oval(
            self.center - radius,
            self.center - radius,
            self.center + radius,
            self.center + radius,
            fill=self.color,
            outline="",
            tags="dot"
        )

    def start_breathing(self):
        self.is_breathing = True
        self._breathe()

    def stop_breathing(self):
        self.is_breathing = False
        self._draw_dot(1.0)

    def _breathe(self):
        if not self.is_breathing:
            return

        import math
        self.breath_phase += 0.1
        scale = 0.7 + 0.3 * (math.sin(self.breath_phase) + 1) / 2

        # Subtle color shift
        alpha = int(180 + 75 * (math.sin(self.breath_phase) + 1) / 2)

        self._draw_dot(scale)
        self.after(50, self._breathe)

    def set_color(self, color: str):
        self.color = color
        self._draw_dot(1.0)


class MinimalProgressBar(ctk.CTkCanvas):
    """Ultra-minimal progress bar with smooth animation"""

    def __init__(self, parent, width: int = 300, height: int = 2, **kwargs):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=THEME.bg_primary,
            highlightthickness=0,
            **kwargs
        )
        self.bar_width = width
        self.bar_height = height
        self.progress = 0.0
        self.target_progress = 0.0

        # Draw background track
        self.create_rectangle(
            0, 0, width, height,
            fill=THEME.bg_tertiary,
            outline="",
            tags="track"
        )

        # Draw progress
        self.progress_rect = self.create_rectangle(
            0, 0, 0, height,
            fill=THEME.accent,
            outline="",
            tags="progress"
        )

    def set_progress(self, value: float, animate: bool = True):
        """Set progress (0.0 to 1.0)"""
        self.target_progress = max(0.0, min(1.0, value))
        if animate:
            self._animate_progress()
        else:
            self.progress = self.target_progress
            self._update_bar()

    def _animate_progress(self):
        if abs(self.progress - self.target_progress) < 0.01:
            self.progress = self.target_progress
            self._update_bar()
            return

        # Smooth easing
        self.progress += (self.target_progress - self.progress) * 0.15
        self._update_bar()
        self.after(16, self._animate_progress)

    def _update_bar(self):
        width = self.bar_width * self.progress
        self.coords(self.progress_rect, 0, 0, width, self.bar_height)


class StateIndicator(ctk.CTkFrame):
    """Shows current state with icon and text"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.dot = BreathingDot(self, size=10)
        self.dot.pack(side="left", padx=(0, THEME.padding_sm))

        self.label = ctk.CTkLabel(
            self,
            text="",
            font=(THEME.font_family, 13),
            text_color=THEME.text_secondary
        )
        self.label.pack(side="left")

    def set_state(self, text: str, breathing: bool = False, color: str = THEME.accent):
        self.label.configure(text=text)
        self.dot.set_color(color)
        if breathing:
            self.dot.start_breathing()
        else:
            self.dot.stop_breathing()


# =============================================================================
# Main Window
# =============================================================================
class TranslatorApp(ctk.CTk):
    """Main application window - Premium design"""

    def __init__(self):
        super().__init__()

        # Window setup
        self.title("Translate")
        self.geometry("480x640")
        self.minsize(400, 500)
        self.configure(fg_color=THEME.bg_primary)

        # State
        self.is_translating = False
        self.cancel_requested = False
        self.on_start_callback: Optional[Callable] = None
        self.on_cancel_callback: Optional[Callable] = None

        # Build UI
        self._create_ui()

        # Center window
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _create_ui(self):
        # Main container with padding
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=THEME.padding_xl, pady=THEME.padding_xl)

        # Header (minimal)
        self.header = ctk.CTkFrame(self.container, fg_color="transparent")
        self.header.pack(fill="x", pady=(0, THEME.padding_xl))

        self.title_label = ctk.CTkLabel(
            self.header,
            text="Excel Translator",
            font=(THEME.font_family_en, 13),
            text_color=THEME.text_tertiary
        )
        self.title_label.pack(anchor="w")

        # Main content area (center)
        self.content = ctk.CTkFrame(self.container, fg_color="transparent")
        self.content.pack(fill="both", expand=True)

        # Status area (vertically centered)
        self.status_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.status_frame.place(relx=0.5, rely=0.4, anchor="center")

        # Main status text
        self.status_text = ctk.CTkLabel(
            self.status_frame,
            text="Ready",
            font=(THEME.font_family_en, 48, "bold"),
            text_color=THEME.text_primary
        )
        self.status_text.pack()

        # Sub status
        self.sub_status = ctk.CTkLabel(
            self.status_frame,
            text="Select cells in Excel and click Start",
            font=(THEME.font_family, 14),
            text_color=THEME.text_secondary
        )
        self.sub_status.pack(pady=(THEME.padding_sm, 0))

        # Progress section (below status)
        self.progress_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.progress_frame.place(relx=0.5, rely=0.6, anchor="center")

        # State indicator
        self.state_indicator = StateIndicator(self.progress_frame)
        self.state_indicator.pack(pady=(0, THEME.padding_md))
        self.state_indicator.set_state("Waiting")

        # Progress bar
        self.progress_bar = MinimalProgressBar(self.progress_frame, width=280, height=3)
        self.progress_bar.pack()

        # Stats
        self.stats_label = ctk.CTkLabel(
            self.progress_frame,
            text="",
            font=(THEME.font_family, 12),
            text_color=THEME.text_tertiary
        )
        self.stats_label.pack(pady=(THEME.padding_md, 0))

        # Bottom section
        self.bottom = ctk.CTkFrame(self.container, fg_color="transparent")
        self.bottom.pack(fill="x", side="bottom")

        # Main action button
        self.action_button = ctk.CTkButton(
            self.bottom,
            text="Start",
            font=(THEME.font_family_en, 16, "bold"),
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary,
            hover_color=THEME.text_secondary,
            height=56,
            corner_radius=12,
            command=self._on_action_click
        )
        self.action_button.pack(fill="x")

        # Settings button (subtle)
        self.settings_frame = ctk.CTkFrame(self.bottom, fg_color="transparent")
        self.settings_frame.pack(fill="x", pady=(THEME.padding_md, 0))

        self.settings_button = ctk.CTkButton(
            self.settings_frame,
            text="Settings",
            font=(THEME.font_family_en, 12),
            fg_color="transparent",
            text_color=THEME.text_tertiary,
            hover_color=THEME.bg_secondary,
            height=32,
            command=self._show_settings
        )
        self.settings_button.pack()

    def _on_action_click(self):
        if self.is_translating:
            self._request_cancel()
        else:
            self._start_translation()

    def _start_translation(self):
        if self.on_start_callback:
            self.on_start_callback()

    def _request_cancel(self):
        self.cancel_requested = True
        self.action_button.configure(
            text="Canceling...",
            state="disabled"
        )
        if self.on_cancel_callback:
            self.on_cancel_callback()

    def _show_settings(self):
        SettingsWindow(self)

    # Public API
    def set_on_start(self, callback: Callable):
        self.on_start_callback = callback

    def set_on_cancel(self, callback: Callable):
        self.on_cancel_callback = callback

    def show_ready(self):
        """Show ready state"""
        self.is_translating = False
        self.cancel_requested = False

        self.status_text.configure(text="Ready")
        self.sub_status.configure(text="Select cells in Excel and click Start")
        self.state_indicator.set_state("Waiting")
        self.progress_bar.set_progress(0, animate=False)
        self.stats_label.configure(text="")

        self.action_button.configure(
            text="Start",
            state="normal",
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary
        )

    def show_connecting(self):
        """Show connecting state"""
        self.is_translating = True

        self.status_text.configure(text="Connecting")
        self.sub_status.configure(text="Starting browser...")
        self.state_indicator.set_state("Initializing", breathing=True)

        self.action_button.configure(
            text="Cancel",
            fg_color=THEME.bg_tertiary,
            text_color=THEME.text_primary
        )

    def show_translating(self, current: int, total: int, batch: int, total_batches: int):
        """Show translation progress"""
        self.is_translating = True

        progress = current / total if total > 0 else 0

        self.status_text.configure(text=f"{int(progress * 100)}%")
        self.sub_status.configure(text=f"Translating batch {batch}/{total_batches}")
        self.state_indicator.set_state("Processing", breathing=True)
        self.progress_bar.set_progress(progress)
        self.stats_label.configure(text=f"{current} / {total} cells")

        self.action_button.configure(
            text="Cancel",
            fg_color=THEME.bg_tertiary,
            text_color=THEME.text_primary
        )

    def show_complete(self, count: int):
        """Show completion state"""
        self.is_translating = False

        self.status_text.configure(text="Complete")
        self.sub_status.configure(text=f"{count} cells translated successfully")
        self.state_indicator.set_state("Done", color=THEME.accent)
        self.progress_bar.set_progress(1.0)
        self.stats_label.configure(text="")

        self.action_button.configure(
            text="Start New",
            state="normal",
            fg_color=THEME.accent,
            text_color=THEME.bg_primary
        )

    def show_error(self, message: str):
        """Show error state"""
        self.is_translating = False

        self.status_text.configure(text="Error")
        self.sub_status.configure(text=message)
        self.state_indicator.set_state("Failed", color=THEME.error)

        self.action_button.configure(
            text="Retry",
            state="normal",
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary
        )

    def show_cancelled(self):
        """Show cancelled state"""
        self.is_translating = False
        self.cancel_requested = False

        self.status_text.configure(text="Cancelled")
        self.sub_status.configure(text="Translation was cancelled")
        self.state_indicator.set_state("Stopped", color=THEME.warning)

        self.action_button.configure(
            text="Start",
            state="normal",
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary
        )


# =============================================================================
# Settings Window
# =============================================================================
class SettingsWindow(ctk.CTkToplevel):
    """Settings panel - Minimal design"""

    def __init__(self, parent):
        super().__init__(parent)

        self.title("Settings")
        self.geometry("400x300")
        self.configure(fg_color=THEME.bg_primary)
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()

        self._create_ui()
        self._center_window(parent)

    def _center_window(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _create_ui(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=THEME.padding_lg, pady=THEME.padding_lg)

        # Title
        title = ctk.CTkLabel(
            container,
            text="Settings",
            font=(THEME.font_family_en, 24, "bold"),
            text_color=THEME.text_primary
        )
        title.pack(anchor="w", pady=(0, THEME.padding_lg))

        # Batch size setting
        batch_frame = ctk.CTkFrame(container, fg_color="transparent")
        batch_frame.pack(fill="x", pady=THEME.padding_sm)

        batch_label = ctk.CTkLabel(
            batch_frame,
            text="Batch Size",
            font=(THEME.font_family_en, 14),
            text_color=THEME.text_primary
        )
        batch_label.pack(anchor="w")

        batch_desc = ctk.CTkLabel(
            batch_frame,
            text="Maximum cells per translation batch",
            font=(THEME.font_family, 12),
            text_color=THEME.text_tertiary
        )
        batch_desc.pack(anchor="w")

        self.batch_slider = ctk.CTkSlider(
            batch_frame,
            from_=50,
            to=500,
            number_of_steps=9,
            fg_color=THEME.bg_tertiary,
            progress_color=THEME.accent,
            button_color=THEME.text_primary,
            button_hover_color=THEME.text_secondary
        )
        self.batch_slider.set(300)
        self.batch_slider.pack(fill="x", pady=(THEME.padding_sm, 0))

        self.batch_value = ctk.CTkLabel(
            batch_frame,
            text="300",
            font=(THEME.font_family_en, 12),
            text_color=THEME.text_secondary
        )
        self.batch_value.pack(anchor="e")

        self.batch_slider.configure(command=self._on_batch_change)

        # Close button
        close_btn = ctk.CTkButton(
            container,
            text="Done",
            font=(THEME.font_family_en, 14),
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary,
            hover_color=THEME.text_secondary,
            height=44,
            corner_radius=10,
            command=self.destroy
        )
        close_btn.pack(fill="x", side="bottom")

    def _on_batch_change(self, value):
        self.batch_value.configure(text=str(int(value)))


# =============================================================================
# Entry Point (for testing)
# =============================================================================
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    app = TranslatorApp()

    # Test states
    def test_flow():
        time.sleep(1)
        app.after(0, app.show_connecting)
        time.sleep(2)

        for i in range(1, 101):
            app.after(0, lambda i=i: app.show_translating(i, 100, 1, 1))
            time.sleep(0.05)

        app.after(0, lambda: app.show_complete(100))

    # threading.Thread(target=test_flow, daemon=True).start()

    app.mainloop()
