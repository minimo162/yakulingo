"""
Excel Translator - Premium UI
A world-class interface inspired by Apple's design philosophy.

Design Concept: "Silent Power" - The beauty of restraint meets functional elegance.
"""

import customtkinter as ctk
import math
import time
from typing import Callable, Optional
from dataclasses import dataclass


# =============================================================================
# Design System - Apple-inspired Design Tokens
# =============================================================================
@dataclass
class Theme:
    """Design tokens - Pursuit of perfection"""
    # Colors - Deep, rich, intentional
    bg_primary: str = "#000000"      # Pure black - the ultimate canvas
    bg_secondary: str = "#0d0d0d"    # Subtle elevation
    bg_card: str = "#1a1a1a"         # Card surfaces
    bg_elevated: str = "#262626"     # Elevated elements

    text_primary: str = "#ffffff"
    text_secondary: str = "#a0a0a0"
    text_tertiary: str = "#666666"
    text_muted: str = "#404040"

    # Accent colors - Subtle, meaningful
    accent: str = "#34c759"          # Apple green - success, go
    accent_blue: str = "#007aff"     # Apple blue - action
    accent_orange: str = "#ff9500"   # Warning, attention
    accent_red: str = "#ff3b30"      # Error, stop

    # Gradients (start, end)
    gradient_active: tuple = ("#34c759", "#30d158")

    # Typography - San Francisco inspired
    font_display: str = "SF Pro Display"
    font_text: str = "SF Pro Text"
    font_mono: str = "SF Mono"
    # Fallbacks for Windows
    font_display_win: str = "Segoe UI"
    font_text_win: str = "Segoe UI"

    # Spacing - 8px grid system
    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 16
    space_lg: int = 24
    space_xl: int = 32
    space_2xl: int = 48
    space_3xl: int = 64

    # Animation
    duration_fast: int = 150
    duration_normal: int = 300
    duration_slow: int = 500

    # Border radius
    radius_sm: int = 8
    radius_md: int = 12
    radius_lg: int = 16
    radius_xl: int = 24
    radius_full: int = 9999


THEME = Theme()


def get_font(style: str = "text", size: int = 14, weight: str = "normal"):
    """Get font tuple with fallback"""
    font_map = {
        "display": THEME.font_display_win,
        "text": THEME.font_text_win,
        "mono": "Consolas"
    }
    return (font_map.get(style, THEME.font_text_win), size, weight)


# =============================================================================
# Custom Components - Crafted with intention
# =============================================================================
class CircularProgress(ctk.CTkCanvas):
    """
    Circular progress indicator - The hero element.
    Inspired by Apple Watch activity rings.
    """

    def __init__(self, parent, size: int = 200, thickness: int = 8, **kwargs):
        super().__init__(
            parent,
            width=size,
            height=size,
            bg=THEME.bg_primary,
            highlightthickness=0,
            **kwargs
        )
        self.size = size
        self.thickness = thickness
        self.progress = 0.0
        self.target_progress = 0.0
        self.center = size / 2
        self.radius = (size - thickness * 2) / 2

        self.glow_phase = 0
        self.is_animating = False

        self._draw()

    def _draw(self):
        """Draw the progress ring"""
        self.delete("all")

        padding = self.thickness
        bbox = (padding, padding, self.size - padding, self.size - padding)

        # Background ring (track)
        self.create_arc(
            *bbox,
            start=90,
            extent=-360,
            style="arc",
            outline=THEME.bg_elevated,
            width=self.thickness,
            tags="track"
        )

        # Progress ring
        if self.progress > 0:
            extent = -360 * self.progress

            # Glow effect (subtle outer ring)
            if self.is_animating:
                glow_alpha = 0.3 + 0.2 * math.sin(self.glow_phase)
                # Create subtle glow by drawing slightly larger arc
                glow_bbox = (
                    padding - 2, padding - 2,
                    self.size - padding + 2, self.size - padding + 2
                )
                self.create_arc(
                    *glow_bbox,
                    start=90,
                    extent=extent,
                    style="arc",
                    outline=THEME.accent,
                    width=self.thickness + 4,
                    tags="glow"
                )

            # Main progress arc
            self.create_arc(
                *bbox,
                start=90,
                extent=extent,
                style="arc",
                outline=THEME.accent,
                width=self.thickness,
                tags="progress"
            )

    def set_progress(self, value: float, animate: bool = True):
        """Set progress with smooth animation"""
        self.target_progress = max(0.0, min(1.0, value))
        if animate:
            self._animate()
        else:
            self.progress = self.target_progress
            self._draw()

    def _animate(self):
        """Smooth easing animation"""
        if abs(self.progress - self.target_progress) < 0.005:
            self.progress = self.target_progress
            self._draw()
            return

        # Ease-out cubic
        diff = self.target_progress - self.progress
        self.progress += diff * 0.12
        self._draw()
        self.after(16, self._animate)

    def start_glow(self):
        """Start subtle glow animation"""
        self.is_animating = True
        self._animate_glow()

    def stop_glow(self):
        """Stop glow animation"""
        self.is_animating = False
        self._draw()

    def _animate_glow(self):
        """Animate the glow effect"""
        if not self.is_animating:
            return
        self.glow_phase += 0.08
        self._draw()
        self.after(30, self._animate_glow)

    def set_color(self, color: str):
        """Change the progress color"""
        # Update theme accent temporarily
        self._draw()


class PulsingDot(ctk.CTkCanvas):
    """Minimal status indicator with breathing animation"""

    def __init__(self, parent, size: int = 8, **kwargs):
        super().__init__(
            parent,
            width=size * 4,
            height=size * 4,
            bg=THEME.bg_primary,
            highlightthickness=0,
            **kwargs
        )
        self.dot_size = size
        self.center = size * 2
        self.color = THEME.accent
        self.phase = 0
        self.is_pulsing = False

        self._draw(1.0, 1.0)

    def _draw(self, scale: float, opacity: float):
        """Draw the dot with scale and opacity"""
        self.delete("all")
        radius = (self.dot_size / 2) * scale

        # Outer glow
        if self.is_pulsing:
            glow_radius = radius * 2
            self.create_oval(
                self.center - glow_radius,
                self.center - glow_radius,
                self.center + glow_radius,
                self.center + glow_radius,
                fill="",
                outline=self.color,
                width=1,
                tags="glow"
            )

        # Main dot
        self.create_oval(
            self.center - radius,
            self.center - radius,
            self.center + radius,
            self.center + radius,
            fill=self.color,
            outline="",
            tags="dot"
        )

    def start_pulse(self):
        """Start breathing animation"""
        self.is_pulsing = True
        self._pulse()

    def stop_pulse(self):
        """Stop animation"""
        self.is_pulsing = False
        self._draw(1.0, 1.0)

    def _pulse(self):
        """Breathing animation loop"""
        if not self.is_pulsing:
            return

        self.phase += 0.06
        scale = 0.85 + 0.15 * (math.sin(self.phase) + 1) / 2
        self._draw(scale, 1.0)
        self.after(30, self._pulse)

    def set_color(self, color: str):
        """Set dot color"""
        self.color = color
        self._draw(1.0, 1.0)


class GlassCard(ctk.CTkFrame):
    """
    Glass-morphism inspired card component.
    Subtle elevation and depth.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            fg_color=THEME.bg_card,
            corner_radius=THEME.radius_lg,
            **kwargs
        )


class MinimalButton(ctk.CTkButton):
    """
    Refined button with subtle interactions.
    """

    def __init__(self, parent, text: str, variant: str = "primary", **kwargs):
        colors = {
            "primary": {
                "fg": THEME.text_primary,
                "bg": THEME.bg_elevated,
                "hover": THEME.bg_card,
                "text": THEME.bg_primary
            },
            "ghost": {
                "fg": "transparent",
                "bg": "transparent",
                "hover": THEME.bg_secondary,
                "text": THEME.text_secondary
            },
            "accent": {
                "fg": THEME.accent,
                "bg": THEME.accent,
                "hover": THEME.gradient_active[1],
                "text": THEME.bg_primary
            }
        }

        c = colors.get(variant, colors["primary"])

        super().__init__(
            parent,
            text=text,
            font=get_font("text", 15, "bold"),
            fg_color=c["fg"] if variant != "primary" else THEME.text_primary,
            text_color=c["text"],
            hover_color=c["hover"] if variant != "primary" else THEME.text_secondary,
            corner_radius=THEME.radius_md,
            height=52,
            **kwargs
        )


# =============================================================================
# Main Application Window
# =============================================================================
class TranslatorApp(ctk.CTk):
    """
    Main application - A study in restraint and elegance.
    Every pixel has purpose. Every animation has meaning.
    """

    def __init__(self):
        super().__init__()

        # Window configuration
        self.title("")  # Minimal - no title needed
        self.geometry("420x680")
        self.minsize(380, 600)
        self.configure(fg_color=THEME.bg_primary)

        # Remove window decorations for cleaner look (optional)
        # self.overrideredirect(True)

        # State
        self.is_translating = False
        self.cancel_requested = False
        self.on_start_callback: Optional[Callable] = None
        self.on_cancel_callback: Optional[Callable] = None

        self._build_ui()
        self._center_window()

    def _center_window(self):
        """Center on screen"""
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        """Construct the interface with surgical precision"""

        # Main container
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=THEME.space_xl, pady=THEME.space_xl)

        # === Header (minimal) ===
        self.header = ctk.CTkFrame(self.container, fg_color="transparent", height=40)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.brand = ctk.CTkLabel(
            self.header,
            text="TRANSLATOR",
            font=get_font("text", 11, "bold"),
            text_color=THEME.text_muted
        )
        self.brand.pack(side="left")

        # === Hero Section (center stage) ===
        self.hero = ctk.CTkFrame(self.container, fg_color="transparent")
        self.hero.pack(fill="both", expand=True)

        # Progress ring - the star of the show
        self.progress_ring = CircularProgress(self.hero, size=180, thickness=6)
        self.progress_ring.place(relx=0.5, rely=0.35, anchor="center")

        # Percentage display (inside ring)
        self.percent_label = ctk.CTkLabel(
            self.hero,
            text="",
            font=get_font("display", 42, "bold"),
            text_color=THEME.text_primary
        )
        self.percent_label.place(relx=0.5, rely=0.35, anchor="center")

        # Status text
        self.status_label = ctk.CTkLabel(
            self.hero,
            text="Ready",
            font=get_font("display", 28, "bold"),
            text_color=THEME.text_primary
        )
        self.status_label.place(relx=0.5, rely=0.58, anchor="center")

        # Subtitle
        self.subtitle_label = ctk.CTkLabel(
            self.hero,
            text="Select cells in Excel",
            font=get_font("text", 14),
            text_color=THEME.text_secondary
        )
        self.subtitle_label.place(relx=0.5, rely=0.66, anchor="center")

        # === Stats Card ===
        self.stats_card = GlassCard(self.hero, height=70)
        self.stats_card.place(relx=0.5, rely=0.82, anchor="center", relwidth=0.9)

        # Stats content
        self.stats_inner = ctk.CTkFrame(self.stats_card, fg_color="transparent")
        self.stats_inner.pack(fill="both", expand=True, padx=THEME.space_lg, pady=THEME.space_md)

        # Left stat
        self.stat_left = ctk.CTkFrame(self.stats_inner, fg_color="transparent")
        self.stat_left.pack(side="left", expand=True)

        self.stat_left_value = ctk.CTkLabel(
            self.stat_left,
            text="--",
            font=get_font("display", 20, "bold"),
            text_color=THEME.text_primary
        )
        self.stat_left_value.pack()

        self.stat_left_label = ctk.CTkLabel(
            self.stat_left,
            text="Cells",
            font=get_font("text", 11),
            text_color=THEME.text_tertiary
        )
        self.stat_left_label.pack()

        # Divider
        self.divider = ctk.CTkFrame(
            self.stats_inner,
            fg_color=THEME.bg_elevated,
            width=1
        )
        self.divider.pack(side="left", fill="y", padx=THEME.space_lg)

        # Right stat
        self.stat_right = ctk.CTkFrame(self.stats_inner, fg_color="transparent")
        self.stat_right.pack(side="left", expand=True)

        self.stat_right_value = ctk.CTkLabel(
            self.stat_right,
            text="--",
            font=get_font("display", 20, "bold"),
            text_color=THEME.text_primary
        )
        self.stat_right_value.pack()

        self.stat_right_label = ctk.CTkLabel(
            self.stat_right,
            text="Status",
            font=get_font("text", 11),
            text_color=THEME.text_tertiary
        )
        self.stat_right_label.pack()

        # === Footer ===
        self.footer = ctk.CTkFrame(self.container, fg_color="transparent")
        self.footer.pack(fill="x", side="bottom")

        # Main action button
        self.action_btn = MinimalButton(
            self.footer,
            text="Start Translation",
            variant="primary",
            command=self._on_action
        )
        self.action_btn.pack(fill="x")

        # About link
        self.about_btn = MinimalButton(
            self.footer,
            text="About",
            variant="ghost",
            height=36,
            command=self._show_about
        )
        self.about_btn.pack(fill="x", pady=(THEME.space_sm, 0))

    def _on_action(self):
        """Handle main action button"""
        if self.is_translating:
            self._request_cancel()
        else:
            self._start()

    def _start(self):
        """Start translation"""
        if self.on_start_callback:
            self.on_start_callback()

    def _request_cancel(self):
        """Request cancellation"""
        self.cancel_requested = True
        self.action_btn.configure(text="Canceling...", state="disabled")
        if self.on_cancel_callback:
            self.on_cancel_callback()

    def _show_about(self):
        """Open about dialog"""
        SettingsSheet(self)

    # === Public API ===

    def set_on_start(self, callback: Callable):
        self.on_start_callback = callback

    def set_on_cancel(self, callback: Callable):
        self.on_cancel_callback = callback

    def show_ready(self):
        """Ready state - calm, inviting"""
        self.is_translating = False
        self.cancel_requested = False

        self.progress_ring.stop_glow()
        self.progress_ring.set_progress(0, animate=False)
        self.percent_label.configure(text="")

        self.status_label.configure(text="Ready")
        self.subtitle_label.configure(text="Select cells in Excel")

        self.stat_left_value.configure(text="--")
        self.stat_right_value.configure(text="--")

        self.action_btn.configure(
            text="Start Translation",
            state="normal",
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary
        )

    def show_connecting(self):
        """Connecting state - anticipation"""
        self.is_translating = True

        self.progress_ring.set_progress(0.05)
        self.progress_ring.start_glow()
        self.percent_label.configure(text="")

        self.status_label.configure(text="Connecting")
        self.subtitle_label.configure(text="Starting browser...")

        self.action_btn.configure(
            text="Cancel",
            fg_color=THEME.bg_elevated,
            text_color=THEME.text_primary
        )

    def show_translating(self, current: int, total: int):
        """Translation in progress - focused energy"""
        self.is_translating = True

        progress = current / total if total > 0 else 0
        percent = int(progress * 100)

        self.progress_ring.set_progress(progress)
        self.progress_ring.start_glow()
        self.percent_label.configure(text=f"{percent}%")

        self.status_label.configure(text="Translating")
        self.subtitle_label.configure(text=f"Processing {total} cells...")

        self.stat_left_value.configure(text=str(total))
        self.stat_right_value.configure(text="Working")

        self.action_btn.configure(
            text="Cancel",
            state="normal",
            fg_color=THEME.bg_elevated,
            text_color=THEME.text_primary
        )

    def show_complete(self, count: int, translation_pairs: list = None):
        """Complete state - quiet celebration"""
        self.is_translating = False
        self.last_translation_pairs = translation_pairs  # Store for viewing

        self.progress_ring.stop_glow()
        self.progress_ring.set_progress(1.0)
        self.percent_label.configure(text="")

        self.status_label.configure(text="Complete")
        self.subtitle_label.configure(text=f"{count} cells translated")

        self.stat_left_value.configure(text=str(count))
        self.stat_right_value.configure(text="Done")

        self.action_btn.configure(
            text="Translate Again",
            state="normal",
            fg_color=THEME.accent,
            text_color=THEME.bg_primary
        )

        # Show results dialog if we have translation pairs
        if translation_pairs:
            self.after(300, lambda: ResultsSheet(self, translation_pairs))

    def show_error(self, message: str):
        """Error state - calm acknowledgment"""
        self.is_translating = False

        self.progress_ring.stop_glow()
        self.progress_ring.set_progress(0, animate=False)
        self.percent_label.configure(text="")

        self.status_label.configure(text="Error")
        self.subtitle_label.configure(text=message[:50])

        self.action_btn.configure(
            text="Try Again",
            state="normal",
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary
        )

    def show_cancelled(self):
        """Cancelled state - graceful stop"""
        self.is_translating = False
        self.cancel_requested = False

        self.progress_ring.stop_glow()
        self.percent_label.configure(text="")

        self.status_label.configure(text="Cancelled")
        self.subtitle_label.configure(text="Translation stopped")

        self.action_btn.configure(
            text="Start Translation",
            state="normal",
            fg_color=THEME.text_primary,
            text_color=THEME.bg_primary
        )


# =============================================================================
# Settings Sheet - Slide-up panel
# =============================================================================
class SettingsSheet(ctk.CTkToplevel):
    """
    Settings panel - Clean, focused information.
    """

    def __init__(self, parent):
        super().__init__(parent)

        self.title("About")
        self.geometry("380x280")
        self.configure(fg_color=THEME.bg_primary)
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._center(parent)

    def _center(self, parent):
        """Center over parent"""
        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """Build settings interface"""
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=THEME.space_lg, pady=THEME.space_lg)

        # Header
        header = ctk.CTkLabel(
            container,
            text="Excel Translator",
            font=get_font("display", 22, "bold"),
            text_color=THEME.text_primary
        )
        header.pack(anchor="w")

        # Info card
        info_frame = GlassCard(container)
        info_frame.pack(fill="x", pady=(THEME.space_lg, 0))

        info_inner = ctk.CTkFrame(info_frame, fg_color="transparent")
        info_inner.pack(fill="x", padx=THEME.space_md, pady=THEME.space_md)

        ctk.CTkLabel(
            info_inner,
            text="Japanese → English Translation",
            font=get_font("text", 14, "bold"),
            text_color=THEME.text_primary
        ).pack(anchor="w")

        ctk.CTkLabel(
            info_inner,
            text="Powered by M365 Copilot",
            font=get_font("text", 12),
            text_color=THEME.text_tertiary
        ).pack(anchor="w", pady=(THEME.space_xs, 0))

        # Hotkey info
        hotkey_frame = GlassCard(container)
        hotkey_frame.pack(fill="x", pady=(THEME.space_md, 0))

        hotkey_inner = ctk.CTkFrame(hotkey_frame, fg_color="transparent")
        hotkey_inner.pack(fill="x", padx=THEME.space_md, pady=THEME.space_sm)

        ctk.CTkLabel(
            hotkey_inner,
            text="Hotkey:  Ctrl + Shift + E",
            font=get_font("mono", 13),
            text_color=THEME.accent
        ).pack(anchor="w")

        # Done button
        done_btn = MinimalButton(
            container,
            text="Done",
            variant="primary",
            command=self.destroy
        )
        done_btn.pack(fill="x", side="bottom")


# =============================================================================
# Results Sheet - Translation log display
# =============================================================================
class ResultsSheet(ctk.CTkToplevel):
    """
    Translation results log - Shows Japanese → English pairs.
    """

    def __init__(self, parent, translation_pairs: list):
        super().__init__(parent)

        self.title("Translation Results")
        self.geometry("500x400")
        self.configure(fg_color=THEME.bg_primary)
        self.minsize(400, 300)

        self.transient(parent)

        self._build_ui(translation_pairs)
        self._center(parent)

    def _center(self, parent):
        """Center over parent"""
        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self, translation_pairs: list):
        """Build results interface"""
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=THEME.space_lg, pady=THEME.space_lg)

        # Header
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x")

        ctk.CTkLabel(
            header_frame,
            text="Translation Log",
            font=get_font("display", 20, "bold"),
            text_color=THEME.text_primary
        ).pack(side="left")

        ctk.CTkLabel(
            header_frame,
            text=f"{len(translation_pairs)} items",
            font=get_font("text", 13),
            text_color=THEME.text_tertiary
        ).pack(side="right")

        # Scrollable results list
        results_frame = ctk.CTkScrollableFrame(
            container,
            fg_color=THEME.bg_card,
            corner_radius=THEME.radius_md,
            scrollbar_button_color=THEME.bg_elevated,
            scrollbar_button_hover_color=THEME.text_tertiary
        )
        results_frame.pack(fill="both", expand=True, pady=(THEME.space_md, THEME.space_md))

        # Add translation pairs
        for i, (japanese, english) in enumerate(translation_pairs):
            self._add_result_row(results_frame, i, japanese, english)

        # Close button
        close_btn = MinimalButton(
            container,
            text="Close",
            variant="primary",
            command=self.destroy
        )
        close_btn.pack(fill="x")

    def _add_result_row(self, parent, index: int, japanese: str, english: str):
        """Add a single result row"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, THEME.space_sm))

        # Row number
        ctk.CTkLabel(
            row,
            text=f"{index + 1}.",
            font=get_font("mono", 11),
            text_color=THEME.text_muted,
            width=30
        ).pack(side="left", anchor="n")

        # Content frame
        content = ctk.CTkFrame(row, fg_color="transparent")
        content.pack(side="left", fill="x", expand=True)

        # Japanese (original)
        jp_label = ctk.CTkLabel(
            content,
            text=japanese[:60] + ("..." if len(japanese) > 60 else ""),
            font=get_font("text", 12),
            text_color=THEME.text_secondary,
            anchor="w",
            justify="left"
        )
        jp_label.pack(fill="x")

        # Arrow and English
        en_frame = ctk.CTkFrame(content, fg_color="transparent")
        en_frame.pack(fill="x")

        ctk.CTkLabel(
            en_frame,
            text="→",
            font=get_font("text", 12),
            text_color=THEME.accent,
            width=20
        ).pack(side="left")

        en_label = ctk.CTkLabel(
            en_frame,
            text=english[:60] + ("..." if len(english) > 60 else ""),
            font=get_font("text", 12, "bold"),
            text_color=THEME.text_primary,
            anchor="w",
            justify="left"
        )
        en_label.pack(side="left", fill="x", expand=True)


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    app = TranslatorApp()
    app.mainloop()
