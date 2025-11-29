# PDF翻訳機能 技術仕様書 v9.5

## 概要

本仕様書は、ECM_translateアプリケーションにPDF翻訳機能を追加するための技術仕様を定義する。

### 参照実装
- **レイアウト解析**: [yomitoku](https://github.com/kotaro-kinoshita/yomitoku-dev) - 日本語特化OCR・レイアウト解析
- **PDF再構築**: [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate) - 体裁維持PDF翻訳

### 設計方針
- yomitoku および PDFMathTranslate の実装に完全準拠
- 翻訳エンジンは既存のCopilot翻訳を使用（オリジナル実装）
- 簡易版は作成しない（全機能を実装）

---

## 1. システムアーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PDF Translation Pipeline                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────┐                                                        │
│  │   PDF入力     │                                                        │
│  └──────┬───────┘                                                        │
│         │                                                                 │
│         ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │ Phase 1: PDF読込 (yomitoku準拠)                               │       │
│  │  - load_pdf(pdf_path, dpi=200)                                │       │
│  │  - 出力: list[np.ndarray] (BGR形式)                           │       │
│  │  - pypdfium2 == 4.30.0 使用                                   │       │
│  └──────────────────────────────────────────────────────────────┘       │
│         │                                                                 │
│         ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │ Phase 2: レイアウト解析 (yomitoku準拠)                         │       │
│  │  - DocumentAnalyzer(device, visualize, reading_order, ...)    │       │
│  │  - 出力: DocumentAnalyzerSchema                               │       │
│  │    - paragraphs: list[ParagraphSchema]                        │       │
│  │    - tables: list[TableStructureRecognizerSchema]             │       │
│  │    - figures: list[FigureSchema]                              │       │
│  │    - words: list[WordPrediction]                              │       │
│  └──────────────────────────────────────────────────────────────┘       │
│         │                                                                 │
│         ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │ Phase 3: 数式保護 (PDFMathTranslate準拠)                       │       │
│  │  - vflag() による数式検出                                      │       │
│  │  - {v0}, {v1}, {v2}... プレースホルダー置換                    │       │
│  │  - 数式スタック管理 (var, varl, varf, vlen)                    │       │
│  └──────────────────────────────────────────────────────────────┘       │
│         │                                                                 │
│         ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │ Phase 4: Copilot翻訳 (オリジナル実装)                          │       │
│  │  - 既存 TranslationEngine 使用                                 │       │
│  │  - TSV形式: [Address]<TAB>[Text]                              │       │
│  │  - アドレス形式: P{page}_{order}, T{page}_{table}_{row}_{col} │       │
│  │  - SmartRetryStrategy による自動リトライ                       │       │
│  │  - IntelligentResponseParser (拡張版)                         │       │
│  │  - 用語集サポート (glossary.csv)                               │       │
│  └──────────────────────────────────────────────────────────────┘       │
│         │                                                                 │
│         ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │ Phase 5: PDF再構築 (PDFMathTranslate準拠)                      │       │
│  │  - PyMuPDF (fitz) によるPDF操作                                │       │
│  │  - gen_op_txt() によるPDFオペレータ生成                        │       │
│  │  - 言語別行高さ調整 (LANG_LINEHEIGHT_MAP)                      │       │
│  │  - 動的圧縮アルゴリズム (5%刻み)                               │       │
│  │  - フォント埋め込み (MS P明朝 / Arial)                          │       │
│  │  - 数式復元 ({v*} → 元の数式)                                  │       │
│  └──────────────────────────────────────────────────────────────┘       │
│         │                                                                 │
│         ▼                                                                 │
│  ┌──────────────┐                                                        │
│  │ 翻訳版PDF    │                                                        │
│  └──────────────┘                                                        │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 依存関係

### 新規追加パッケージ

```python
# requirements_pdf.txt

# yomitoku (レイアウト解析・OCR)
yomitoku >= 0.8.0

# yomitoku 依存関係
torch >= 2.5.0
torchvision >= 0.20.0
opencv-python >= 4.10.0.84
pypdfium2 == 4.30.0
pydantic >= 2.9.2
omegaconf >= 2.3.0
shapely >= 2.0.6
huggingface-hub >= 0.26.1

# PDF再構築
PyMuPDF >= 1.24.0

# フォント
# - Noto Sans JP (日本語)
# - Tiro Devanagari (Latin)
```

### システム要件

| 項目 | 要件 |
|------|------|
| Python | 3.10, 3.11, 3.12 (3.10 <= version < 3.13) |
| 画像解像度 | 短辺720px以上推奨 |

**注意**: デフォルトはCPU専用環境で動作。GPU高速化はオプション。

#### オプション: GPU高速化

| 項目 | 要件 |
|------|------|
| CUDA | 11.8以上 |
| VRAM | 8GB以上推奨 |
| 設定 | `device: "cuda"` に変更 |

---

## 3. Phase 1: PDF読込 (yomitoku準拠)

### 3.1 バッチ処理設定

大量ページのPDFを効率的に処理するため、バッチ処理を採用する。

| 設定項目 | 値 | 説明 |
|---------|-----|------|
| バッチサイズ | 5ページ | 一度にメモリに読み込むページ数 |
| 最大ページ数 | 制限なし | ページ数に上限なし |
| DPI | 200 (固定) | 精度優先のため固定値 |

### 3.2 ストリーミング読込

```python
import pypdfium2 as pdfium
import numpy as np
from typing import Iterator

BATCH_SIZE = 5  # バッチサイズ
DPI = 200       # 固定DPI

def iterate_pdf_pages(
    pdf_path: str,
    batch_size: int = BATCH_SIZE,
    dpi: int = DPI,
) -> Iterator[tuple[int, list[np.ndarray]]]:
    """
    PDFをバッチ単位でストリーミング読込

    Args:
        pdf_path: PDFファイルパス
        batch_size: バッチサイズ (デフォルト: 5)
        dpi: 解像度 (デフォルト: 200, 固定)

    Yields:
        (batch_start_page, list[np.ndarray]): バッチ開始ページ番号と画像リスト
    """
    pdf = pdfium.PdfDocument(pdf_path)
    total_pages = len(pdf)

    for batch_start in range(0, total_pages, batch_size):
        batch_end = min(batch_start + batch_size, total_pages)
        batch_images = []

        for page_idx in range(batch_start, batch_end):
            page = pdf[page_idx]
            # DPI固定で高精度レンダリング
            bitmap = page.render(scale=dpi / 72)
            img = bitmap.to_numpy()
            # RGB to BGR (OpenCV互換)
            img = img[:, :, ::-1].copy()
            batch_images.append(img)

        yield batch_start, batch_images

    pdf.close()

def get_total_pages(pdf_path: str) -> int:
    """総ページ数を取得"""
    pdf = pdfium.PdfDocument(pdf_path)
    total = len(pdf)
    pdf.close()
    return total
```

### 3.3 load_pdf 関数 (互換性維持)

```python
from yomitoku.data.functions import load_pdf

def load_pdf_document(pdf_path: str, dpi: int = 200) -> list[np.ndarray]:
    """
    PDFファイルを読み込み、ページ画像のリストを返す

    注意: 小規模PDF向け。大規模PDFはiterate_pdf_pages()を使用すること。

    Args:
        pdf_path: PDFファイルパス
        dpi: 解像度 (デフォルト: 200)

    Returns:
        list[np.ndarray]: BGR形式の画像配列リスト

    Note:
        - pypdfium2 == 4.30.0 を使用
        - 各ページは numpy.ndarray (BGR) として返される
        - OpenCV (cv2) との互換性あり
    """
    imgs = load_pdf(pdf_path, dpi=dpi)
    return imgs
```

### 3.2 画像形式

| 属性 | 値 |
|------|-----|
| 形式 | numpy.ndarray |
| カラー | BGR (OpenCV互換) |
| データ型 | uint8 |
| 形状 | (height, width, 3) |

---

## 4. Phase 2: レイアウト解析 (yomitoku準拠)

### 4.1 DocumentAnalyzer クラス

```python
from yomitoku import DocumentAnalyzer

analyzer = DocumentAnalyzer(
    configs={},                    # カスタムモデル設定 (dict)
    device="cpu",                  # "cpu" (デフォルト) または "cuda" (GPU高速化)
    visualize=True,                # 可視化画像生成
    ignore_meta=False,             # ヘッダー/フッター除外
    reading_order="auto",          # 読み順: "auto", "left2right", "top2bottom", "right2left"
    split_text_across_cells=False, # テーブルセル内テキスト再配置
)

# 解析実行
results, ocr_vis, layout_vis = analyzer(img)
```

### 4.2 DocumentAnalyzerSchema (出力構造)

```python
class DocumentAnalyzerSchema:
    paragraphs: list[ParagraphSchema]
    tables: list[TableStructureRecognizerSchema]
    figures: list[FigureSchema]
    words: list[WordPrediction]

    def to_json(self, path: str) -> None: ...
    def to_html(self, path: str, img: np.ndarray) -> None: ...
    def to_markdown(self, path: str) -> None: ...
    def to_csv(self, path: str) -> None: ...
```

### 4.3 ParagraphSchema

```python
class ParagraphSchema:
    box: list[float]      # [x1, y1, x2, y2] バウンディングボックス
    contents: str         # テキスト内容
    direction: str        # "horizontal" または "vertical"
    order: int            # 読み順 (0始まり)
    role: str             # 役割分類
```

#### role の値

| role | 説明 | 翻訳対象 |
|------|------|---------|
| `section_headings` | セクション見出し | Yes |
| `text` | 本文 | Yes |
| `page_header` | ページヘッダー | No (オプション) |
| `page_footer` | ページフッター | No (オプション) |
| `caption` | キャプション | Yes |

### 4.4 WordPrediction

```python
class WordPrediction:
    points: list[list[float]]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] 四角形
    content: str               # 認識テキスト
    direction: str             # "horizontal" または "vertical"
    rec_score: float           # 認識信頼度 (0-1)
    det_score: float           # 検出信頼度 (0-1)
```

### 4.5 TableStructureRecognizerSchema

```python
class TableStructureRecognizerSchema:
    box: list[float]           # [x1, y1, x2, y2]
    n_row: int                 # 行数
    n_col: int                 # 列数
    rows: list[...]            # 水平グリッド線
    cols: list[...]            # 垂直グリッド線
    cells: list[TableCellSchema]    # セルリスト
    order: int                      # 読み順

class TableCellSchema:
    row: int                   # 行インデックス
    col: int                   # 列インデックス
    row_span: int              # 行スパン
    col_span: int              # 列スパン
    box: list[float]           # [x1, y1, x2, y2]
    contents: str              # セル内テキスト
```

### 4.6 FigureSchema

```python
class FigureSchema:
    box: list[float]              # [x1, y1, x2, y2]
    order: int                    # 読み順
    paragraphs: list[...]         # 関連キャプション
    direction: str                # テキスト方向
```

### 4.7 バウンディングボックス形式

| 要素 | 形式 | 説明 |
|------|------|------|
| paragraphs, tables, figures | `[x1, y1, x2, y2]` | 軸平行矩形 |
| words | `[[x1,y1], [x2,y2], [x3,y3], [x4,y4]]` | 四角形 (回転対応) |

座標系: 左上原点、右方向+X、下方向+Y

---

## 5. Phase 3: 数式保護 (PDFMathTranslate準拠)

### 5.1 数式検出関数 vflag()

```python
import re
import unicodedata

# デフォルト数式フォントパターン (PDFMathTranslate converter.py:156-177 準拠)
DEFAULT_VFONT_PATTERN = (
    r"(CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|"
    r"TeX-|rsfs|txsy|wasy|stmary|"
    r".*Mono|.*Code|.*Ital|.*Sym|.*Math)"
)

# 数式として扱うUnicodeカテゴリ
FORMULA_UNICODE_CATEGORIES = [
    "Lm",  # Letter, modifier
    "Mn",  # Mark, nonspacing
    "Sk",  # Symbol, modifier
    "Sm",  # Symbol, math
    "Zl",  # Separator, line
    "Zp",  # Separator, paragraph
    "Zs",  # Separator, space
]

def vflag(font: str, char: str, vfont: str = None, vchar: str = None) -> bool:
    """
    文字が数式かどうかを判定

    PDFMathTranslate converter.py:156-177 準拠

    Args:
        font: フォント名
        char: 文字
        vfont: カスタム数式フォントパターン (正規表現)
        vchar: カスタム数式文字パターン (正規表現)

    Returns:
        True: 数式として扱う
        False: 通常テキストとして翻訳
    """
    # Rule 1: CID記法
    if re.match(r"\(cid:", char):
        return True

    # Rule 2: フォントベース検出
    font_pattern = vfont if vfont else DEFAULT_VFONT_PATTERN
    if re.match(font_pattern, font):
        return True

    # Rule 3: 文字クラス検出
    if vchar:
        if re.match(vchar, char):
            return True
    else:
        if char and unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
            return True

    return False
```

### 5.2 数式スタック管理

```python
class FormulaManager:
    """
    数式の保護と復元を管理

    PDFMathTranslate converter.py:175-181 準拠
    """

    def __init__(self):
        # 現在処理中
        self.vstk: list = []      # 現在の数式文字
        self.vlstk: list = []     # 現在の数式線
        self.vfix: float = 0      # Y座標オフセット

        # 保存済みスタック
        self.var: list[list] = []      # 数式文字グループ
        self.varl: list[list] = []     # 数式線グループ
        self.varf: list[float] = []    # Y座標オフセット
        self.vlen: list[float] = []    # 幅

    def protect(self, text: str) -> tuple[str, int]:
        """
        テキスト内の数式を {vN} プレースホルダーで置換

        Returns:
            (protected_text, formula_count)
        """
        # 数式を検出してプレースホルダーに置換
        formula_id = len(self.var)
        self.var.append(self.vstk)
        self.varl.append(self.vlstk)
        self.varf.append(self.vfix)

        # リセット
        self.vstk = []
        self.vlstk = []

        return f"{{v{formula_id}}}", formula_id

    def restore(self, text: str) -> str:
        """
        {vN} プレースホルダーを元の数式に復元

        PDFMathTranslate converter.py:409-420 準拠
        """
        pattern = r"\{\s*v([\d\s]+)\}"

        def replacer(match):
            vid = int(match.group(1).replace(" ", ""))
            # 元の数式データを使用して復元
            return self._render_formula(vid)

        return re.sub(pattern, replacer, text, flags=re.IGNORECASE)
```

### 5.3 プレースホルダー形式

| 形式 | 説明 | 例 |
|------|------|-----|
| `{v0}` | 最初の数式 | E = mc² |
| `{v1}` | 2番目の数式 | ∫f(x)dx |
| `{v 2}` | スペース許容 | Σ(n=1) |

正規表現: `r"\{\s*v([\d\s]+)\}"`

---

## 6. Phase 4: Copilot翻訳 (オリジナル実装)

### 6.1 既存エンジン統合

```python
# translate.py の既存クラスを使用

class TranslationEngine:
    """既存の翻訳エンジン"""

    def translate(
        self,
        prompt_header: str,
        japanese_cells: list[dict],  # {"address": "P1_1", "text": "..."}
        glossary_path: Path = None,
    ) -> TranslationResult: ...

class SmartRetryStrategy:
    """指数バックオフリトライ"""
    max_retries: int = 3

class IntelligentResponseParser:
    """レスポンスパーサー (拡張版)"""

    @staticmethod
    def parse_tsv(response: str) -> dict[str, str]:
        # 拡張: P#_#, T#_#_#_# 形式をサポート
        pass
```

### 6.2 アドレス形式

| 形式 | 説明 | 例 |
|------|------|-----|
| `R{row}C{col}` | Excelセル (既存) | R1C1, R10C5 |
| `P{page}_{order}` | PDF段落 | P1_1, P1_2, P2_1 |
| `T{page}_{table}_{row}_{col}` | PDFテーブルセル | T1_1_0_0, T1_1_0_1 |

### 6.3 IntelligentResponseParser 拡張

```python
# translate.py:435, 443, 465 の修正

# 変更前
if re.match(r"R\d+C\d+", address):

# 変更後 (Excel SHAPE形式も含む)
ADDRESS_PATTERN = r"(R\d+C\d+|P\d+_\d+|T\d+_\d+_\d+_\d+|SHAPE:\w+)"

if re.match(ADDRESS_PATTERN, address):
```

### 6.4 翻訳データ準備

```python
def prepare_translation_cells(
    results: DocumentAnalyzerSchema,
    page_num: int,
    include_headers: bool = False,
) -> list[dict]:
    """
    yomitoku結果をTranslationEngine形式に変換

    Args:
        results: DocumentAnalyzer出力
        page_num: ページ番号 (1始まり)
        include_headers: ヘッダー/フッターを含めるか

    Returns:
        list[dict]: [{"address": "P1_1", "text": "...", "box": [...], ...}, ...]
    """
    cells = []

    # 段落
    for para in sorted(results.paragraphs, key=lambda p: p.order):
        if not include_headers and para.role in ["page_header", "page_footer"]:
            continue

        cells.append({
            "address": f"P{page_num}_{para.order}",
            "text": para.contents,
            "box": para.box,
            "direction": para.direction,
            "role": para.role,
        })

    # テーブル
    for table in results.tables:
        for cell in table.cells:
            if cell.contents.strip():
                cells.append({
                    "address": f"T{page_num}_{table.order}_{cell.row}_{cell.col}",
                    "text": cell.contents,
                    "box": cell.box,
                    "direction": "horizontal",
                    "role": "table_cell",
                })

    return cells
```

### 6.5 TSV形式

```
P1_1	これは最初の段落です。
P1_2	これは2番目の段落です。
T1_1_0_0	表のセル内容
T1_1_0_1	別のセル
P2_1	2ページ目の段落です。
```

---

## 7. Phase 5: PDF再構築 (PDFMathTranslate準拠)

### 7.1 PDFオペレータ生成

```python
def gen_op_txt(font: str, size: float, x: float, y: float, rtxt: str) -> str:
    """
    PDFテキストオペレータを生成

    PDFMathTranslate converter.py:384-385 準拠

    Args:
        font: フォント名
        size: フォントサイズ
        x: X座標
        y: Y座標
        rtxt: 16進エンコードテキスト

    Returns:
        PDF演算子文字列

    PDF Operators:
        Tf: フォントとサイズを設定
        Tm: テキスト行列を設定 (位置決め)
        TJ: テキストを表示
    """
    return f"/{font} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "
```

### 7.2 言語別行高さマップ

```python
# PDFMathTranslate converter.py:376-380 準拠
# 本アプリでは日本語・英語のみ対応

LANG_LINEHEIGHT_MAP = {
    "ja": 1.1,   # 日本語
    "en": 1.2,   # 英語
}

DEFAULT_LINE_HEIGHT = 1.1
```

### 7.3 動的圧縮アルゴリズム

```python
def calculate_line_height(
    translated_text: str,
    box: list[float],
    font_size: float,
    lang_out: str,
) -> float:
    """
    テキストがボックスに収まるよう行高さを動的に調整

    PDFMathTranslate converter.py:512-515 準拠

    Algorithm:
        1. 言語別ベース行高さを取得
        2. 必要行数を計算
        3. 収まらない場合、5%刻みで圧縮
        4. 最小値 1.0 まで圧縮
    """
    x1, y1, x2, y2 = box
    height = y2 - y1

    # ベース行高さ
    line_height = LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    # 行数推定
    chars_per_line = (x2 - x1) / (font_size * 0.5)
    lines_needed = max(1, len(translated_text) / chars_per_line)

    # 動的圧縮
    while (lines_needed + 1) * font_size * line_height > height and line_height >= 1.0:
        line_height -= 0.05  # 5%刻みで圧縮

    return max(line_height, 1.0)
```

### 7.4 テキスト位置計算

```python
def calculate_text_position(
    box: list[float],
    line_index: int,
    font_size: float,
    line_height: float,
    dy: float = 0,
) -> tuple[float, float]:
    """
    テキストのY座標を計算

    PDFMathTranslate converter.py:519 準拠

    Formula:
        y = box_top + dy - (line_index * font_size * line_height)
    """
    x1, y1, x2, y2 = box

    x = x1
    y = y2 + dy - (line_index * font_size * line_height)

    return x, y
```

### 7.5 フォント管理

```python
# PDFMathTranslate high_level.py:187-203 準拠
# 本アプリでは日本語・英語のみ対応

# フォント定義
FONT_CONFIG = {
    "ja": {
        "name": "MS-PMincho",           # MS P明朝
        "path": "C:/Windows/Fonts/msmincho.ttc",
        "fallback": "msgothic.ttc",     # MS ゴシック (フォールバック)
    },
    "en": {
        "name": "Arial",                # Arial
        "path": "C:/Windows/Fonts/arial.ttf",
        "fallback": "times.ttf",        # Times New Roman (フォールバック)
    },
}

class FontManager:
    """デュアルフォントシステム (日本語: MS P明朝, 英語: Arial)"""

    def __init__(self, lang_out: str):
        """
        Args:
            lang_out: 出力言語 ("ja" or "en")
        """
        self.lang_out = lang_out
        self.font_config = FONT_CONFIG.get(lang_out, FONT_CONFIG["en"])
        self.font_id = {}

    def get_font_name(self) -> str:
        """出力言語に応じたフォント名を取得"""
        return self.font_config["name"]

    def get_font_path(self) -> str:
        """出力言語に応じたフォントパスを取得"""
        import os
        path = self.font_config["path"]
        if os.path.exists(path):
            return path
        # フォールバック
        fallback = self.font_config.get("fallback")
        if fallback:
            fallback_path = f"C:/Windows/Fonts/{fallback}"
            if os.path.exists(fallback_path):
                return fallback_path
        return None

    def embed_fonts(self, doc: fitz.Document) -> None:
        """
        全ページにフォントを埋め込み

        PDFMathTranslate high_level.py:187-203 準拠
        """
        font_path = self.get_font_path()
        font_name = self.get_font_name()

        for page in doc:
            self.font_id[font_name] = page.insert_font(
                fontname=font_name,
                fontfile=font_path,
            )

    def select_font(self, text: str) -> str:
        """
        テキストに応じたフォントを選択

        日本語文字を含む場合はMS P明朝、それ以外はArial
        """
        # 日本語文字 (ひらがな、カタカナ、漢字) を含むかチェック
        for char in text:
            if '\u3040' <= char <= '\u309F':  # ひらがな
                return FONT_CONFIG["ja"]["name"]
            if '\u30A0' <= char <= '\u30FF':  # カタカナ
                return FONT_CONFIG["ja"]["name"]
            if '\u4E00' <= char <= '\u9FFF':  # 漢字
                return FONT_CONFIG["ja"]["name"]
        return FONT_CONFIG["en"]["name"]
```

### 7.6 PDF再構築メイン処理

```python
import fitz  # PyMuPDF

def reconstruct_pdf(
    original_pdf_path: str,
    translations: dict[str, str],
    paragraph_data: list[dict],
    lang_out: str,
    output_path: str,
) -> None:
    """
    翻訳テキストでPDFを再構築

    Args:
        original_pdf_path: 元PDFパス
        translations: {"P1_1": "translated...", ...}
        paragraph_data: 段落データ (box含む)
        lang_out: 出力言語
        output_path: 出力PDFパス
    """
    doc = fitz.open(original_pdf_path)
    font_manager = FontManager(lang_out)

    # フォント埋め込み
    font_manager.embed_fonts(doc)

    for page_num, page in enumerate(doc, start=1):
        for para in paragraph_data:
            # ページフィルタリング
            if not para["address"].startswith(f"P{page_num}_"):
                continue

            address = para["address"]
            if address not in translations:
                continue

            translated = translations[address]
            box = para["box"]

            # 元テキストを白で塗りつぶし (redact)
            rect = fitz.Rect(box[0], box[1], box[2], box[3])
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

            # フォントサイズと行高さを計算
            font_size = estimate_font_size(box, translated)
            line_height = calculate_line_height(translated, box, font_size, lang_out)

            # テキスト挿入
            font_name = font_manager.select_font(translated[0] if translated else "A")

            page.insert_textbox(
                rect,
                translated,
                fontname=font_name,
                fontfile=font_manager.get_font_path(font_name),
                fontsize=font_size,
                align=fitz.TEXT_ALIGN_LEFT,
            )

    # フォントサブセット化
    doc.subset_fonts()

    # 保存
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
```

### 7.7 バッチ処理パイプライン

大量ページPDFを効率的に処理するメインパイプライン。

```python
from typing import Callable

def translate_pdf_batch(
    pdf_path: str,
    output_path: str,
    lang_in: str,
    lang_out: str,
    translation_engine: "TranslationEngine",
    progress_callback: Callable[[int, int, str], None] = None,
    batch_size: int = 5,
) -> None:
    """
    バッチ処理によるPDF翻訳

    Args:
        pdf_path: 入力PDFパス
        output_path: 出力PDFパス
        lang_in: 入力言語 ("ja" or "en")
        lang_out: 出力言語 ("ja" or "en")
        translation_engine: 翻訳エンジンインスタンス
        progress_callback: 進捗コールバック (current_page, total_pages, phase)
        batch_size: バッチサイズ (デフォルト: 5)
    """
    total_pages = get_total_pages(pdf_path)
    all_translations = {}
    all_paragraph_data = []

    # Phase 1-4: バッチごとに処理
    for batch_start, batch_images in iterate_pdf_pages(pdf_path, batch_size):
        for i, img in enumerate(batch_images):
            page_num = batch_start + i + 1

            # 進捗通知
            if progress_callback:
                progress_callback(page_num, total_pages, "layout")

            # レイアウト解析
            results = analyze_document(img)

            # 翻訳データ準備
            cells = prepare_translation_cells(results, page_num)
            all_paragraph_data.extend(cells)

            # 進捗通知
            if progress_callback:
                progress_callback(page_num, total_pages, "translation")

            # Copilot翻訳 (バッチ内でも分割可能)
            if cells:
                tsv_data = "\n".join(
                    f"{c['address']}\t{c['text']}" for c in cells
                )
                result = translation_engine.translate(
                    prompt_header=get_prompt(lang_in, lang_out),
                    data=tsv_data,
                )
                all_translations.update(result.translations)

        # バッチ完了後にメモリ解放
        del batch_images
        import gc
        gc.collect()

    # Phase 5: PDF再構築 (全ページ一括)
    if progress_callback:
        progress_callback(total_pages, total_pages, "reconstruction")

    reconstruct_pdf(
        original_pdf_path=pdf_path,
        translations=all_translations,
        paragraph_data=all_paragraph_data,
        lang_out=lang_out,
        output_path=output_path,
    )
```

### 7.8 Copilotトークン制限対応

1回のリクエストで送信可能なテキスト量に制限がある場合の分割処理。

```python
MAX_CHARS_PER_REQUEST = 6000  # 1リクエストあたりの最大文字数

def split_cells_for_translation(
    cells: list[dict],
    max_chars: int = MAX_CHARS_PER_REQUEST,
) -> list[list[dict]]:
    """
    翻訳対象セルをトークン制限に応じて分割

    Args:
        cells: 翻訳対象セルリスト
        max_chars: 1リクエストの最大文字数

    Returns:
        分割されたセルリストのリスト
    """
    chunks = []
    current_chunk = []
    current_chars = 0

    for cell in cells:
        cell_chars = len(cell["text"]) + len(cell["address"]) + 2  # タブと改行
        if current_chars + cell_chars > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0
        current_chunk.append(cell)
        current_chars += cell_chars

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
```

---

## 8. プロンプトファイル

### 8.1 prompt_pdf_jp_to_en.txt

既存のExcel翻訳プロンプト (prompt.txt) に準拠し、体裁維持のための圧縮ルールを適用。

```
Role Definition
あなたは、TSV形式の日本語テキストを「PDFの段落幅に収まるよう短く圧縮した英語」に変換する、完全自動化されたヘッドレス・データ処理エンジンです。
あなたはチャットボットではありません。人間のような挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Critical Mission & Priorities
以下の優先順位を厳守して処理を行ってください。

1. 記号使用の絶対禁止 (NO SYMBOLS for Logic): 比較・変動・関係性を示す記号（> < = ↑ ↓ ~）は絶対に使用しない。文字数が増えても必ず英単語を使用する。
2. 出力形式の厳守 (Strict Format): TSVデータ以外の文字（挨拶、Markdownの枠、解説）を1文字たりとも出力しない。
3. 構造維持 (Structure): 入力行数と出力行数は完全に一致させる。
4. 積極的な短縮 (Smart Compression): 上記「記号禁止ルール」を守った上で、単語を短縮形にする。
5. 数式記法保持 (Formula): {v*} 形式の数式記法はそのまま保持する。
6. 用語集の適用 (Glossary): 添付の用語集ファイルがある場合、その訳語を優先して使用する。

Processing Rules (Step-by-Step)

Step 1: 入力解析
- 入力は [ParagraphAddress] [TAB] [JapaneseText] の形式である。
- 左列（P1_1, P1_2, T1_1_0_0等）は一文字も変更せずそのまま出力する。

Step 2: 翻訳と効率的な短縮 (Smart Abbreviation)
日本語を英語に翻訳し、以下のルールで短縮する。

2-1. 文体と削除
- 見出しスタイル: 完全文（S+V+O）は禁止。名詞句にする。
- 削除対象: 冠詞(a/the)、Be動詞、所有格(our/its)、明白な前置詞(of/for等)は削除する。

2-2. 記号禁止と強制置換ルール (最重要・厳守)
「意味の短縮」に記号を使うことは厳禁である。必ず英単語に置換せよ。
- 禁止記号リスト:
  - 禁止: [ > ]
  - 禁止: [ < ]
  - 禁止: [ = ]
  - 禁止: [ ↑ ]
  - 禁止: [ ↓ ]
  - 禁止: [ ~ ]

2-3. 一般的な単語短縮
記号以外の手法（略語・カット）で短縮を行う。
- Consolidated → Consol.
- Accounting → Acct.
- Production → Prod.
- Volume → Vol.
- Operating Profit → OP
- Year Over Year → YOY
- 億 → oku / 1,000単位 → k (例: 5k yen)
- 負数 → (Number) (例: (50))

2-4. 数式記法保持
- {v0}, {v1}, {v2} などの数式記法はそのまま保持する。

Step 3: 最終チェック (Final Check)
- 出力文字列の中に `> < = ↑ ↓` が含まれていないか確認する。含まれている場合は必ず単語に直すこと。

Few-Shot Examples (Reference)
以下の短縮パターンに厳密に従ってください。
| Input (JP) | Ideal Output (EN) | Note |
|---|---|---|
| P1_1	4,500億円 | P1_1	4,500 oku | oku rule |
| P1_2	▲12,000円 | P1_2	(12k) yen | k & negative rule |
| P1_3	売上高は{v0}で計算 | P1_3	Revenue calc by {v0} | formula preserved |

Input Data
これより下のデータを変換し、結果のみを出力せよ。
【翻訳対象TSV】
```

### 8.2 prompt_pdf_en_to_jp.txt

既存のExcel翻訳プロンプト (prompt_excel_en_to_jp.txt) に準拠し、体裁維持のための圧縮ルールを適用。

```
Role Definition
あなたは、TSV形式の英語テキストを「PDFの段落幅に収まるよう短く圧縮した日本語」に変換する、完全自動化されたヘッドレス・データ処理エンジンです。
あなたはチャットボットではありません。人間のような挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Critical Mission & Priorities
以下の優先順位を厳守して処理を行ってください。

1. 出力形式の厳守 (Strict Format): TSVデータ以外の文字（挨拶、Markdownの枠、解説）を1文字たりとも出力しない。
2. 構造維持 (Structure): 入力行数と出力行数は完全に一致させる。
3. 自然な日本語 (Natural Japanese): 直訳ではなく、ビジネス文書として自然で読みやすい日本語にする。
4. 簡潔さ (Conciseness): PDFの段落幅を考慮し、冗長な表現を避けて簡潔に訳す。
5. 数式記法保持 (Formula): {v*} 形式の数式記法はそのまま保持する。
6. 用語集の適用 (Glossary): 添付の用語集ファイルがある場合、その訳語を優先して使用する。

Processing Rules (Step-by-Step)

Step 1: 入力解析
- 入力は [ParagraphAddress] [TAB] [EnglishText] の形式である。
- 左列（P1_1, P1_2, T1_1_0_0等）は一文字も変更せずそのまま出力する。

Step 2: 翻訳と圧縮
英語を日本語に翻訳し、以下のルールで圧縮する。

2-1. 文体
- ビジネス文書: 丁寧語（です・ます調）は使用しない。簡潔な体言止めを使用。
- 見出しスタイル: 名詞句を使用。
- 略語は一般的な日本語訳があればそれを使用。

2-2. 数値表記
- k → 千（例: 5k → 5千）または 億 を使用
- oku → 億
- 負数は▲を使用（例: (50) → ▲50）

2-3. 数式記法保持
- {v0}, {v1}, {v2} などの数式記法はそのまま保持する。

Step 3: 最終チェック (Final Check)
- 出力行数が入力行数と一致することを確認する。
- 各行がTSV形式（アドレス + タブ + 翻訳）であることを確認する。

Few-Shot Examples (Reference)
以下のパターンに従ってください。
| Input (EN) | Ideal Output (JP) | Note |
|---|---|---|
| P1_1	4,500 oku | P1_1	4,500億円 | oku rule |
| P1_2	(12k) yen | P1_2	▲12,000円 | k & negative rule |
| P1_3	YOY growth | P1_3	前年比成長 | abbreviation |
| P1_4	Revenue calc by {v0} | P1_4	売上高は{v0}で計算 | formula preserved |

Input Data
これより下のデータを変換し、結果のみを出力せよ。
【翻訳対象TSV】
```

---

## 9. UI設計 (既存UI統合)

### 9.1 設計方針

既存の `TranslatorApp` (ui.py) を拡張し、PDF翻訳機能を統合する。

| 方針 | 内容 |
|------|------|
| 既存UI維持 | Dynamic Island, Aurora Background, Settings Section を維持 |
| 進捗表示 | 既存の Dynamic Island を使用 (新規コンポーネント不要) |
| ファイル選択 | Hero Section にドロップエリアを追加 |
| 入力自動判別 | Excel / PDF を自動判別して適切な処理を実行 |

### 9.2 統合後レイアウト

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│              ┌─────────────────────────────────────┐                        │
│              │  Dynamic Island (進捗表示)          │                        │
│              │  "翻訳中" ページ 6/10               │                        │
│              │  [████████████░░░░░░░░] 60%         │                        │
│              └─────────────────────────────────────┘                        │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                        Hero Section                                     │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  📄 ファイルをドラッグ&ドロップ                                   │  │ │
│  │  │     または [ファイルを選択...]                                    │  │ │
│  │  │     対応形式: .pdf, .xlsx, .xls                                  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  │  [選択中: document.pdf (2.5 MB, 10ページ)]                             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Direction Section (既存)                                              │ │
│  │    [日本語 → English]     [English → 日本語]                           │ │
│  │              [          Translate          ]                           │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Settings Section (既存)                                               │ │
│  │    Glossary: [file.csv]  [Browse] [Clear]                             │ │
│  │    Start with Windows: [switch]                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.3 TranslatorApp の拡張

既存の `TranslatorApp` クラスにPDF翻訳用のプロパティを追加する。

**注意**: TkinterDnD の継承は行わない。ドラッグ&ドロップ機能は `FileDropArea` コンポーネント内で `tk.Frame` を使用して実装する（9.5節参照）。これにより CustomTkinter との互換性問題を回避する。

```python
# ui.py の TranslatorApp クラスを変更

import customtkinter as ctk
from pathlib import Path
from typing import Callable, Optional

class TranslatorApp(ctk.CTk):
    """
    Main application - 既存UIを維持しつつPDF機能を追加

    注意: TkinterDnD.DnDWrapper は継承しない。
    DnD機能は FileDropArea 内で tk.Frame を使用して実装する。
    """

    def __init__(self):
        super().__init__()

        # === 既存の初期化コード ===
        self.is_translating = False
        self.cancel_requested = False
        self.on_start_callback: Optional[Callable] = None
        self.on_cancel_callback: Optional[Callable] = None
        self.on_jp_to_en_callback: Optional[Callable] = None
        self.on_en_to_jp_callback: Optional[Callable] = None
        self.last_translation_pairs = None

        # === PDF翻訳用の追加プロパティ ===
        self.on_pdf_jp_to_en_callback: Optional[Callable[[Path], None]] = None
        self.on_pdf_en_to_jp_callback: Optional[Callable[[Path], None]] = None
        self.selected_file: Optional[Path] = None
        self.selected_file_type: Optional[str] = None  # "pdf" or "excel"

        # ... 残りの初期化コード ...
```

### 9.3.1 キャンセル機構

PDF翻訳のキャンセルは**既存のキャンセル機構**をそのまま使用する。

| 状態 | ボタン表示 | 動作 |
|------|-----------|------|
| 待機中 | "Translate" | 翻訳開始 |
| 翻訳中 | "Cancel" | キャンセル要求 |
| キャンセル中 | "Canceling..." (無効) | 処理完了待ち |

```python
# 既存の _on_action メソッド (変更不要)
def _on_action(self):
    """Handle main action button"""
    if self.is_translating:
        self._request_cancel()  # 既存キャンセル処理
    else:
        self._start()

def _request_cancel(self):
    """Request cancellation - PDF/Excel共通"""
    self.cancel_requested = True
    self.action_btn.configure(text="Canceling...", state="disabled")
    if self.on_cancel_callback:
        self.on_cancel_callback()
```

**PDF翻訳でのキャンセル確認**:
```python
# translate_pdf_batch 内でキャンセルを確認
def translate_pdf_batch(..., cancel_check: Callable[[], bool] = None):
    for batch_start, batch_images in iterate_pdf_pages(pdf_path, batch_size):
        for i, img in enumerate(batch_images):
            # キャンセル確認
            if cancel_check and cancel_check():
                return  # 翻訳中断

            # ... 翻訳処理 ...
```

**注意**: ×ボタン（ウィンドウ閉じる）はアプリ終了となるため、キャンセル目的では使用しない。

### 9.4 既存メソッド拡張 (状態管理)

既存の `show_translating`, `show_complete`, `show_error`, `show_ready` メソッドを拡張し、PDF翻訳に対応する。

#### 9.4.1 show_translating 拡張

```python
def show_translating(self, current: int, total: int, phase: str = None):
    """
    翻訳進捗表示 - PDF/Excel両対応

    Args:
        current: 現在の進捗 (ページ番号 or セル番号)
        total: 総数
        phase: PDF翻訳フェーズ (Excelの場合はNone)
    """
    self.is_translating = True

    # 翻訳中は最前面に表示
    self.attributes("-topmost", True)
    self.lift()

    progress = current / total if total > 0 else 0
    percent = int(progress * 100)

    if phase:
        # PDF翻訳の場合
        phase_names = {
            "loading": "PDF読込中",
            "layout": "レイアウト解析中",
            "formula": "数式保護中",
            "translation": "翻訳中",
            "reconstruction": "PDF再構築中",
        }
        phase_display = phase_names.get(phase, phase)

        self.dynamic_island.expand()
        self.dynamic_island.set_status(
            phase_display,
            f"ページ {current}/{total}",
            progress
        )
        self.dynamic_island.start_pulse()

        self.status_text.set_text(phase_display, animate=False)
        self.subtitle_text.set_text(f"ページ {current}/{total}", animate=False)
    else:
        # Excel翻訳の場合 (既存動作)
        self.dynamic_island.set_status(
            f"Translating {percent}%",
            f"Processing {total} cells...",
            progress
        )
        self.status_text.set_text("Translating", animate=False)
        self.subtitle_text.set_text(f"Processing {total} cells...", animate=False)

    # アクションボタンをキャンセルモードに
    self.action_btn.configure(
        text="Cancel",
        state="normal",
        fg_color=THEME.bg_elevated,
        text_color=THEME.text_primary
    )

    # Ambient Glow - 翻訳中モード (PDF/Excel共通)
    self.ambient_glow.set_mode("active")
```

#### 9.4.2 show_complete 拡張

```python
def show_complete(self, count: int, translation_pairs: list = None,
                  confidence: int = 100, output_path: str = None):
    """
    翻訳完了表示 - PDF/Excel両対応

    Args:
        count: 翻訳数 (セル数 or ページ数)
        translation_pairs: 翻訳ペア (Excel用)
        confidence: 信頼度 (Excel用)
        output_path: 出力ファイルパス (PDF用)
    """
    # 状態リセット
    self.is_translating = False
    self.cancel_requested = False
    self.last_translation_pairs = translation_pairs

    # 最前面解除
    self.attributes("-topmost", False)

    # 品質テキスト
    if confidence >= 95:
        quality_text = "Excellent"
    elif confidence >= 80:
        quality_text = "Good"
    elif confidence >= 60:
        quality_text = "Fair"
    else:
        quality_text = "Review"

    # ボタン状態リセット
    self.action_btn.configure(
        text="Translate",
        state="normal",
        fg_color=THEME.text_primary,
        text_color=THEME.bg_primary
    )

    # Dynamic Island 更新
    try:
        self.dynamic_island.stop_pulse()

        if output_path:
            # PDF翻訳完了
            self.dynamic_island.set_status(
                "PDF Complete!",
                Path(output_path).name,
                1.0
            )
        else:
            # Excel翻訳完了 (既存動作)
            self.dynamic_island.set_status(
                "Complete!",
                f"{count} cells | {quality_text}",
                1.0
            )
    except Exception:
        pass

    # Ambient Glow - 待機モードに戻す
    self.ambient_glow.set_mode("idle")

    # サウンド再生
    try:
        SoundPlayer.play_success()
    except Exception:
        pass

    # ファイル選択クリア
    if hasattr(self, 'file_drop_area'):
        self.file_drop_area.clear()

    # 3秒後に待機状態に戻る
    self.after(3000, self.show_ready)
```

#### 9.4.3 show_error 拡張

```python
def show_error(self, message: str):
    """
    エラー表示 - PDF/Excel共通

    Args:
        message: エラーメッセージ
    """
    self.is_translating = False
    self.cancel_requested = False

    # 最前面解除
    self.attributes("-topmost", False)

    # Dynamic Island - エラー状態
    self.dynamic_island.stop_pulse()
    self.dynamic_island.expand()
    self.dynamic_island.set_status("Error", message[:40], 0)

    # Ambient Glow - エラーモード (赤)
    self.ambient_glow.set_mode("error")

    # サウンド再生
    SoundPlayer.play_error()

    # Kinetic Typography
    self.status_text.set_text("Error")
    self.subtitle_text.set_text(message[:50])

    # ボタン状態リセット
    self.action_btn.configure(
        text="Translate",
        state="normal",
        fg_color=THEME.text_primary,
        text_color=THEME.bg_primary
    )

    # 5秒後に待機状態に戻る
    self.after(5000, self.show_ready)
```

#### 9.4.4 show_ready (既存維持)

```python
def show_ready(self):
    """待機状態 - PDF/Excel共通"""
    self.is_translating = False
    self.cancel_requested = False

    # Dynamic Island - コンパクトモード
    self.dynamic_island.compact()
    self.dynamic_island.set_status("Ready")
    self.dynamic_island.stop_pulse()

    # Ambient Glow - 待機モード
    self.ambient_glow.set_mode("idle")

    # ボタン状態リセット
    self.action_btn.configure(
        text="Translate",
        state="normal",
        fg_color=THEME.text_primary,
        hover_color=THEME.text_secondary,
        text_color=THEME.bg_primary
    )

    # Kinetic Typography
    self.status_text.set_text("Ready")
    if self.current_mode == "jp_to_en":
        self.subtitle_text.set_text("Japanese → English")
    else:
        self.subtitle_text.set_text("English → Japanese")
```

#### 9.4.5 show_cancelled (既存維持)

```python
def show_cancelled(self):
    """キャンセル状態 - PDF/Excel共通"""
    self.is_translating = False
    self.cancel_requested = False

    # 最前面解除
    self.attributes("-topmost", False)

    # Dynamic Island - コンパクトモードでキャンセル表示
    self.dynamic_island.stop_pulse()
    self.dynamic_island.compact()
    self.dynamic_island.set_status("Cancelled")

    # Ambient Glow - フェードアウト
    self.ambient_glow.fade_out()

    # Kinetic Typography
    self.status_text.set_text("Cancelled")
    self.subtitle_text.set_text("Translation stopped")

    # ボタン状態リセット
    self.action_btn.configure(
        text="Translate",
        state="normal",
        fg_color=THEME.text_primary,
        text_color=THEME.bg_primary
    )
```

#### 9.4.6 show_connecting (既存メソッド使用)

PDF翻訳はCopilotを使用するため、既存の`show_connecting`メソッドを接続フェーズで使用する。

```python
def show_connecting(self, step: int = 0, message: str = "Starting browser..."):
    """
    接続状態表示 - PDF/Excel共通

    Args:
        step: 接続ステップ (0-5)
        message: 表示メッセージ
    """
    self.is_translating = True

    # 翻訳中は最前面に表示
    self.attributes("-topmost", True)
    self.lift()

    # 進捗計算 (0-95%)
    progress = min(step / 5, 0.95) if step > 0 else 0.05

    # Dynamic Island - 接続中表示
    self.dynamic_island.expand()
    self.dynamic_island.set_status("Connecting", message, progress)
    self.dynamic_island.start_pulse()

    # Ambient Glow - 翻訳中モード
    self.ambient_glow.set_mode("active")

    # Kinetic Typography
    self.status_text.set_text("Connecting")
    self.subtitle_text.set_text(message)

    # アクションボタンをキャンセルモードに
    self.action_btn.configure(
        text="Cancel",
        fg_color=THEME.bg_elevated,
        text_color=THEME.text_primary
    )

    self.update_idletasks()
```

**PDF翻訳での使用タイミング**:
```python
# Copilot接続開始時
ui.show_connecting(0, "Copilotに接続中...")

# ブラウザ起動後
ui.show_connecting(1, "ブラウザを起動中...")

# ページ読込後
ui.show_connecting(2, "ページを読込中...")

# 接続完了後、show_translating() に移行
ui.show_translating(1, total_pages, "loading")
```

#### 9.4.7 SoundPlayer (既存クラス使用)

```python
# 翻訳開始時
SoundPlayer.play_start()

# 翻訳完了時
SoundPlayer.play_success()

# エラー時
SoundPlayer.play_error()
```

### 9.5 ファイルドロップエリア

Hero Section 内にドロップエリアを追加する。

**TkinterDnD 初期化について:**
- `TranslatorApp` は `TkinterDnD.DnDWrapper` を継承しない（CustomTkinter との互換性問題を回避）
- 代わりに `FileDropArea` 内で `TkinterDnD._require()` を使用してルートウィンドウを初期化
- ドロップ対象は `tk.Frame`（標準 tkinter）を使用し、その中に `ctk` ウィジェットを配置

```python
import tkinter as tk
import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
from pathlib import Path

class FileDropArea(ctk.CTkFrame):
    """
    ファイルドラッグ&ドロップエリア
    PDF / Excel 両対応

    TkinterDnD の初期化は本クラス内で行う。
    ルートウィンドウ (TranslatorApp) の継承変更は不要。
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}
    _dnd_initialized = False  # クラス変数: 初期化済みフラグ

    def __init__(self, parent, on_file_selected: callable, theme):
        super().__init__(parent, fg_color="transparent")
        self.on_file_selected = on_file_selected
        self.theme = theme
        self.selected_file: Path = None
        self.file_type: str = None  # "pdf" or "excel"

        self._setup_ui()
        self._init_tkdnd()  # TkinterDnD 初期化
        self._setup_dnd()

    def _init_tkdnd(self):
        """TkinterDnD をルートウィンドウに初期化（1回のみ）"""
        if not FileDropArea._dnd_initialized:
            try:
                # ルートウィンドウを取得して TkinterDnD を初期化
                root = self.winfo_toplevel()
                TkinterDnD._require(root)
                FileDropArea._dnd_initialized = True
            except Exception as e:
                print(f"Warning: TkinterDnD initialization failed: {e}")
                # DnD が使えなくてもファイル選択ダイアログは使用可能

    def _setup_ui(self):
        """UI構築 - 既存テーマを使用"""
        # ドロップエリア (tkinter.Frame - DnD互換性)
        self.drop_frame = tk.Frame(
            self,
            bg=self.theme.bg_card,
            highlightthickness=2,
            highlightbackground=self.theme.glass_border,
        )
        self.drop_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # アイコン
        self.icon_label = ctk.CTkLabel(
            self.drop_frame,
            text="📄",
            font=("", 36),
            text_color=self.theme.text_secondary,
            fg_color="transparent",
        )
        self.icon_label.pack(pady=(20, 5))

        # メインテキスト
        self.drop_label = ctk.CTkLabel(
            self.drop_frame,
            text="ファイルをドラッグ&ドロップ",
            font=("", 14),
            text_color=self.theme.text_primary,
            fg_color="transparent",
        )
        self.drop_label.pack()

        # サブテキスト
        self.format_label = ctk.CTkLabel(
            self.drop_frame,
            text="対応形式: .pdf, .xlsx, .xls",
            font=("", 10),
            text_color=self.theme.text_tertiary,
            fg_color="transparent",
        )
        self.format_label.pack(pady=(5, 10))

        # ファイル選択ボタン
        self.select_button = ctk.CTkButton(
            self.drop_frame,
            text="ファイルを選択...",
            command=self._on_select_click,
            width=140,
            height=32,
            fg_color=self.theme.bg_elevated,
            hover_color=self.theme.bg_primary,
            text_color=self.theme.text_secondary,
            corner_radius=8,
        )
        self.select_button.pack(pady=(0, 15))

        # ファイル情報表示
        self.file_info_label = ctk.CTkLabel(
            self,
            text="",
            font=("", 11),
            fg_color="transparent",
        )
        self.file_info_label.pack(pady=(0, 5))

    def _setup_dnd(self):
        """ドラッグ&ドロップ設定"""
        if not FileDropArea._dnd_initialized:
            # TkinterDnD 初期化失敗時はスキップ（ファイル選択ダイアログは使用可能）
            return

        try:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_frame.dnd_bind("<<DropEnter>>", self._on_drag_enter)
            self.drop_frame.dnd_bind("<<DropLeave>>", self._on_drag_leave)
        except Exception as e:
            print(f"Warning: DnD setup failed: {e}")

    def _parse_drop_data(self, data: str) -> list[str]:
        """ドロップデータをパース"""
        return self.tk.splitlist(data)

    def _on_drop(self, event):
        """ファイルドロップ時"""
        files = self._parse_drop_data(event.data)
        if files:
            self._validate_and_set_file(Path(files[0]))
        self._reset_drop_style()

    def _on_drag_enter(self, event):
        """ドラッグ進入時 - アクセントカラーでハイライト"""
        self.drop_frame.configure(highlightbackground=self.theme.accent)

    def _on_drag_leave(self, event):
        """ドラッグ退出時"""
        self._reset_drop_style()

    def _reset_drop_style(self):
        """スタイルリセット"""
        self.drop_frame.configure(highlightbackground=self.theme.glass_border)

    def _on_select_click(self):
        """ファイル選択ダイアログ"""
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="ファイルを選択",
            filetypes=[
                ("対応ファイル", "*.pdf *.xlsx *.xls"),
                ("PDF files", "*.pdf"),
                ("Excel files", "*.xlsx *.xls"),
                ("All files", "*.*"),
            ],
        )
        if file_path:
            self._validate_and_set_file(Path(file_path))

    def _validate_and_set_file(self, file_path: Path):
        """ファイル検証と設定"""
        if not file_path.exists():
            self._show_error("ファイルが見つかりません")
            return

        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            self._show_error("対応していないファイル形式です")
            return

        self.selected_file = file_path
        self.file_type = "pdf" if ext == ".pdf" else "excel"
        self._update_file_info()

        if self.on_file_selected:
            self.on_file_selected(file_path, self.file_type)

    def _update_file_info(self):
        """ファイル情報表示更新"""
        if self.selected_file:
            size_mb = self.selected_file.stat().st_size / (1024 * 1024)
            type_icon = "📄" if self.file_type == "pdf" else "📊"
            self.file_info_label.configure(
                text=f"{type_icon} {self.selected_file.name} ({size_mb:.1f} MB)",
                text_color=self.theme.accent,
            )

    def _show_error(self, message: str):
        """エラー表示"""
        self.file_info_label.configure(
            text=f"⚠️ {message}",
            text_color="#ff6b6b",
        )

    def clear(self):
        """選択クリア"""
        self.selected_file = None
        self.file_type = None
        self.file_info_label.configure(text="")
```

### 9.6 TranslatorApp への統合

```python
# ui.py の TranslatorApp._build_ui() に追加

def _build_ui(self):
    # ... 既存コード ...

    # === Hero Section (ファイルドロップエリア追加) ===
    self.hero = ctk.CTkFrame(self.container, fg_color="transparent")
    self.hero.pack(fill="both", expand=True)

    # ファイルドロップエリア
    self.file_drop_area = FileDropArea(
        self.hero,
        on_file_selected=self._on_file_selected,
        theme=THEME,
    )
    self.file_drop_area.pack(fill="both", expand=True, pady=THEME.space_md)

    # ... 既存コード ...

def _on_file_selected(self, file_path: Path, file_type: str):
    """ファイル選択時のコールバック"""
    self.selected_file = file_path
    self.selected_file_type = file_type

    # Dynamic Island で表示
    if file_type == "pdf":
        self.dynamic_island.set_status(f"PDF: {file_path.name}")
    else:
        self.dynamic_island.set_status(f"Excel: {file_path.name}")

def _start(self):
    """翻訳開始 - ファイルタイプで分岐"""
    # 開始サウンド
    SoundPlayer.play_start()

    if hasattr(self, 'selected_file_type') and self.selected_file_type == "pdf":
        # PDF翻訳
        if self.current_mode == "jp_to_en" and self.on_pdf_jp_to_en_callback:
            self.on_pdf_jp_to_en_callback(self.selected_file)
        elif self.current_mode == "en_to_jp" and self.on_pdf_en_to_jp_callback:
            self.on_pdf_en_to_jp_callback(self.selected_file)
    else:
        # Excel翻訳 (既存動作)
        if self.current_mode == "jp_to_en" and self.on_jp_to_en_callback:
            self.on_jp_to_en_callback()
        elif self.current_mode == "en_to_jp" and self.on_en_to_jp_callback:
            self.on_en_to_jp_callback()
        elif self.on_start_callback:
            # Fallback to start callback (legacy)
            self.on_start_callback()
```

### 9.7 新規コールバック

```python
# TranslatorApp に追加するコールバック設定メソッド

def set_on_pdf_jp_to_en(self, callback: Callable[[Path], None]):
    """PDF日本語→英語翻訳コールバック"""
    self.on_pdf_jp_to_en_callback = callback

def set_on_pdf_en_to_jp(self, callback: Callable[[Path], None]):
    """PDF英語→日本語翻訳コールバック"""
    self.on_pdf_en_to_jp_callback = callback
```

### 9.8 依存パッケージ

```python
# requirements.txt 追加
tkinterdnd2 >= 0.3.0   # ドラッグ&ドロップ対応
```

---

## 10. 出力仕様

### 10.1 出力形式

| 出力 | 形式 | 編集可否 |
|------|------|---------|
| 翻訳版PDF | PDF | ✗ 編集不可 |

**注意**: PDF翻訳の出力は最終版として扱い、編集機能は提供しない。
翻訳結果の調整が必要な場合は、既存のExcel翻訳機能を使用すること。

### 10.2 自動検出

```python
def detect_input_type(file_path: str) -> str:
    """
    ファイル種別を自動検出

    Returns:
        "pdf": PDFファイル
        "excel": Excel (.xlsx, .xls)
        "text": その他テキスト
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        return "pdf"
    elif ext in [".xlsx", ".xls"]:
        return "excel"
    else:
        return "text"
```

### 10.3 設定項目

```python
# config.json 追加項目

{
    "pdf": {
        "dpi": 200,                    # PDF読込解像度 (固定)
        "device": "cpu",               # "cpu" (デフォルト) or "cuda" (GPU高速化)
        "batch_size": 5,               # バッチサイズ (ページ数)
        "max_chars_per_request": 6000, # Copilot 1リクエストあたり最大文字数
        "reading_order": "auto",       # 読み順検出
        "include_headers": false,      # ヘッダー/フッター翻訳
        "font_path": "fonts/",         # フォントディレクトリ
    }
}
```

---

## 11. エラーハンドリング

### 11.1 想定エラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `pypdfium2.PdfiumError` | 破損PDF | エラーメッセージ表示 |
| `fitz.FileDataError` | PDF書込エラー | 一時ファイル使用 |
| `TranslationStatus.FAILED` | Copilot応答なし | リトライ or エラー表示 |
| `torch.cuda.OutOfMemoryError` | GPU VRAM不足 (GPU使用時) | CPUにフォールバック |

### 11.2 デバイス選択

```python
import torch

def get_device(config_device: str = "cpu") -> str:
    """
    実行デバイスを決定

    Args:
        config_device: 設定値 ("cpu" or "cuda")

    Returns:
        使用するデバイス
    """
    if config_device == "cuda":
        if torch.cuda.is_available():
            return "cuda"
        else:
            print("Warning: CUDA not available, falling back to CPU")
            return "cpu"
    return "cpu"

def analyze_document(img: np.ndarray, device: str = "cpu") -> DocumentAnalyzerSchema:
    """レイアウト解析実行"""
    analyzer = DocumentAnalyzer(device=device)
    return analyzer(img)
```

---

## 12. テスト計画

### 12.1 単体テスト

| テスト項目 | 内容 |
|-----------|------|
| `test_load_pdf` | PDF読込、ページ数、画像サイズ確認 |
| `test_layout_analysis` | 段落/テーブル/図検出 |
| `test_formula_protection` | {v*}プレースホルダー置換・復元 |
| `test_address_parser` | P#_#, T#_#_#_# パース |
| `test_line_height` | 動的圧縮計算 |
| `test_pdf_reconstruction` | PDF出力、フォント埋込 |

### 12.2 統合テスト

| テスト項目 | 内容 |
|-----------|------|
| `test_jp_to_en_pdf` | 日本語PDF→英語PDF |
| `test_en_to_jp_pdf` | 英語PDF→日本語PDF |
| `test_mixed_content` | 段落+テーブル+図混在 |
| `test_glossary` | 用語集適用確認 |

---

## 13. 実装優先順位

### Phase 1 (MVP)
1. PDF読込 (yomitoku load_pdf)
2. レイアウト解析 (DocumentAnalyzer)
3. Copilot翻訳統合 (既存エンジン拡張)
4. PDF再構築 (基本)

### Phase 2 (機能拡充)
1. 数式保護 ({v*})
2. 動的行高さ調整
3. テーブル翻訳

### Phase 3 (最適化)
1. GPU/CPUフォールバック
2. 大規模PDF対応
3. フォントサブセット最適化
4. キャッシュ機能

---

## 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| v1.0 | - | 初版 |
| v2.0 | - | 翻訳キャッシュ追加 |
| v3.0 | - | タブUI削除、自動検出 |
| v4.0 | - | yomitoku-dev統合 |
| v5.0 | - | 座標変換、redactアプローチ |
| v6.0 | - | PDFMathTranslate準拠 |
| v7.0 | - | 既存Excel翻訳アプローチ採用 |
| v8.0 | - | 完全仕様 (簡易版なし)、yomitoku/PDFMathTranslate完全準拠 |
| v8.1 | 2024-11 | 言語対応を日本語・英語のみに限定、フォント変更 (MS P明朝/Arial)、プロンプトにExcel圧縮ルール追加 (記号禁止、数値圧縮、体言止め) |
| v8.2 | 2024-11 | 出力仕様を明確化 (PDF出力のみ、編集不可)、編集が必要な場合は既存Excel翻訳を使用 |
| v8.3 | 2024-11 | バイリンガルPDF出力機能を削除 |
| v8.4 | 2024-11 | UI設計セクション追加 (PDFドラッグ&ドロップエリア、進捗表示) |
| v8.5 | 2024-11 | API整合性修正: CellSchema→TableCellSchema、vflag()フォントパターン拡充、CustomTkinter+tkinterdnd2互換性対応 |
| v8.6 | 2024-11 | CPU専用環境をデフォルトに変更、GPU高速化をオプション化 |
| v8.7 | 2024-11 | バッチ処理追加 (大量ページ対応)、最大ページ数制限なし、DPI固定(200)、Copilotトークン制限対応 |
| v8.8 | 2024-11 | API整合性修正: PyMuPDF subset_fonts()パラメータ修正、tkinterdnd2イベント名修正(DropEnter/DropLeave)、ファイルパース改善(splitlist使用) |
| v8.9 | 2024-11 | UI設計を既存TranslatorAppと統合、Dynamic Islandで進捗表示、PDF/Excel両対応ドロップエリア、既存Settings維持 |
| v9.0 | 2024-11 | 既存メソッド拡張方式に変更 (show_translating/complete/error/ready)、SoundPlayer/AmbientGlow統合、状態管理フラグ追加 |
| v9.1 | 2024-11 | `__init__`初期化追加 (PDF用コールバック・ファイル選択)、キャンセル機構明確化 (既存Cancel機構使用)、AmbientGlowモード修正 ("translating"→"active")、`_start()`にon_start_callbackフォールバック追加 |
| v9.2 | 2024-11 | ambient_glowをPDF/Excel共通で適用 (UI一貫性向上) |
| v9.3 | 2024-11 | show_cancelled追加、show_error 5秒タイマー確定、show_readyサフィックス削除確定 |
| v9.4 | 2024-11 | show_connecting追加 (Copilot接続フェーズ用、PDF/Excel共通) |
| v9.5 | 2024-11 | translate.py拡張: ADDRESS_PATTERNにPDFアドレス形式(P#_#, T#_#_#_#)追加、SHAPE形式も含む |
| v9.6 | 2024-11 | TkinterDnD継承廃止 (FileDropArea内で初期化)、show_complete try/except追加、show_ready hover_color追加 |
| v9.7 | 2024-11 | 既存実装との整合性修正: show_complete dynamic_island try/except追加、show_error 処理順序修正 (SoundPlayer→Typography→Button) |
