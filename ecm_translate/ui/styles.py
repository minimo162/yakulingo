# ecm_translate/ui/styles.py
"""
M3 Expressive-inspired styles for YakuLingo.
Simple, practical, emotionally resonant design.
"""

COMPLETE_CSS = """
/* === M3 Expressive Design Tokens === */
:root {
    /* Warm, friendly primary - coral/peach tones */
    --primary: #E07B54;
    --primary-container: #FFDAD1;
    --on-primary: #FFFFFF;
    --on-primary-container: #3A0B00;

    /* Surface colors - warm neutrals */
    --surface: #FFFBFF;
    --surface-container: #F5EDE8;
    --surface-container-high: #EFE6E1;
    --on-surface: #201A17;
    --on-surface-variant: #53433E;

    /* Accent colors */
    --secondary: #77574D;
    --tertiary: #6C5D2F;
    --success: #3D6B4D;
    --error: #BA1A1A;

    /* Expressive motion - spring physics */
    --motion-spring: cubic-bezier(0.2, 0, 0, 1);
    --motion-bounce: cubic-bezier(0.34, 1.56, 0.64, 1);
    --duration-short: 200ms;
    --duration-medium: 350ms;
    --duration-long: 500ms;

    /* Expressive shapes */
    --radius-sm: 12px;
    --radius-md: 16px;
    --radius-lg: 28px;
    --radius-full: 9999px;

    /* Elevation */
    --shadow-1: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
    --shadow-2: 0 4px 8px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.06);
}

/* Dark theme - cozy warmth */
@media (prefers-color-scheme: dark) {
    :root {
        --primary: #FFB5A0;
        --primary-container: #6B2B17;
        --on-primary: #5D1900;
        --on-primary-container: #FFDAD1;

        --surface: #1A1110;
        --surface-container: #271E1C;
        --surface-container-high: #322824;
        --on-surface: #F1DFDA;
        --on-surface-variant: #D8C2BB;

        --secondary: #E7BDB2;
        --tertiary: #D9C68D;
    }
}

/* === Spring Keyframes === */
@keyframes springIn {
    0% { opacity: 0; transform: scale(0.9) translateY(8px); }
    60% { transform: scale(1.02) translateY(-2px); }
    100% { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes gentlePulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

@keyframes springBounce {
    0% { transform: scale(1); }
    40% { transform: scale(1.08); }
    100% { transform: scale(1); }
}

/* === Base === */
body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Meiryo UI', sans-serif;
    background: var(--surface);
    color: var(--on-surface);
}

/* === Header - Clean & Minimal === */
.app-header {
    background: var(--surface);
    border-bottom: 1px solid var(--surface-container);
}

.app-logo {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--primary);
    letter-spacing: -0.02em;
}

/* === Tabs - Pill Style === */
.tab-btn {
    padding: 0.5rem 1rem;
    color: var(--on-surface-variant);
    font-weight: 500;
    font-size: 0.875rem;
    border-radius: var(--radius-full);
    transition: all var(--duration-short) var(--motion-spring);
}

.tab-btn:hover {
    background: var(--surface-container);
}

.tab-btn.active {
    background: var(--primary-container);
    color: var(--on-primary-container);
}

/* === Text Areas - Soft Container === */
.text-box {
    background: var(--surface);
    border: 1.5px solid var(--surface-container-high);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: all var(--duration-medium) var(--motion-spring);
    animation: springIn var(--duration-medium) var(--motion-spring);
}

.text-box:focus-within {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(224, 123, 84, 0.15);
}

.text-label {
    padding: 0.75rem 1rem;
    background: var(--surface-container);
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--on-surface-variant);
    letter-spacing: 0.02em;
}

/* === Primary Button - Expressive === */
.btn-primary {
    background: var(--primary);
    color: var(--on-primary);
    padding: 0.875rem 2rem;
    border-radius: var(--radius-full);
    font-weight: 600;
    font-size: 0.9375rem;
    letter-spacing: 0.01em;
    box-shadow: var(--shadow-1);
    transition: all var(--duration-short) var(--motion-spring);
}

.btn-primary:hover:not(:disabled) {
    box-shadow: var(--shadow-2);
    transform: translateY(-1px);
}

.btn-primary:active:not(:disabled) {
    transform: scale(0.98);
}

.btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* === Secondary Button === */
.btn-outline {
    background: transparent;
    border: 1.5px solid var(--surface-container-high);
    color: var(--on-surface);
    padding: 0.75rem 1.5rem;
    border-radius: var(--radius-full);
    font-weight: 500;
    transition: all var(--duration-short) var(--motion-spring);
}

.btn-outline:hover {
    background: var(--surface-container);
    border-color: var(--on-surface-variant);
}

/* === Swap Button - Playful === */
.swap-btn {
    width: 2.75rem;
    height: 2.75rem;
    border-radius: var(--radius-full);
    background: var(--surface-container);
    border: none;
    color: var(--on-surface-variant);
    transition: all var(--duration-medium) var(--motion-bounce);
}

.swap-btn:hover {
    background: var(--primary-container);
    color: var(--on-primary-container);
    transform: rotate(180deg);
}

/* === Drop Zone - Inviting === */
.drop-zone {
    border: 2px dashed var(--surface-container-high);
    border-radius: var(--radius-lg);
    padding: 3rem 2rem;
    text-align: center;
    transition: all var(--duration-medium) var(--motion-spring);
    cursor: pointer;
    background: var(--surface);
}

.drop-zone:hover {
    border-color: var(--primary);
    background: var(--primary-container);
}

.drop-zone-icon {
    font-size: 2.5rem;
    color: var(--primary);
    margin-bottom: 0.75rem;
}

.drop-zone-text {
    font-size: 1rem;
    font-weight: 500;
    color: var(--on-surface);
}

.drop-zone-hint {
    font-size: 0.8125rem;
    color: var(--on-surface-variant);
    margin-top: 0.25rem;
}

/* === File Card === */
.file-card {
    background: var(--surface-container);
    border: none;
    border-radius: var(--radius-lg);
    padding: 1.25rem;
    animation: springIn var(--duration-medium) var(--motion-spring);
}

.file-card.success {
    background: linear-gradient(135deg, #E8F5E9 0%, #C8E6C9 100%);
}

/* === Progress === */
.progress-track {
    height: 6px;
    background: var(--surface-container-high);
    border-radius: var(--radius-full);
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: var(--primary);
    border-radius: var(--radius-full);
    transition: width var(--duration-medium) var(--motion-spring);
}

/* === Status Dot === */
.status-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-full);
    background: var(--on-surface-variant);
}

.status-dot.connected {
    background: var(--success);
}

.status-dot.connecting {
    background: var(--primary);
    animation: gentlePulse 1.5s ease infinite;
}

/* === Success State === */
.success-icon {
    font-size: 3rem;
    color: var(--success);
    animation: springBounce var(--duration-long) var(--motion-bounce);
}

.success-text {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--success);
}

/* === Utility === */
.text-primary { color: var(--primary); }
.text-success { color: var(--success); }
.text-error { color: var(--error); }
.text-muted { color: var(--on-surface-variant); }

.animate-in { animation: springIn var(--duration-medium) var(--motion-spring); }

/* === Chip/Badge === */
.chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem 0.75rem;
    background: var(--surface-container);
    border-radius: var(--radius-full);
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--on-surface-variant);
}

/* === Dialog === */
.q-card {
    border-radius: var(--radius-lg) !important;
}

.q-dialog__backdrop {
    background: rgba(0, 0, 0, 0.3) !important;
    backdrop-filter: blur(4px);
}
"""
