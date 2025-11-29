# ecm_translate/ui/styles.py
"""
Simplified CSS styles for YakuLingo UI.
Clean, minimal design inspired by LocaLingo.
"""

COMPLETE_CSS = """
/* === Variables === */
:root {
    --primary: #3b82f6;
    --primary-hover: #2563eb;
    --bg: #ffffff;
    --bg-alt: #f9fafb;
    --border: #e5e7eb;
    --text: #111827;
    --text-dim: #6b7280;
    --success: #10b981;
    --error: #ef4444;
}

@media (prefers-color-scheme: dark) {
    :root {
        --primary: #60a5fa;
        --primary-hover: #3b82f6;
        --bg: #111827;
        --bg-alt: #1f2937;
        --border: #374151;
        --text: #f9fafb;
        --text-dim: #9ca3af;
    }
}

/* === Base === */
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Meiryo', sans-serif;
    background: var(--bg);
    color: var(--text);
}

/* === Header === */
.app-header {
    background: var(--bg);
    border-bottom: 1px solid var(--border);
}

/* === Tabs === */
.tab-btn {
    padding: 0.75rem 1.25rem;
    color: var(--text-dim);
    border-bottom: 2px solid transparent;
    font-weight: 500;
    transition: all 0.15s;
}

.tab-btn:hover { color: var(--text); }

.tab-btn.active {
    color: var(--primary);
    border-color: var(--primary);
}

/* === Text Areas === */
.text-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    overflow: hidden;
}

.text-box:focus-within { border-color: var(--primary); }

.text-label {
    padding: 0.5rem 0.75rem;
    background: var(--bg-alt);
    border-bottom: 1px solid var(--border);
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--text-dim);
}

/* === Buttons === */
.btn-primary {
    background: var(--primary);
    color: white;
    padding: 0.75rem 2rem;
    border-radius: 0.5rem;
    font-weight: 500;
    transition: background 0.15s;
}

.btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-outline {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.5rem 1rem;
    border-radius: 0.5rem;
}

.btn-outline:hover { background: var(--bg-alt); }

.btn-icon {
    width: 2rem;
    height: 2rem;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-dim);
}

.btn-icon:hover {
    background: var(--bg-alt);
    color: var(--text);
}

/* === Swap Button === */
.swap-btn {
    width: 2.5rem;
    height: 2.5rem;
    border-radius: 50%;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    color: var(--text-dim);
    transition: all 0.15s;
}

.swap-btn:hover {
    background: var(--primary);
    border-color: var(--primary);
    color: white;
}

/* === File Drop Zone === */
.drop-zone {
    border: 2px dashed var(--border);
    border-radius: 0.75rem;
    padding: 3rem;
    text-align: center;
    transition: all 0.15s;
    cursor: pointer;
}

.drop-zone:hover {
    border-color: var(--primary);
    background: rgba(59, 130, 246, 0.05);
}

/* === File Card === */
.file-card {
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
}

/* === Progress === */
.progress-track {
    height: 0.375rem;
    background: var(--border);
    border-radius: 1rem;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: var(--primary);
    transition: width 0.3s;
}

/* === Status === */
.status-dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--error);
}

.status-dot.connected { background: var(--success); }

.text-success { color: var(--success); }
.text-error { color: var(--error); }
"""
