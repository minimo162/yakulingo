# ecm_translate/ui/styles.py
"""
Emotional UI styles for YakuLingo.
Simple yet warm design that responds to user actions.
"""

COMPLETE_CSS = """
/* === Color Palette === */
:root {
    /* Warm, friendly primary colors */
    --primary: #6366f1;
    --primary-light: #818cf8;
    --primary-dark: #4f46e5;
    --primary-glow: rgba(99, 102, 241, 0.3);

    /* Warm accent for success moments */
    --success: #10b981;
    --success-light: #34d399;
    --success-glow: rgba(16, 185, 129, 0.3);

    /* Gentle warning/error */
    --warning: #f59e0b;
    --error: #ef4444;
    --error-light: #f87171;

    /* Soft backgrounds */
    --bg: #fafafa;
    --bg-warm: #fffbf5;
    --bg-card: #ffffff;
    --bg-elevated: #ffffff;

    /* Text hierarchy */
    --text: #1f2937;
    --text-secondary: #6b7280;
    --text-muted: #9ca3af;

    /* Borders and shadows */
    --border: #e5e7eb;
    --border-focus: #c7d2fe;
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    --shadow-glow: 0 0 20px var(--primary-glow);
}

/* Dark mode - cozy, not harsh */
@media (prefers-color-scheme: dark) {
    :root {
        --primary: #818cf8;
        --primary-light: #a5b4fc;
        --primary-dark: #6366f1;

        --bg: #0f172a;
        --bg-warm: #1e1b2e;
        --bg-card: #1e293b;
        --bg-elevated: #334155;

        --text: #f1f5f9;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;

        --border: #334155;
        --border-focus: #6366f1;
    }
}

/* === Animations === */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes slideIn {
    from { opacity: 0; transform: translateX(-10px); }
    to { opacity: 1; transform: translateX(0); }
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

@keyframes breathe {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.02); }
}

@keyframes celebrate {
    0% { transform: scale(1); }
    25% { transform: scale(1.1) rotate(-2deg); }
    50% { transform: scale(1.15) rotate(2deg); }
    75% { transform: scale(1.1) rotate(-1deg); }
    100% { transform: scale(1); }
}

@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}

@keyframes bounce {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-4px); }
}

@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* === Base === */
body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Meiryo UI', sans-serif;
    background: linear-gradient(135deg, var(--bg) 0%, var(--bg-warm) 100%);
    color: var(--text);
    min-height: 100vh;
}

/* === Header === */
.app-header {
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    box-shadow: var(--shadow-sm);
    backdrop-filter: blur(8px);
}

.app-logo {
    font-weight: 700;
    font-size: 1.25rem;
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

/* === Tabs === */
.tab-btn {
    padding: 0.75rem 1.5rem;
    color: var(--text-secondary);
    font-weight: 500;
    border-radius: 0.5rem 0.5rem 0 0;
    transition: all 0.2s ease;
    position: relative;
}

.tab-btn:hover {
    color: var(--primary);
    background: rgba(99, 102, 241, 0.05);
}

.tab-btn.active {
    color: var(--primary);
    background: rgba(99, 102, 241, 0.1);
}

.tab-btn.active::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--primary) 0%, var(--primary-light) 100%);
    border-radius: 3px 3px 0 0;
}

/* === Text Areas === */
.text-box {
    background: var(--bg-card);
    border: 2px solid var(--border);
    border-radius: 1rem;
    overflow: hidden;
    transition: all 0.3s ease;
    box-shadow: var(--shadow-sm);
    animation: fadeIn 0.4s ease;
}

.text-box:hover {
    border-color: var(--border-focus);
    box-shadow: var(--shadow-md);
}

.text-box:focus-within {
    border-color: var(--primary);
    box-shadow: var(--shadow-glow);
}

.text-label {
    padding: 0.75rem 1rem;
    background: linear-gradient(180deg, var(--bg-card) 0%, var(--bg) 100%);
    border-bottom: 1px solid var(--border);
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.text-label .flag {
    font-size: 1.1rem;
}

/* === Primary Button === */
.btn-primary {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
    color: white;
    padding: 0.875rem 2.5rem;
    border-radius: 0.75rem;
    font-weight: 600;
    font-size: 1rem;
    box-shadow: var(--shadow-md), 0 0 0 0 var(--primary-glow);
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
}

.btn-primary::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
    transform: translateX(-100%);
    transition: transform 0.5s ease;
}

.btn-primary:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: var(--shadow-lg), 0 0 20px var(--primary-glow);
}

.btn-primary:hover:not(:disabled)::before {
    transform: translateX(100%);
}

.btn-primary:active:not(:disabled) {
    transform: translateY(0);
}

.btn-primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    background: var(--text-muted);
}

.btn-primary.loading {
    animation: breathe 1.5s ease infinite;
}

/* === Outline Button === */
.btn-outline {
    background: transparent;
    border: 2px solid var(--border);
    color: var(--text);
    padding: 0.625rem 1.25rem;
    border-radius: 0.75rem;
    font-weight: 500;
    transition: all 0.2s ease;
}

.btn-outline:hover {
    border-color: var(--primary);
    color: var(--primary);
    background: rgba(99, 102, 241, 0.05);
}

/* === Swap Button === */
.swap-btn {
    width: 3rem;
    height: 3rem;
    border-radius: 50%;
    background: var(--bg-card);
    border: 2px solid var(--border);
    color: var(--text-secondary);
    box-shadow: var(--shadow-md);
    transition: all 0.3s ease;
}

.swap-btn:hover {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
    border-color: var(--primary);
    color: white;
    transform: rotate(180deg) scale(1.1);
    box-shadow: var(--shadow-lg), 0 0 15px var(--primary-glow);
}

/* === File Drop Zone === */
.drop-zone {
    border: 2px dashed var(--border);
    border-radius: 1.5rem;
    padding: 4rem 2rem;
    text-align: center;
    transition: all 0.3s ease;
    cursor: pointer;
    background: var(--bg-card);
    position: relative;
    overflow: hidden;
}

.drop-zone::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, var(--primary-glow) 0%, transparent 50%);
    opacity: 0;
    transition: opacity 0.3s ease;
}

.drop-zone:hover {
    border-color: var(--primary);
    transform: scale(1.01);
    box-shadow: var(--shadow-lg);
}

.drop-zone:hover::before {
    opacity: 1;
}

.drop-zone-icon {
    font-size: 3.5rem;
    color: var(--primary);
    margin-bottom: 1rem;
    animation: bounce 2s ease infinite;
}

.drop-zone-text {
    font-size: 1.125rem;
    font-weight: 500;
    color: var(--text);
    margin-bottom: 0.5rem;
}

.drop-zone-hint {
    font-size: 0.875rem;
    color: var(--text-muted);
}

/* === File Card === */
.file-card {
    background: var(--bg-card);
    border: 2px solid var(--border);
    border-radius: 1rem;
    padding: 1.5rem;
    box-shadow: var(--shadow-md);
    animation: fadeIn 0.4s ease;
    transition: all 0.3s ease;
}

.file-card:hover {
    box-shadow: var(--shadow-lg);
}

.file-card.success {
    border-color: var(--success);
    animation: celebrate 0.6s ease;
}

.file-card.success::before {
    content: '';
    position: absolute;
    inset: -2px;
    background: var(--success-glow);
    border-radius: 1rem;
    z-index: -1;
    animation: pulse 2s ease infinite;
}

/* === Progress === */
.progress-container {
    padding: 2rem;
    text-align: center;
}

.progress-track {
    height: 0.5rem;
    background: var(--border);
    border-radius: 1rem;
    overflow: hidden;
    position: relative;
}

.progress-bar {
    height: 100%;
    background: linear-gradient(90deg, var(--primary) 0%, var(--primary-light) 50%, var(--primary) 100%);
    background-size: 200% 100%;
    border-radius: 1rem;
    transition: width 0.3s ease;
    animation: shimmer 2s linear infinite;
}

.progress-text {
    font-size: 2rem;
    font-weight: 700;
    color: var(--primary);
    margin-top: 1rem;
}

.progress-status {
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-top: 0.5rem;
}

/* === Status Indicators === */
.status-dot {
    width: 0.625rem;
    height: 0.625rem;
    border-radius: 50%;
    background: var(--error);
    position: relative;
}

.status-dot::after {
    content: '';
    position: absolute;
    inset: -3px;
    border-radius: 50%;
    background: var(--error);
    opacity: 0.3;
    animation: pulse 2s ease infinite;
}

.status-dot.connected {
    background: var(--success);
}

.status-dot.connected::after {
    background: var(--success);
}

.status-dot.connecting {
    background: var(--warning);
    animation: pulse 1s ease infinite;
}

/* === Success State === */
.success-icon {
    font-size: 4rem;
    color: var(--success);
    animation: celebrate 0.8s ease;
}

.success-text {
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--success);
    margin-top: 1rem;
}

/* === Utility Classes === */
.text-primary { color: var(--primary); }
.text-success { color: var(--success); }
.text-error { color: var(--error); }
.text-muted { color: var(--text-muted); }

.animate-fade-in { animation: fadeIn 0.4s ease; }
.animate-slide-in { animation: slideIn 0.4s ease; }
.animate-bounce { animation: bounce 2s ease infinite; }
.animate-pulse { animation: pulse 2s ease infinite; }

/* === Dialog Enhancements === */
.progress-dialog {
    backdrop-filter: blur(8px);
}

.progress-dialog .q-card {
    border-radius: 1.5rem;
    box-shadow: var(--shadow-lg);
    animation: fadeIn 0.3s ease;
}

/* === Notifications === */
.q-notification {
    border-radius: 0.75rem;
    font-weight: 500;
}
"""
