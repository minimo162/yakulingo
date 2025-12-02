# yakulingo/ui/styles.py
"""
M3 Component-based styles for YakuLingo.
Nani-inspired sidebar layout with clean, minimal design.
"""

COMPLETE_CSS = """
/* === M3 Design Tokens === */
:root {
    /* Primary - Professional indigo (M3 compliant, inspired by baseline) */
    --md-sys-color-primary: #4355B9;
    --md-sys-color-on-primary: #FFFFFF;
    --md-sys-color-primary-container: #DEE0FF;
    --md-sys-color-on-primary-container: #00105C;

    /* Secondary - Neutral blue-gray for balance */
    --md-sys-color-secondary: #595D72;
    --md-sys-color-on-secondary: #FFFFFF;
    --md-sys-color-secondary-container: #DDE1F9;
    --md-sys-color-on-secondary-container: #161B2C;

    /* Tertiary - Warm mauve accent for highlights */
    --md-sys-color-tertiary: #76546E;
    --md-sys-color-on-tertiary: #FFFFFF;
    --md-sys-color-tertiary-container: #FFD7F2;
    --md-sys-color-on-tertiary-container: #2D1228;

    /* Surface - M3 neutral palette with subtle warmth */
    --md-sys-color-surface: #FEFBFF;
    --md-sys-color-surface-dim: #DDD9DE;
    --md-sys-color-surface-bright: #FEFBFF;
    --md-sys-color-surface-container-lowest: #FFFFFF;
    --md-sys-color-surface-container-low: #F8F5FA;
    --md-sys-color-surface-container: #F2EFF4;
    --md-sys-color-surface-container-high: #ECE9EE;
    --md-sys-color-surface-container-highest: #E6E3E8;
    --md-sys-color-on-surface: #1B1B1F;
    --md-sys-color-on-surface-variant: #46464F;
    --md-sys-color-outline: #777680;
    --md-sys-color-outline-variant: #C7C5D0;

    /* Inverse (for snackbars, tooltips) */
    --md-sys-color-inverse-surface: #303034;
    --md-sys-color-inverse-on-surface: #F3EFF4;
    --md-sys-color-inverse-primary: #BAC3FF;

    /* States */
    --md-sys-color-error: #BA1A1A;
    --md-sys-color-on-error: #FFFFFF;
    --md-sys-color-error-container: #FFDAD6;
    --md-sys-color-on-error-container: #410002;

    /* Success (extended) */
    --md-sys-color-success: #1B6B3D;
    --md-sys-color-on-success: #FFFFFF;
    --md-sys-color-success-container: #A3F5B8;
    --md-sys-color-on-success-container: #00210D;

    /* Warning (extended) */
    --md-sys-color-warning: #7D5700;
    --md-sys-color-on-warning: #FFFFFF;
    --md-sys-color-warning-container: #FFDEA6;
    --md-sys-color-on-warning-container: #271900;

    /* Shape - M3 corner radius scale */
    --md-sys-shape-corner-full: 9999px;
    --md-sys-shape-corner-3xl: 32px;   /* Extra large cards */
    --md-sys-shape-corner-2xl: 28px;   /* Large rounded cards */
    --md-sys-shape-corner-xl: 24px;    /* Main cards */
    --md-sys-shape-corner-large: 20px; /* Cards, dialogs, buttons (M3: 20dp) */
    --md-sys-shape-corner-medium: 16px; /* Inputs, chips */
    --md-sys-shape-corner-small: 12px;  /* Small elements */

    /* M3 Button sizing tokens */
    --md-comp-button-height: 2.5rem;         /* 40dp - M3 standard button height */
    --md-comp-button-padding-x: 1.5rem;      /* 24dp - horizontal padding with icon */
    --md-comp-button-padding-x-no-icon: 1rem; /* 16dp - horizontal padding without icon */
    --md-comp-icon-button-size: 2.5rem;      /* 40dp - icon button container */
    --md-comp-icon-button-icon-size: 1.5rem; /* 24dp - icon size inside button */
    --md-comp-touch-target-size: 3rem;       /* 48dp - minimum touch target */

    /* Typography - font size hierarchy (larger for better readability) */
    --md-sys-typescale-size-xs: 0.9375rem;    /* 15px - captions, badges */
    --md-sys-typescale-size-sm: 1rem;         /* 16px - labels, buttons */
    --md-sys-typescale-size-md: 1.0625rem;    /* 17px - body text */
    --md-sys-typescale-size-lg: 1.125rem;     /* 18px - subheadings */
    --md-sys-typescale-size-xl: 1.5rem;       /* 24px - headings */
    --md-sys-typescale-size-2xl: 1.75rem;     /* 28px - large headings */

    /* Typography - font weight hierarchy */
    --md-sys-typescale-weight-regular: 400;   /* Body text, descriptions */
    --md-sys-typescale-weight-medium: 500;    /* Labels, buttons */
    --md-sys-typescale-weight-semibold: 600;  /* Section headers */
    --md-sys-typescale-weight-bold: 700;      /* Headlines, brand */

    /* Motion - M3 standard easing */
    --md-sys-motion-easing-standard: cubic-bezier(0.2, 0, 0, 1);
    --md-sys-motion-easing-spring: cubic-bezier(0.175, 0.885, 0.32, 1.275);
    --md-sys-motion-duration-short: 200ms;
    --md-sys-motion-duration-medium: 300ms;

    /* Elevation - softer, more subtle shadows */
    --md-sys-elevation-1: 0 2px 8px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03);
    --md-sys-elevation-2: 0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);

    /* Sidebar */
    --sidebar-width: 220px;

    /* 3-Column Layout (Nani-inspired) */
    --input-panel-width: 320px;
    --input-panel-width-wide: 480px;  /* Wider input for 2-column mode */
    --bp-desktop: 1200px;        /* Full 3-column with sidebar */
    --bp-tablet-portrait: 800px; /* 2-column with fixed input */
    --bp-mobile: 800px;          /* Single column layout */
}

/* === Base === */
html {
    font-size: 16px;  /* Explicit base for rem calculations */
}

body {
    /* 日本語フォントを優先（system-uiは汎用的すぎるため避ける） */
    /* BIZ UDPGothic: Windows 10+用、UIの上下中央揃えが正確 */
    /* Yu Gothic UI: Windows 8.1+用、UI最適化版 */
    /* Hiragino Sans: macOS用 */
    font-family: 'BIZ UDPGothic', 'Yu Gothic UI', 'Hiragino Sans', 'Segoe UI', -apple-system, sans-serif;
    /* Clean M3-inspired gradient background */
    background:
        radial-gradient(circle at 20% 20%, rgba(67, 85, 185, 0.02) 0%, transparent 50%),
        radial-gradient(circle at 80% 80%, rgba(118, 84, 110, 0.02) 0%, transparent 50%),
        linear-gradient(180deg, var(--md-sys-color-surface) 0%, var(--md-sys-color-surface-container-low) 100%);
    background-size: 100% 100%, 100% 100%, 100% 100%;
    background-attachment: fixed;
    color: var(--md-sys-color-on-surface);
    font-size: 1rem;  /* 16px - comfortable reading size */
    line-height: 1.6;
    margin: 0;
    padding: 0;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* === 3-Column Layout Container === */
.app-container {
    display: flex;
    min-height: 100vh;
    width: 100%;
}

/* === Sidebar Layout === */
.sidebar {
    width: var(--sidebar-width);
    height: 100vh;
    position: fixed;
    left: 0;
    top: 0;
    /* M3 surface gradient sidebar */
    background: linear-gradient(180deg, var(--md-sys-color-surface-container-lowest) 0%, var(--md-sys-color-surface-container-low) 100%);
    border-right: 1px solid var(--md-sys-color-outline-variant);
    display: flex;
    flex-direction: column;
    padding: 1rem;
    gap: 0.75rem;
    z-index: 100;
}

.sidebar-header {
    padding: 0.5rem 0.5rem 0.75rem;
}

/* === 3-Column Main Layout === */
.main-area {
    margin-left: var(--sidebar-width);
    flex: 1;
    min-height: 100vh;
    display: flex;
    flex-direction: row;
}

/* Input Panel (Middle Column - Sticky) */
.input-panel {
    width: var(--input-panel-width);
    min-width: var(--input-panel-width);
    height: 100vh;
    position: sticky;
    top: 0;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    background: var(--md-sys-color-surface);
    border-right: 1px solid var(--md-sys-color-outline-variant);
    overflow-y: auto;
}

/* Result Panel (Right Column - Scrollable) */
.result-panel {
    flex: 1;
    min-height: 100vh;
    padding: 1.5rem 2rem;
    overflow-y: auto;
}

/* Empty Result State Placeholder */
.empty-result-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    min-height: 200px;
    padding: 2rem;
    border: 2px dashed var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-large);
    background-color: var(--md-sys-color-surface-container-low);
}

/* === Logo === */
.app-logo {
    font-size: 1.25rem;
    font-weight: 700;  /* Bold for brand name */
    color: var(--md-sys-color-primary);
    letter-spacing: -0.02em;
}

.app-logo-icon {
    width: 2.5rem;
    height: 2.5rem;
    border-radius: var(--md-sys-shape-corner-medium);
    /* M3 primary gradient */
    background: linear-gradient(135deg, #5A6AC9 0%, #4355B9 50%, #3345A9 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--md-sys-color-on-primary);
    box-shadow:
        0 4px 12px rgba(67, 85, 185, 0.25),
        0 2px 4px rgba(0, 0, 0, 0.08);
}

/* === Navigation Tabs (M3 Vertical Tabs) === */
.sidebar-nav {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-top: 0.5rem;
    /* M3 tabs container has no shape */
    background: transparent;
}

.nav-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.875rem 1rem;
    /* M3 tabs have no rounded corners */
    border-radius: 0;
    /* M3 title-small typography */
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.1px;
    line-height: 1.25rem;
    color: var(--md-sys-color-on-surface-variant);
    width: 100%;
    /* M3 tab container color */
    background: transparent;
    /* Vertical indicator line on left */
    border-left: 3px solid transparent;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) backwards;
    position: relative;
    cursor: pointer;
}

/* Staggered nav item animations */
.nav-item:nth-child(1) { animation-delay: 50ms; }
.nav-item:nth-child(2) { animation-delay: 100ms; }
.nav-item:nth-child(3) { animation-delay: 150ms; }

/* M3 hover state layer */
.nav-item:hover {
    background: color-mix(in srgb, var(--md-sys-color-on-surface) 8%, transparent);
    color: var(--md-sys-color-on-surface);
}

/* M3 focus state */
.nav-item:focus-visible {
    outline: 2px solid var(--md-sys-color-primary);
    outline-offset: -2px;
    background: color-mix(in srgb, var(--md-sys-color-on-surface) 12%, transparent);
}

/* M3 active tab with indicator */
.nav-item.active {
    /* M3 primary indicator color */
    border-left-color: var(--md-sys-color-primary);
    /* Active text color */
    color: var(--md-sys-color-primary);
    background: color-mix(in srgb, var(--md-sys-color-primary) 8%, transparent);
}

.nav-item.active:hover {
    background: color-mix(in srgb, var(--md-sys-color-primary) 12%, transparent);
}

/* M3 icon styling in tabs */
.nav-item .q-icon {
    font-size: 1.25rem;
    color: inherit;
}

.nav-item.disabled {
    opacity: 0.38;  /* M3 disabled opacity */
    cursor: not-allowed;
    pointer-events: none;
}

/* === History Section === */
.sidebar-history {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
}

.history-scroll {
    flex: 1;
    min-height: 0;
    max-height: calc(100vh - 280px);
}

.history-item {
    display: flex;
    padding: 0.625rem 0.75rem;
    border-radius: var(--md-sys-shape-corner-medium);
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    position: relative;
    animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) backwards;
}

/* Staggered history item animations */
.history-item:nth-child(1) { animation-delay: 0ms; }
.history-item:nth-child(2) { animation-delay: 40ms; }
.history-item:nth-child(3) { animation-delay: 80ms; }
.history-item:nth-child(4) { animation-delay: 120ms; }
.history-item:nth-child(5) { animation-delay: 160ms; }

.history-item:hover {
    background: var(--md-sys-color-surface-container);
}

/* Note: .history-delete-btn is defined below in the Nani-inspired enhancements section */

/* === Status Indicator === */
.status-indicator {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.375rem 0.875rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.9375rem;  /* 15px - better readability */
    font-weight: 500;
    background: var(--md-sys-color-surface-container);
    color: var(--md-sys-color-on-surface-variant);
    margin-left: 0.5rem;
}

.status-indicator.connected {
    background: var(--md-sys-color-success-container);
    color: var(--md-sys-color-on-success-container);
}

.status-indicator.connecting {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
}

.status-indicator.login-required {
    background: var(--md-sys-color-warning-container);
    color: var(--md-sys-color-on-warning-container);
}

.status-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--md-sys-shape-corner-full);
    background: var(--md-sys-color-outline);
}

.status-dot.connected {
    background: var(--md-sys-color-success);
}

.status-dot.connecting {
    background: var(--md-sys-color-primary);
    animation: pulse 1.5s ease infinite;
}

.status-dot.login-required {
    background: var(--md-sys-color-warning);
    animation: pulse 1.5s ease infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* === Main Card Container (Nani-style) === */
.main-card {
    background: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-3xl);
    box-shadow: var(--md-sys-elevation-1);
    padding: 0.375rem;
    overflow: hidden;
    animation: fadeInSpring 400ms var(--md-sys-motion-easing-spring);
}

.main-card-inner {
    background: var(--md-sys-color-surface);
    border-radius: calc(var(--md-sys-shape-corner-3xl) - 0.375rem);
    border: 1px solid var(--md-sys-color-outline-variant);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

/* Focus state for main card (when textarea is focused) */
.main-card-inner:focus-within {
    border-color: var(--md-sys-color-primary);
    box-shadow: 0 0 0 3px rgba(67, 85, 185, 0.12);
    transform: scale(1.005);
}

/* === M3 Text Field Container === */
.text-box {
    background: var(--md-sys-color-surface);
    border: 1px solid var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-3xl);
    overflow: hidden;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.text-box:focus-within {
    border-color: var(--md-sys-color-primary);
    box-shadow: 0 0 0 2px rgba(67, 85, 185, 0.15);
}

/* === Translate Button (alias for btn-primary) === */
/* Note: .translate-btn is an alias for .btn-primary for backward compatibility */

/* === Keycap Style Shortcut Keys === */
.shortcut-keys {
    display: inline-flex;
    align-items: center;
    gap: 2px;
}

.keycap {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.625rem;
    height: 1.5rem;
    padding: 0 0.5rem;
    background: rgba(255, 255, 255, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: 6px;
    font-family: ui-monospace, monospace;
    font-size: 0.8125rem;  /* 13px - minimum readable size */
    font-weight: 500;
    color: rgba(255, 255, 255, 0.95);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

.keycap-plus {
    font-size: 0.8125rem;
    color: rgba(255, 255, 255, 0.7);
    margin: 0 2px;
}

/* === M3 Outlined Button === */
.btn-outline {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    height: var(--md-comp-button-height);
    min-height: var(--md-comp-button-height);
    padding: 0 var(--md-comp-button-padding-x);
    background: transparent;
    border: 1px solid var(--md-sys-color-outline);
    border-radius: var(--md-sys-shape-corner-full);
    color: var(--md-sys-color-primary);
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.btn-outline:hover {
    background: rgba(67, 85, 185, 0.08);
    border-color: var(--md-sys-color-outline);
}

.btn-outline:active {
    background: rgba(67, 85, 185, 0.12);
}

.btn-outline:disabled {
    border-color: rgba(27, 27, 31, 0.12);
    color: rgba(27, 27, 31, 0.38);
    cursor: default;
}

/* === M3 Filled Button (Primary) === */
/* .translate-btn is an alias for backward compatibility */
.btn-primary,
.translate-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    height: var(--md-comp-button-height);
    min-height: var(--md-comp-button-height);
    padding: 0 var(--md-comp-button-padding-x);
    background: var(--md-sys-color-primary);
    color: var(--md-sys-color-on-primary);
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    border: none;
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    /* M3 elevation level 0 for filled buttons */
    box-shadow: none;
}

.btn-primary:hover:not(:disabled),
.translate-btn:hover:not(:disabled) {
    /* M3: State layer overlay on hover (8% opacity) */
    background: linear-gradient(rgba(255,255,255,0.08), rgba(255,255,255,0.08)), var(--md-sys-color-primary);
    /* M3: Elevation level 1 on hover */
    box-shadow: var(--md-sys-elevation-1);
}

.btn-primary:active:not(:disabled),
.translate-btn:active:not(:disabled) {
    /* M3: State layer overlay on press (12% opacity) */
    background: linear-gradient(rgba(255,255,255,0.12), rgba(255,255,255,0.12)), var(--md-sys-color-primary);
    box-shadow: none;
}

.btn-primary:disabled,
.translate-btn:disabled {
    background: rgba(27, 27, 31, 0.12);
    color: rgba(27, 27, 31, 0.38);
    cursor: default;
    box-shadow: none;
}

/* === M3 Tonal Button (Filled Tonal) === */
.btn-tonal {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    height: var(--md-comp-button-height);
    min-height: var(--md-comp-button-height);
    padding: 0 var(--md-comp-button-padding-x);
    background: var(--md-sys-color-secondary-container);
    color: var(--md-sys-color-on-secondary-container);
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    border: none;
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.btn-tonal:hover {
    background: linear-gradient(rgba(0,0,0,0.08), rgba(0,0,0,0.08)), var(--md-sys-color-secondary-container);
    box-shadow: var(--md-sys-elevation-1);
}

.btn-tonal:active {
    background: linear-gradient(rgba(0,0,0,0.12), rgba(0,0,0,0.12)), var(--md-sys-color-secondary-container);
}

/* === M3 Text Button === */
.btn-text {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    height: var(--md-comp-button-height);
    min-height: var(--md-comp-button-height);
    padding: 0 0.75rem;
    background: transparent;
    color: var(--md-sys-color-primary);
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    border: none;
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.btn-text:hover {
    background: rgba(67, 85, 185, 0.08);
}

.btn-text:active {
    background: rgba(67, 85, 185, 0.12);
}

/* === Drop Zone (Gradio-inspired) === */
.drop-zone {
    border: 2px dashed var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-xl);
    padding: 3rem 2rem;
    text-align: center;
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    background: var(--md-sys-color-surface);
    position: relative;
}

/* Make entire drop zone clickable - expand the hidden input to cover full area */
.drop-zone .q-uploader__input {
    position: absolute !important;
    top: 0 !important;
    left: 0 !important;
    width: 100% !important;
    height: 100% !important;
    opacity: 0 !important;
    cursor: pointer !important;
    z-index: 10 !important;
}

/* Hide ALL Quasar uploader internal elements */
.drop-zone .q-uploader__header,
.drop-zone .q-uploader__list,
.drop-zone .q-uploader__file,
.drop-zone .q-uploader__dnd,
.drop-zone .q-uploader__subtitle,
.drop-zone .q-uploader__overlay,
.drop-zone .q-uploader__spinner,
.drop-zone .q-uploader__expand-btn {
    display: none !important;
}

/* Make q-uploader completely invisible except for the input */
.drop-zone .q-uploader {
    width: 100% !important;
    min-height: auto !important;
    max-height: none !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    overflow: visible !important;
}

/* Ensure custom content inside drop zone doesn't block clicks */
.drop-zone > *:not(.q-uploader) {
    pointer-events: none;
}

.drop-zone-icon,
.drop-zone-text,
.drop-zone-subtext,
.drop-zone-hint {
    pointer-events: none;
    position: relative;
    z-index: 1;
}

.drop-zone:hover {
    border-color: var(--md-sys-color-primary);
    background: var(--md-sys-color-primary-container);
    transform: scale(1.02);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

.drop-zone-icon {
    font-size: 3rem;
    color: var(--md-sys-color-on-surface-variant);
    margin-bottom: 0.75rem;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

.drop-zone:hover .drop-zone-icon {
    transform: translateY(-4px);
    color: var(--md-sys-color-primary);
}

.drop-zone-text {
    font-size: 1.125rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
    margin-bottom: 0.375rem;
}

.drop-zone-subtext {
    font-size: 1rem;
    color: var(--md-sys-color-outline);
    margin-bottom: 0.75rem;
}

.drop-zone-hint {
    font-size: 0.9375rem;
    color: var(--md-sys-color-on-surface-variant);
    background: var(--md-sys-color-surface-container);
    padding: 0.375rem 0.75rem;
    border-radius: var(--md-sys-shape-corner-small);
}

/* === M3 Card === */
.file-card {
    background: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-large);
    padding: 1.25rem;
    animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

.file-card.success {
    background: var(--md-sys-color-success-container);
}

/* === M3 Progress Indicator === */
.progress-track {
    height: 6px;
    background: var(--md-sys-color-surface-container-high);
    border-radius: var(--md-sys-shape-corner-full);
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    /* M3 primary gradient */
    background: linear-gradient(90deg, #3345A9 0%, #4355B9 50%, #5A6AC9 100%);
    border-radius: var(--md-sys-shape-corner-full);
    transition: width var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
    position: relative;
}

/* Shimmer effect for progress bar */
.progress-bar::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(255, 255, 255, 0.3) 50%,
        transparent 100%
    );
    animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
}

/* === Chip === */
.chip {
    display: inline-block;
    padding: 0.4375rem 0.875rem;
    background: var(--md-sys-color-surface-container-high);
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.9375rem;  /* 15px - better readability */
    color: var(--md-sys-color-on-surface-variant);
}

.chip-primary {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
}

/* === Option Cards === */
.option-card {
    background: var(--md-sys-color-surface);
    border: 1px solid var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-xl);
    padding: 1.25rem;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.option-card:hover {
    border-color: var(--md-sys-color-outline);
    box-shadow: var(--md-sys-elevation-2);
    transform: translateY(-3px) scale(1.01);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

.option-text {
    line-height: 1.7;
    word-break: break-word;
    font-size: 1.0625rem;
}

.option-action {
    opacity: 0.5;
    transition: opacity var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.option-card:hover .option-action {
    opacity: 1;
}

/* === Result Section === */
.result-section {
    background: var(--md-sys-color-surface);
    border-radius: var(--md-sys-shape-corner-3xl);
    box-shadow: var(--md-sys-elevation-1);
    overflow: hidden;
    animation: fadeInSpring 400ms var(--md-sys-motion-easing-spring);
}

.result-header {
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--md-sys-color-outline-variant);
    font-size: 0.9375rem;  /* 15px - improved readability */
    font-weight: 600;  /* Semibold for section headers */
    color: var(--md-sys-color-on-surface-variant);
}

/* === Success === */
.success-icon {
    font-size: 2.5rem;
    color: var(--md-sys-color-success);
}

.success-text {
    font-size: 1rem;
    font-weight: 500;
    color: var(--md-sys-color-on-success-container);
}

.success-circle {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 4rem;
    height: 4rem;
    border-radius: var(--md-sys-shape-corner-full);
    background: var(--md-sys-color-success);
    animation: scaleIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

.success-check {
    font-size: 2rem;
    color: var(--md-sys-color-on-success);
}

@keyframes scaleIn {
    from {
        transform: scale(0);
        opacity: 0;
    }
    to {
        transform: scale(1);
        opacity: 1;
    }
}

/* === File Type Icon === */
.file-type-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 3.5rem;
    height: 3.5rem;
    border-radius: var(--md-sys-shape-corner-large);
    flex-shrink: 0;
}

.file-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 200px;
}

/* === Utility === */
.text-muted { color: var(--md-sys-color-on-surface-variant); }
.text-primary { color: var(--md-sys-color-primary); }
.text-error { color: var(--md-sys-color-error); }
.text-2xs { font-size: 0.9375rem; }  /* 15px - better readability */

.animate-in {
    animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

/* Staggered fadeIn animations */
.animate-stagger-1 { animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) 50ms backwards; }
.animate-stagger-2 { animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) 100ms backwards; }
.animate-stagger-3 { animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) 150ms backwards; }
.animate-stagger-4 { animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) 200ms backwards; }

/* fadeIn with spring easing for more dynamic feel */
.animate-in-spring {
    animation: fadeInSpring 400ms var(--md-sys-motion-easing-spring);
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeInSpring {
    from { opacity: 0; transform: translateY(8px) scale(0.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
}

/* === Responsive Design (Nani-inspired breakpoints) === */

/* ========================================
   Desktop (1200px+): Dynamic 2/3 column
   - Default: 2-column (sidebar + wide input)
   - With results: 3-column (sidebar + input + results)
   ======================================== */

/* Default 2-column mode (no results) */
.main-area:not(.has-results) .input-panel {
    width: var(--input-panel-width-wide);
    min-width: var(--input-panel-width-wide);
    border-right: none;
}

.main-area:not(.has-results) .result-panel {
    display: none;
}

/* 3-column mode when has results */
.main-area.has-results .input-panel {
    width: var(--input-panel-width);
    min-width: var(--input-panel-width);
    border-right: 1px solid var(--md-sys-color-outline-variant);
}

.main-area.has-results .result-panel {
    display: flex;
}

/* File panel always 2-column (centered) */
.main-area.file-mode .result-panel {
    display: none;
}

.main-area.file-mode .input-panel {
    width: 100%;
    min-width: 100%;
    max-width: none;
    border-right: none;
}

/* ========================================
   Tablet Portrait (800px - 1200px):
   Always 2-column with fixed input at top
   Nani-style layout
   ======================================== */
@media (min-width: 800px) and (max-width: 1200px) {
    /* Keep sidebar visible */
    .sidebar {
        display: flex;
    }

    /* Hide mobile header */
    .mobile-header {
        display: none !important;
    }

    .main-area {
        margin-left: var(--sidebar-width);
        padding-top: 0;
        flex-direction: column;
        min-height: 100vh;
    }

    /* Input panel fixed at top */
    .input-panel {
        width: 100% !important;
        min-width: 100% !important;
        height: auto !important;
        min-height: auto !important;
        position: sticky;
        top: 0;
        z-index: 50;
        border-right: none !important;
        border-bottom: 1px solid var(--md-sys-color-outline-variant);
        background: var(--md-sys-color-surface);
        padding: 1rem 1.5rem;
        box-shadow: var(--md-sys-elevation-1);
    }

    /* Result panel scrollable below */
    .result-panel {
        display: flex !important;
        flex: 1;
        min-height: 0;
        padding: 1.5rem;
        overflow-y: auto;
    }

    /* Override has-results/no-results for tablet portrait */
    .main-area.has-results .input-panel,
    .main-area:not(.has-results) .input-panel {
        width: 100% !important;
        min-width: 100% !important;
        border-right: none !important;
    }

    .main-area.has-results .result-panel,
    .main-area:not(.has-results) .result-panel {
        display: flex !important;
    }
}

/* ========================================
   Mobile (<800px): Single column, sidebar hidden
   ======================================== */
@media (max-width: 800px) {
    .sidebar {
        display: none;
    }

    .main-area {
        margin-left: 0;
        flex-direction: column;
        padding-top: 3.5rem; /* Space for mobile header */
    }

    /* Show mobile header with hamburger menu */
    .mobile-header {
        display: flex;
    }

    .input-panel {
        width: 100% !important;
        min-width: 100% !important;
        height: auto;
        position: relative;
        border-right: none !important;
        border-bottom: 1px solid var(--md-sys-color-outline-variant);
        padding: 1rem;
    }

    .result-panel {
        display: flex !important;
        padding: 1rem;
    }

    /* Override dynamic column classes */
    .main-area.has-results .input-panel,
    .main-area:not(.has-results) .input-panel {
        width: 100% !important;
        min-width: 100% !important;
    }

    .main-area.has-results .result-panel,
    .main-area:not(.has-results) .result-panel {
        display: flex !important;
    }

    /* Improve touch targets on mobile */
    .btn-primary,
    .translate-btn,
    .btn-outline {
        min-height: 44px;
        padding: 0.75rem 1.25rem;
    }
}

/* Mobile header (hidden on large screens) */
.mobile-header {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 3.5rem;
    background: var(--md-sys-color-surface);
    border-bottom: 1px solid var(--md-sys-color-outline-variant);
    padding: 0 1rem;
    align-items: center;
    gap: 0.75rem;
    z-index: 200;
}

.mobile-header-btn {
    width: 2.5rem;
    height: 2.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--md-sys-shape-corner-full);
    background: transparent;
    color: var(--md-sys-color-on-surface);
    border: none;
    cursor: pointer;
    transition: background var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.mobile-header-btn:hover {
    background: var(--md-sys-color-surface-container);
}

/* Mobile sidebar overlay */
.sidebar-overlay {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.25);
    backdrop-filter: blur(4px);
    z-index: 150;
    animation: fadeIn var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.sidebar-overlay.visible {
    display: block;
}

/* Mobile sidebar (slide-in) */
.sidebar.mobile-visible {
    display: flex;
    animation: slideInLeft var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

@keyframes slideInLeft {
    from {
        transform: translateX(-100%);
    }
    to {
        transform: translateX(0);
    }
}

/* High DPI display adjustments */
@media (-webkit-min-device-pixel-ratio: 2), (min-resolution: 192dpi) {
    html {
        font-size: 16px;
    }
}

/* === Dialog === */
.q-card {
    border-radius: var(--md-sys-shape-corner-xl) !important;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12) !important;
    animation: fadeInSpring 300ms var(--md-sys-motion-easing-spring) !important;
}

.q-dialog__backdrop {
    background: rgba(0, 0, 0, 0.25) !important;
    animation: fadeIn 200ms var(--md-sys-motion-easing-standard) !important;
    backdrop-filter: blur(4px);
}

/* === Truncate === */
.truncate {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* === M3 Segmented Button Container === */
.segmented-btn-container {
    display: inline-flex;
    height: var(--md-comp-button-height);
    border: 1px solid var(--md-sys-color-outline);
    border-radius: var(--md-sys-shape-corner-full);
    overflow: hidden;
}

.segmented-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    height: 100%;
    min-width: 3rem;
    padding: 0 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    color: var(--md-sys-color-on-surface);
    background: transparent;
    border: none;
    border-right: 1px solid var(--md-sys-color-outline);
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.segmented-btn:last-child {
    border-right: none;
}

.segmented-btn:hover:not(.segmented-btn-selected) {
    background: rgba(27, 27, 31, 0.08);
}

.segmented-btn-selected {
    background: var(--md-sys-color-secondary-container);
    color: var(--md-sys-color-on-secondary-container);
}

.segmented-btn-selected:hover {
    background: linear-gradient(rgba(0,0,0,0.08), rgba(0,0,0,0.08)), var(--md-sys-color-secondary-container);
}

/* Checkmark icon for selected state */
.segmented-btn-selected::before {
    content: '✓';
    margin-right: 0.25rem;
    font-size: 0.875rem;
}

/* === Language Selector (Legacy - Segmented Button style) === */
.language-selector {
    display: inline-flex;
    height: var(--md-comp-button-height);
    border: 1px solid var(--md-sys-color-outline);
    border-radius: var(--md-sys-shape-corner-full);
    overflow: hidden;
}

.lang-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.375rem;
    height: 100%;
    padding: 0 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    color: var(--md-sys-color-on-surface);
    background: transparent;
    border: none;
    border-right: 1px solid var(--md-sys-color-outline);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    cursor: pointer;
}

.lang-btn:last-child,
.lang-btn-right {
    border-right: none;
}

.lang-btn-left {
    border-radius: 0;
}

.lang-btn-right {
    border-radius: 0;
}

.lang-btn:hover:not(.lang-btn-active) {
    background: rgba(27, 27, 31, 0.08);
}

.lang-btn-active {
    background: var(--md-sys-color-secondary-container);
    color: var(--md-sys-color-on-secondary-container);
}

/* === Translation Style Selector (Legacy - Segmented Button style) === */
.style-selector {
    display: inline-flex;
    height: var(--md-comp-button-height);
    border: 1px solid var(--md-sys-color-outline);
    border-radius: var(--md-sys-shape-corner-full);
    overflow: hidden;
}

.style-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-width: 4rem;
    padding: 0 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    color: var(--md-sys-color-on-surface);
    background: transparent;
    border: none;
    border-right: 1px solid var(--md-sys-color-outline);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    cursor: pointer;
}

.style-btn:last-child {
    border-right: none;
}

.style-btn-left {
    border-radius: 0;
}

.style-btn-middle {
    border-radius: 0;
}

.style-btn-right {
    border-radius: 0;
}

.style-btn:hover:not(.style-btn-active) {
    background: rgba(27, 27, 31, 0.08);
}

.style-btn-active {
    background: var(--md-sys-color-secondary-container);
    color: var(--md-sys-color-on-secondary-container);
}

/* === →Japanese Translation Result Card === */
.jp-result-card {
    background: var(--md-sys-color-surface);
    border: 1px solid var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-xl);
    padding: 1.5rem;
}

.jp-result-text {
    line-height: 1.8;
    word-break: break-word;
    color: var(--md-sys-color-on-surface);
}

/* === Explanation Card === */
.explanation-card {
    background: var(--md-sys-color-surface-container);
    border: none;
    border-radius: var(--md-sys-shape-corner-large);
    padding: 1.25rem;
}

/* === Nani-style Avatar and Status === */
.avatar-status-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-left: 0.25rem;
    margin-top: 1.375rem;
    margin-bottom: 0.625rem;
}

.avatar-container {
    width: 1.75rem;
    height: 1.75rem;
    flex-shrink: 0;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 11px;
    background: var(--md-sys-color-primary-container);
}

.avatar-container .avatar-icon {
    width: 1.125rem;
    height: 1.125rem;
    color: var(--md-sys-color-primary);
}

.status-text {
    min-width: 0;
}

.status-label {
    font-size: 1rem;
    line-height: 1.5;
    color: var(--md-sys-color-on-surface-variant);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.result-container {
    display: flex;
    flex-direction: column;
    gap: 0.875rem;
    margin-top: 0.625rem;
}

/* === Nani-style Result Card === */
.nani-result-card {
    border-radius: calc(var(--md-sys-shape-corner-2xl) + 0.25rem);
    padding: 0.25rem;
    position: relative;
    background: var(--md-sys-color-surface);
    box-shadow: var(--md-sys-elevation-1);
    border: 1px solid var(--md-sys-color-outline-variant);
}

.nani-result-content {
    padding: 0.75rem 1rem 0.625rem;
}

.nani-result-text {
    white-space: pre-wrap;
    flex: 1;
    font-size: 1.0625rem;
    line-height: 1.6;
    color: var(--md-sys-color-on-surface);
    word-break: break-word;
}

.nani-toolbar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.625rem;
    margin-left: -0.25rem;
}

.nani-toolbar-btn {
    opacity: 0.6;
    transition: opacity var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.nani-toolbar-btn:hover {
    opacity: 1;
}

/* === Nani-style Explanation === */
.nani-explanation {
    background: var(--md-sys-color-primary-container);
    padding: 1rem 1.125rem;
    margin-top: 0.25rem;
    color: var(--md-sys-color-on-primary-container);
    border-radius: 1rem;
    border-left: 4px solid var(--md-sys-color-primary);
    font-size: 0.9375rem;
    line-height: 1.8;
}

.nani-explanation ul {
    margin: 0;
    padding-left: 1.25rem;
    list-style-type: disc;
}

.nani-explanation li {
    margin-bottom: 0.5rem;
}

.nani-explanation li:last-child {
    margin-bottom: 0;
}

.nani-explanation strong {
    font-weight: 600;
}

.nani-explanation i {
    font-style: normal;
    opacity: 0.7;
}

/* === Follow-up Actions === */
.follow-up-section {
    padding: 0.875rem 0;
}

.follow-up-btn {
    height: var(--md-comp-button-height) !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
    padding: 0 var(--md-comp-button-padding-x) !important;
    border: 1px solid var(--md-sys-color-outline) !important;
    color: var(--md-sys-color-primary) !important;
    border-radius: var(--md-sys-shape-corner-full) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.follow-up-btn:hover {
    background: rgba(67, 85, 185, 0.08) !important;
}

.follow-up-btn:active {
    background: rgba(67, 85, 185, 0.12) !important;
}

/* === Additional Result Cards (for follow-up responses) === */
.additional-result {
    border-left: 3px solid var(--md-sys-color-primary);
    padding-left: 1rem;
    margin-top: 1rem;
}

/* === Nani-inspired Enhancements === */

/* Language detection animated icon */
.lang-detect-icon {
    width: 1.25rem;
    height: 1.25rem;
    flex-shrink: 0;
}

.lang-detect-icon path {
    opacity: 0.5;
}

.lang-detect-icon .flow-top,
.lang-detect-icon .flow-bottom {
    opacity: 1;
}

@keyframes flowTop {
    0% { clip-path: inset(0 100% 0 0); }
    100% { clip-path: inset(0 0 0 0); }
}

@keyframes flowBottom {
    0% { clip-path: inset(0 100% 0 0); }
    100% { clip-path: inset(0 0 0 0); }
}

.lang-detect-icon .flow-top {
    animation: flowTop 1.2s ease-in-out infinite;
}

.lang-detect-icon .flow-bottom {
    animation: flowBottom 1.2s ease-in-out infinite;
    animation-delay: 1.2s;
}

/* Security badge */
.security-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.125rem 0.5rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.8125rem;
    color: var(--md-sys-color-on-surface-variant);
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.security-badge:hover {
    background: var(--md-sys-color-surface-container);
    color: var(--md-sys-color-on-surface);
}

.security-badge svg {
    width: 0.875rem;
    height: 0.875rem;
}

/* Note: .main-card and .main-card-inner are defined above (lines 268-281) */

/* Apple character for translation states */
.apple-character {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    animation: bounce 1s ease-in-out infinite;
}

.apple-character.thinking {
    animation: thinking 1.5s ease-in-out infinite;
}

.apple-character.success {
    animation: celebrate 0.6s ease-out;
}

@keyframes bounce {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-4px); }
}

@keyframes thinking {
    0%, 100% { transform: rotate(-5deg); }
    50% { transform: rotate(5deg); }
}

@keyframes celebrate {
    0% { transform: scale(1); }
    50% { transform: scale(1.2); }
    100% { transform: scale(1); }
}

/* Enhanced hover animations */
.app-logo-icon {
    transition: transform var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

.app-logo-icon:hover {
    transform: rotate(5deg) scale(1.05);
}

.nav-item {
    position: relative;
    overflow: hidden;
}

.nav-item.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 3px;
    height: 60%;
    background: var(--md-sys-color-primary);
    border-radius: var(--md-sys-shape-corner-full);
    animation: slideIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

@keyframes slideIn {
    from {
        opacity: 0;
        transform: translateY(-50%) scaleY(0);
    }
    to {
        opacity: 1;
        transform: translateY(-50%) scaleY(1);
    }
}

/* Gradient delete button for history */
.history-delete-btn {
    opacity: 0;
    transition: opacity var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    position: absolute;
    right: 0;
    top: 50%;
    transform: translateY(-50%);
    background: linear-gradient(to left,
        var(--md-sys-color-surface-container) 70%,
        transparent
    ) !important;
    padding-left: 1.5rem !important;
    padding-right: 0.5rem !important;
}

.history-item:hover .history-delete-btn {
    opacity: 1;
}

/* Flag icons for language selector */
.flag-icon {
    font-size: 1rem;
    margin-right: 0.25rem;
}

.lang-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
}

/* Translation result stagger animation */
.option-card {
    animation: slideUp var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) backwards;
}

.option-card:nth-child(1) { animation-delay: 0ms; }
.option-card:nth-child(2) { animation-delay: 80ms; }
.option-card:nth-child(3) { animation-delay: 160ms; }
.option-card:nth-child(4) { animation-delay: 240ms; }

@keyframes slideUp {
    from {
        opacity: 0;
        transform: translateY(12px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Loading state with character */
.loading-character {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    padding: 2rem;
}

.loading-character .emoji {
    font-size: 2.5rem;
    animation: thinking 1.5s ease-in-out infinite;
}

.loading-character .message {
    font-size: 1rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
}

.loading-character .submessage {
    font-size: 0.9375rem;
    color: var(--md-sys-color-on-surface-variant);
}

/* Success state with character */
.success-character {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
}

.success-character .emoji {
    font-size: 1.5rem;
    animation: celebrate 0.6s ease-out;
}

.success-character .message {
    font-size: 0.9375rem;
    color: var(--md-sys-color-on-surface-variant);
}

/* Hint section improvements */
.hint-section {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    padding: 0.875rem 0;
}

.hint-primary {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--md-sys-color-on-surface-variant);
    font-size: 0.9375rem;
}

.hint-secondary {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    color: var(--md-sys-color-on-surface-variant);
    opacity: 0.6;
    font-size: 0.9375rem;
}

/* Security tooltip */
.security-tooltip {
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    background: var(--md-sys-color-on-surface);
    color: var(--md-sys-color-surface);
    padding: 0.5rem 0.75rem;
    border-radius: var(--md-sys-shape-corner-small);
    font-size: 0.8125rem;
    white-space: nowrap;
    opacity: 0;
    visibility: hidden;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    z-index: 100;
    margin-bottom: 0.5rem;
}

.security-tooltip::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: var(--md-sys-color-on-surface);
}

.security-badge:hover .security-tooltip {
    opacity: 1;
    visibility: visible;
}

/* Result count badge */
.result-count-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem 0.625rem;
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.8125rem;
    font-weight: 500;
}

.result-count-badge .emoji {
    font-size: 0.875rem;
}

/* === M3 Icon Button (Standard) === */
/* Container: 40dp, Icon: 24dp, Touch target: 48dp */
.icon-btn {
    display: grid;
    place-items: center;
    width: var(--md-comp-icon-button-size);
    height: var(--md-comp-icon-button-size);
    min-width: var(--md-comp-touch-target-size);
    min-height: var(--md-comp-touch-target-size);
    border: none;
    border-radius: var(--md-sys-shape-corner-full);
    background: transparent;
    color: var(--md-sys-color-on-surface-variant);
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    flex-shrink: 0;
}

.icon-btn:hover {
    background: rgba(70, 70, 79, 0.08);
}

.icon-btn:active {
    background: rgba(70, 70, 79, 0.12);
}

.icon-btn .q-icon,
.icon-btn svg {
    width: var(--md-comp-icon-button-icon-size);
    height: var(--md-comp-icon-button-icon-size);
    font-size: var(--md-comp-icon-button-icon-size);
}

/* M3 Icon Button - Filled */
.icon-btn-filled {
    background: var(--md-sys-color-primary);
    color: var(--md-sys-color-on-primary);
}

.icon-btn-filled:hover {
    background: linear-gradient(rgba(255,255,255,0.08), rgba(255,255,255,0.08)), var(--md-sys-color-primary);
}

/* M3 Icon Button - Tonal */
.icon-btn-tonal {
    background: var(--md-sys-color-secondary-container);
    color: var(--md-sys-color-on-secondary-container);
}

.icon-btn-tonal:hover {
    background: linear-gradient(rgba(0,0,0,0.08), rgba(0,0,0,0.08)), var(--md-sys-color-secondary-container);
}

/* M3 Icon Button - Outlined */
.icon-btn-outlined {
    border: 1px solid var(--md-sys-color-outline);
    color: var(--md-sys-color-on-surface-variant);
}

.icon-btn-outlined:hover {
    background: rgba(70, 70, 79, 0.08);
}

/* === Attach Button (extends icon-btn) === */
.attach-btn {
    display: grid;
    place-items: center;
    width: var(--md-comp-icon-button-size);
    height: var(--md-comp-icon-button-size);
    border: none;
    border-radius: var(--md-sys-shape-corner-full);
    background: transparent;
    color: var(--md-sys-color-on-surface-variant);
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    flex-shrink: 0;
}

.attach-btn:hover {
    background: rgba(67, 85, 185, 0.08);
    color: var(--md-sys-color-primary);
}

.attach-btn:active {
    background: rgba(67, 85, 185, 0.12);
}

.attach-btn.has-file {
    color: var(--md-sys-color-primary);
    background: var(--md-sys-color-primary-container);
}

.attach-btn svg {
    width: var(--md-comp-icon-button-icon-size);
    height: var(--md-comp-icon-button-icon-size);
}

/* Attachment file indicator */
.attach-file-indicator {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.25rem 0.5rem;
    background: var(--md-sys-color-primary-container);
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.8125rem;
    color: var(--md-sys-color-on-primary-container);
}

.attach-file-indicator .file-name {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.attach-file-indicator .remove-btn {
    padding: 0.125rem;
    border-radius: var(--md-sys-shape-corner-full);
    cursor: pointer;
    transition: background var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.attach-file-indicator .remove-btn:hover {
    background: rgba(0, 0, 0, 0.1);
}

/* === Nani-style Inline Adjustment Section === */
.inline-adjust-section {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-top: 0.5rem;
    animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

.inline-adjust-connector {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-bottom: 0.5rem;
}

.connector-line {
    position: relative;
    height: 3rem;
    border-left: 2px dotted var(--md-sys-color-outline);
    display: flex;
    flex-direction: column;
    align-items: center;
}

.connector-branch {
    position: absolute;
    top: 0.625rem;
    left: 0;
    height: 0.75rem;
    width: 1.125rem;
    border-left: 2px dotted var(--md-sys-color-outline);
    border-bottom: 2px dotted var(--md-sys-color-outline);
    border-bottom-left-radius: 0.5rem;
}

.connector-icon {
    color: var(--md-sys-color-on-surface-variant);
    margin-top: 0.375rem;
    margin-left: 1.25rem;
}

.connector-btn {
    margin-top: 0.25rem;
    margin-left: 1rem;
    color: var(--md-sys-color-on-surface-variant) !important;
    background: var(--md-sys-color-surface-container) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.connector-btn:hover {
    color: var(--md-sys-color-primary) !important;
    background: var(--md-sys-color-primary-container) !important;
}

/* === Suggestion Hint Row (吹き出し風) === */
.suggestion-hint-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 1rem 0 0.75rem 0;
    padding: 0.5rem 0.75rem;
    background: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-full);
    max-width: fit-content;
}

.suggestion-hint-icon {
    color: var(--md-sys-color-primary);
    font-size: 1.25rem !important;
}

.retry-btn {
    color: var(--md-sys-color-on-surface-variant) !important;
    background: var(--md-sys-color-surface) !important;
    border-radius: var(--md-sys-shape-corner-full) !important;
    padding: 0.375rem 0.75rem !important;
    font-size: 0.875rem !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.retry-btn:hover {
    color: var(--md-sys-color-primary) !important;
    background: var(--md-sys-color-primary-container) !important;
}

.inline-adjust-panel {
    max-width: 24rem;
    width: 100%;
    background: var(--md-sys-color-surface);
    border-radius: var(--md-sys-shape-corner-xl);
    padding: 0.75rem;
    box-shadow: var(--md-sys-elevation-1);
}

.adjust-option-row {
    display: flex;
    align-items: center;
    background: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-medium);
    overflow: hidden;
}

.adjust-option-btn {
    flex: 1;
    padding: 0.75rem 0.875rem !important;
    font-size: 0.9375rem !important;
    color: var(--md-sys-color-on-surface) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
    border-radius: var(--md-sys-shape-corner-medium) !important;
}

.adjust-option-btn:hover {
    background: var(--md-sys-color-surface-container-high) !important;
}

.adjust-option-divider {
    width: 2.5px;
    height: 1.375rem;
    background: var(--md-sys-color-outline-variant);
    border-radius: 1px;
}

.adjust-option-btn-full {
    width: 100%;
    padding: 0.625rem 0.875rem !important;
    font-size: 0.9375rem !important;
    color: var(--md-sys-color-on-surface) !important;
    background: var(--md-sys-color-surface-container) !important;
    border-radius: var(--md-sys-shape-corner-medium) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
    text-align: left !important;
    justify-content: flex-start !important;
}

.adjust-option-btn-full:hover {
    background: var(--md-sys-color-surface-container-high) !important;
}

/* === Inline Question Section === */
.inline-question-section {
    max-width: 24rem;
    width: 100%;
    margin-top: 1rem;
    background: var(--md-sys-color-surface);
    border-radius: var(--md-sys-shape-corner-xl);
    padding: 0.625rem;
    box-shadow: var(--md-sys-elevation-1);
}

.quick-chip {
    font-size: 0.9375rem !important;
    padding: 0.375rem 0.75rem !important;
    border: 1px solid var(--md-sys-color-outline-variant) !important;
    border-radius: var(--md-sys-shape-corner-small) !important;
    color: var(--md-sys-color-on-surface-variant) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.quick-chip:hover {
    border-color: var(--md-sys-color-outline) !important;
    color: var(--md-sys-color-on-surface) !important;
}

.question-input {
    font-size: 1rem !important;
}

.question-input .q-field__control {
    border-radius: var(--md-sys-shape-corner-xl) !important;
}

.send-question-btn {
    background: var(--md-sys-color-primary) !important;
    color: var(--md-sys-color-on-primary) !important;
    width: var(--md-comp-icon-button-size) !important;
    height: var(--md-comp-icon-button-size) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.send-question-btn:hover {
    background: linear-gradient(rgba(255,255,255,0.08), rgba(255,255,255,0.08)), var(--md-sys-color-primary) !important;
    box-shadow: var(--md-sys-elevation-1) !important;
}

.send-question-btn:active {
    background: linear-gradient(rgba(255,255,255,0.12), rgba(255,255,255,0.12)), var(--md-sys-color-primary) !important;
}

.send-question-btn:disabled {
    background: rgba(27, 27, 31, 0.12) !important;
    color: rgba(27, 27, 31, 0.38) !important;
}

/* === Back-translate Button (M3 Text Button) === */
.back-translate-btn {
    height: var(--md-comp-button-height) !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
    padding: 0 0.75rem !important;
    color: var(--md-sys-color-primary) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.back-translate-btn:hover {
    background: rgba(67, 85, 185, 0.08) !important;
}

.back-translate-btn:active {
    background: rgba(67, 85, 185, 0.12) !important;
}

.back-translate-btn .q-icon {
    margin-right: 0.25rem;
}

/* === Elapsed Time Badge === */
.elapsed-time-badge {
    font-size: 0.9375rem;
    color: var(--md-sys-color-on-surface-variant);
    background: var(--md-sys-color-surface-container);
    padding: 0.25rem 0.625rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-weight: 500;
}

/* === Explain More Button (Nani-inspired) === */
.explain-more-section {
    margin-top: 1rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--md-sys-color-outline-variant);
    display: flex;
    justify-content: center;
}

.explain-more-btn {
    height: var(--md-comp-button-height) !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
    color: var(--md-sys-color-primary) !important;
    padding: 0 var(--md-comp-button-padding-x) !important;
    border-radius: var(--md-sys-shape-corner-full) !important;
    background: transparent !important;
    border: 1px solid var(--md-sys-color-outline) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.explain-more-btn:hover {
    background: rgba(67, 85, 185, 0.08) !important;
}

.explain-more-btn:active {
    background: rgba(67, 85, 185, 0.12) !important;
}

.explain-more-btn .q-icon {
    color: var(--md-sys-color-primary);
    margin-right: 0.25rem;
}

/* === Settings Button (M3 Icon Button) === */
.settings-btn {
    width: var(--md-comp-icon-button-size) !important;
    height: var(--md-comp-icon-button-size) !important;
    color: var(--md-sys-color-on-surface-variant) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.settings-btn:hover {
    background: rgba(67, 85, 185, 0.08) !important;
    color: var(--md-sys-color-primary) !important;
}

.settings-btn:active {
    background: rgba(67, 85, 185, 0.12) !important;
}

/* === Settings Dialog === */
.settings-dialog {
    border-radius: var(--md-sys-shape-corner-large) !important;
}

.settings-dialog .q-slider {
    margin-top: 0.25rem;
}

.settings-dialog .q-slider__track {
    background: var(--md-sys-color-surface-container-highest) !important;
}

.settings-dialog .q-slider__thumb {
    background: var(--md-sys-color-primary) !important;
}

.settings-dialog .q-slider__inner {
    background: var(--md-sys-color-primary) !important;
}

/* Copy success feedback animation */
.copy-success {
    animation: copyPulse 400ms var(--md-sys-motion-easing-spring);
}

@keyframes copyPulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.2); color: var(--md-sys-color-success); }
    100% { transform: scale(1); }
}

/* === Skeleton Loading (Nani-inspired) === */
.skeleton {
    background: linear-gradient(
        90deg,
        var(--md-sys-color-surface-container) 25%,
        var(--md-sys-color-surface-container-high) 50%,
        var(--md-sys-color-surface-container) 75%
    );
    background-size: 200% 100%;
    animation: skeletonShimmer 1.5s infinite;
    border-radius: var(--md-sys-shape-corner-medium);
}

.skeleton-text {
    height: 1rem;
    margin-bottom: 0.5rem;
}

.skeleton-text-sm {
    height: 0.75rem;
    width: 60%;
}

@keyframes skeletonShimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

/* === Textarea Placeholder Animation === */
.main-card-inner textarea::placeholder {
    transition: opacity var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.main-card-inner textarea:focus::placeholder {
    opacity: 0.5;
}

/* === Icon Button Hover Glow === */
.nani-toolbar-btn:hover {
    opacity: 1;
    background: var(--md-sys-color-surface-container) !important;
}

/* === Success Confetti-style Animation === */
.success-bounce {
    animation: successBounce 600ms var(--md-sys-motion-easing-spring);
}

@keyframes successBounce {
    0% { transform: scale(0.8); opacity: 0; }
    50% { transform: scale(1.1); }
    100% { transform: scale(1); opacity: 1; }
}

/* === Tooltip Fade In === */
.q-tooltip {
    animation: fadeIn 150ms var(--md-sys-motion-easing-standard) !important;
}

/* === Custom Scrollbar (Nani-inspired) === */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-full);
    border: 2px solid transparent;
    background-clip: content-box;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--md-sys-color-outline);
    background-clip: content-box;
}

/* Firefox scrollbar */
* {
    scrollbar-width: thin;
    scrollbar-color: var(--md-sys-color-outline-variant) transparent;
}

/* === Text Selection (Brand Color) === */
::selection {
    background: rgba(67, 85, 185, 0.2);
    color: inherit;
}

::-moz-selection {
    background: rgba(67, 85, 185, 0.2);
    color: inherit;
}

/* === Input Caret Color === */
input, textarea {
    caret-color: var(--md-sys-color-primary);
}

/* === Custom Checkbox Style === */
.q-checkbox__inner {
    color: var(--md-sys-color-outline) !important;
}

.q-checkbox__inner--truthy {
    color: var(--md-sys-color-primary) !important;
}

.q-checkbox__bg {
    border-radius: 6px !important;
}

/* === Focus Ring Enhancement === */
*:focus-visible {
    outline: 2px solid var(--md-sys-color-primary);
    outline-offset: 2px;
}

button:focus-visible,
.q-btn:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px rgba(67, 85, 185, 0.2) !important;
}

/* === Link Hover Effect === */
a {
    color: var(--md-sys-color-primary);
    text-decoration: none;
    transition: color var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

a:hover {
    color: #5A6AC9;
    text-decoration: underline;
}

/* === Smooth Page Transitions === */
.page-transition-enter {
    opacity: 0;
    transform: translateX(20px);
}

.page-transition-enter-active {
    opacity: 1;
    transform: translateX(0);
    transition: all 300ms var(--md-sys-motion-easing-standard);
}

.page-transition-leave {
    opacity: 1;
    transform: translateX(0);
}

.page-transition-leave-active {
    opacity: 0;
    transform: translateX(-20px);
    transition: all 300ms var(--md-sys-motion-easing-standard);
}

/* === M3 Warning Color Utilities === */
.bg-warning {
    background-color: var(--md-sys-color-warning) !important;
}

.bg-warning-container {
    background-color: var(--md-sys-color-warning-container) !important;
}

.text-warning {
    color: var(--md-sys-color-warning) !important;
}

.text-on-warning {
    color: var(--md-sys-color-on-warning) !important;
}

.text-on-warning-container {
    color: var(--md-sys-color-on-warning-container) !important;
}

.border-warning {
    border-color: var(--md-sys-color-warning) !important;
}

/* Warning banner */
.warning-banner {
    background-color: var(--md-sys-color-warning);
    color: var(--md-sys-color-on-warning);
}

/* Primary banner (for update notifications) */
.primary-banner {
    background-color: var(--md-sys-color-primary);
    color: var(--md-sys-color-on-primary);
}

/* Warning container box */
.warning-box {
    background-color: var(--md-sys-color-warning-container);
    border: 1px solid var(--md-sys-color-warning);
    border-radius: var(--md-sys-shape-corner-large);
    padding: 0.75rem;
}

/* === M3 Surface Utilities === */
.bg-surface {
    background-color: var(--md-sys-color-surface) !important;
}

.bg-surface-container {
    background-color: var(--md-sys-color-surface-container) !important;
}

.bg-surface-container-high {
    background-color: var(--md-sys-color-surface-container-high) !important;
}

.text-on-surface {
    color: var(--md-sys-color-on-surface) !important;
}

.text-on-surface-variant {
    color: var(--md-sys-color-on-surface-variant) !important;
}

/* Dialog section background */
.dialog-section {
    background-color: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-large);
    padding: 0.75rem;
}

/* === File Panel Checkbox === */
.pdf-mode-checkbox {
    font-size: 1rem;
}

.pdf-mode-checkbox .q-checkbox__label {
    color: var(--md-sys-color-on-surface-variant);
}

/* === M3 File Type Icon Backgrounds === */
.file-icon-excel {
    background-color: rgba(33, 115, 70, 0.08);
    color: #217346;
}

.file-icon-word {
    background-color: rgba(43, 87, 154, 0.08);
    color: #2B579A;
}

.file-icon-powerpoint {
    background-color: rgba(210, 71, 38, 0.08);
    color: #D24726;
}

.file-icon-pdf {
    background-color: rgba(244, 15, 2, 0.08);
    color: #F40F02;
}

.file-icon-default {
    background-color: rgba(102, 102, 102, 0.08);
    color: #666666;
}

/* === Duration Badge === */
.duration-badge {
    font-size: 0.8125rem;
    padding: 0.125rem 0.5rem;
    border-radius: var(--md-sys-shape-corner-full);
    background-color: var(--md-sys-color-surface-container-high);
    color: var(--md-sys-color-on-surface-variant);
    width: fit-content;
}

/* === Completion Dialog Styles === */
.completion-file-row {
    width: 100%;
    padding: 0.75rem;
    background-color: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-medium);
}

.completion-file-icon {
    font-size: 1.125rem;
    color: var(--md-sys-color-on-surface-variant);
}

.completion-file-name {
    font-size: 1rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
}

.completion-file-desc {
    font-size: 0.9375rem;
    color: var(--md-sys-color-on-surface-variant);
}

/* === Loading Screen === */
.loading-screen {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: var(--md-sys-color-surface);
    z-index: 9999;
}

.loading-title {
    margin-top: 1rem;
    font-size: 1.5rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
    letter-spacing: 0.02em;
}
"""
