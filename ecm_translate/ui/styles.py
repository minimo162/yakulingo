# ecm_translate/ui/styles.py
"""
M3 Component-based styles for YakuLingo.
Inspired by Nani Translate's clean, minimal design.
"""

COMPLETE_CSS = """
/* === M3 Design Tokens === */
:root {
    /* Primary - warm coral */
    --md-sys-color-primary: #C04000;
    --md-sys-color-on-primary: #FFFFFF;
    --md-sys-color-primary-container: #FFDBD0;
    --md-sys-color-on-primary-container: #390C00;

    /* Surface - Nani-inspired light palette */
    --md-sys-color-surface: #FFFFFF;
    --md-sys-color-surface-dim: #F4F6F8;
    --md-sys-color-surface-container: #F0F2F4;
    --md-sys-color-surface-container-high: #E8EAEC;
    --md-sys-color-on-surface: #1A1C1E;
    --md-sys-color-on-surface-variant: #5C5F62;
    --md-sys-color-outline: #9CA3AF;
    --md-sys-color-outline-variant: #E5E7EB;

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

    /* Shape - more rounded corners */
    --md-sys-shape-corner-full: 9999px;
    --md-sys-shape-corner-xl: 24px;
    --md-sys-shape-corner-large: 16px;
    --md-sys-shape-corner-medium: 12px;
    --md-sys-shape-corner-small: 8px;

    /* Motion - M3 standard easing */
    --md-sys-motion-easing-standard: cubic-bezier(0.2, 0, 0, 1);
    --md-sys-motion-easing-spring: cubic-bezier(0.175, 0.885, 0.32, 1.275);
    --md-sys-motion-duration-short: 200ms;
    --md-sys-motion-duration-medium: 300ms;

    /* Elevation */
    --md-sys-elevation-1: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
    --md-sys-elevation-2: 0 4px 6px rgba(0,0,0,0.1), 0 2px 4px rgba(0,0,0,0.06);
}

/* === Base === */
body {
    font-family: system-ui, -apple-system, 'Segoe UI', 'Hiragino Sans', 'Meiryo', sans-serif;
    background-color: var(--md-sys-color-surface-dim);
    background-image: radial-gradient(circle, rgba(0,0,0,0.03) 1px, transparent 1px);
    background-size: 20px 20px;
    background-attachment: fixed;
    color: var(--md-sys-color-on-surface);
    line-height: 1.5;
}

/* === Header === */
.app-header {
    background: var(--md-sys-color-surface);
    border-bottom: 1px solid var(--md-sys-color-outline-variant);
    box-shadow: var(--md-sys-elevation-1);
}

.app-logo {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--md-sys-color-primary);
    letter-spacing: -0.02em;
}

.app-logo-icon {
    width: 2rem;
    height: 2rem;
    border-radius: var(--md-sys-shape-corner-small);
    background: var(--md-sys-color-primary);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--md-sys-color-on-primary);
    font-size: 1.25rem;
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
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.375rem;
    background: var(--md-sys-color-on-surface);
    color: var(--md-sys-color-surface);
    padding: 0.75rem 1.25rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.9375rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.btn-primary:hover:not(:disabled) {
    background: #374151;
}

.btn-primary:disabled {
    background: var(--md-sys-color-outline);
    cursor: default;
}

.btn-primary .arrow-icon {
    transform: rotate(90deg);
}

/* === Translate Button (Nani-style) === */
.translate-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.375rem;
    background: var(--md-sys-color-on-surface);
    color: var(--md-sys-color-surface);
    padding: 0.75rem 1.25rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.9375rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    border: none;
    cursor: pointer;
}

.translate-btn:hover:not(:disabled) {
    background: #374151;
}

.translate-btn:disabled {
    background: var(--md-sys-color-outline);
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

/* === Main Card Container (Nani-inspired) === */
.main-card {
    background: var(--md-sys-color-surface);
    border-radius: var(--md-sys-shape-corner-xl);
    box-shadow: var(--md-sys-elevation-1);
    padding: 0.375rem;
    overflow: hidden;
}

.main-card-inner {
    background: var(--md-sys-color-surface);
    border-radius: calc(var(--md-sys-shape-corner-xl) - 0.375rem);
    border: 1px solid var(--md-sys-color-outline-variant);
}

/* === M3 Text Field Container === */
.text-box {
    background: var(--md-sys-color-surface);
    border: 1px solid var(--md-sys-color-outline-variant);
    border-radius: var(--md-sys-shape-corner-xl);
    overflow: hidden;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.text-box:focus-within {
    border-color: var(--md-sys-color-primary);
    box-shadow: 0 0 0 1px var(--md-sys-color-primary);
}

.text-label {
    padding: 0.625rem 1rem;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--md-sys-color-on-surface-variant);
    background: transparent;
    letter-spacing: 0.02em;
}

/* === Language Switch Button (Nani-style) === */
.lang-switch-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.5rem 0.75rem;
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--md-sys-color-on-surface);
    background: transparent;
    border: none;
    border-radius: var(--md-sys-shape-corner-medium);
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
    cursor: pointer;
}

.lang-switch-btn:hover {
    background: var(--md-sys-color-surface-container);
}

.lang-switch-btn .icon {
    color: var(--md-sys-color-on-surface-variant);
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
.status-indicator {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.25rem 0.625rem;
    border-radius: var(--md-sys-shape-corner-full);
    font-size: 0.75rem;
    font-weight: 500;
    background: var(--md-sys-color-surface-container);
    color: var(--md-sys-color-on-surface-variant);
}

.status-indicator.connected {
    background: var(--md-sys-color-success-container);
    color: var(--md-sys-color-on-success-container);
}

.status-indicator.connecting {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
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
    border-radius: var(--md-sys-shape-corner-large);
    padding: 1rem;
    transition: all var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.option-card:hover {
    border-color: var(--md-sys-color-outline);
    box-shadow: var(--md-sys-elevation-1);
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
    border-radius: var(--md-sys-shape-corner-xl);
    box-shadow: var(--md-sys-elevation-1);
}

.result-header {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--md-sys-color-outline-variant);
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--md-sys-color-on-surface-variant);
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

/* === File Type Icon === */
.file-type-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 3rem;
    height: 3rem;
    border-radius: var(--md-sys-shape-corner-medium);
    flex-shrink: 0;
}

.file-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 200px;
}

/* === Chip Primary === */
.chip-primary {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
}

/* === Success Circle Animation === */
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

/* === Small Swap Button === */
.swap-btn-small {
    width: 2rem;
    height: 2rem;
    min-width: 2rem;
    min-height: 2rem;
    border-radius: var(--md-sys-shape-corner-full);
    background: var(--md-sys-color-surface-container);
    border: none;
    color: var(--md-sys-color-on-surface-variant);
    padding: 0;
    transition: all var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-standard);
}

.swap-btn-small:hover {
    background: var(--md-sys-color-primary-container);
    color: var(--md-sys-color-on-primary-container);
    transform: rotate(180deg);
}

/* === Direction Label === */
.direction-label {
    color: var(--md-sys-color-on-surface);
    letter-spacing: 0.01em;
}
"""
