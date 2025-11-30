# YakuLingo - 技術仕様書

> **Version**: 2.0
> **Date**: 2024-11
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
10. [設定・配布](#10-設定配布)

---

## 1. 概要

### 1.1 システム目的

YakuLingoは、日本語と英語の双方向翻訳を提供するデスクトップアプリケーション。
M365 Copilotを翻訳エンジンとして使用し、テキストとドキュメントファイルの翻訳をサポート。

### 1.2 主要機能

| 機能 | 説明 |
|------|------|
| **Text Translation** | テキストを入力して即座に翻訳 |
| **File Translation** | Excel/Word/PowerPoint/PDF の一括翻訳 |
| **Layout Preservation** | 翻訳後もファイルの体裁を維持 |
| **Reference Files** | 用語集による一貫した翻訳 |

### 1.3 対応ファイル形式

| 形式 | 拡張子 | ライブラリ |
|------|--------|----------|
| Excel | `.xlsx` `.xls` | openpyxl |
| Word | `.docx` `.doc` | python-docx |
| PowerPoint | `.pptx` `.ppt` | python-pptx |
| PDF | `.pdf` | PyMuPDF, yomitoku |

### 1.4 技術スタック

| Layer | Technology |
|-------|------------|
| UI | NiceGUI (Python) |
| Backend | FastAPI (via NiceGUI) |
| Translation | M365 Copilot (Playwright + Edge) |
| File Processing | openpyxl, python-docx, python-pptx, PyMuPDF |

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
│  │                           (NiceGUI)                               │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │   Header    │  │  Text Tab   │  │  File Tab   │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         Service Layer                             │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │ TranslationService        │ BatchTranslator                 │  │  │
│  │  │ + translate_text()        │ + translate_blocks()            │  │  │
│  │  │ + translate_file()        │                                 │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│          │                         │                         │          │
│          ▼                         ▼                         ▼          │
│  ┌───────────────┐     ┌─────────────────────┐     ┌───────────────┐    │
│  │ CopilotHandler│     │   File Processors   │     │  AppSettings  │    │
│  │ (Edge+        │     │ Excel/Word/PPT/PDF  │     │  (JSON)       │    │
│  │  Playwright)  │     │                     │     │               │    │
│  └───────────────┘     └─────────────────────┘     └───────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 レイヤー責務

| Layer | Responsibility |
|-------|----------------|
| **Presentation** | NiceGUIによるUI、タブ管理、状態表示 |
| **Service** | 翻訳処理の調整、バッチ処理、プログレス管理 |
| **CopilotHandler** | Edge起動、Playwright接続、メッセージ送受信 |
| **File Processors** | ファイル解析、テキスト抽出、翻訳適用 |
| **Config** | 設定読み込み/保存、参照ファイル管理 |

---

## 3. ディレクトリ構造

```
ECM_translate/
├── app.py                          # エントリーポイント
├── pyproject.toml
├── requirements.txt
│
├── ecm_translate/                  # メインパッケージ
│   ├── __init__.py
│   │
│   ├── ui/                         # Presentation Layer
│   │   ├── app.py                  # YakuLingoApp クラス
│   │   ├── state.py                # AppState, Tab, FileState
│   │   ├── styles.py               # CSS定義
│   │   └── components/
│   │       ├── header.py
│   │       ├── tabs.py
│   │       ├── text_panel.py
│   │       └── file_panel.py
│   │
│   ├── services/                   # Service Layer
│   │   ├── translation_service.py  # TranslationService
│   │   ├── copilot_handler.py      # CopilotHandler
│   │   └── prompt_builder.py       # PromptBuilder
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
│   ├── models/
│   │   └── types.py                # 型定義
│   │
│   └── config/
│       └── settings.py             # AppSettings
│
├── prompts/                        # 翻訳プロンプト
│   ├── translate_jp_to_en.txt
│   └── translate_en_to_jp.txt
│
├── config/
│   └── settings.json               # ユーザー設定
│
├── glossary.csv                    # 参照用語集
│
└── docs/
    └── SPECIFICATION.md            # この仕様書
```

---

## 4. データモデル

### 4.1 列挙型

```python
class TranslationDirection(Enum):
    JP_TO_EN = "jp_to_en"
    EN_TO_JP = "en_to_jp"

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

class Tab(Enum):
    TEXT = "text"
    FILE = "file"

class FileState(Enum):
    EMPTY = "empty"
    SELECTED = "selected"
    TRANSLATING = "translating"
    COMPLETE = "complete"
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

@dataclass
class TranslationResult:
    status: TranslationStatus
    output_path: Optional[Path]     # ファイル翻訳
    output_text: Optional[str]      # テキスト翻訳
    blocks_translated: int
    blocks_total: int
    duration_seconds: float
    error_message: Optional[str]
    warnings: list[str]
```

### 4.3 アプリケーション状態

```python
@dataclass
class AppState:
    # タブ
    current_tab: Tab = Tab.TEXT

    # 翻訳方向
    direction: TranslationDirection = TranslationDirection.JP_TO_EN

    # テキストタブ
    source_text: str = ""
    target_text: str = ""
    text_translating: bool = False

    # ファイルタブ
    file_state: FileState = FileState.EMPTY
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
```

---

## 5. UI仕様

### 5.1 ウィンドウ設定

| Property | Value |
|----------|-------|
| Host | 127.0.0.1 |
| Port | 8765 |
| Title | YakuLingo |
| Favicon | 🍎 |
| Theme | System preference (Light/Dark) |

### 5.2 全体レイアウト

```
┌─────────────────────────────────────────────────────────────────┐
│  🍎 YakuLingo                                        HEADER     │
├─────────────────────────────────────────────────────────────────┤
│  [ 📝 Text ]  [ 📁 File ]                            TAB BAR    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                        CONTENT AREA                             │
│                      (Tab-specific UI)                          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  ▸ Settings                                    COLLAPSIBLE      │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Text Tab

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌─────────────────────────┐       ┌─────────────────────────┐  │
│  │ 日本語               [✕]│       │ English             [📋]│  │
│  ├─────────────────────────┤       ├─────────────────────────┤  │
│  │                         │       │                         │  │
│  │   (Source Textarea)     │ [⇄]  │   (Target Textarea)     │  │
│  │                         │       │                         │  │
│  └─────────────────────────┘       └─────────────────────────┘  │
│                                                                 │
│                        [ Translate ]                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**テキストエリア仕様:**

| Property | Value |
|----------|-------|
| Min height | 250px |
| Font | Meiryo UI |
| Font size | 16px |
| Line height | 1.7 |
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
│  │  ✓ Translation Complete                                   │  │
│  │  📊 report_2024_EN.xlsx                                   │  │
│         [ Download ]              [ Translate Another ]         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.5 出力ファイル命名

| Direction | Input | Output |
|-----------|-------|--------|
| JP → EN | `report.xlsx` | `report_EN.xlsx` |
| EN → JP | `report.xlsx` | `report_JP.xlsx` |
| 既存時 | `report.xlsx` | `report_EN_2.xlsx` |

### 5.6 カラーシステム

**Light Mode:**
```css
--primary: #2563eb;
--primary-hover: #1d4ed8;
--bg: #ffffff;
--bg-secondary: #f8fafc;
--border: #e2e8f0;
--text: #1e293b;
--text-secondary: #64748b;
--success: #22c55e;
--error: #ef4444;
```

**Dark Mode:**
```css
--primary: #3b82f6;
--primary-hover: #60a5fa;
--bg: #0f172a;
--bg-secondary: #1e293b;
--border: #334155;
--text: #f1f5f9;
--text-secondary: #94a3b8;
--success: #4ade80;
--error: #f87171;
```

### 5.7 フォント

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
        1. プロンプトをCopilotに送信
        2. 応答を待機（安定するまで）
        3. 結果をパース
        """

    def disconnect() -> None:
        """ブラウザ接続を終了"""
```

**Edge起動設定:**
- Profile: `%LOCALAPPDATA%/YakuLingo/EdgeProfile`
- CDP Port: 9333
- オプション: `--no-first-run --no-default-browser-check`

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

    def translate_text(text, direction, reference_files) -> TranslationResult:
        """テキスト翻訳"""

    def translate_file(input_path, direction, reference_files, on_progress) -> TranslationResult:
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
    MAX_BATCH_SIZE = 50          # ブロック数上限
    MAX_CHARS_PER_BATCH = 10000  # 文字数上限

    def translate_blocks(blocks, direction, reference_files, on_progress) -> dict[str, str]:
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
    def build(direction, input_text, has_reference_files) -> str:
        """
        1. テンプレート読み込み（prompts/translate_*.txt）
        2. 参照ファイル指示を挿入（添付時のみ）
        3. 入力テキストを埋め込み
        """

    def build_batch(direction, texts, has_reference_files) -> str:
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

## 10. 設定・配布

### 10.1 AppSettings

```python
@dataclass
class AppSettings:
    reference_files: list[str] = ["glossary.csv"]
    output_directory: Optional[str] = None  # None = 入力と同じ
    last_direction: str = "jp_to_en"
    last_tab: str = "text"
    window_width: int = 900
    window_height: int = 700
    max_batch_size: int = 50
    request_timeout: int = 120
    max_retries: int = 3
```

**設定ファイル:** `config/settings.json`

### 10.2 起動方法

```bash
python app.py
# ブラウザで http://localhost:8765 を開く
```

### 10.3 起動フロー

```
1. NiceGUIサーバー起動（port=8765）
2. ブラウザで自動アクセス
3. Copilot接続開始（バックグラウンド）
4. 接続完了まで翻訳ボタンは disabled
5. 接続完了後、翻訳機能が有効化
```

### 10.4 システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.11+ |
| Browser | Microsoft Edge |
| M365 | Copilot アクセス権 |

### 10.5 依存パッケージ

```
nicegui>=1.4.0
playwright>=1.40.0
openpyxl>=3.1.0
python-docx>=1.0.0
python-pptx>=0.6.0
PyMuPDF>=1.24.0
```

---

## 変更履歴

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2024-11 | 実装コードに基づく完全な仕様書作成 |

---

> この仕様書は実装コードから自動生成されたものです。
> コードとの差異がある場合は、実装コードが正となります。
