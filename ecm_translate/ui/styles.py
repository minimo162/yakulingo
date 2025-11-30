# ecm_translate/ui/styles.py
"""
M3 Component-based styles for YakuLingo.
Following Material Design 3 component guidelines.
"""

COMPLETE_CSS = """
/* === M3 Design Tokens === */
:root {
    /* Primary - warm coral */
    --md-sys-color-primary: #C04000;
    --md-sys-color-on-primary: #FFFFFF;
    --md-sys-color-primary-container: #FFDBD0;
    --md-sys-color-on-primary-container: #390C00;

    /* Surface */
    --md-sys-color-surface: #FFFBFF;
    --md-sys-color-surface-container: #F3EDE9;
    --md-sys-color-surface-container-high: #EDE7E3;
    --md-sys-color-on-surface: #201A17;
    --md-sys-color-on-surface-variant: #52443D;
    --md-sys-color-outline: #85746B;
    --md-sys-color-outline-variant: #D7C2B9;

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

    /* Shape */
    --md-sys-shape-corner-full: 9999px;
    --md-sys-shape-corner-large: 16px;
    --md-sys-shape-corner-medium: 12px;
    --md-sys-shape-corner-small: 8px;

    /* Motion - M3 standard easing */
    --md-sys-motion-easing-standard: cubic-bezier(0.2, 0, 0, 1);
    --md-sys-motion-duration-short: 200ms;
    --md-sys-motion-duration-medium: 300ms;

    /* Elevation */
    --md-sys-elevation-1: 0 1px 2px rgba(0,0,0,0.1);
    --md-sys-elevation-2: 0 2px 6px rgba(0,0,0,0.12);
}

/* === Base === */
body {
    font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
    background: var(--md-sys-color-surface);
    color: var(--md-sys-color-on-surface);
    line-height: 1.5;
}

/* === Header === */
.app-header {
    background: var(--md-sys-color-surface);
    border-bottom: 1px solid var(--md-sys-color-outline-variant);
}

.app-logo {
    font-size: 1.125rem;
    font-weight: 500;
    color: var(--md-sys-color-primary);
    letter-spacing: -0.01em;
}

/* === M3 Segmented Button (Tabs) === */
.tab-btn {
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
    border-radius: var(--md-sys-shape-corner-full);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.tab-btn:hover {
    background: var(--md-sys-color-surface-container);
}

.tab-btn.active {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
}

/* === M3 Filled Button (Primary) === */
.btn-primary {
    background: var(--md-sys-color-primary);
    color: var(--md-sys-color-on-primary);
    padding: 0.625rem 1.5rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    box-shadow: var(--md-sys-elevation-1);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.btn-primary:hover:not(:disabled) {
    box-shadow: var(--md-sys-elevation-2);
}

.btn-primary:disabled {
    opacity: 0.38;
    cursor: default;
}

/* === M3 Outlined Button === */
.btn-outline {
    background: transparent;
    border: 1px solid var(--md-sys-color-outline);
    color: var(--md-sys-color-primary);
    padding: 0.5rem 1.25rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.btn-outline:hover {
    background: var(--md-sys-color-primary-container);
}

/* === M3 Text Field Container === */
.text-box {
    background: var(--md-sys-color-surface);
    border: 1px solid var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-medium);
    overflow: hidden;
    transition: border-color var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.text-box:focus-within {
    border-color: var(--md-sys-color-primary);
    border-width: 2px;
}

.text-label {
    padding: 0.5rem 0.75rem;
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface-variant);
    background: var(--md-sys-color-surface-container);
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

/* === Swap Button === */
.swap-btn {
    width: 2.5rem;
    height: 2.5rem;
    border-radius: var(--md-sys-shape-corner-full);
    background: var(--md-sys-color-surface-container);
    border: none;
    color: var(--md-sys-color-on-surface-variant);
    transition: all var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

.swap-btn:hover {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
    transform: rotate(180deg);
}

/* === Drop Zone === */
.drop-zone {
    border: 1px dashed var(--md-sys-color-outline);
    border-radius: var(--md-sys-shape-corner-large);
    padding: 2.5rem 1.5rem;
    text-align: center;
    cursor: pointer;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.drop-zone:hover {
    border-color: var(--md-sys-color-primary);
    background: var(--md-sys-color-primary-container);
}

.drop-zone-icon {
    font-size: 2rem;
    color: var(--md-sys-color-on-surface-variant);
    margin-bottom: 0.5rem;
}

.drop-zone-text {
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--md-sys-color-on-surface);
}

.drop-zone-hint {
    font-size: 0.75rem;
    color: var(--md-sys-color-on-surface-variant);
    margin-top: 0.25rem;
}

/* === M3 Card === */
.file-card {
    background: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-medium);
    padding: 1rem;
}

.file-card.success {
    background: var(--md-sys-color-success-container);
}

/* === M3 Progress Indicator === */
.progress-track {
    height: 4px;
    background: var(--md-sys-color-surface-container-high);
    border-radius: 2px;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: var(--md-sys-color-primary);
    border-radius: 2px;
    transition: width var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

/* === Status === */
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

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
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

/* === Chip === */
.chip {
    display: inline-block;
    padding: 0.25rem 0.5rem;
    background: var(--md-sys-color-surface-container-high);
    border-radius: var(--md-sys-shape-corner-small);
    font-size: 0.6875rem;
    color: var(--md-sys-color-on-surface-variant);
}

/* === Utility === */
.text-muted { color: var(--md-sys-color-on-surface-variant); }
.text-primary { color: var(--md-sys-color-primary); }
.text-error { color: var(--md-sys-color-error); }

.animate-in {
    animation: fadeIn var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

/* === Dialog === */
.q-card {
    border-radius: var(--md-sys-shape-corner-large) !important;
}

.q-dialog__backdrop {
    background: rgba(0, 0, 0, 0.32) !important;
}

/* === Option Cards === */
.option-card {
    background: var(--md-sys-color-surface);
    border: 1px solid var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-medium);
    padding: 0.875rem;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.option-card:hover {
    border-color: var(--md-sys-color-primary);
    box-shadow: var(--md-sys-elevation-1);
}

.option-text {
    line-height: 1.6;
    word-break: break-word;
}

.option-action {
    opacity: 0.6;
    transition: opacity var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.option-card:hover .option-action {
    opacity: 1;
}

/* === Shortcut Hint === */
.shortcut-hint {
    opacity: 0.5;
    font-family: ui-monospace, monospace;
    font-size: 0.6875rem;
}

/* === History Button === */
.history-btn {
    color: var(--md-sys-color-on-surface-variant);
}

.history-btn:hover {
    background: var(--md-sys-color-surface-container);
}

/* === History Drawer === */
.history-drawer {
    background: var(--md-sys-color-surface);
    width: 320px !important;
}

.history-drawer .border-b {
    border-color: var(--md-sys-color-outline-variant);
}

/* === History Item === */
.history-item {
    background: var(--md-sys-color-surface-container);
    border-radius: var(--md-sys-shape-corner-small);
    padding: 0.75rem;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.history-item:hover {
    background: var(--md-sys-color-primary-container);
}
"""
