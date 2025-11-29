# ECM Translate - UI Specification v3
## "Clean & Functional" Design

> **Design Philosophy**: シンプルで実用的。ユーザーが翻訳作業に集中できるUI。
> LocaLingoを参考に、必要な機能だけを美しく配置する。

---

## 1. Design Principles

### 1.1 Core Values

| Principle | Description |
|-----------|-------------|
| **Simplicity** | 余計な装飾を排除し、機能に集中 |
| **Clarity** | 一目で使い方が分かる |
| **Efficiency** | 最小クリックで目的を達成 |
| **Familiarity** | 馴染みのあるUIパターンを使用 |

### 1.2 What We DON'T Do

- 過度なアニメーション
- グラデーションの多用
- パーティクルエフェクト
- 複雑なマイクロインタラクション
- ダークテーマ強制

---

## 2. Technology Stack

```
┌─────────────────────────────────────────┐
│              NiceGUI                    │
│  (Python → FastAPI → Vue.js)            │
├─────────────────────────────────────────┤
│  Styling: CSS Variables + Tailwind      │
│  Icons: Material Icons                  │
│  Theme: System preference (auto)        │
└─────────────────────────────────────────┘
```

### 2.1 Dependencies

```txt
nicegui>=1.4.0
```

### 2.2 File Structure

```
ECM_translate/
├── app.py                  # Main entry point
├── ui/
│   ├── __init__.py
│   ├── styles.py           # CSS styles
│   ├── components/
│   │   ├── header.py       # Header with lang toggle
│   │   ├── tabs.py         # Tab navigation
│   │   ├── text_panel.py   # Text translation
│   │   ├── pdf_panel.py    # PDF translation
│   │   └── excel_panel.py  # Excel translation
│   └── state.py            # Application state
├── core/
│   ├── translator.py       # Translation logic (Copilot)
│   ├── pdf_translator.py   # PDF processing
│   └── excel_handler.py    # Excel COM integration
└── config/
    └── settings.py         # User settings
```

---

## 3. Color System

### 3.1 CSS Variables (Light/Dark Auto)

```css
:root {
    /* Light theme (default) */
    --primary: #2563eb;
    --primary-hover: #1d4ed8;
    --primary-light: rgba(37, 99, 235, 0.1);

    --bg: #ffffff;
    --bg-secondary: #f8fafc;
    --bg-tertiary: #f1f5f9;

    --border: #e2e8f0;
    --border-focus: #2563eb;

    --text: #1e293b;
    --text-secondary: #64748b;
    --text-muted: #94a3b8;

    --success: #22c55e;
    --warning: #f59e0b;
    --error: #ef4444;
}

@media (prefers-color-scheme: dark) {
    :root {
        --primary: #3b82f6;
        --primary-hover: #60a5fa;
        --primary-light: rgba(59, 130, 246, 0.1);

        --bg: #0f172a;
        --bg-secondary: #1e293b;
        --bg-tertiary: #334155;

        --border: #334155;
        --border-focus: #3b82f6;

        --text: #f1f5f9;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;

        --success: #4ade80;
        --warning: #fbbf24;
        --error: #f87171;
    }
}
```

### 3.2 Color Usage

| Element | Color Variable |
|---------|---------------|
| Primary buttons | `--primary` |
| Background | `--bg` |
| Cards | `--bg-secondary` |
| Borders | `--border` |
| Main text | `--text` |
| Labels | `--text-secondary` |
| Placeholders | `--text-muted` |

---

## 4. Typography

### 4.1 Font Stack

```css
font-family:
    -apple-system,        /* macOS/iOS */
    BlinkMacSystemFont,   /* macOS Chrome */
    'Segoe UI',           /* Windows */
    'Noto Sans JP',       /* Japanese */
    sans-serif;
```

### 4.2 Type Scale

| Use | Size | Weight |
|-----|------|--------|
| Page title | 24px | Bold (700) |
| Section title | 18px | Semibold (600) |
| Body text | 14px | Regular (400) |
| Labels | 14px | Medium (500) |
| Small text | 12px | Regular (400) |

---

## 5. Spacing System

8px grid system:

| Token | Value | Use |
|-------|-------|-----|
| `xs` | 4px | Tight spacing |
| `sm` | 8px | Between related elements |
| `md` | 16px | Section padding |
| `lg` | 24px | Card padding |
| `xl` | 32px | Section gaps |

---

## 6. Layout

### 6.1 Overall Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │                         HEADER                              │ │
│ │   Logo + Title                           Language Toggle    │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │  [ Text ]  [ PDF ]  [ Excel ]              TABS             │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │                                                             │ │
│ │                                                             │ │
│ │                      CONTENT AREA                           │ │
│ │                   (Tab-specific UI)                         │ │
│ │                                                             │ │
│ │                                                             │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │  ▸ Settings                              COLLAPSIBLE        │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │                         FOOTER                              │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Responsive Breakpoints

| Breakpoint | Width | Layout |
|------------|-------|--------|
| Mobile | < 640px | Single column, stacked textareas |
| Tablet | 640-1024px | Side-by-side with smaller textareas |
| Desktop | > 1024px | Full layout, max-width 896px |

---

## 7. Components

### 7.1 Header

```
┌─────────────────────────────────────────────────────────────────┐
│  🌐 ECM Translate                              [ JP → EN  ⇄ ]   │
└─────────────────────────────────────────────────────────────────┘
```

**Specifications:**
- Height: 64px
- Padding: 16px 24px
- Logo icon: Material `translate`, 32px, primary color
- Title: 24px, bold
- Language toggle: Pill button with swap icon

**Language Toggle States:**
```
[ JP → EN  ⇄ ]  ←  Default
[ EN → JP  ⇄ ]  ←  After click
```

### 7.2 Tab Navigation

```
┌─────────────────────────────────────────────────────────────────┐
│  [ 📄 Text ]  [ 📑 PDF ]  [ 📊 Excel ]                          │
│      ▔▔▔▔▔                                                      │
└─────────────────────────────────────────────────────────────────┘
```

**Specifications:**
- Tab height: 48px
- Active indicator: 2px bottom border, primary color
- Inactive text: `--text-secondary`
- Active text: `--primary`
- Hover: `--text`

### 7.3 Text Translation Panel

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Japanese                              English                  │
│  ┌──────────────────────────┐         ┌──────────────────────┐  │
│  │                          │         │                  [📋]│  │
│  │                          │   →     │                      │  │
│  │                          │         │                      │  │
│  │                          │         │                      │  │
│  └──────────────────────────┘         └──────────────────────┘  │
│                                                                 │
│                       [ Translate ]                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Specifications:**

| Element | Spec |
|---------|------|
| Container | padding: 24px |
| Textarea | min-height: 200px, border-radius: 8px |
| Label | 14px, medium, `--text-secondary` |
| Arrow icon | 24px, `--text-secondary` |
| Copy button | 32px, flat, top-right of output |
| Translate button | 48px height, 160px min-width, primary |

**Textarea Behavior:**
- Auto-resize with content (max 400px)
- Focus: blue border + subtle shadow
- Placeholder: `--text-muted`

### 7.4 PDF Translation Panel

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐  │
│  │                                                           │  │
│  │                         📄                                │  │
│  │                                                           │  │
│  │            Drop PDF file here or click to browse          │  │
│  │                                                           │  │
│  └─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘  │
│                                                                 │
│  Translating...                                           45%   │
│  [████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]  │
│                                                                 │
│                     [ Translate PDF ]                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Drop Zone Specifications:**

| State | Border | Background | Icon Color |
|-------|--------|------------|------------|
| Empty | 2px dashed `--border` | transparent | `--text-muted` |
| Hover | 2px dashed `--primary` | `--primary-light` | `--primary` |
| Has file | 2px solid `--primary` | `--primary-light` | `--primary` |

**Progress Bar:**
- Height: 4px
- Border-radius: 2px
- Track: `--bg-tertiary`
- Fill: `--primary`

### 7.5 Excel Translation Panel

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                           📊                                    │
│                                                                 │
│                    Excel Translation                            │
│                                                                 │
│     Select cells in Excel, then click the button below          │
│                                                                 │
│                [ Translate Selected Cells ]                     │
│                                                                 │
│                    ─────────────────────                        │
│                                                                 │
│                    Keyboard Shortcuts:                          │
│                    Ctrl+Alt+E  →  JP → EN                       │
│                    Ctrl+Alt+J  →  EN → JP                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.6 Settings Panel

```
┌─────────────────────────────────────────────────────────────────┐
│  ▸ Settings                                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Glossary file                                                  │
│  ┌────────────────────────────────────────────────────┐  [📁]  │
│  │ glossary.csv                                       │        │
│  └────────────────────────────────────────────────────┘        │
│                                                                 │
│  ☐ Auto-start on Windows boot                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Specifications:**
- Collapsed by default
- Icon: `settings`
- Expand animation: slide down, 200ms

---

## 8. Interactions

### 8.1 Button States

| State | Style |
|-------|-------|
| Default | `--primary` background, white text |
| Hover | `--primary-hover` background |
| Active | Slightly darker, scale(0.98) |
| Disabled | 50% opacity, cursor: not-allowed |
| Loading | Spinner icon, disabled |

### 8.2 Transitions

All transitions: `200ms ease`

| Element | Property |
|---------|----------|
| Buttons | background-color, transform |
| Borders | border-color |
| Tabs | color, border-color |
| Expansion | height |

### 8.3 Feedback

| Action | Feedback |
|--------|----------|
| Translation complete | Toast notification (bottom, 3s) |
| Copy to clipboard | Toast "Copied!" |
| Error | Toast with error style |
| File uploaded | Drop zone visual change |

---

## 9. Implementation

### 9.1 Main Entry Point

```python
# app.py
from nicegui import ui
from ui.styles import setup_styles
from ui.components.header import create_header
from ui.components.tabs import create_tabs
from ui.components.text_panel import create_text_panel
from ui.components.pdf_panel import create_pdf_panel
from ui.components.excel_panel import create_excel_panel
from ui.state import state

def main():
    setup_styles()

    with ui.column().classes('w-full max-w-4xl mx-auto min-h-screen'):
        create_header()
        create_tabs()

        with ui.element('div').classes('card mx-6 mt-6'):
            create_text_panel()
            create_pdf_panel()
            create_excel_panel()

        create_settings()
        create_footer()

    ui.run(
        title='ECM Translate',
        port=8080,
        reload=False,  # Production
    )

if __name__ == '__main__':
    main()
```

### 9.2 State Management

```python
# ui/state.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AppState:
    # Navigation
    current_tab: str = 'text'

    # Translation direction
    direction: str = 'jp_to_en'  # or 'en_to_jp'

    # Text translation
    source_text: str = ''
    result_text: str = ''

    # PDF translation
    pdf_file: Optional[str] = None
    pdf_progress: float = 0
    pdf_status: str = ''

    # Status
    is_translating: bool = False

    # Settings
    glossary_path: str = 'glossary.csv'
    auto_start: bool = False

state = AppState()
```

### 9.3 Styles Module

```python
# ui/styles.py
from nicegui import ui

STYLES = """
:root {
    --primary: #2563eb;
    --primary-hover: #1d4ed8;
    --primary-light: rgba(37, 99, 235, 0.1);
    --bg: #ffffff;
    --bg-secondary: #f8fafc;
    --bg-tertiary: #f1f5f9;
    --border: #e2e8f0;
    --text: #1e293b;
    --text-secondary: #64748b;
    --text-muted: #94a3b8;
    --success: #22c55e;
    --error: #ef4444;
}

@media (prefers-color-scheme: dark) {
    :root {
        --primary: #3b82f6;
        --primary-hover: #60a5fa;
        --primary-light: rgba(59, 130, 246, 0.1);
        --bg: #0f172a;
        --bg-secondary: #1e293b;
        --bg-tertiary: #334155;
        --border: #334155;
        --text: #f1f5f9;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;
        --success: #4ade80;
        --error: #f87171;
    }
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 'Noto Sans JP', sans-serif;
    background: var(--bg);
    color: var(--text);
}

.card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
}

.btn-primary {
    background: var(--primary);
    color: white;
    border: none;
    padding: 12px 32px;
    border-radius: 8px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
}

.btn-primary:hover {
    background: var(--primary-hover);
}

.btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.textarea-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    min-height: 200px;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.textarea-box:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 3px var(--primary-light);
}

.drop-zone {
    border: 2px dashed var(--border);
    border-radius: 12px;
    padding: 48px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s ease;
}

.drop-zone:hover,
.drop-zone.drag-over {
    border-color: var(--primary);
    background: var(--primary-light);
}

.drop-zone.has-file {
    border-style: solid;
    border-color: var(--primary);
    background: var(--primary-light);
}

.tab-btn {
    padding: 12px 20px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-weight: 500;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.2s ease;
}

.tab-btn:hover {
    color: var(--text);
}

.tab-btn.active {
    color: var(--primary);
    border-bottom-color: var(--primary);
}

.lang-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 24px;
    cursor: pointer;
    font-weight: 500;
    transition: all 0.2s ease;
}

.lang-toggle:hover {
    border-color: var(--primary);
}
"""

def setup_styles():
    ui.add_head_html(f'<style>{STYLES}</style>')
    ui.add_head_html('''
        <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&display=swap" rel="stylesheet">
    ''')
```

---

## 10. Build & Deploy

### 10.1 Development

```bash
# Install dependencies
pip install nicegui

# Run in development mode
python app.py
# Opens http://localhost:8080
```

### 10.2 Production Build (PyInstaller)

```bash
pip install pyinstaller

pyinstaller \
    --name="ECM_Translate" \
    --windowed \
    --onedir \
    --collect-all=nicegui \
    --icon=assets/icon.ico \
    app.py
```

### 10.3 Native Mode

```python
from nicegui import ui, native

ui.run(
    native=True,                    # Native window
    window_size=(900, 700),         # Window size
    reload=False,                   # Disable for production
    port=native.find_open_port(),   # Auto port
)
```

---

## 11. Migration Checklist

### Phase 1: Core UI (Day 1-2)
- [ ] Setup NiceGUI project structure
- [ ] Implement styles module
- [ ] Create header component
- [ ] Create tab navigation
- [ ] Implement text translation panel

### Phase 2: Features (Day 3-4)
- [ ] Implement PDF translation panel
- [ ] Implement Excel translation panel
- [ ] Add settings panel
- [ ] Connect to existing translation logic

### Phase 3: Integration (Day 5-6)
- [ ] Integrate Copilot translator
- [ ] Integrate PDF translator
- [ ] Integrate Excel COM handler
- [ ] Add keyboard shortcuts

### Phase 4: Polish (Day 7)
- [ ] Test all features
- [ ] Fix bugs
- [ ] Build executable
- [ ] Documentation

---

## 12. Reference

- [NiceGUI Documentation](https://nicegui.io/documentation)
- [LocaLingo](https://github.com/soukouki/LocaLingo) - Design inspiration
- [Tailwind CSS](https://tailwindcss.com/) - Utility classes reference
