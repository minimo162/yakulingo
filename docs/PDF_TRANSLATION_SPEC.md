# PDF翻訳機能 技術仕様書 v8.3

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
| CUDA | 11.8以上 (GPU使用時) |
| VRAM | 8GB以上 (GPU使用時) |
| 画像解像度 | 短辺720px以上推奨 |

---

## 3. Phase 1: PDF読込 (yomitoku準拠)

### 3.1 load_pdf 関数

```python
from yomitoku.data.functions import load_pdf

def load_pdf_document(pdf_path: str, dpi: int = 200) -> list[np.ndarray]:
    """
    PDFファイルを読み込み、ページ画像のリストを返す

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
    device="cuda",                 # "cuda" または "cpu"
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
    cells: list[CellSchema]    # セルリスト
    order: int                 # 読み順

class CellSchema:
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

def vflag(font: str, char: str, vfont: str = None, vchar: str = None) -> bool:
    """
    文字が数式かどうかを判定

    PDFMathTranslate converter.py:190-224 準拠

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
    if vfont:
        if re.match(vfont, font):
            return True
    else:
        # デフォルトLaTeXフォント: CM*, MS*, XY, TeX-*, rsfs, wasy, etc.
        if re.match(r"(CM[^R]|MS.M|XY|.*Math)", font):
            return True

    # Rule 3: 文字クラス検出
    if vchar:
        if re.match(vchar, char):
            return True
    else:
        # Unicodeカテゴリ: Lm (修飾), Mn (マーク), Sk (記号), Sm (数学)
        # + ギリシャ文字 (U+0370-U+03FF)
        if char and unicodedata.category(char[0]) in ["Lm", "Mn", "Sk", "Sm"]:
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

# 変更後
ADDRESS_PATTERN = r"(R\d+C\d+|P\d+_\d+|T\d+_\d+_\d+_\d+)"

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
    doc.subset_fonts(fallback=True)

    # 保存
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
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

## 9. 出力仕様

### 9.1 出力形式

| 出力 | 形式 | 編集可否 |
|------|------|---------|
| 翻訳版PDF | PDF | ✗ 編集不可 |

**注意**: PDF翻訳の出力は最終版として扱い、編集機能は提供しない。
翻訳結果の調整が必要な場合は、既存のExcel翻訳機能を使用すること。

### 9.2 自動検出

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

### 9.3 設定項目

```python
# config.json 追加項目

{
    "pdf": {
        "dpi": 200,                    # PDF読込解像度
        "device": "cuda",              # yomitoku実行デバイス
        "reading_order": "auto",       # 読み順検出
        "include_headers": false,      # ヘッダー/フッター翻訳
        "font_path": "fonts/",         # フォントディレクトリ
    }
}
```

---

## 10. エラーハンドリング

### 10.1 想定エラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `yomitoku.CUDAOutOfMemoryError` | VRAM不足 | device="cpu"にフォールバック |
| `pypdfium2.PdfiumError` | 破損PDF | エラーメッセージ表示 |
| `fitz.FileDataError` | PDF書込エラー | 一時ファイル使用 |
| `TranslationStatus.FAILED` | Copilot応答なし | リトライ or エラー表示 |

### 10.2 フォールバック戦略

```python
def analyze_with_fallback(img: np.ndarray) -> DocumentAnalyzerSchema:
    """GPU失敗時にCPUにフォールバック"""
    try:
        analyzer = DocumentAnalyzer(device="cuda")
        return analyzer(img)
    except Exception as e:
        if "CUDA" in str(e) or "memory" in str(e).lower():
            analyzer = DocumentAnalyzer(device="cpu")
            return analyzer(img)
        raise
```

---

## 11. テスト計画

### 11.1 単体テスト

| テスト項目 | 内容 |
|-----------|------|
| `test_load_pdf` | PDF読込、ページ数、画像サイズ確認 |
| `test_layout_analysis` | 段落/テーブル/図検出 |
| `test_formula_protection` | {v*}プレースホルダー置換・復元 |
| `test_address_parser` | P#_#, T#_#_#_# パース |
| `test_line_height` | 動的圧縮計算 |
| `test_pdf_reconstruction` | PDF出力、フォント埋込 |

### 11.2 統合テスト

| テスト項目 | 内容 |
|-----------|------|
| `test_jp_to_en_pdf` | 日本語PDF→英語PDF |
| `test_en_to_jp_pdf` | 英語PDF→日本語PDF |
| `test_mixed_content` | 段落+テーブル+図混在 |
| `test_glossary` | 用語集適用確認 |

---

## 12. 実装優先順位

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
