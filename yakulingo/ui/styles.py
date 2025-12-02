# yakulingo/ui/styles.py
"""
M3 Component-based styles for YakuLingo.
Nani-inspired sidebar layout with clean, minimal design.
"""

COMPLETE_CSS = """
/* === M3 Design Tokens === */
:root {
    /* Primary - warm coral */
    --md-sys-color-primary: #C04000;
    --md-sys-color-on-primary: #FFFFFF;
    --md-sys-color-primary-container: #FFEEE8;
    --md-sys-color-on-primary-container: #390C00;

    /* Surface - Nani-inspired warm light palette */
    --md-sys-color-surface: #FFFFFF;
    --md-sys-color-surface-dim: #FFF9F5;
    --md-sys-color-surface-container: #FFF5F0;
    --md-sys-color-surface-container-high: #FFEDE5;
    --md-sys-color-surface-container-highest: #FFE5DA;
    --md-sys-color-on-surface: #1A1C1E;
    --md-sys-color-on-surface-variant: #4A4D50;  /* Darker for better contrast */
    --md-sys-color-outline: #8A7A72;  /* Darker for better visibility */
    --md-sys-color-outline-variant: #E8DED8;

    /* States */
    --md-sys-color-error: #BA1A1A;
    --md-sys-color-on-error: #FFFFFF;
    --md-sys-color-error-container: #FFDAD6;
    --md-sys-color-on-error-container: #410002;

    /* Success (extended) */
    --md-sys-color-success: #2E7D32;
    --md-sys-color-on-success: #FFFFFF;
    --md-sys-color-success-container: #C8E6C9;
    --md-sys-color-on-success-container: #1B5E20;

    /* Warning (extended) */
    --md-sys-color-warning: #FF9800;
    --md-sys-color-on-warning: #FFFFFF;
    --md-sys-color-warning-container: #FFF3E0;
    --md-sys-color-on-warning-container: #E65100;

    /* Shape - Nani-inspired extra rounded corners */
    --md-sys-shape-corner-full: 9999px;
    --md-sys-shape-corner-3xl: 32px;   /* Extra large cards */
    --md-sys-shape-corner-2xl: 28px;   /* Large rounded cards */
    --md-sys-shape-corner-xl: 24px;    /* Main cards */
    --md-sys-shape-corner-large: 20px; /* Cards, dialogs */
    --md-sys-shape-corner-medium: 16px; /* Buttons, inputs */
    --md-sys-shape-corner-small: 12px;  /* Chips, small elements */

    /* Typography - font size hierarchy */
    --md-sys-typescale-size-xs: 0.8125rem;    /* 13px - minimum, captions, badges */
    --md-sys-typescale-size-sm: 0.875rem;     /* 14px - labels, buttons */
    --md-sys-typescale-size-md: 0.9375rem;    /* 15px - body text */
    --md-sys-typescale-size-lg: 1rem;         /* 16px - subheadings */
    --md-sys-typescale-size-xl: 1.25rem;      /* 20px - headings */
    --md-sys-typescale-size-2xl: 1.5rem;      /* 24px - large headings */

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
    --sidebar-width: 280px;
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
    /* Nani-inspired gradient background with subtle pattern */
    background:
        radial-gradient(circle at 20% 20%, rgba(192, 64, 0, 0.03) 0%, transparent 50%),
        radial-gradient(circle at 80% 80%, rgba(255, 150, 100, 0.03) 0%, transparent 50%),
        radial-gradient(circle, rgba(192,64,0,0.015) 1px, transparent 1px),
        linear-gradient(180deg, #FFFBF8 0%, #FFF5EE 100%);
    background-size: 100% 100%, 100% 100%, 20px 20px, 100% 100%;
    background-attachment: fixed;
    color: var(--md-sys-color-on-surface);
    font-size: 0.9375rem;  /* 15px - comfortable reading size */
    line-height: 1.6;
    margin: 0;
    padding: 0;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* === Sidebar Layout === */
.sidebar {
    width: var(--sidebar-width);
    height: 100vh;
    position: fixed;
    left: 0;
    top: 0;
    /* Nani-inspired subtle gradient sidebar */
    background: linear-gradient(180deg, #FFFFFF 0%, #FFFAF7 100%);
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

.main-area {
    margin-left: var(--sidebar-width);
    flex: 1;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
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
    /* Nani-inspired vibrant gradient */
    background: linear-gradient(135deg, #E84A00 0%, #FF6B35 50%, #C04000 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--md-sys-color-on-primary);
    box-shadow:
        0 4px 12px rgba(232, 74, 0, 0.3),
        0 2px 4px rgba(0, 0, 0, 0.1);
}

/* === Navigation === */
.sidebar-nav {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin-top: 0.5rem;
}

.nav-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    border-radius: var(--md-sys-shape-corner-large);
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface-variant);
    width: 100%;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard) backwards;
}

/* Staggered nav item animations */
.nav-item:nth-child(1) { animation-delay: 50ms; }
.nav-item:nth-child(2) { animation-delay: 100ms; }
.nav-item:nth-child(3) { animation-delay: 150ms; }

.nav-item:hover {
    background: var(--md-sys-color-surface-container);
    color: var(--md-sys-color-on-surface);
}

.nav-item.active {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
}

.nav-item.disabled {
    opacity: 0.5;
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
    padding: 0.3rem 0.75rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.8125rem;  /* 13px - better readability */
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
    box-shadow: 0 0 0 3px rgba(192, 64, 0, 0.08);
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
    box-shadow: 0 0 0 2px rgba(192, 64, 0, 0.15);
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
    background: transparent;
    border: 1.5px solid var(--md-sys-color-outline-variant);
    color: var(--md-sys-color-on-surface);
    padding: 0.625rem 1.25rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.btn-outline:hover {
    background: var(--md-sys-color-surface-container);
    border-color: var(--md-sys-color-outline);
    transform: translateY(-1px);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

/* === M3 Filled Button (Primary) === */
/* .translate-btn is an alias for backward compatibility */
.btn-primary,
.translate-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    background: var(--md-sys-color-on-surface);
    color: var(--md-sys-color-surface);
    padding: 0.875rem 1.5rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.9375rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    border: none;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

.btn-primary:hover:not(:disabled),
.translate-btn:hover:not(:disabled) {
    /* Lighter shade derived from on-surface (#1A1C1E → #2D3035) */
    background: color-mix(in srgb, var(--md-sys-color-on-surface) 85%, white);
    transform: translateY(-2px) scale(1.02);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

.btn-primary:disabled,
.translate-btn:disabled {
    background: var(--md-sys-color-outline);
    cursor: default;
    box-shadow: none;
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

/* Hide default Quasar uploader header/controls */
.drop-zone .q-uploader__header,
.drop-zone .q-uploader__list {
    display: none !important;
}

/* Make q-uploader fill the drop-zone */
.drop-zone .q-uploader {
    width: 100% !important;
    min-height: auto !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

.drop-zone:hover {
    border-color: var(--md-sys-color-primary);
    background: var(--md-sys-color-primary-container);
    transform: scale(1.02);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

/* Visual click hint - Gradio style */
.drop-zone::after {
    content: 'クリック または ドラッグ＆ドロップ';
    position: absolute;
    bottom: 0.75rem;
    left: 50%;
    transform: translateX(-50%);
    font-size: 0.6875rem;
    color: var(--md-sys-color-outline);
    opacity: 0;
    transition: opacity var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.drop-zone:hover::after {
    opacity: 1;
}

.drop-zone-icon {
    font-size: 2.5rem;
    color: var(--md-sys-color-on-surface-variant);
    margin-bottom: 0.75rem;
    transition: transform var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-spring);
}

.drop-zone:hover .drop-zone-icon {
    transform: translateY(-4px);
    color: var(--md-sys-color-primary);
}

.drop-zone-text {
    font-size: 0.9375rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
}

.drop-zone-hint {
    font-size: 0.8125rem;  /* 13px - improved readability */
    color: var(--md-sys-color-on-surface-variant);
    margin-top: 0.25rem;
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
    /* Nani-inspired vibrant progress gradient */
    background: linear-gradient(90deg, #E84A00 0%, #FF6B35 50%, #FF8C42 100%);
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
    padding: 0.375rem 0.75rem;
    background: var(--md-sys-color-surface-container-high);
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.8125rem;  /* 13px - minimum readable size */
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
    line-height: 1.65;
    word-break: break-word;
    font-size: 0.9375rem;
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
    font-size: 0.8125rem;  /* 13px - improved readability */
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
.text-2xs { font-size: 0.8125rem; }  /* 13px - minimum readable size */

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

/* === Responsive Design === */
@media (max-width: 1024px) {
    :root {
        --sidebar-width: 240px;
    }
}

@media (max-width: 768px) {
    :root {
        --sidebar-width: 100%;
    }

    .main-area {
        margin-left: 0;
    }

    .sidebar {
        width: 100%;
        height: auto;
        position: relative;
        border-right: none;
        border-bottom: 1px solid var(--md-sys-color-outline-variant);
        padding: 0.75rem;
    }

    .sidebar-header {
        padding: 0.25rem 0.5rem 0.5rem;
    }

    .sidebar-nav {
        flex-direction: row;
        gap: 0.5rem;
        margin-top: 0.25rem;
    }

    .nav-item {
        flex: 1;
        justify-content: center;
        padding: 0.5rem 0.75rem;
    }

    .sidebar-history {
        display: flex;
        flex-direction: row;
        min-height: auto;
        overflow: hidden;
        padding: 0.5rem 0;
    }

    .sidebar-history > .items-center {
        display: none;  /* Hide header on mobile */
    }

    .history-scroll {
        max-height: 80px;
        overflow-x: auto;
        overflow-y: hidden;
    }

    .history-scroll > .column {
        flex-direction: row;
        gap: 0.5rem;
        padding: 0 0.5rem;
    }

    .history-item {
        flex-shrink: 0;
        max-width: 150px;
        padding: 0.5rem;
        background: var(--md-sys-color-surface-container);
        border-radius: var(--md-sys-shape-corner-small);
    }

    .history-item .column {
        max-width: 120px;
    }

    .history-delete-btn {
        display: none;  /* Hide delete on mobile for space */
    }

    /* Improve touch targets on mobile */
    .btn-primary,
    .translate-btn,
    .btn-outline {
        min-height: 44px;
        padding: 0.75rem 1.25rem;
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

/* === Language Selector (Segmented Button) === */
.language-selector {
    display: inline-flex;
    background: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-full);
    padding: 4px;
    gap: 0;
}

.lang-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface-variant);
    background: transparent;
    border: none;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    cursor: pointer;
}

.lang-btn-left {
    border-radius: var(--md-sys-shape-corner-full) 0 0 var(--md-sys-shape-corner-full);
}

.lang-btn-right {
    border-radius: 0 var(--md-sys-shape-corner-full) var(--md-sys-shape-corner-full) 0;
}

.lang-btn:hover:not(.lang-btn-active) {
    background: var(--md-sys-color-surface-container-high);
}

.lang-btn-active {
    background: var(--md-sys-color-surface);
    color: var(--md-sys-color-on-surface);
    box-shadow: var(--md-sys-elevation-1);
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
    font-size: 0.875rem;
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
    font-size: 1rem;
    line-height: 1.5;
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
    padding: 0.875rem;
    margin-top: 0.25rem;
    color: var(--md-sys-color-on-primary-container);
    border-radius: 1rem;
    font-size: 0.875rem;
    line-height: 1.85;
}

.nani-explanation ul {
    margin: 0;
    padding-left: 1.25rem;
}

.nani-explanation li {
    margin-bottom: 0.25rem;
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
    padding: 0.75rem 0;
}

.follow-up-btn {
    font-size: 0.8125rem !important;
    padding: 0.625rem 1rem !important;
    border-color: var(--md-sys-color-outline-variant) !important;
    color: var(--md-sys-color-on-surface-variant) !important;
    border-radius: var(--md-sys-shape-corner-full) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.follow-up-btn:hover {
    background: var(--md-sys-color-surface-container-high) !important;
    border-color: var(--md-sys-color-outline) !important;
    color: var(--md-sys-color-on-surface) !important;
    transform: translateY(-1px) !important;
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
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
}

.loading-character .submessage {
    font-size: 0.8125rem;
    color: var(--md-sys-color-on-surface-variant);
}

/* Streaming content display */
.streaming-content {
    width: 100%;
    max-width: 600px;
    opacity: 1;
    transform: translateY(0);
    transition: opacity 0.2s ease-out, transform 0.2s ease-out;
}

.streaming-content[style*="display: none"] {
    opacity: 0;
    transform: translateY(-8px);
}

.streaming-text-box {
    background: var(--md-sys-color-surface-container-low);
    border-radius: var(--md-sys-shape-corner-medium);
    padding: 1rem;
    max-height: 300px;
    overflow-y: auto;
    border: 1px solid var(--md-sys-color-outline-variant);
}

.streaming-text {
    font-size: 0.875rem;
    line-height: 1.6;
    color: var(--md-sys-color-on-surface);
    white-space: pre-wrap;
    word-break: break-word;
}

.streaming-status-label {
    opacity: 0.7;
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
    font-size: 0.8125rem;
    color: var(--md-sys-color-on-surface-variant);
}

/* Hint section improvements */
.hint-section {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 0;
}

.hint-primary {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--md-sys-color-on-surface-variant);
    font-size: 0.8125rem;
}

.hint-secondary {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    color: var(--md-sys-color-on-surface-variant);
    opacity: 0.6;
    font-size: 0.8125rem;
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

/* === Nani-style Attachment Button === */
.attach-btn {
    display: grid;
    place-items: center;
    width: 2.5rem;
    height: 2.5rem;
    border: 1.5px dashed var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-full);
    background: transparent;
    color: var(--md-sys-color-on-surface-variant);
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    flex-shrink: 0;
}

.attach-btn:hover {
    border-color: var(--md-sys-color-primary);
    color: var(--md-sys-color-primary);
    background: var(--md-sys-color-primary-container);
}

.attach-btn.has-file {
    border-style: solid;
    border-color: var(--md-sys-color-primary);
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
}

.attach-btn svg {
    width: 1.25rem;
    height: 1.25rem;
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
    padding: 0.625rem 0.75rem !important;
    font-size: 0.8125rem !important;
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
    padding: 0.5rem 0.75rem !important;
    font-size: 0.8125rem !important;
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
    font-size: 0.8125rem !important;
    padding: 0.25rem 0.625rem !important;
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
    font-size: 0.875rem !important;
}

.question-input .q-field__control {
    border-radius: var(--md-sys-shape-corner-xl) !important;
}

.send-question-btn {
    background: var(--md-sys-color-on-surface) !important;
    color: var(--md-sys-color-surface) !important;
    width: 2.375rem !important;
    height: 2.375rem !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.send-question-btn:hover {
    background: color-mix(in srgb, var(--md-sys-color-on-surface) 85%, white) !important;
    transform: translateY(-1px) !important;
}

.send-question-btn:disabled {
    background: var(--md-sys-color-outline) !important;
}

/* === Back-translate Button === */
.back-translate-btn {
    font-size: 0.8125rem !important;
    padding: 0.375rem 0.75rem !important;
    color: var(--md-sys-color-on-surface-variant) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.back-translate-btn:hover {
    color: var(--md-sys-color-primary) !important;
    background: var(--md-sys-color-primary-container) !important;
}

.back-translate-btn .q-icon {
    margin-right: 0.25rem;
}

/* === Elapsed Time Badge === */
.elapsed-time-badge {
    font-size: 0.8125rem;
    color: var(--md-sys-color-on-surface-variant);
    background: var(--md-sys-color-surface-container);
    padding: 0.125rem 0.5rem;
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
    font-size: 0.8125rem !important;
    color: var(--md-sys-color-primary) !important;
    padding: 0.5rem 1rem !important;
    border-radius: var(--md-sys-shape-corner-full) !important;
    background: transparent !important;
    border: 1px solid var(--md-sys-color-outline-variant) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.explain-more-btn:hover {
    background: var(--md-sys-color-primary-container) !important;
    border-color: var(--md-sys-color-primary) !important;
}

.explain-more-btn .q-icon {
    color: var(--md-sys-color-primary);
    margin-right: 0.25rem;
}

/* === Settings Button (Nani-inspired) === */
.settings-btn {
    color: var(--md-sys-color-on-surface-variant) !important;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard) !important;
}

.settings-btn:hover {
    color: var(--md-sys-color-primary) !important;
    background: var(--md-sys-color-primary-container) !important;
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

/* === Button Active States (Nani-inspired) === */
.btn-primary:active:not(:disabled),
.translate-btn:active:not(:disabled) {
    transform: translateY(0) scale(0.98) !important;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1) !important;
}

.btn-outline:active {
    transform: translateY(0) scale(0.98) !important;
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
    background: rgba(232, 74, 0, 0.2);
    color: inherit;
}

::-moz-selection {
    background: rgba(232, 74, 0, 0.2);
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
    box-shadow: 0 0 0 3px rgba(232, 74, 0, 0.2) !important;
}

/* === Link Hover Effect === */
a {
    color: var(--md-sys-color-primary);
    text-decoration: none;
    transition: color var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

a:hover {
    color: #E84A00;
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
    font-size: 0.875rem;
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
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
}

.completion-file-desc {
    font-size: 0.8125rem;
    color: var(--md-sys-color-on-surface-variant);
}
"""
