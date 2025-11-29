# ecm_translate/ui/styles.py
"""
CSS styles for YakuLingo UI.
Based on UI_SPECIFICATION_v4.md color system.
"""

# CSS Variables (Light/Dark mode)
CSS_VARIABLES = """
:root {
    /* Primary */
    --primary: #2563eb;
    --primary-hover: #1d4ed8;
    --primary-light: rgba(37, 99, 235, 0.1);

    /* Background */
    --bg: #ffffff;
    --bg-secondary: #f8fafc;
    --bg-tertiary: #f1f5f9;

    /* Border */
    --border: #e2e8f0;

    /* Text */
    --text: #1e293b;
    --text-secondary: #64748b;
    --text-muted: #94a3b8;

    /* Status */
    --success: #22c55e;
    --warning: #f59e0b;
    --error: #ef4444;
}

@media (prefers-color-scheme: dark) {
    :root {
        --primary: #3b82f6;
        --primary-hover: #60a5fa;
        --primary-light: rgba(59, 130, 246, 0.15);

        --bg: #0f172a;
        --bg-secondary: #1e293b;
        --bg-tertiary: #334155;

        --border: #334155;

        --text: #f1f5f9;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;

        --success: #4ade80;
        --warning: #fbbf24;
        --error: #f87171;
    }
}
"""

# Main application styles
APP_STYLES = """
/* Font stack */
body {
    font-family: 'Meiryo UI', 'Meiryo', 'Yu Gothic UI', 'Hiragino Sans', 'Noto Sans JP', sans-serif;
    font-size: 15px;
    line-height: 1.5;
    color: var(--text);
    background-color: var(--bg);
}

/* Header */
.header {
    display: flex;
    align-items: center;
    padding: 12px 24px;
    background-color: var(--bg);
    border-bottom: 1px solid var(--border);
}

.header-logo {
    font-size: 24px;
    margin-right: 8px;
}

.header-title {
    font-size: 20px;
    font-weight: bold;
    color: var(--text);
}

/* Tab bar */
.tab-bar {
    display: flex;
    padding: 0 24px;
    background-color: var(--bg);
    border-bottom: 1px solid var(--border);
}

.tab-button {
    padding: 12px 20px;
    font-size: 15px;
    font-weight: 500;
    color: var(--text-secondary);
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    cursor: pointer;
    transition: all 0.2s;
}

.tab-button:hover {
    color: var(--text);
}

.tab-button.active {
    color: var(--primary);
    border-bottom-color: var(--primary);
}

/* Text panel */
.text-panel {
    display: flex;
    gap: 16px;
    padding: 24px;
    flex: 1;
}

.text-area-container {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.text-area-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background-color: var(--bg-secondary);
    border: 1px solid var(--border);
    border-bottom: none;
    border-radius: 8px 8px 0 0;
}

.text-area-label {
    font-size: 14px;
    font-weight: 500;
    color: var(--text);
}

.text-area {
    flex: 1;
    min-height: 250px;
    padding: 16px;
    font-family: 'Meiryo UI', 'Meiryo', sans-serif;
    font-size: 16px;
    line-height: 1.7;
    color: var(--text);
    background-color: var(--bg);
    border: 1px solid var(--border);
    border-radius: 0 0 8px 8px;
    resize: none;
}

.text-area:focus {
    outline: none;
    border-color: var(--primary);
}

/* Swap button */
.swap-button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    background-color: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.2s;
    align-self: center;
}

.swap-button:hover {
    background-color: var(--primary-light);
    border-color: var(--primary);
}

/* Translate button */
.translate-button {
    min-width: 160px;
    padding: 12px 24px;
    font-size: 15px;
    font-weight: 600;
    color: white;
    background-color: var(--primary);
    border: none;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
}

.translate-button:hover {
    background-color: var(--primary-hover);
}

.translate-button:disabled {
    background-color: var(--text-muted);
    cursor: not-allowed;
}

/* File drop zone */
.drop-zone {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 48px;
    border: 2px dashed var(--border);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.2s;
}

.drop-zone:hover {
    border-color: var(--primary);
    background-color: var(--primary-light);
}

.drop-zone.drag-over {
    border-style: solid;
    border-color: var(--primary);
    background-color: rgba(37, 99, 235, 0.1);
}

.drop-zone-icon {
    font-size: 48px;
    color: var(--text-muted);
    margin-bottom: 16px;
}

.drop-zone-text {
    font-size: 16px;
    color: var(--text-secondary);
    margin-bottom: 8px;
}

.drop-zone-formats {
    font-size: 13px;
    color: var(--text-muted);
}

/* File info */
.file-info {
    padding: 24px;
    background-color: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
}

.file-info-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
}

.file-info-name {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    font-weight: 500;
}

.file-info-icon {
    font-size: 24px;
}

.file-info-details {
    font-size: 14px;
    color: var(--text-secondary);
    line-height: 1.8;
}

/* Progress bar */
.progress-container {
    margin-top: 16px;
}

.progress-bar {
    height: 8px;
    background-color: var(--bg-tertiary);
    border-radius: 4px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    background-color: var(--primary);
    transition: width 0.3s;
}

.progress-text {
    display: flex;
    justify-content: space-between;
    margin-top: 8px;
    font-size: 13px;
    color: var(--text-secondary);
}

/* Settings panel */
.settings-panel {
    padding: 16px 24px;
    background-color: var(--bg-secondary);
    border-top: 1px solid var(--border);
}

.settings-header {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
}

.settings-content {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
}

/* Toast notifications */
.toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    padding: 12px 24px;
    background-color: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    z-index: 1000;
}

.toast.success {
    border-left: 4px solid var(--success);
}

.toast.error {
    border-left: 4px solid var(--error);
}

/* Reference files */
.reference-files {
    padding: 16px;
    background-color: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 16px;
}

.reference-files-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.reference-file-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background-color: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    margin-bottom: 8px;
}

.reference-file-name {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
}
"""

# Complete CSS
COMPLETE_CSS = CSS_VARIABLES + APP_STYLES
