# YakuLingo - UI Specification v4
## Text + File Translation

> **App Name**: YakuLingo (訳リンゴ)
> - 訳 (yaku) = translation in Japanese
> - Lingo = playful term for language
> - Inspired by [LocaLingo](https://github.com/soukouki/LocaLingo)
>
> **Design Philosophy**: LocaLingoを参考に、テキスト翻訳をメインに、ファイル翻訳を追加機能として提供。
> シンプルで直感的、すぐに使い始められるUI。

---

## 1. Product Overview

### 1.1 Core Features

| 機能 | 説明 | 優先度 |
|------|------|--------|
| **Text Translation** | テキストを入力して即座に翻訳 | ★★★ メイン機能 |
| **File Translation** | ファイルをドロップして一括翻訳 | ★★☆ 追加機能 |

### 1.2 Supported Languages

- Japanese ↔ English（双方向）

### 1.3 Supported File Formats

| 形式 | 拡張子 | 翻訳対象 |
|------|--------|----------|
| Excel | `.xlsx` `.xls` | セル、図形、グラフタイトル |
| Word | `.docx` `.doc` | 段落、表、ヘッダー/フッター |
| PowerPoint | `.pptx` `.ppt` | スライド、ノート、図形 |
| PDF | `.pdf` | 全ページテキスト |

---

## 2. UI Structure

### 2.1 Overall Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                           HEADER                                │
│  Logo + Title                              Language Toggle      │
├─────────────────────────────────────────────────────────────────┤
│  [ Text ]  [ File ]                              TAB BAR        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                                                                 │
│                        CONTENT AREA                             │
│                      (Tab-specific UI)                          │
│                                                                 │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  ▸ Settings                                    COLLAPSIBLE      │
├─────────────────────────────────────────────────────────────────┤
│                           FOOTER                                │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Window Specifications

| Property | Value |
|----------|-------|
| Default size | 900 x 700 px |
| Minimum size | 700 x 550 px |
| Resizable | Yes |
| Theme | Light / Dark (system preference) |

> **Design Note**: LocaLingoを参考に、テキストエリアに十分な領域を確保。
> 翻訳作業では入力・出力を同時に確認できることが重要。

---

## 3. Header

### 3.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🍎 YakuLingo                                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Components

| Component | Description |
|-----------|-------------|
| Logo | Apple emoji 🍎 (リンゴ pun), 24px |
| Title | "YakuLingo", 20px, bold |

> **Design Note**: 言語切り替えはヘッダーから削除し、
> テキストエリア間のスワップボタンに移動（より直感的）

---

## 4. Tab Bar

### 4.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [ 📝 Text ]  [ 📁 File ]                                       │
│       ▔▔▔▔                                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Tab States

| State | Style |
|-------|-------|
| Active | Primary color text, bottom border |
| Inactive | Secondary color text, no border |
| Hover | Darker text |

### 4.3 Default Tab

- `Text` tab is selected by default

---

## 5. Text Tab

### 5.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌─────────────────────────┐       ┌─────────────────────────┐  │
│  │ 日本語               [✕]│       │ English             [📋]│  │
│  ├─────────────────────────┤       ├─────────────────────────┤  │
│  │                         │       │                         │  │
│  │                         │       │                         │  │
│  │                         │ [⇄]  │                         │  │
│  │                         │       │                         │  │
│  │                         │       │                         │  │
│  │                         │       │                         │  │
│  └─────────────────────────┘       └─────────────────────────┘  │
│                                                                 │
│                        [ Translate ]                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Language Swap Button

テキストエリア間の中央に配置されるスワップボタン。

```
┌─────────────────────────┐         ┌─────────────────────────┐
│        日本語           │         │        English          │
│        (入力)           │  [⇄]   │        (出力)           │
└─────────────────────────┘         └─────────────────────────┘
                          ↑
                    Swap Button
                (クリックで入出力言語を切り替え)
```

| Property | Value |
|----------|-------|
| Icon | `⇄` または `swap_horiz` (Material icon) |
| Size | 40×40px |
| Position | テキストエリア間の中央、垂直方向も中央 |
| Tooltip | "言語を切り替え" / "Swap languages" |

**スワップ時の動作:**
- 左右のラベルが入れ替わる（日本語 ↔ English）
- 入力済みテキストはそのまま維持
- 翻訳結果はクリアされる

### 5.3 Components

#### Source Panel (Left)

| Element | Description |
|---------|-------------|
| Label | "日本語" または "English"（言語名を明確に表示） |
| Clear button | `[✕]` - Clears input text |
| Textarea | Editable, placeholder text |

#### Target Panel (Right)

| Element | Description |
|---------|-------------|
| Label | "English" または "日本語"（言語名を明確に表示） |
| Copy button | `[📋]` - Copies result to clipboard |
| Textarea | Read-only, shows translation result |

#### Translate Button

| Property | Value |
|----------|-------|
| Text | "Translate" |
| Width | 160px |
| Position | Center, below textareas |

### 5.4 Textarea Specifications

| Property | Value |
|----------|-------|
| Height | **flex-grow: 1** (利用可能な領域を最大限使用) |
| Min height | 250px |
| Max height | 制限なし（ウィンドウサイズに追従） |
| Placeholder (JP→EN) | "日本語を入力..." |
| Placeholder (EN→JP) | "Enter English text..." |
| Font family | Meiryo UI (See Section 14.1) |
| Font size | 16px |
| Line height | 1.7 |
| Padding | 16px |

> **LocaLingo Style**: テキストエリアはウィンドウの大部分を占め、
> ユーザーがウィンドウをリサイズすると自動的に拡大/縮小する。

### 5.5 Behavior

1. **Input**: User types in source textarea
2. **Translate**: User clicks "Translate" button
3. **Loading**: Button shows spinner, disabled, **tab switching disabled**
4. **Result**: Translation appears in target textarea
5. **Copy**: User clicks copy button → toast "Copied!"

> **Note**: テキスト翻訳時も参考ファイル（用語集等）がCopilotに添付されます。

### 5.6 Language Swap Effect

スワップボタン [⇄] クリック時の動作:
- 左右のラベルが入れ替わる（日本語 ↔ English）
- プレースホルダーが更新される
- 入力済みテキストはそのまま維持
- 翻訳結果はクリアされる

---

## 6. File Tab

### 6.1 State: Empty (No file selected)

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐ │
│  │                                                           │ │
│  │                          📄                               │ │
│  │                                                           │ │
│  │                 Drop file to translate                    │ │
│  │                   or click to browse                      │ │
│  │                                                           │ │
│  │            .xlsx   .docx   .pptx   .pdf                   │ │
│  │                                                           │ │
│  └─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Drop Zone Specifications

| Property | Value |
|----------|-------|
| Border | 2px dashed, `--border` color |
| Border radius | 12px |
| Padding | 48px |
| Icon | `description`, 48px, muted color |

#### Drop Zone States

| State | Border | Background |
|-------|--------|------------|
| Default | Dashed, muted | Transparent |
| Hover | Dashed, primary | Primary 5% |
| Drag over | Solid, primary | Primary 10% |

### 6.2 State: File Selected

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │  📊 report_2024.xlsx                              [✕]     │  │
│  │                                                           │  │
│  │  File size: 1.2 MB                                        │  │
│  │  Sheets: 4                                                │  │
│  │  Text cells: 234                                          │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│                      [ Translate File ]                         │  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### File Info Display

| File Type | Icon | Info Shown |
|-----------|------|------------|
| Excel | 📊 | Sheets count, text cells count |
| Word | 📄 | Pages count, paragraphs count |
| PowerPoint | 📽️ | Slides count, text boxes count |
| PDF | 📕 | Pages count |

### 6.3 State: Translating

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │  📊 report_2024.xlsx                                      │  │
│  │                                                           │  │
│  │  Translating...                                     75%   │  │
│  │  ████████████████████████████████░░░░░░░░░░░░░░░░░        │  │
│  │                                                           │  │
│  │  Processing: Sheet 3 of 4 (Sales Data)                    │  │
│  │  Estimated: ~2 min remaining                              │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│                         [ Cancel ]                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Progress Display

| Element | Description |
|---------|-------------|
| Percentage | Right-aligned, updates in real-time |
| Progress bar | Full width, primary color fill |
| Status text | Current operation (e.g., "Sheet 3 of 4") |
| Time estimate | Approximate remaining time |

#### UI State During Translation

| 項目 | 状態 |
|------|------|
| タブ切り替え | **禁止**（グレーアウト） |
| ファイル選択 | 禁止 |
| 設定変更 | 禁止 |
| キャンセルボタン | 有効 |
| アプリ終了 | 許可（即終了、確認なし） |

### 6.4 State: Complete

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │  ✓ Translation Complete                                   │  │
│  │                                                           │  │
│  │  📊 report_2024_EN.xlsx                                   │  │
│  │                                                           │  │
│  │  234 cells translated                                     │  │
│  │  4 sheets processed                                       │  │
│  │  Time: 3 min 24 sec                                       │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│         [ Download ]              [ Translate Another ]         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Output File Naming

| Direction | Input | Output |
|-----------|-------|--------|
| JP → EN | `report.xlsx` | `report_EN.xlsx` |
| EN → JP | `report.xlsx` | `report_JP.xlsx` |

### 6.5 State: Error

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │  ⚠️ Translation Failed                                    │  │
│  │                                                           │  │
│  │  Error: Could not connect to translation service.         │  │
│  │  Please check your network connection and try again.      │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│                        [ Try Again ]                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Settings Panel

### 7.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  ▸ Settings                                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Startup                                                        │
│  ☐ Start with Windows                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Settings Items

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| Start with Windows | Checkbox | ☐ Off | Windows起動時に自動起動 |

### 7.3 Output Behavior (固定)

- 翻訳結果は常に新規ファイルとして保存
- ファイル名には `_EN` または `_JP` が自動付与
- 元ファイルは変更されない

| 方向 | 入力 | 出力 |
|------|------|------|
| JP → EN | `report.xlsx` | `report_EN.xlsx` |
| EN → JP | `report.xlsx` | `report_JP.xlsx` |

---

## 8. Notifications

### 8.1 Toast Notifications

| Event | Message | Type | Duration |
|-------|---------|------|----------|
| Copy success | "Copied to clipboard" | Success | 2s |
| Translation complete | "Translation complete" | Success | 3s |
| File download | "File downloaded" | Success | 2s |
| Error | Error message | Error | 5s |
| Cancel | "Translation cancelled" | Info | 2s |

### 8.2 Toast Position

- Bottom center
- Stack vertically if multiple

---

## 9. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + Enter` | Translate (in Text tab) |
| `Ctrl + Shift + C` | Copy result |
| `Ctrl + L` | Toggle language direction |
| `Escape` | Cancel translation |

---

## 10. Responsive Behavior

### 10.1 Breakpoints

| Breakpoint | Width | Layout Change |
|------------|-------|---------------|
| Mobile | < 640px | Stack textareas vertically |
| Tablet | 640-1024px | Side-by-side, smaller textareas |
| Desktop | > 1024px | Full layout |

### 10.2 Mobile Layout (Text Tab)

```
┌───────────────────────┐
│ Japanese          [✕] │
├───────────────────────┤
│                       │
│                       │
└───────────────────────┘

     [ Translate ]

┌───────────────────────┐
│ English           [📋]│
├───────────────────────┤
│                       │
│                       │
└───────────────────────┘
```

---

## 11. File Processing Details

### 11.1 Excel (.xlsx)

**Translated:**
- Cell values (text only)
- Shape text (TextBox, etc.)
- Chart titles and labels
- Header/Footer text

**Preserved:**
- Formulas (not translated)
- Cell formatting (font, color, borders)
- Column widths, row heights
- Merged cells
- Images
- Charts (structure)

**Not translated:**
- Sheet names
- Named ranges
- Comments (optional)

### 11.2 Word (.docx)

**Translated:**
- Paragraphs
- Tables (cell text)
- Headers and footers
- Text boxes
- Footnotes and endnotes

**Preserved:**
- Styles (headings, fonts)
- Images and positions
- Page layout
- Lists (bullets, numbers)
- Table formatting

### 11.3 PowerPoint (.pptx)

**Translated:**
- Slide text (titles, body)
- Shape text
- Speaker notes
- Table text

**Preserved:**
- Slide layouts
- Animations
- Transitions
- Images
- Charts

### 11.4 PDF

**Translated:**
- All text content

**Preserved:**
- Layout (approximate)
- Images
- Page structure

**Note:** PDF reconstruction may have minor layout differences.

---

## 12. Error Handling

### 12.1 Error Types

| Error | Message | Recovery |
|-------|---------|----------|
| No file selected | "Please select a file" | - |
| Invalid file type | "Unsupported file format" | Show supported formats |
| File too large | "File exceeds 50MB limit" | - |
| Network error | "Could not connect to service" | Retry button |
| Translation timeout | "Translation timed out" | Retry button |
| Parse error | "Could not read file" | Check file integrity |

### 12.2 Validation

| Check | When | Action |
|-------|------|--------|
| File extension | On drop/select | Reject with message |
| File size | On drop/select | Reject if > 50MB |
| Empty content | Before translation | Show warning |

---

## 13. Color System

### 13.1 CSS Variables

```css
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

/* Dark mode */
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
```

---

## 14. Typography

### 14.1 Font Stack

```css
font-family:
    'Meiryo UI',
    'Meiryo',
    'Yu Gothic UI',
    'Hiragino Sans',
    'Noto Sans JP',
    sans-serif;
```

> **Note**: Windows環境ではMeiryo UIを優先。Mac/Linuxでは代替フォントにフォールバック。

### 14.2 Type Scale

| Use | Size | Weight |
|-----|------|--------|
| Logo | 24px | Bold |
| Title | 20px | Bold |
| Tab label | 15px | Medium |
| Body | 15px | Regular |
| Textarea | 16px | Regular |
| Label | 14px | Medium |
| Small | 13px | Regular |
| Button | 15px | Semibold |

> **Design Note**: 日本語テキストは英語より視認性が低いため、
> 本文サイズを15px以上に設定。テキストエリアは長時間の作業を考慮し16pxに。

---

## 15. Implementation Notes

### 15.1 Technology Stack

```
NiceGUI (Python)
├── FastAPI (Backend)
├── Vue.js (Frontend)
└── Tailwind CSS (Styling)
```

**実行形態**:
- ブラウザベースUI（デスクトップアプリではない）
- `★run.bat` でNiceGUIサーバー起動 → ブラウザ自動オープン
- ポート番号: `8765` (固定)
- URL: `http://localhost:8765`

**Python要件**:
- Python 3.11（yomitoku/torch互換性のため）

> **Note**: 初回起動時にファイアウォール警告が表示される場合があります。
> 「プライベートネットワーク」へのアクセスを許可してください。

### 15.2 File Processing Libraries

| Format | Library |
|--------|---------|
| Excel | `openpyxl` |
| Word | `python-docx` |
| PowerPoint | `python-pptx` |
| PDF | `yomitoku` (OCR) + `PyMuPDF` (再構築) |

> **PDF翻訳**: 既存の `pdf_translator.py` のロジックをすべて引き継ぎます。
> - yomitoku（OCR + レイアウト解析）
> - FormulaManager（数式保護）
> - FontRegistry（多言語フォント管理）
> - ContentStreamReplacer（PDF再構築）

### 15.3 Translation Backend

- M365 Copilot via Playwright automation
- Batch processing for large documents
- Retry logic with exponential backoff

### 15.4 Application Startup

```
アプリ起動フロー:
  1. NiceGUI サーバー起動
  2. ブラウザ自動オープン
  3. Copilot 自動接続開始（バックグラウンド）
  4. 接続完了まで翻訳ボタンは disabled
  5. 接続完了後、翻訳機能が有効化
```

**Copilot接続状態の表示**:
- 接続中: "Connecting to Copilot..." (spinner)
- 接続完了: 表示なし（通常状態）
- 接続失敗: エラーメッセージ + リトライボタン

### 15.5 Error Handling & Auto-Retry

翻訳失敗時は自動でリトライ（SmartRetryStrategy）:

| リトライ回数 | 待機時間 | 動作 |
|-------------|---------|------|
| 1回目 | 2秒 | 同じプロンプトで再試行 |
| 2回目 | 4秒 | より詳細な指示を追加 |
| 3回目 | 8秒 | 最大限詳細な指示 |
| 失敗 | - | エラー表示 + 手動リトライボタン |

> 既存の `SmartRetryStrategy` をそのまま再利用

### 15.6 Output File Naming

出力ファイルは自動で一意な名前を生成（上書き確認なし）:

```
入力: report.xlsx (JP→EN)

出力:
  report_EN.xlsx      ← 存在しない場合
  report_EN_2.xlsx    ← report_EN.xlsx が存在する場合
  report_EN_3.xlsx    ← report_EN_2.xlsx も存在する場合
```

---

## 16. Distribution

### 16.1 配布方法

PyInstallerは使用せず、`setup.bat` + `make_distribution.bat` でzip配布:

```
YakuLingo_YYYYMMDD.zip
├── .venv/                    # 仮想環境
├── .uv-python/               # Python 3.11
├── .playwright-browsers/     # Chromium
├── ecm_translate/            # メインパッケージ
│   ├── ui/
│   ├── services/
│   ├── processors/
│   ├── models/
│   └── config/
├── prompts/                  # 統一プロンプト
│   ├── translate_jp_to_en.txt
│   └── translate_en_to_jp.txt
├── app.py                    # エントリーポイント
├── glossary.csv              # デフォルト参考ファイル
├── pyproject.toml
├── uv.toml
├── ★run.bat                  # 起動スクリプト
├── setup.bat                 # 初回セットアップ
└── README.md
```

### 16.2 セットアップ手順（ユーザー向け）

1. zipを任意の場所に展開
2. `★run.bat` をダブルクリック
3. ブラウザが自動で開く (`http://localhost:8765`)

---

## 17. Migration Checklist

### Phase 1: Core UI
- [ ] NiceGUI project setup
- [ ] Header component
- [ ] Tab navigation (Text / File)
- [ ] Text tab (input/output/swap/translate)
- [ ] Basic styling (Tailwind CSS)

### Phase 2: File Tab
- [ ] Drop zone component
- [ ] File info display
- [ ] Progress indicator
- [ ] Complete/Error states
- [ ] Reference files UI

### Phase 3: File Processing
- [ ] Excel processor (openpyxl)
- [ ] Word processor (python-docx)
- [ ] PowerPoint processor (python-pptx)
- [ ] PDF processor (migrate existing yomitoku logic)

### Phase 4: Integration
- [ ] Connect to Copilot translator
- [ ] Settings panel
- [ ] Error handling
- [ ] Output file auto-naming

### Phase 5: Polish
- [ ] Responsive layout
- [ ] Keyboard shortcuts
- [ ] Batch scripts update (setup.bat, make_distribution.bat, ★run.bat)
- [ ] Documentation (README.md)

---

## 18. References

- [LocaLingo](https://github.com/soukouki/LocaLingo) - UI inspiration
- [NiceGUI Documentation](https://nicegui.io/documentation)
- [python-docx](https://python-docx.readthedocs.io/)
- [python-pptx](https://python-pptx.readthedocs.io/)
- [openpyxl](https://openpyxl.readthedocs.io/)
