# YakuLingo - 技術仕様書

> **Version**: 0.0.1
> **Date**: 2025-12-13
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
| **File Translation** | Excel/Word/PowerPoint/PDF/TXT の一括翻訳 |
| **Layout Preservation** | 翻訳後もファイルの体裁を維持 |
| **Bilingual Output** | 原文と訳文を並べた対訳ファイルを自動生成 |
| **Glossary Export** | 翻訳ペアをCSVで出力（用語管理に活用） |
| **Reference Files** | 用語集・スタイルガイド・参考資料による一貫した翻訳（同梱glossaryの使用ON/OFF切替可） |
| **Translation History** | 過去の翻訳をローカルに保存・検索 |
| **Auto Update** | GitHub Releases経由で自動更新 |

### 1.3 言語自動検出

入力テキストの言語をM365 Copilotで自動検出し、適切な方向に翻訳：

| 入力言語 | 出力 |
|---------|------|
| 日本語 | 英語（3スタイル比較表示） |
| その他 | 日本語（解説付き、アクションボタン付き） |

**検出メカニズム:**
- `detect_language()`: ローカルのみで検出（Copilot呼び出しなし、高速）
  - ひらがな/カタカナ検出 → 日本語
  - ハングル検出 → 韓国語
  - ラテン文字優勢 → 英語
  - CJKのみ（仮名なし） → 日本語（ターゲットユーザー向けデフォルト）
  - その他/混合 → 日本語（フォールバック）

### 1.4 対応ファイル形式

| 形式 | 拡張子 | ライブラリ |
|------|--------|----------|
| Excel | `.xlsx` `.xls` | xlwings (Win/Mac) / openpyxl (fallback) |
| Word | `.docx` | python-docx（*.doc* は未対応） |
| PowerPoint | `.pptx` `.ppt` | python-pptx |
| PDF | `.pdf` | PyMuPDF, pdfminer.six, PP-DocLayout-L (PaddleOCR) |
| Text | `.txt` | Built-in (plain text) |
| Outlook | `.msg` | win32com (Windows + Outlook環境のみ) |

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
│  │ (Edge+        │     │ Excel/Word/PPT/PDF │     │   (SQLite)    │    │
│  │  Playwright)  │     │ + TXT              │     │               │    │
│  └───────────────┘     └─────────────────────┘     └───────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 レイヤー責務

| Layer | Responsibility |
|-------|----------------|
| **Presentation** | NiceGUI + pywebviewによるUI、状態表示 |
| **Service** | 翻訳処理の制御、バッチ処理、自動更新 |
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
│   │   ├── styles.css              # 静的CSS（グローバルスタイル）
│   │   ├── utils.py                # UI utilities (temp files, dialogs, text formatting)
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
│   │   ├── pdf_font_manager.py     # PDFフォント置換・選択
│   │   ├── pdf_operators.py        # PDFオペレーター生成ユーティリティ
│   │   ├── excel_processor.py
│   │   ├── word_processor.py
│   │   ├── pptx_processor.py
│   │   ├── pdf_processor.py
│   │   └── txt_processor.py
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
├── tests/                          # テストスイート（33ファイル）
│   ├── conftest.py
│   └── test_*.py
│
├── prompts/                        # 翻訳プロンプト（19ファイル）
│   ├── translation_rules.txt       # 共通翻訳ルール
│   ├── detect_language.txt         # 言語検出用（現在未使用、ローカル検出を優先）
│   ├── copilot_injection_review.md # プロンプトのインジェクションリスクレビュー
│   ├── file_translate_to_en_{standard|concise|minimal}.txt  # ファイル翻訳（日→英）
│   ├── file_translate_to_jp.txt    # ファイル翻訳用（英→日）
│   ├── text_translate_to_en_{standard|concise|minimal}.txt  # テキスト翻訳（日→英）
│   ├── text_translate_to_en_compare.txt  # テキスト翻訳（日→英、3スタイル比較）
│   ├── text_translate_to_jp.txt    # テキスト翻訳用（英→日、解説付き/共通ルール挿入）
│   ├── adjust_custom.txt           # カスタムリクエスト
│   ├── text_alternatives.txt       # フォローアップ: 他の言い方
│   ├── text_review_en.txt          # フォローアップ: 英文をチェック
│   ├── text_check_my_english.txt   # フォローアップ: ユーザー編集英文チェック
│   ├── text_summarize.txt          # フォローアップ: 要点を教えて
│   ├── text_question.txt           # フォローアップ: 質問への回答
│   └── text_reply_email.txt        # フォローアップ: 返信メール作成
│
├── config/
│   └── settings.template.json      # 設定テンプレート
│
├── glossary.csv                    # デフォルト参照ファイル（用語集）
│
├── packaging/                      # 配布・ビルド関連
│   ├── installer/                  # ネットワーク共有インストーラ
│   ├── launcher/                   # ネイティブランチャー（Rust製）
│   │   ├── Cargo.toml              # Rust プロジェクト設定
│   │   └── src/main.rs             # ランチャーソースコード
│   ├── install_deps.bat            # 依存関係インストール
│   └── make_distribution.bat       # 配布パッケージ作成
│
└── docs/
    ├── DISTRIBUTION.md             # 配布ガイド
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
    TEXT = "text"

class TranslationStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TranslationPhase(Enum):
    EXTRACTING = "extracting"      # テキスト抽出中
    OCR = "ocr"                    # OCR処理中（PDF）
    TRANSLATING = "translating"    # 翻訳中
    APPLYING = "applying"          # 翻訳適用中
    COMPLETE = "complete"          # 完了

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
class SectionDetail:
    """セクション詳細（シート、ページ、スライド）- 部分翻訳対応"""
    index: int        # セクションインデックス
    name: str         # セクション名
    selected: bool = True  # 翻訳対象として選択されているか

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
    section_details: list[SectionDetail]  # 部分翻訳用セクション情報

    @property
    def selected_block_count(self) -> int:
        """選択されたセクションのテキストブロック数を計算"""

@dataclass
class TranslationProgress:
    current: int
    total: int
    status: str
    phase: TranslationPhase = TranslationPhase.TRANSLATING
    phase_detail: str = ""        # 詳細（例: "Page 3/10", "Batch 2/5"）
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
    file_size: int = 0
    requires_reinstall: bool = False  # [REQUIRES_REINSTALL]マーカー検出時

@dataclass
class BatchTranslationResult:
    """バッチ翻訳結果の詳細"""
    translations: dict[str, str]           # block_id -> translated_text
    untranslated_block_ids: list[str]      # 翻訳されなかったブロック
    mismatched_batch_count: int = 0        # バッチ結果数の不一致回数

    @property
    def has_issues(self) -> bool:
        """翻訳に問題があったかどうか"""

    @property
    def success_rate(self) -> float:
        """成功率を計算"""
```

### 4.3 アプリケーション状態

```python
# UI状態列挙型 (yakulingo/ui/state.py)
class Tab(Enum):
    TEXT = "text"
    FILE = "file"

class FileState(Enum):
    EMPTY = "empty"
    SELECTED = "selected"
    TRANSLATING = "translating"
    COMPLETE = "complete"
    ERROR = "error"

class TextViewState(Enum):
    INPUT = "input"    # 大きな入力エリア（2カラム幅）
    RESULT = "result"  # コンパクト入力 + 結果パネル

@dataclass
class AppState:
    # テキストタブ
    source_text: str = ""
    text_result: Optional[TextTranslationResult] = None
    text_translating: bool = False
    text_view_state: TextViewState = TextViewState.INPUT
    text_translation_elapsed_time: Optional[float] = None

    # ファイルタブ
    file_state: FileState = FileState.EMPTY
    selected_file: Optional[Path] = None
    file_info: Optional[FileInfo] = None
    file_output_language: str = "en"  # or "jp"
    translation_progress: float = 0.0
    translation_status: str = ""
    output_file: Optional[Path] = None
    error_message: str = ""

    # 参照ファイル
    reference_files: List[Path] = field(default_factory=list)

    # Copilot接続
    copilot_ready: bool = False

    # 翻訳履歴（SQLiteバック）
    history: list[HistoryEntry] = field(default_factory=list)
    history_drawer_open: bool = False

    # メソッド
    def can_translate(self) -> bool: ...
    def is_translating(self) -> bool: ...
    def add_to_history(self, entry: HistoryEntry) -> None: ...
    def delete_history_entry(self, entry_id: int) -> None: ...
    def toggle_section_selection(self, index: int) -> None: ...
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

### 5.3 ローディング画面

アプリケーション起動時に即座にローディング画面を表示し、UIの準備完了を待機。

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                                                                 │
│                          ⋯ (spinner)                            │
│                          YakuLingo                              │
│                                                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

NiceGUIの`await client.connected()`パターンを使用して、クライアント接続後にメインUIをレンダリング。

### 5.4 Text Tab

**統一UI構造（英訳・和訳共通）:**
```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 原文                                                   [📋]││
│  │ "入力テキスト..."                                           ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ⋯ 🇯🇵 日本語から🇺🇸 英語へ翻訳中...    ← 翻訳状態（翻訳中）   │
│  ✓ 🇯🇵 日本語から🇺🇸 英語へ翻訳しました [3.2秒] ← 翻訳状態（完了）│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ "Translation text / 日本語訳..."               [📋] [戻し訳]││
│  │ Explanation / 解説...                                       ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  💡 [🔄 再翻訳]                         ← 吹き出し風ヒント      │
│                                                                 │
│  [オプション1]                          ← 単独オプションスタイル│
│  [オプション2]                                                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐ [↑]  │
│  │ 例: ...                     （縦幅いっぱいに拡張）     │      │
│  └──────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

**原文セクション:**
- 翻訳結果パネル上部に原文テキストを表示
- コピーボタンで原文をクリップボードにコピー

**翻訳状態表示:**
- 翻訳中: 「⋯ 🇯🇵 日本語から🇺🇸 英語へ翻訳中...」（スピナー付き）
- 完了後: 「✓ 翻訳しました」+ 経過時間バッジ
- 言語判定中: 「🔍 言語を判定しています...」

**日本語入力時（英訳）:**
- 結果カード: 3スタイルの訳文（標準/簡潔/最簡潔）を縦並び表示
- ?? [再翻訳]: 吹き出し風ヒント行
- 追加入力: 「アレンジした英文をチェック」入力欄

**その他入力時（和訳）:**
- 結果カード: 訳文 + 解説
- 💡 [再翻訳]: 吹き出し風ヒント行
- 追加入力: 「返信文を作成」入力欄

**テキストエリア仕様:**

| Property | Value |
|----------|-------|
| Min height | 160px |
| Font | System default |
| Auto-grow | Yes |
| Padding | 16px |

**アクションボタン（和訳）:**
| ボタン | 機能 |
|--------|------|
| 返信文を作成 | 返信文の草案を作成 |

### 5.5 File Tab

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

### 5.6 出力ファイル命名

| Output Type | Input | Output |
|-------------|-------|--------|
| 翻訳ファイル (JP→EN) | `report.xlsx` | `report_translated.xlsx` |
| 対訳ファイル | `report.xlsx` | `report_bilingual.xlsx` |
| 用語集CSV | `report.xlsx` | `report_glossary.csv` |

**PDF対訳出力:**
| Output Type | Input | Output |
|-------------|-------|--------|
| 対訳PDF | `report.pdf` | `report_bilingual.pdf` |

### 5.7 ウィンドウサイズ

**固定サイズ:** 1400×850 ピクセル（ノートPC 1920×1200 向けに設計）

**特徴:**
- **固定サイズ**: 動的なスケーリングは行わない
- **外部モニター対応**: 外部モニターへのスケーリングはOSのDPI設定に任せる
- **設定ファイル**: `window_width`/`window_height`（デフォルト: 1400×850）で変更可能

### 5.8 カラーシステム (Material Design 3)

```css
:root {
  /* Primary - Professional indigo palette */
  --md-sys-color-primary: #4355B9;
  --md-sys-color-primary-container: #DEE0FF;
  --md-sys-color-on-primary: #FFFFFF;
  --md-sys-color-on-primary-container: #00105C;

  /* Secondary - Neutral blue-gray */
  --md-sys-color-secondary: #595D72;
  --md-sys-color-secondary-container: #DDE1F9;

  /* Surface */
  --md-sys-color-surface: #FEFBFF;
  --md-sys-color-surface-container: #F2EFF4;
  --md-sys-color-surface-container-high: #ECE9EE;
  --md-sys-color-on-surface: #1B1B1F;
  --md-sys-color-on-surface-variant: #46464F;

  /* Outline */
  --md-sys-color-outline: #777680;
  --md-sys-color-outline-variant: #C7C5D0;

  /* Status */
  --md-sys-color-error: #BA1A1A;
  --md-sys-color-success: #1B6B3D;
}
```

### 5.9 シェイプシステム

```css
:root {
  --md-sys-shape-corner-full: 9999px;   /* Pills, FABs */
  --md-sys-shape-corner-large: 20px;    /* Cards, Dialogs */
  --md-sys-shape-corner-medium: 16px;   /* Inputs, Chips */
  --md-sys-shape-corner-small: 12px;    /* Small elements */
}
```

### 5.10 フォント

```css
font-family: 'Meiryo UI', 'Meiryo', 'Yu Gothic UI',
             'Hiragino Sans', 'Noto Sans JP', sans-serif;
```

---

## 6. サービスレイヤー

### 6.1 CopilotHandler

M365 Copilot との通信を担当。

```python
# スレッドセーフな遅延インポート管理
class PlaywrightManager:
    """Playwrightモジュールの遅延読み込み（インストールされていない場合のエラー回避）"""
    def get_playwright()       # playwright types と sync_playwright を返す
    def get_async_playwright() # async_playwright を返す
    def get_error_types()      # Playwright例外型を返す

# スレッド実行管理（greenletコンテキスト対応）
class PlaywrightThreadExecutor:
    """Playwright操作を専用スレッドで実行（asyncio.to_threadからの呼び出し対応）"""
    def start()               # ワーカースレッド開始
    def stop()                # スレッド停止
    def execute(func, *args, timeout=120)  # 関数を専用スレッドで実行

class CopilotHandler:
    COPILOT_URL = "https://m365.cloud.microsoft/chat/"
    cdp_port = 9333  # Edge CDP専用ポート

    def connect() -> bool:
        """
        1. Edgeが起動していなければ起動（専用プロファイル使用）
        2. Playwrightで接続（PlaywrightThreadExecutor経由）
        3. Copilotページを開く
        4. ログインページ判定（ステップ式タイムアウト）
        ※ セッション保持はEdgeProfileのCookiesが担当
        """

    def translate_sync(texts: list[str], prompt: str, reference_files: list[Path]) -> list[str]:
        """
        1. プロンプトをCopilotに送信（送信可能状態の安定化を待機）
        2. 応答を待機（安定するまで）
        3. 結果をパース
        """

    def translate_single(text: str, prompt: str, reference_files: list[Path]) -> str:
        """単一テキスト翻訳（生のレスポンスを返す）"""

    def disconnect() -> None:
        """ブラウザ接続を終了"""

    def ensure_gpt_mode() -> None:
        """
        GPT-5.2 Think Deeperモードを設定
        - 接続完了後、UI表示後に非同期で呼び出し（UIブロック回避）
        - ポーリング方式（100msごとにチェック、最大15秒）
        - ボタンが見つからない場合は静かにスキップ
        """
```

**Edge起動設定:**
- Profile: `%LOCALAPPDATA%/YakuLingo/EdgeProfile`
- CDP Port: 9333
- オプション: `--no-first-run --no-default-browser-check`

**ブラウザ操作の信頼性:**
- 固定sleep()の代わりにPlaywrightの`wait_for_selector`を使用
- 送信ボタン: 有効化と入力可能状態が一定時間安定するまで待機（添付中は継続）
- メニュー表示: `div[role="menu"]`の表示を確認
- ファイル添付: 添付インジケータをポーリングで確認
- GPTモード: UI表示後に`ensure_gpt_mode()`で非同期設定（wait_for_selector + JS一括実行）

**Copilot文字数制限:**
- Free ライセンス: 8,000文字
- Paid ライセンス: 128,000文字

**動的プロンプト切り替え:**
プロンプトが`max_chars_per_batch`（デフォルト: 4,000文字）を超える場合、自動的にファイル添付モードに切り替え：
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
        '.txt': TxtProcessor(),
    }

    def detect_language(text: str) -> str:
        """
        ローカルで言語を検出（Copilot呼び出しなし）
        - ひらがな/カタカナ → "日本語"
        - ハングル → "韓国語"
        - ラテン文字優勢 → "英語"
        - CJKのみ → "日本語"（デフォルト）
        """

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
    MAX_CHARS_PER_BATCH = 4000  # 文字数上限（信頼性向上のため縮小）

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
    使用ライブラリ:
    - Primary: xlwings (Windows/macOS、Excelインストール必要)
      - 図形、グラフ、テキストボックスのサポート
    - Fallback: openpyxl (Linux or Excelなし環境)
      - セルのみ対応

    翻訳対象:
    - セル値（テキストのみ）
    - 図形テキスト (xlwingsのみ)
    - グラフタイトル (xlwingsのみ)
    - グラフ軸タイトル (xlwingsのみ)

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
    - pdfminer.six: テキスト抽出、フォント種別判定（PDFMathTranslate準拠）
    - PP-DocLayout-L (PaddleOCR): レイアウト解析のみ（OCRは使用しない）

    単一パス抽出（PDFMathTranslate準拠）:
    - pdfminer: テキスト抽出（正確な文字データ、フォント情報、CID値）
    - PP-DocLayout-L: 段落検出、読み順、図表/数式の識別（LayoutArray生成）
    - _group_chars_into_blocks: LayoutArrayを参照して文字を段落にグループ化
    - TextBlock: 抽出結果を一元管理（PDF座標、フォント情報、段落情報）
    - OCRなし: スキャンPDFはサポート対象外

    TranslationCell廃止（PDFMathTranslate準拠）:
    - apply_translations: text_blocksパラメータでTextBlockを直接受け取り
    - apply_translations_with_cells: 廃止予定（警告ログを出力、後方互換性のみ維持）
    - DPIスケーリング不要: TextBlockはPDF座標を保持

    座標系の違いと変換:
    - PDF座標系: 左下原点、Y軸上向き (0,0 = 左下)
    - 画像座標系: 左上原点、Y軸下向き (0,0 = 左上)
    - 変換式: image_y = page_height - pdf_y
    - _group_chars_into_blocks: LayoutArrayを参照して座標変換・グループ化
    - テキスト結合順序: (y0, x0)でソートし読み順を保証（上→下、左→右）

    読み順推定（yomitokuスタイル）:
    - グラフベースの読み順推定アルゴリズム
    - ReadingDirection: TOP_TO_BOTTOM（横書き）、RIGHT_TO_LEFT（縦書き）、LEFT_TO_RIGHT（多段組み）
    - 距離度量による開始ノード選定（方向別の優先度計算）
    - 中間要素がある場合はエッジを作成しない（正確な読み順）
    - 優先度付きDFS: 親ノードがすべて訪問済みの場合のみ子ノードを訪問

    縦書き文書の自動検出:
    - detect_reading_direction(): アスペクト比から縦書き/横書きを自動判定
    - VERTICAL_TEXT_ASPECT_RATIO_THRESHOLD: 2.0（height/width > 2.0で縦書き要素）
    - VERTICAL_TEXT_COLUMN_THRESHOLD: 0.7（70%以上が縦書きなら縦書き文書）
    - estimate_reading_order_auto(): 自動検出と読み順推定を統合
    - apply_reading_order_to_layout_auto(): 自動検出とLayoutArray更新を統合

    PDFMathTranslate準拠機能:
    - 低レベルAPI: PDFオペレータを直接生成（高精度レイアウト制御）
    - 既存フォント再利用: PDFに埋め込まれたCID/Simpleフォントを検出・再利用
    - フォント種別判定: pdfminer.sixでCID vs Simpleフォントを判定
    - フォントサブセッティング: 未使用グリフを削除してファイルサイズを削減
    - Form XObjectテキスト除去: 全ページ翻訳時のみ文書全体フィルタを実行
      - 部分ページ翻訳は未選択ページ保護を優先し、XObjectフィルタをスキップ

    フォント種別に応じたエンコーディング:
    - EMBEDDED (新規埋め込み): has_glyph()でグリフID取得 → 4桁hex
    - CID (既存CIDフォント): ord(c)をそのまま4桁hex
    - SIMPLE (既存Simpleフォント): ord(c)を2桁hex

    フォールバックフォント:
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

フォント設定が簡略化され、翻訳方向のみで出力フォントを決定（元フォント種別は無視）。

| 翻訳方向 | 出力フォント |
|---------|-------------|
| JP → EN | Arial |
| EN → JP | MS Pゴシック |

> **Note**: 全ファイル形式（Excel, Word, PowerPoint, PDF）で共通の設定を使用。

### 8.3 フォントサイズ調整

| 翻訳方向 | 調整 | 最小サイズ |
|---------|-----|----------|
| JP → EN | なし (0pt) | 6pt |
| EN → JP | なし | - |

**備考:** フォントサイズ調整は設定で変更可能（`font_size_adjustment_jp_to_en`）。

---

## 9. プロンプト設計

### 9.1 PromptBuilder

```python
class PromptBuilder:
    _template_cache: dict[str, str] = {}  # テンプレートキャッシュ

    def build(input_text, has_reference_files) -> str:
        """
        1. 言語を自動検出
        2. 適切なテンプレート選択（prompts/file_translate_*.txt）
        3. 参照ファイル指示を挿入（添付時のみ）
        4. 入力テキストを埋め込み
        """

    def build_batch(texts, has_reference_files) -> str:
        """番号付きリストとして入力"""

    def get_text_template(style: str) -> str:
        """
        テンプレートをキャッシュから取得（初回はファイルから読み込み）
        - prompts/text_translate_to_en_{style}.txt
        - キャッシュにより毎回のファイルI/Oを回避
        """
```

**並列プロンプト構築（3バッチ以上）:**
```python
if len(batches) >= 3:
    with ThreadPoolExecutor(max_workers=4) as executor:
        prompts = list(executor.map(build_prompt, batches))
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

### 9.4 テキスト翻訳プロンプト（英訳/和訳）

- 英訳/和訳とも「ビジネス文書向け」を明記
- 既にターゲット言語の場合はそのまま出力
- `{translation_rules}` を両方向に挿入し、数値・記号ルールを統一
- 出力は「訳文」「解説」のみ。解説は日本語で簡潔に、見出し・ラベルなし
- 禁止事項は英訳/和訳で共通（質問・提案・指示の繰り返し・訳文と解説以外）

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
    # デフォルトで同梱のglossary.csvを参照
    reference_files: list[str] = field(default_factory=lambda: ["glossary.csv"])
    output_directory: Optional[str] = None  # None = 入力と同じ

    # UI
    last_tab: str = "text"
    window_width: int = 1400              # 3カラムレイアウト対応
    window_height: int = 850

    # Advanced
    max_chars_per_batch: int = 4000      # 信頼性向上のため縮小
    request_timeout: int = 600           # 10分（大規模翻訳対応）
    max_retries: int = 3

    # File Translation Options
    bilingual_output: bool = False       # 対訳出力（原文と翻訳を交互に配置）
    export_glossary: bool = False        # 対訳CSV出力（glossaryとして再利用可能）
    translation_style: str = "concise"   # ファイル翻訳の英訳スタイル

    # Text Translation Options
    use_bundled_glossary: bool = False        # 同梱glossary.csvを常に利用

    # Font Settings (全ファイル形式共通)
    font_size_adjustment_jp_to_en: float = 0.0  # pt（0で調整なし）
    font_size_min: float = 6.0                  # pt（最小フォントサイズ）
    font_jp_to_en: str = "Arial"                # 英訳時の出力フォント
    font_en_to_jp: str = "MS Pゴシック"         # 和訳時の出力フォント

    # PDF Layout Options (PP-DocLayout-L)
    ocr_batch_size: int = 5              # ページ/バッチ
    ocr_dpi: int = 200                   # レイアウト解析解像度
    ocr_device: str = "auto"             # "auto", "cpu", "cuda"

    # Auto Update
    auto_update_enabled: bool = True
    auto_update_check_interval: int = 86400  # 24時間
    github_repo_owner: str = "minimo162"
    github_repo_name: str = "yakulingo"
    last_update_check: Optional[str] = None
```

**設定ファイル:** `config/settings.json`

### 12.2 起動方法

```bash
# 開発環境
python app.py

# 配布版
YakuLingo.exe    # Rust製ネイティブランチャー
```

### 12.3 起動フロー

```
1. main()でmultiprocessing.freeze_support()を呼び出し（Windows/PyInstaller対応）
2. PYWEBVIEW_GUI=edgechromium環境変数を設定（ランタイムインストールダイアログ回避）
3. ロギング設定（コンソール出力）
4. NiceGUI importを遅延実行（ネイティブモードでの二重初期化を回避）
5. pywebviewでネイティブウィンドウを起動
6. ローディングスクリーンを即座に表示（await client.connected()後にUI構築）
7. NiceGUIサーバー起動（port=8765, reconnect_timeout=30.0）
8. Copilot接続開始（バックグラウンド、PlaywrightThreadExecutorで専用スレッド実行）
9. 自動更新チェック（バックグラウンド）
10. 接続完了後、翻訳機能が有効化
```

**起動最適化ポイント:**
- NiceGUI importを`main()`内に配置し、pywebviewのmultiprocessingによる二重初期化を回避
- `show=False`でブラウザ自動起動を抑制（ネイティブモードはpywebviewウィンドウを使用）
- ローディング画面を先行表示し、体感起動速度を向上
- ブラウザモード時はEdgeを`--app=`で起動し、タスクバーで`YakuLingo (UI)`として識別しやすくする

### 12.4 システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.11+ |
| Browser | Microsoft Edge |
| M365 | Copilot アクセス権 |

### 12.5 依存パッケージ

```
nicegui>=3.3.1
pywebview>=5.0.0
playwright>=1.40.0
openpyxl>=3.1.0
python-docx>=1.1.0
python-pptx>=0.6.23
PyMuPDF>=1.24.0
pdfminer.six>=20231228
pypdfium2>=4.30.0
pillow>=10.0.0
numpy>=1.24.0
```

### 12.6 オプション依存

```
# レイアウト解析サポート (PP-DocLayout-L)
paddleocr>=3.0.0
paddlepaddle>=3.0.0

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
packaging\make_distribution.bat

# 出力
share_package/
├── setup.vbs          # ユーザー実行ファイル
├── YakuLingo_*.zip    # 配布パッケージ
└── .scripts/
    └── setup.ps1      # インストールスクリプト
```

詳細は `docs/DISTRIBUTION.md` を参照。

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

#### WebSocket接続最適化

NiceGUIのWebSocket接続を安定化するため、`reconnect_timeout`を調整。

```python
# yakulingo/ui/app.py
ui.run(
    ...
    reconnect_timeout=30.0,  # デフォルト3秒から30秒に増加
)
```

**効果:**
- デフォルトの3秒ではping_interval=4秒、ping_timeout=2秒
- 30秒に設定すると接続の安定性が大幅に向上
- 長時間の翻訳操作中も接続が維持される

#### 非同期処理の最適化

すべての翻訳操作は`asyncio.to_thread()`でバックグラウンドスレッドにオフロードし、NiceGUIのイベントループをブロックしない。

```python
# yakulingo/ui/app.py
async def _translate_text(self):
    client = self._client  # 保存されたクライアント参照を使用

    result = await asyncio.to_thread(
        self.translation_service.translate_text_with_options,
        source_text,
        reference_files,
    )

    with client:  # UIコンテキストを復元
        self._refresh_content()
```

**重要**: NiceGUIの`context.client`は非同期タスク内で利用不可（スロットスタックが空）。
`@ui.page`ハンドラで`self._client = client`として保存し、非同期ハンドラで使用する。

**対象メソッド:**
- `_translate_text()` - テキスト翻訳
- `_back_translate()` - 戻し訳
- `_follow_up_action()` - フォローアップアクション
- `_translate_file()` - ファイル翻訳

#### Playwrightスレッドモデル

Playwrightのsync APIはgreenletを使用し、初期化されたスレッドでのみ動作する。
`PlaywrightThreadExecutor`シングルトンが専用スレッドで全Playwright操作を実行。

```python
# yakulingo/services/copilot_handler.py
def translate_sync(self, texts, prompt, ...) -> list[str]:
    # asyncio.to_thread()から呼ばれてもスレッド切り替えエラーを回避
    return _playwright_executor.execute(
        self._translate_sync_impl, texts, prompt, ...
    )
```

これにより、UIの`asyncio.to_thread()`から呼び出されても、
Playwright操作は常に正しいスレッドコンテキストで実行される。

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

### 2.19 (2025-12)
- PDF翻訳バグ修正
  - 非翻訳対象テキスト消失を修正
  - 番号パース失敗を修正
  - CID記法を日本語コンテンツとして認識
  - 日本語日時パターンの正規表現を修正
  - テーブルセル境界検出を改善
- 認証フロー改善
  - Copilotページ上の認証ダイアログを検出
  - 認証フロー中の強制ナビゲーションを防止
- Copilot送信プロセス最適化
  - Enterを最初の送信方法として使用（最小限のUI操作で送信）
  - 送信優先度: 1. Enter key → 2. JS click() → 3. Playwright click（force=True）
  - 送信ボタンが画面外（y: -5）にある場合はDOM click()でフォールバック
- UI改善
  - 「略語」表記を「用語集」に修正
  - main-cardのborder-radiusを無効化
  - ファイル翻訳パネルのホバーエフェクトを削除
- ログ出力改善
  - マルチプロセス対応でログ出力を修正
  - ログファイルのローテーションを廃止
  - ログファイルを起動ごとにクリア
- 用語集処理変更
  - abbreviations.csvをglossary.csvに統合
  - マージ方式からバックアップ＆上書き方式に変更
- Outlook MSG対応
  - Windows + Outlook環境でMSGファイル翻訳サポートを追加
- Excel翻訳最適化
  - セル読み取り効率化
  - 書き込み効率化
  - apply_translations最適化
  - 保存時にread_only_recommendedをクリア
- 言語検出高速化
  - Copilot呼び出しを廃止してローカル検出のみに
  - ファイル言語検出の高速化

### 2.18 (2025-12)
- コードレビュー修正
  - PlaywrightThreadExecutorシャットダウン競合を修正（`_thread_lock`でフラグ設定を保護）
  - translate_singleのタイムアウト不足を修正（`DEFAULT_RESPONSE_TIMEOUT + EXECUTOR_TIMEOUT_BUFFER`）
  - 自動ログイン検出の一時例外処理を改善（3回連続エラーまでリトライ）
  - ログイン待機のキャンセル機能を強化（`interruptible_sleep`関数）
  - PDF処理のMemoryErrorハンドリングを追加（明確な日本語エラーメッセージ）
  - Excelシート名アンダースコア解析問題を修正（安定したソート）
  - openpyxlリソースリーク可能性の軽減（FontManager初期化をwbオープン前に移動）
- 依存関係管理
  - clr-loaderのSSL証明書エラーを解決（pythonnetをpywebview依存から除外）
  - uv.tomlにdependency-metadataを追加
- install_deps.bat改善
  - プロキシなし環境でも使えるようにオプション化
  - if-else構文をgotoに変更して構文エラーを回避
- 翻訳結果UIの2カラム化
  - 3カラム（サイドバー+入力パネル+結果パネル）→2カラム（サイドバー+結果パネル）に簡素化
  - 翻訳結果表示時は入力パネルをCSSで非表示にし、結果パネルを中央配置
  - 新しい翻訳は「テキスト翻訳」タブをクリックしてINPUT状態に戻す
- Ctrl+Jヒントのフォントサイズを拡大
- ファイル翻訳完了画面から「新しいファイルを翻訳」ボタンを削除
- Copilot送信の信頼性向上
  - Enter送信前にフォーカスを再設定
  - 送信後に入力欄クリアを確認してリトライ
- ファイル翻訳ボタンを言語検出完了まで非アクティブ化
- 再翻訳後のフォローアップで原文が渡されない問題を修正

### 2.17 (2025-12)
- 英文チェック機能の解説を日本語で出力するよう修正
- ログインページの早期検出を実装（ユーザーにログインを促す）
- 翻訳結果パース時のCopilot出力混入を修正
- 送信可能状態の安定化待ちを追加（一定時間連続で有効化を確認）
- 翻訳結果画面でテキスト選択を有効にする

### 2.16 (2025-12)
- Copilot入力の信頼性向上（fill()メソッド、Enter優先+クリックフォールバック）
- Edge起動タイムアウトを6秒→20秒に延長
- 自動ログイン検出を改善し、不要なブラウザ前面表示を防止
- PP-DocLayout-L起動時の事前初期化でPlaywright競合を回避
- 翻訳結果カードUIを英訳・和訳で統一
- バッチサイズ縮小（7000→4000文字）で信頼性向上
- request_timeout延長（120秒→600秒）で大規模翻訳対応
- Excel COM接続の事前クリーンアップ追加

### 2.16 (2025-12)
- PDF翻訳: TranslationCellを廃止しTextBlockベースに移行（PDFMathTranslate準拠）
- PDF翻訳: 単一パス処理（二重変換を排除しコード簡素化）
- PDF翻訳: apply_translationsにtext_blocksパラメータ追加
- PDF翻訳: DPIスケーリング不要（TextBlockはPDF座標を保持）

### 2.15 (2025-12)
- PDF翻訳: yomitokuをPP-DocLayout-Lに置き換え（Apache-2.0、商用利用可）
- PDF翻訳: 23カテゴリのレイアウト検出（90.4% mAP@0.5）
- PDF翻訳: CPUでも動作可能（~760ms/ページ）

### 2.14 (2025-12)
- PDF翻訳: OCRを廃止しLayoutAnalyzerに切り替え（PDFMathTranslate準拠）
- PDF翻訳: pdfminerテキスト + PP-DocLayout-Lレイアウト
- フォント設定: 4設定→2設定に簡略化（翻訳方向のみで決定）
- フォント設定: PDF専用設定を廃止し全形式で共通設定を使用

### 2.13 (2025-12)
- PDF翻訳: 既存フォント再利用機能追加（PDFMathTranslate準拠）
- PDF翻訳: pdfminer.sixによるCID/Simpleフォント種別判定
- PDF翻訳: 高レベルAPIフォールバックを削除し低レベルAPIに統一

### 2.12 (2025-12)
- PDF翻訳精度向上（キャッシュ機構、数式検出、フォント調整の改善）
- 中国語→日本語翻訳時のスキップ判定を修正
- ファイル翻訳の言語選択UIラベルを明確化
- WindowsのDPIスケーリング対応を改善
- アプリ終了時のクリーンアップ処理を確実に実行
- Excel図形テキスト取得時のCOMオブジェクトアクセスを最適化
- 自動更新時にglossary.csvとsettings.jsonを上書きするように変更

### 2.11 (2025-12)
- ウィンドウサイズを固定（1400×850、ノートPC 1920×1200 向け）
- 動的スケーリングとCSSズームを削除し、OSのDPI設定に任せる
- 翻訳パネルのレイアウトを改善（2/3幅・中央揃え）
- 翻訳中と翻訳後の入力パネル表示を統一

### 2.10 (2025-12)
- セットアップ完了後にYakuLingoを自動起動
- AppDataのバックアップ処理を削除（設定ファイルは上書きされないため不要）
- フォント読み込み完了前にアイコンがテキスト表示される問題を修正
- 左カラムのタブを大きく見やすく改善
- 履歴プレビューの文字切り詰めをCSSに委任

### 2.10 (2025-12)
- UIのちらつき・表示問題修正（翻訳結果表示、Edgeウィンドウ）
- 履歴削除機能改善（1クリック削除、ボタン動作修正）
- 言語検出改善（英字+漢字混合テキストを日本語として正しく検出）
- PDF翻訳準備ダイアログの即時表示
- Copilotプロンプト送信の信頼性向上（送信可能状態の安定待ち、セレクタ変更検知）
- PP-DocLayout-Lオンデマンド初期化（起動時間約10秒短縮）
- 読み順推定アルゴリズム追加（グラフベース、トポロジカルソート）
- 縦書き文書の自動検出（yomitokuスタイル、アスペクト比ベース）
- 優先度付きDFS（yomitokuスタイル、親依存性を考慮）
- TableCellsDetection統合（テーブルセル境界検出）
- rowspan/colspan検出（座標クラスタリング）

### 2.9 (2025-12)
- 翻訳速度の最適化（テキスト・ファイル翻訳のポーリング間隔短縮）
- プロンプトテンプレートのキャッシュ機能追加（PromptBuilder）
- 3バッチ以上の並列プロンプト構築（ThreadPoolExecutor）

### 2.8 (2025-12)
- 翻訳結果パネルに原文セクションと翻訳状態表示を追加
- 入力欄を縦幅いっぱいに拡張

### 2.7 (2025-12)
- ローカル言語検出機能追加（`detect_language()`、Copilot呼び出しなし）
- 言語検出プロンプト追加（互換性のため保持、未使用）

### 2.6 (2025-12)
- ローディング画面追加、テキスト翻訳UI簡素化（3スタイル比較表示）
- 翻訳スタイル設定追加、Rust製ネイティブランチャー対応

### 2.5 (2025-12)
- パフォーマンス最適化（遅延インポート、正規表現事前コンパイル、DB接続プーリング）
- ウィンドウサイズ設定対応

### 2.4 (2025-12)
- 対訳出力・用語集CSV機能追加（全ファイル形式対応）
- 翻訳完了ダイアログ改善（出力ファイル一覧・アクションボタン）

### 2.3 (2025-12)
- Copilot Free対応（動的プロンプト切り替え）
- コード品質向上（例外処理、リソース管理、定数化）

### 2.2 (2025-12)
- 参照ファイル機能拡張（用語集→汎用参照ファイル対応）
- 設定項目追加

### 2.1 (2025-11)
- 言語自動検出、翻訳履歴、自動更新、M3デザイン対応

### 2.0 (2024-11)
- 実装コードに基づく完全な仕様書作成

---

> この仕様書は実装コードから自動生成されたものです。
> コードとの差異がある場合は、実装コードが正となります。
