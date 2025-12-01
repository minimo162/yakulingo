# YakuLingo - 技術仕様書

> **Version**: 2.5
> **Date**: 2025-12
> **App Name**: YakuLingo (訳リンゴ)

---

## 目次

1. [概要](#1-概要)
2. [システムアーキテクチャ](#2-システムアーキテクチャ)
3. [ディレクトリ構造](#3-ディレクトリ構造)
4. [データモデル](#4-データモデル)
5. [UI仕様](#5-ui仕様)
6. [サービスレイヤー](#6-サービスレイヤー)
7. [ファイルプロセッサ](#7-ファイルプロセッサ)
8. [フォント管理](#8-フォント管理)
9. [プロンプト設計](#9-プロンプト設計)
10. [ストレージ](#10-ストレージ)
11. [自動更新](#11-自動更新)
12. [設定・配布](#12-設定配布)
13. [パフォーマンス最適化](#13-パフォーマンス最適化)

---

## 1. 概要

### 1.1 システム目的

YakuLingoは、日本語と英語の双方向翻訳を提供するデスクトップアプリケーション。
M365 Copilotを翻訳エンジンとして使用し、テキストとドキュメントファイルの翻訳をサポート。

### 1.2 主要機能

| 機能 | 説明 |
|------|------|
| **Text Translation** | テキストを入力して即座に翻訳（言語自動検出） |
| **File Translation** | Excel/Word/PowerPoint/PDF の一括翻訳 |
| **Layout Preservation** | 翻訳後もファイルの体裁を維持 |
| **Bilingual Output** | 原文と訳文を並べた対訳ファイルを自動生成 |
| **Glossary Export** | 翻訳ペアをCSVで出力（用語管理に活用） |
| **Reference Files** | 用語集・スタイルガイド・参考資料による一貫した翻訳 |
| **Translation History** | 過去の翻訳をローカルに保存・検索 |
| **Auto Update** | GitHub Releases経由で自動更新 |

### 1.3 言語自動検出

入力テキストの言語を自動検出し、適切な方向に翻訳：

| 入力言語 | 出力 |
|---------|------|
| 日本語 | 英語（複数の訳文オプション付き） |
| その他 | 日本語（解説・使用例付き） |

### 1.4 対応ファイル形式

| 形式 | 拡張子 | ライブラリ |
|------|--------|----------|
| Excel | `.xlsx` `.xls` | openpyxl |
| Word | `.docx` `.doc` | python-docx |
| PowerPoint | `.pptx` `.ppt` | python-pptx |
| PDF | `.pdf` | PyMuPDF, yomitoku |

### 1.5 技術スタック

| Layer | Technology |
|-------|------------|
| UI | NiceGUI + pywebview (Material Design 3) |
| Backend | FastAPI (via NiceGUI) |
| Translation | M365 Copilot (Playwright + Edge) |
| File Processing | openpyxl, python-docx, python-pptx, PyMuPDF |
| Storage | SQLite (translation history) |
| Auto Update | GitHub Releases API |

---

## 2. システムアーキテクチャ

### 2.1 全体構成

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            YakuLingo                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        Presentation Layer                         │  │
│  │                     (NiceGUI + pywebview)                         │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐   │  │
│  │  │  Text Tab   │  │  File Tab   │  │  Update Notification    │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         Service Layer                             │  │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │  │
│  │  │TranslationService│  │ BatchTranslator  │  │  AutoUpdater   │  │  │
│  │  │+ translate_text()│  │+ translate_blocks│  │+ check_update()│  │  │
│  │  │+ translate_file()│  │                  │  │+ download()    │  │  │
│  │  └──────────────────┘  └──────────────────┘  └────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│          │                         │                         │          │
│          ▼                         ▼                         ▼          │
│  ┌───────────────┐     ┌─────────────────────┐     ┌───────────────┐    │
│  │ CopilotHandler│     │   File Processors   │     │   HistoryDB   │    │
│  │ (Edge+        │     │ Excel/Word/PPT/PDF  │     │   (SQLite)    │    │
│  │  Playwright)  │     │                     │     │               │    │
│  └───────────────┘     └─────────────────────┘     └───────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 レイヤー責務

| Layer | Responsibility |
|-------|----------------|
| **Presentation** | NiceGUI + pywebviewによるUI、状態表示 |
| **Service** | 翻訳処理の調整、バッチ処理、自動更新 |
| **CopilotHandler** | Edge起動、Playwright接続、メッセージ送受信 |
| **File Processors** | ファイル解析、テキスト抽出、翻訳適用 |
| **Storage** | 翻訳履歴の永続化（SQLite） |
| **Config** | 設定読み込み/保存、参照ファイル管理 |

---

## 3. ディレクトリ構造

```
YakuLingo/
├── app.py                          # エントリーポイント
├── pyproject.toml
├── uv.lock                         # 依存関係ロックファイル
├── requirements.txt
│
├── yakulingo/                      # メインパッケージ
│   ├── __init__.py
│   │
│   ├── ui/                         # Presentation Layer
│   │   ├── app.py                  # YakuLingoApp クラス
│   │   ├── state.py                # AppState
│   │   ├── styles.py               # M3 デザイントークン & CSS
│   │   └── components/
│   │       ├── text_panel.py       # テキスト翻訳パネル
│   │       ├── file_panel.py       # ファイル翻訳パネル
│   │       └── update_notification.py  # 更新通知UI
│   │
│   ├── services/                   # Service Layer
│   │   ├── translation_service.py  # TranslationService
│   │   ├── copilot_handler.py      # CopilotHandler
│   │   ├── prompt_builder.py       # PromptBuilder
│   │   └── updater.py              # 自動更新サービス
│   │
│   ├── processors/                 # File Processors
│   │   ├── base.py                 # FileProcessor (ABC)
│   │   ├── translators.py          # CellTranslator, ParagraphTranslator
│   │   ├── font_manager.py         # FontManager, FontTypeDetector
│   │   ├── excel_processor.py
│   │   ├── word_processor.py
│   │   ├── pptx_processor.py
│   │   └── pdf_processor.py
│   │
│   ├── storage/                    # Storage Layer
│   │   └── history_db.py           # HistoryDB (SQLite)
│   │
│   ├── models/
│   │   └── types.py                # 型定義
│   │
│   └── config/
│       └── settings.py             # AppSettings
│
├── tests/                          # テストスイート（26ファイル）
│   ├── conftest.py
│   └── test_*.py
│
├── prompts/                        # 翻訳プロンプト
│   ├── translate_to_en.txt         # ファイル翻訳用（日→英）
│   ├── translate_to_jp.txt         # ファイル翻訳用（英→日）
│   ├── text_translate_to_en.txt    # テキスト翻訳用（日→英）
│   ├── text_translate_to_jp.txt    # テキスト翻訳用（英→日）
│   └── ... (調整用・特殊用途プロンプト)
│
├── config/
│   └── settings.json               # ユーザー設定
│
├── glossary.csv                    # デフォルト参照ファイル（用語集）
│
├── installer/                      # 配布用インストーラ
│
└── docs/
    └── SPECIFICATION.md            # この仕様書
```

---

## 4. データモデル

### 4.1 列挙型

```python
class FileType(Enum):
    EXCEL = "excel"
    WORD = "word"
    POWERPOINT = "powerpoint"
    PDF = "pdf"

class TranslationStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# 自動更新用
class UpdateStatus(Enum):
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    DOWNLOADING = "downloading"
    READY_TO_INSTALL = "ready_to_install"
    ERROR = "error"
```

### 4.2 データクラス

```python
@dataclass
class TextBlock:
    id: str           # 一意識別子（例: "Sheet1_A1"）
    text: str         # 元テキスト
    location: str     # 位置表示（例: "Sheet1, A1"）
    metadata: dict    # 追加情報（font_name, font_size等）

@dataclass
class FileInfo:
    path: Path
    file_type: FileType
    size_bytes: int
    sheet_count: Optional[int]      # Excel
    page_count: Optional[int]       # Word, PDF
    slide_count: Optional[int]      # PowerPoint
    text_block_count: int

@dataclass
class TranslationProgress:
    current: int
    total: int
    status: str
    percentage: float = 0.0
    estimated_remaining: Optional[int] = None

@dataclass
class TranslationOption:
    """単一の翻訳オプション"""
    text: str                        # 翻訳テキスト
    explanation: str                 # 使用文脈・説明
    char_count: int = 0

@dataclass
class TextTranslationResult:
    """テキスト翻訳結果（複数オプション付き）"""
    source_text: str
    source_char_count: int
    options: list[TranslationOption]
    output_language: str = "en"      # "en" or "jp" - 自動検出された出力言語
    error_message: Optional[str] = None

@dataclass
class TranslationResult:
    """ファイル翻訳結果"""
    status: TranslationStatus
    output_path: Optional[Path]           # 翻訳ファイル
    bilingual_path: Optional[Path]        # 対訳ファイル (原文+訳文)
    glossary_path: Optional[Path]         # 用語集CSV
    blocks_translated: int
    blocks_total: int
    duration_seconds: float
    error_message: Optional[str]
    warnings: list[str]

    @property
    def output_files(self) -> list[tuple[Path, str]]:
        """全出力ファイルのリスト [(path, description), ...]"""

@dataclass
class HistoryEntry:
    """翻訳履歴エントリ"""
    source_text: str
    result: TextTranslationResult
    timestamp: str                   # ISO format

@dataclass
class VersionInfo:
    """バージョン情報（自動更新用）"""
    version: str
    release_date: str
    download_url: str
    release_notes: str
```

### 4.3 アプリケーション状態

```python
@dataclass
class AppState:
    # テキストタブ
    source_text: str = ""
    text_result: Optional[TextTranslationResult] = None
    text_translating: bool = False

    # ファイルタブ
    selected_file: Optional[Path] = None
    file_info: Optional[FileInfo] = None
    translation_progress: float = 0.0
    translation_status: str = ""
    output_file: Optional[Path] = None
    error_message: str = ""

    # 参照ファイル
    reference_files: List[Path] = field(default_factory=list)

    # Copilot接続
    copilot_connected: bool = False
    copilot_connecting: bool = False
    copilot_error: str = ""

    # 自動更新
    update_available: bool = False
    update_info: Optional[VersionInfo] = None
```

---

## 5. UI仕様

### 5.1 ウィンドウ設定

| Property | Value |
|----------|-------|
| Mode | Native window (pywebview) |
| Host | 127.0.0.1 |
| Port | 8765 |
| Title | YakuLingo |
| Favicon | 🍎 |
| Theme | Light (M3 Design) |

### 5.2 全体レイアウト

```
┌─────────────────────────────────────────────────────────────────┐
│  🍎 YakuLingo                              [Update Available]    │
├─────────────────────────────────────────────────────────────────┤
│  [ Text ]  [ File ]                                   TAB BAR    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                        CONTENT AREA                             │
│                      (Tab-specific UI)                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Text Tab

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 翻訳したいテキストを入力...                           [✕]   ││
│  │                                                             ││
│  │   (Source Textarea - 言語自動検出)                          ││
│  │                                                             ││
│  │─────────────────────────────────────────────────────────────││
│  │ 123 文字                              [翻訳する] Ctrl+Enter ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Translation Options (日本語入力時)                          ││
│  │ ┌─────────────────────────────────────────────────────────┐ ││
│  │ │ Option 1: "Translation text..."                    [📋] │ ││
│  │ │ Formal business tone                                    │ ││
│  │ └─────────────────────────────────────────────────────────┘ ││
│  │ ┌─────────────────────────────────────────────────────────┐ ││
│  │ │ Option 2: "Another translation..."                 [📋] │ ││
│  │ │ Casual conversational style                             │ ││
│  │ └─────────────────────────────────────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

**テキストエリア仕様:**

| Property | Value |
|----------|-------|
| Min height | 160px |
| Font | System default |
| Auto-grow | Yes |
| Padding | 16px |

### 5.4 File Tab

**State: Empty**
```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐  │
│  │                          📄                               │  │
│  │                 Drop file to translate                    │  │
│  │                   or click to browse                      │  │
│  │            .xlsx   .docx   .pptx   .pdf                   │  │
│  └─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘  │
└─────────────────────────────────────────────────────────────────┘
```

**State: Translating**
```
┌─────────────────────────────────────────────────────────────────┐
│  │  📊 report_2024.xlsx                                      │  │
│  │  Translating...                                     75%   │  │
│  │  ████████████████████████████████░░░░░░░░░░░░░░░░░        │  │
│                         [ Cancel ]                              │
└─────────────────────────────────────────────────────────────────┘
```

**State: Complete**
```
┌─────────────────────────────────────────────────────────────────┐
│  翻訳完了ダイアログ (Completion Dialog)                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ✓ 翻訳が完了しました                     45.2秒           ││
│  │                                                             ││
│  │  出力ファイル:                                              ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ 📊 report_2024_EN.xlsx                                 │││
│  │  │    翻訳ファイル          [開く] [フォルダで表示]         │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ 📊 report_2024_bilingual.xlsx                          │││
│  │  │    対訳ファイル          [開く] [フォルダで表示]         │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ 📋 report_2024_glossary.csv                            │││
│  │  │    用語集CSV            [開く] [フォルダで表示]          │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │                                                  [ 閉じる ] ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 5.5 出力ファイル命名

| Output Type | Input | Output |
|-------------|-------|--------|
| 翻訳ファイル (JP→EN) | `report.xlsx` | `report_translated.xlsx` |
| 対訳ファイル | `report.xlsx` | `report_bilingual.xlsx` |
| 用語集CSV | `report.xlsx` | `report_glossary.csv` |

**PDF対訳出力:**
| Output Type | Input | Output |
|-------------|-------|--------|
| 対訳PDF | `report.pdf` | `report_bilingual.pdf` |

### 5.6 カラーシステム (Material Design 3)

```css
:root {
  /* Primary - warm coral palette */
  --md-sys-color-primary: #C04000;
  --md-sys-color-primary-container: #FFDBD0;
  --md-sys-color-on-primary: #FFFFFF;
  --md-sys-color-on-primary-container: #3A0A00;

  /* Secondary */
  --md-sys-color-secondary: #77574D;
  --md-sys-color-secondary-container: #FFDBD0;

  /* Surface */
  --md-sys-color-surface: #FFFBFF;
  --md-sys-color-surface-container: #F3EDE9;
  --md-sys-color-surface-container-high: #EDE7E3;
  --md-sys-color-on-surface: #231917;
  --md-sys-color-on-surface-variant: #534340;

  /* Outline */
  --md-sys-color-outline: #85736E;
  --md-sys-color-outline-variant: #D8C2BC;

  /* Status */
  --md-sys-color-error: #BA1A1A;
  --md-sys-color-success: #2E7D32;
}
```

### 5.7 シェイプシステム

```css
:root {
  --md-sys-shape-corner-full: 9999px;   /* Pills, FABs */
  --md-sys-shape-corner-large: 16px;    /* Cards, Dialogs */
  --md-sys-shape-corner-medium: 12px;   /* Text fields */
  --md-sys-shape-corner-small: 8px;     /* Chips */
}
```

### 5.8 フォント

```css
font-family: 'Meiryo UI', 'Meiryo', 'Yu Gothic UI',
             'Hiragino Sans', 'Noto Sans JP', sans-serif;
```

---

## 6. サービスレイヤー

### 6.1 CopilotHandler

M365 Copilot との通信を担当。

```python
class CopilotHandler:
    COPILOT_URL = "https://m365.cloud.microsoft/chat/?auth=2"
    cdp_port = 9333  # Edge CDP専用ポート

    def connect(on_progress: Callable) -> bool:
        """
        1. Edgeが起動していなければ起動（専用プロファイル使用）
        2. Playwrightで接続
        3. Copilotページを開く
        4. チャット入力欄の準備完了を待機
        """

    def translate_sync(texts: list[str], prompt: str, reference_files: list[Path]) -> list[str]:
        """
        1. GPT-5トグルを有効化（送信前に確認）
        2. プロンプトをCopilotに送信（送信ボタン有効化を待機）
        3. 応答を待機（安定するまで）
        4. 結果をパース
        """

    def disconnect() -> None:
        """ブラウザ接続を終了"""

    def _ensure_gpt5_enabled(max_wait: float = 1.0) -> bool:
        """
        GPT-5トグルボタンを確認・有効化
        - 送信直前に呼び出し（遅延描画対応）
        - 複数の検出方法（CSS selector + JS parent traversal）
        - ボタンが見つからない場合は静かにスキップ（将来の変更対応）
        """
```

**Edge起動設定:**
- Profile: `%LOCALAPPDATA%/YakuLingo/EdgeProfile`
- CDP Port: 9333
- オプション: `--no-first-run --no-default-browser-check`

**ブラウザ操作の信頼性:**
- 固定sleep()の代わりにPlaywrightの`wait_for_selector`を使用
- 送信ボタン: `:not([disabled])`条件で有効化を待機
- メニュー表示: `div[role="menu"]`の表示を確認
- ファイル添付: 添付インジケータをポーリングで確認
- GPT-5トグル: 送信直前に状態確認・必要に応じて有効化

**Copilot文字数制限:**
- Free ライセンス: 8,000文字
- Paid ライセンス: 128,000文字

**動的プロンプト切り替え:**
プロンプトが`copilot_char_limit`（デフォルト: 7,500文字）を超える場合、自動的にファイル添付モードに切り替え：
1. プロンプトを一時ファイルとして保存
2. Copilotにファイルを添付
3. トリガーメッセージを送信: "Please follow the instructions in the attached file and translate accordingly."

これにより、FreeとPaidの両方のCopilotユーザーに対応。

### 6.2 TranslationService

翻訳処理の中心クラス。

```python
class TranslationService:
    processors = {
        '.xlsx': ExcelProcessor(),
        '.xls': ExcelProcessor(),
        '.docx': WordProcessor(),
        '.doc': WordProcessor(),
        '.pptx': PptxProcessor(),
        '.ppt': PptxProcessor(),
        '.pdf': PdfProcessor(),
    }

    def translate_text(text, reference_files) -> TextTranslationResult:
        """
        テキスト翻訳（言語自動検出）
        - 日本語入力 → 英語（複数オプション）
        - その他入力 → 日本語（解説付き）
        """

    def translate_file(input_path, reference_files, on_progress) -> TranslationResult:
        """
        1. プロセッサを取得
        2. テキストブロックを抽出
        3. バッチ翻訳実行
        4. 翻訳を適用して出力ファイル作成
        """

    def get_file_info(file_path) -> FileInfo:
        """ファイル情報取得"""
```

### 6.3 BatchTranslator

バッチ処理による効率的な翻訳。

```python
class BatchTranslator:
    MAX_BATCH_SIZE = 50         # ブロック数上限
    MAX_CHARS_PER_BATCH = 7000  # 文字数上限（Copilot Free 8000制限対応）

    def translate_blocks(blocks, reference_files, on_progress) -> dict[str, str]:
        """
        1. ブロックをバッチに分割
        2. 各バッチを翻訳
        3. 結果をマージ
        """
```

---

## 7. ファイルプロセッサ

### 7.1 FileProcessor (基底クラス)

```python
class FileProcessor(ABC):
    @property
    def file_type(self) -> FileType
    @property
    def supported_extensions(self) -> list[str]

    def get_file_info(file_path: Path) -> FileInfo
    def extract_text_blocks(file_path: Path) -> Iterator[TextBlock]
    def apply_translations(input_path, output_path, translations, direction) -> None

    def should_translate(text: str) -> bool:
        """翻訳対象判定（空文字、数値のみ等を除外）"""
```

### 7.2 翻訳判定クラス

#### CellTranslator

Excelセル、Word/PowerPointテーブルセル用の翻訳判定ロジック。

```python
class CellTranslator:
    SKIP_PATTERNS = [
        r'^[\d\s\.,\-\+\(\)\/]+$',           # 数値のみ
        r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$',    # 日付 (YYYY-MM-DD)
        r'^\d{1,2}[-/]\d{1,2}[-/]\d{4}$',    # 日付 (DD/MM/YYYY)
        r'^[\w\.\-]+@[\w\.\-]+\.\w+$',       # メールアドレス
        r'^https?://\S+$',                    # URL
        r'^[A-Z]{2,5}[-_]?\d+$',             # コード（ABC-123）
        r'^[\d\s%]+$',                        # パーセント付き数値
        r'^[¥$€£]\s*[\d,\.]+$',               # 通貨記号付き数値
        r'^\d+[年月日時分秒]',                  # 日本語日時
    ]

    def should_translate(text: str) -> bool:
        """スキップパターンに一致しなければ翻訳対象（2文字未満も除外）"""
```

#### ParagraphTranslator

Word/PowerPointの本文段落用の翻訳判定ロジック。

```python
class ParagraphTranslator:
    SKIP_PATTERNS = [
        r'^[\d\s\.,\-\+\(\)\/]+$',           # 数値のみ
        r'^https?://\S+$',                    # URL
        r'^[\w\.\-]+@[\w\.\-]+\.\w+$',       # メールアドレス
    ]

    def should_translate(text: str) -> bool:
        """スキップパターンに一致しなければ翻訳対象"""

    def apply_translation_to_paragraph(para, translated_text: str) -> None:
        """
        段落スタイルを保持しながら翻訳を適用
        - 最初のrunに翻訳テキストを設定
        - 残りのrunはクリア
        """
```

### 7.3 ExcelProcessor

```python
class ExcelProcessor(FileProcessor):
    """
    翻訳対象:
    - セル値（テキストのみ）
    - 図形テキスト
    - グラフタイトル

    保持:
    - 数式（翻訳しない）
    - セル書式（フォント、色、罫線）
    - 列幅、行高さ
    - 結合セル
    - 画像

    非対象:
    - シート名
    - コメント
    - ヘッダー/フッター

    追加機能:
    - create_bilingual_workbook(): 原文/訳文シートを並列配置
    - export_glossary_csv(): 翻訳ペアをCSV出力
    """
```

### 7.4 WordProcessor

```python
class WordProcessor(FileProcessor):
    """
    翻訳対象:
    - 本文段落 (ParagraphTranslator)
    - テーブルセル (CellTranslator - Excel互換ロジック)
    - テキストボックス (ParagraphTranslator)

    保持:
    - 段落スタイル（見出し、本文等）
    - テーブル構造・書式
    - 画像・位置
    - 箇条書き・番号リスト
    - ページレイアウト

    非対象:
    - ヘッダー/フッター（翻訳しない）

    追加機能:
    - create_bilingual_document(): 原文→訳文の段落を交互に配置
      - 【翻訳】ヘッダーで訳文セクションを明示
      - 罫線で原文/訳文を分離
    """
```

### 7.5 PptxProcessor

```python
class PptxProcessor(FileProcessor):
    """
    翻訳対象:
    - 図形テキスト (ParagraphTranslator)
    - テーブルセル (CellTranslator - Excel互換ロジック)
    - スピーカーノート (ParagraphTranslator)

    保持:
    - スライドレイアウト
    - アニメーション
    - トランジション
    - 画像・グラフ

    追加機能:
    - create_bilingual_presentation(): 原文→訳文のスライドを交互に配置
      - XML直接操作でスライドをマージ
      - presentation.xml.relsにリレーションを追加
    """
```

### 7.6 PdfProcessor

```python
class PdfProcessor(FileProcessor):
    """
    使用ライブラリ:
    - PyMuPDF (fitz): PDF読み書き
    - yomitoku: OCR/レイアウト解析（オプション）

    フォント設定（PDFMathTranslate準拠）:
    - ja: SourceHanSerifJP-Regular.ttf
    - en: Tiro
    - zh-CN: SourceHanSerifSC-Regular.ttf
    - ko: SourceHanSerifKR-Regular.ttf

    追加機能:
    - create_bilingual_pdf(): 原文→訳文のページを交互に配置
    - export_glossary_csv(): 翻訳ペアをCSV出力
    """
```

---

## 8. フォント管理

### 8.1 FontTypeDetector

元ファイルのフォント種類を自動検出。

**明朝系パターン:**
- Mincho, 明朝, Ming, Serif, Times, Georgia, Cambria, Palatino

**ゴシック系パターン:**
- Gothic, ゴシック, Sans, Arial, Helvetica, Calibri, Meiryo, メイリオ

### 8.2 フォントマッピング

| 翻訳方向 | 元フォント種類 | 出力フォント |
|---------|--------------|-------------|
| JP → EN | 明朝系 (default) | Arial |
| JP → EN | ゴシック系 | Calibri |
| EN → JP | セリフ系 (default) | MS P明朝 |
| EN → JP | サンセリフ系 | Meiryo UI |

### 8.3 フォントサイズ調整

| 翻訳方向 | 調整 | 最小サイズ |
|---------|-----|----------|
| JP → EN | −2pt | 6pt |
| EN → JP | なし | - |

**調整理由:** 英語は日本語より文字数が増える傾向があるため、レイアウト崩れを防ぐ。

---

## 9. プロンプト設計

### 9.1 PromptBuilder

```python
class PromptBuilder:
    def build(input_text, has_reference_files) -> str:
        """
        1. 言語を自動検出
        2. 適切なテンプレート選択（prompts/translate_*.txt）
        3. 参照ファイル指示を挿入（添付時のみ）
        4. 入力テキストを埋め込み
        """

    def build_batch(texts, has_reference_files) -> str:
        """番号付きリストとして入力"""
```

### 9.2 プロンプトテンプレート例（JP→EN）

```
Role Definition
あなたは日本語を英語に翻訳する、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Critical Rules (優先順位順)

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

2. 自然な翻訳
   - 読みやすく自然な英語に翻訳
   - 過度な省略は避ける

3. 数値表記（必須ルール）
   - 億 → oku (例: 4,500億円 → 4,500 oku yen)
   - 千単位 → k (例: 12,000 → 12k)
   - 負数 → () (例: ▲50 → (50))

{reference_section}

Input
{input_text}
```

### 9.3 参照ファイル指示

```
Reference Files
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
```

---

## 10. ストレージ

### 10.1 HistoryDB

翻訳履歴をSQLiteで永続化。

```python
class HistoryDB:
    """
    データベースパス: ~/.yakulingo/history.db

    テーブル: history
    - id: INTEGER PRIMARY KEY
    - source_text: TEXT
    - result_json: TEXT (TextTranslationResult をJSON化)
    - timestamp: TEXT (ISO format)
    - created_at: TIMESTAMP
    """

    def add_entry(entry: HistoryEntry) -> int:
        """履歴エントリを追加"""

    def get_recent(limit: int = 50) -> List[HistoryEntry]:
        """最近の履歴を取得"""

    def search(query: str) -> List[HistoryEntry]:
        """キーワード検索"""

    def delete_entry(entry_id: int) -> bool:
        """エントリを削除"""

    def clear_all() -> None:
        """全履歴を削除"""
```

### 10.2 データ保存場所

| データ | パス |
|--------|------|
| アプリ設定 | `config/settings.json` |
| 翻訳履歴 | `~/.yakulingo/history.db` |
| 参照ファイル | `glossary.csv`（デフォルト） |

---

## 11. 自動更新

### 11.1 AutoUpdater

GitHub Releases経由で自動更新。

```python
class AutoUpdater:
    """
    GitHub Releases APIを使用した自動更新

    機能:
    - バージョンチェック
    - ダウンロード（プログレス付き）
    - インストール（ZIP展開）
    - Windows NTLMプロキシ対応
    """

    def check_for_updates() -> Optional[VersionInfo]:
        """最新バージョンをチェック"""

    def download_update(version_info: VersionInfo, on_progress: Callable) -> Path:
        """アップデートをダウンロード"""

    def install_update(downloaded_path: Path) -> bool:
        """アップデートをインストール"""
```

### 11.2 プロキシ対応

```python
# Windowsシステムプロキシを自動検出
# レジストリから設定を読み取り

# NTLM認証プロキシ対応（pywin32が必要）
if HAS_PYWIN32:
    # SSPI経由でNTLM認証
```

### 11.3 更新フロー

```
1. アプリ起動時にバックグラウンドでバージョンチェック
2. 新バージョンがあれば通知を表示
3. ユーザーが「更新」をクリック
4. バックグラウンドでダウンロード（プログレス表示）
5. ダウンロード完了後、インストール確認
6. アプリ再起動で更新完了
```

---

## 12. 設定・配布

### 12.1 AppSettings

```python
@dataclass
class AppSettings:
    # Reference Files (用語集、参考資料など)
    reference_files: list[str] = ["glossary.csv"]
    output_directory: Optional[str] = None  # None = 入力と同じ

    # UI
    last_tab: str = "text"
    window_width: int = 1100
    window_height: int = 750

    # Advanced
    max_batch_size: int = 50
    max_chars_per_batch: int = 7000      # Copilot Free 8000制限対応
    request_timeout: int = 120
    max_retries: int = 3

    # Copilot License
    copilot_char_limit: int = 7500       # ファイル添付切り替え閾値

    # Auto Update
    auto_update_enabled: bool = True
    auto_update_check_interval: int = 86400  # 24時間
    github_repo_owner: str = "minimo162"
    github_repo_name: str = "yakulingo"
    last_update_check: Optional[str] = None
    skipped_version: Optional[str] = None
```

**設定ファイル:** `config/settings.json`

### 12.2 起動方法

```bash
# 開発環境
python app.py

# 配布版
run.vbs
```

### 12.3 起動フロー

```
1. pywebviewでネイティブウィンドウを起動
2. NiceGUIサーバー起動（port=8765）
3. Copilot接続開始（バックグラウンド）
4. 自動更新チェック（バックグラウンド）
5. 接続完了後、翻訳機能が有効化
```

### 12.4 システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.11+ |
| Browser | Microsoft Edge |
| M365 | Copilot アクセス権 |

### 12.5 依存パッケージ

```
nicegui>=1.4.0
pywebview>=5.0.0
playwright>=1.40.0
openpyxl>=3.1.0
python-docx>=1.1.0
python-pptx>=0.6.23
PyMuPDF>=1.24.0
pillow>=10.0.0
numpy>=1.24.0
```

### 12.6 オプション依存

```
# OCRサポート
yomitoku>=0.8.0

# Windows NTLMプロキシ
pywin32>=306

# テスト
pytest>=8.0.0
pytest-cov>=5.0.0
pytest-asyncio>=0.23.0
```

### 12.7 配布

ネットワーク共有からのワンクリックインストール対応。

```bash
# 配布パッケージ作成
make_distribution.bat

# 出力
share_package/
├── setup.vbs          # ユーザー実行ファイル
├── YakuLingo_*.zip    # 配布パッケージ
└── .scripts/
    └── setup.ps1      # インストールスクリプト
```

詳細は `DISTRIBUTION.md` を参照。

---

## 13. パフォーマンス最適化

### 13.1 起動時間最適化

#### 遅延インポート (Lazy Import)

重いモジュールの読み込みを初回アクセス時まで遅延させることで、起動時間を短縮。

```python
# yakulingo/processors/__init__.py
_LAZY_IMPORTS = {
    'ExcelProcessor': 'excel_processor',
    'WordProcessor': 'word_processor',
    'PptxProcessor': 'pptx_processor',
    'PdfProcessor': 'pdf_processor',
}

_SUBMODULES = {'excel_processor', 'word_processor', 'pptx_processor', 'pdf_processor'}

def __getattr__(name: str):
    """遅延ロード: 初回アクセス時にモジュールをインポート"""
    import importlib
    if name in _SUBMODULES:
        return importlib.import_module(f'.{name}', __package__)
    if name in _LAZY_IMPORTS:
        module_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(f'.{module_name}', __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**適用パッケージ:**
- `yakulingo.processors` - ファイルプロセッサ（Excel, Word, PowerPoint, PDF）
- `yakulingo.services` - サービス（CopilotHandler, AutoUpdater等）
- `yakulingo.ui` - UIコンポーネント（YakuLingoApp等）

**`_SUBMODULES`パターン:**
`unittest.mock.patch`でサブモジュールをパッチする場合に必要。これにより`patch('yakulingo.processors.excel_processor')`が正常に動作する。

### 13.2 ランタイム最適化

#### 正規表現の事前コンパイル

頻繁に使用される正規表現パターンをモジュールレベルで事前コンパイル。

```python
# yakulingo/ui/utils.py
_RE_BOLD = re.compile(r'\*\*([^*]+)\*\*')
_RE_QUOTE = re.compile(r'"([^"]+)"')
_RE_TRANSLATION_TEXT = re.compile(r'訳文:\s*(.+?)(?=解説:|$)', re.DOTALL)
_RE_EXPLANATION = re.compile(r'解説:\s*(.+)', re.DOTALL)

# yakulingo/services/translation_service.py
_RE_MULTI_OPTION = re.compile(r'\[(\d+)\]\s*訳文:\s*(.+?)\s*解説:\s*(.+?)(?=\[\d+\]|$)', re.DOTALL)
_RE_MARKDOWN_SEPARATOR = re.compile(r'\n?\s*[\*\-]{3,}\s*')

# yakulingo/services/copilot_handler.py
_RE_NUMBERING_PREFIX = re.compile(r'^\d+\.\s*(.+)')
```

**最適化効果:**
- 毎回の`re.compile()`呼び出しを回避
- 複数回使用時のパターンコンパイルコストを削減

#### 遅延コンパイルパターン

使用頻度が低いパターンは遅延コンパイルで初回使用時のみコンパイル。

```python
# yakulingo/processors/font_manager.py
class FontTypeDetector:
    _compiled_mincho: Optional[list] = None
    _compiled_gothic: Optional[list] = None

    @classmethod
    def _get_mincho_patterns(cls) -> list:
        if cls._compiled_mincho is None:
            cls._compiled_mincho = [
                re.compile(p, re.IGNORECASE)
                for p in cls.MINCHO_PATTERNS
            ]
        return cls._compiled_mincho
```

#### 句読点判定の最適化

`unicodedata`カテゴリの先頭文字チェックで句読点判定を高速化。

```python
# Before (遅い)
def _is_punctuation(char: str) -> bool:
    cat = unicodedata.category(char)
    return cat.startswith('P')  # 文字列メソッド呼び出し

# After (高速)
def _is_punctuation(char: str) -> bool:
    cat = unicodedata.category(char)
    return cat[0] == 'P'  # 直接インデックスアクセス
```

### 13.3 データベース最適化

#### スレッドローカル接続プーリング

SQLite接続をスレッドごとに再利用し、接続オーバーヘッドを削減。

```python
# yakulingo/storage/history_db.py
class HistoryDB:
    _local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path,
                timeout=DB_TIMEOUT,
                check_same_thread=False
            )
            self._local.conn.execute('PRAGMA journal_mode=WAL')
        return self._local.conn
```

**WALモード:**
Write-Ahead Loggingモードにより、読み取りと書き込みの並行実行が可能。

### 13.4 パフォーマンス測定

起動時間の測定:
```bash
python -c "import time; t=time.time(); from yakulingo.ui import run_app; print(f'Import: {time.time()-t:.3f}s')"
```

---

## 変更履歴

| Version | Date | Changes |
|---------|------|---------|
| 2.5 | 2025-12 | パフォーマンス最適化（遅延インポート、正規表現事前コンパイル、DB接続プーリング）、ウィンドウサイズ設定対応 |
| 2.4 | 2025-12 | 対訳出力・用語集CSV機能追加（全ファイル形式対応）、翻訳完了ダイアログ改善（出力ファイル一覧・アクションボタン） |
| 2.3 | 2025-12 | Copilot Free対応（動的プロンプト切り替え）、コード品質向上（例外処理、リソース管理、定数化） |
| 2.2 | 2025-12 | 参照ファイル機能拡張（用語集→汎用参照ファイル対応）、設定項目追加 |
| 2.1 | 2025-11 | 言語自動検出、翻訳履歴、自動更新、M3デザイン対応 |
| 2.0 | 2024-11 | 実装コードに基づく完全な仕様書作成 |

---

> この仕様書は実装コードから自動生成されたものです。
> コードとの差異がある場合は、実装コードが正となります。
