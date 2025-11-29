# PDF低レベルオペレータ生成への移行仕様書

## 概要

本仕様書は、現在の`PyMuPDF insert_textbox`ベースのPDF再構築を、PDFMathTranslate準拠の**低レベルPDFオペレータ生成**方式へ移行するための設計・実装ガイドラインを定義する。

### 移行の目的

| 項目 | 現状 (insert_textbox) | 移行後 (低レベルオペレータ) |
|------|----------------------|---------------------------|
| 位置精度 | 文字単位の丸め誤差あり | ピクセルレベルの精度 |
| フォント混在 | 同一textbox内は単一フォント | 同一行内で自由に切替可能 |
| CJK対応 | 折り返し制限あり | 完全対応 |
| 数式統合 | 別処理が必要 | シームレスに統合 |

### 参照ドキュメント

- [PDFMathTranslate converter.py](https://github.com/PDFMathTranslate/PDFMathTranslate/blob/main/pdf2zh/converter.py)
- [Adobe PDF Reference 1.7](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf) - Appendix A: Operator Summary
- [PyMuPDF Low-Level Interfaces](https://pymupdf.readthedocs.io/en/latest/recipes-low-level-interfaces.html)

---

## 1. PDFテキストオペレータ基礎

### 1.1 必須オペレータ

PDF内でテキストを描画するために使用する主要オペレータ：

| オペレータ | 構文 | 説明 |
|-----------|------|------|
| **BT** | `BT` | テキストオブジェクト開始 (Begin Text) |
| **ET** | `ET` | テキストオブジェクト終了 (End Text) |
| **Tf** | `/{font} {size} Tf` | フォントとサイズを設定 |
| **Tm** | `{a} {b} {c} {d} {e} {f} Tm` | テキスト行列を設定（位置・変形） |
| **TJ** | `[<hex>] TJ` | テキスト配列を表示（精密間隔制御） |
| **Tj** | `<hex> Tj` | 単純テキスト表示 |

### 1.2 テキスト行列 (Tm) の解説

```
1 0 0 1 x y Tm
│ │ │ │ │ └── Y座標
│ │ │ │ └──── X座標
│ │ │ └────── スケールY (1 = 100%)
│ │ └──────── 傾きY (0 = なし)
│ └────────── 傾きX (0 = なし)
└──────────── スケールX (1 = 100%)
```

標準的なテキスト配置では `1 0 0 1 x y Tm` を使用。

### 1.3 座標系

```
┌─────────────────────────────────────────────────────────────────┐
│                         座標系の違い                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  yomitoku (画像座標系)          PDF座標系                        │
│  ┌──────────────┐              ▲ Y                              │
│  │ (0,0)        │              │                                │
│  │   ┌─────┐    │              │    ┌─────┐                     │
│  │   │ box │    │    ───►      │    │ box │                     │
│  │   └─────┘    │              │    └─────┘                     │
│  │         (W,H)│              └──────────────► X               │
│  └──────────────┘              (0,0)                            │
│                                                                 │
│  原点: 左上                     原点: 左下                        │
│  Y軸: 下が正                    Y軸: 上が正                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.4 フォントエンコーディング

```python
# CIDフォント (日本語等のマルチバイト) - 4桁hex
# Unicode コードポイントをそのまま使用
def encode_cid(text: str) -> str:
    return "".join(["%04x" % ord(c) for c in text])

# Type1/TrueType (ASCII) - 2桁hex
def encode_simple(text: str) -> str:
    return "".join(["%02x" % ord(c) for c in text])
```

**注意**: TrueType/OpenTypeフォント（MS P明朝、Arial等）をPDFに埋め込む場合、
PyMuPDFの`insert_font`がCMapを自動生成するため、Unicodeコードポイントで問題ない。

---

## 2. 既存コードとの統合

### 2.1 既存の定数・クラスとの関係

```
pdf_translator.py (既存)
├── FONT_CONFIG                    # 維持: FontRegistry.DEFAULT_FONTSに統合
├── LANG_LINEHEIGHT_MAP            # 維持: そのまま使用
├── DEFAULT_LINE_HEIGHT            # 維持: そのまま使用
├── class TranslationCell          # 維持: そのまま使用
├── class FontManager              # 廃止: FontRegistryに置き換え
├── calculate_line_height()        # 維持: そのまま使用
├── estimate_font_size()           # 維持: そのまま使用
└── reconstruct_pdf()              # 書き換え: 低レベル実装に変更

pdf_translator.py (追加)
├── @dataclass FontInfo            # 新規
├── class FontRegistry             # 新規: FontManagerを置き換え
├── class PdfOperatorGenerator     # 新規
├── class ContentStreamBuilder     # 新規
├── convert_to_pdf_coordinates()   # 新規
├── split_text_into_lines()        # 新規
├── _is_address_on_page()          # 新規
└── reconstruct_pdf_low_level()    # 新規: reconstruct_pdfを置き換え
```

### 2.2 必要なimport追加

```python
# pdf_translator.py の先頭に追加
from typing import Iterator, Optional, Callable, Any
from dataclasses import dataclass, field
```

---

## 3. 実装仕様

### 3.1 FontInfo データクラス

```python
@dataclass
class FontInfo:
    """
    フォント情報

    既存 FONT_CONFIG を置き換え
    """
    font_id: str           # PDF内部ID (F1, F2, ...)
    family: str            # フォントファミリ名 (表示用)
    path: str              # フォントファイルパス
    fallback: Optional[str]  # フォールバックパス
    encoding: str          # "cid" or "simple"
    is_cjk: bool          # CJKフォントか
```

### 3.2 FontRegistry クラス

```python
class FontRegistry:
    """
    フォント登録・管理

    既存 FontManager を置き換え
    PDFMathTranslate high_level.py:187-203 準拠
    """

    # デフォルトフォント定義 (既存 FONT_CONFIG を統合)
    DEFAULT_FONTS = {
        "ja": FontInfo(
            font_id="F1",
            family="MS-PMincho",
            path="C:/Windows/Fonts/msmincho.ttc",
            fallback="C:/Windows/Fonts/msgothic.ttc",
            encoding="cid",
            is_cjk=True,
        ),
        "en": FontInfo(
            font_id="F2",
            family="Arial",
            path="C:/Windows/Fonts/arial.ttf",
            fallback="C:/Windows/Fonts/times.ttf",
            encoding="simple",
            is_cjk=False,
        ),
    }

    def __init__(self):
        self.fonts: dict[str, FontInfo] = {}
        self._font_xrefs: dict[str, int] = {}  # font_id -> xref
        self._counter = 0

    def register_font(self, lang: str, doc: 'fitz.Document') -> str:
        """
        フォントを登録しIDを返す

        Args:
            lang: 言語コード ("ja" or "en")
            doc: PyMuPDF Document

        Returns:
            フォントID (F1, F2, ...)
        """
        if lang in self.fonts:
            return self.fonts[lang].font_id

        self._counter += 1
        font_id = f"F{self._counter}"

        default = self.DEFAULT_FONTS.get(lang, self.DEFAULT_FONTS["en"])
        font_info = FontInfo(
            font_id=font_id,
            family=default.family,
            path=default.path,
            fallback=default.fallback,
            encoding=default.encoding,
            is_cjk=default.is_cjk,
        )

        self.fonts[lang] = font_info
        return font_id

    def get_font_path(self, font_id: str) -> Optional[str]:
        """フォントIDからパスを取得（フォールバック対応）"""
        import os
        for font_info in self.fonts.values():
            if font_info.font_id == font_id:
                if os.path.exists(font_info.path):
                    return font_info.path
                if font_info.fallback and os.path.exists(font_info.fallback):
                    return font_info.fallback
        return None

    def get_encoding_type(self, font_id: str) -> str:
        """フォントIDからエンコードタイプを取得"""
        for font_info in self.fonts.values():
            if font_info.font_id == font_id:
                return font_info.encoding
        return "simple"

    def get_is_cjk(self, font_id: str) -> bool:
        """フォントIDからCJK判定"""
        for font_info in self.fonts.values():
            if font_info.font_id == font_id:
                return font_info.is_cjk
        return False

    def get_font_by_id(self, font_id: str) -> Optional[FontInfo]:
        """フォントIDからFontInfo取得"""
        for font_info in self.fonts.values():
            if font_info.font_id == font_id:
                return font_info
        return None

    def select_font_for_text(self, text: str) -> str:
        """
        テキスト内容から適切なフォントIDを選択

        既存 FontManager.select_font() と同等
        """
        for char in text:
            if '\u3040' <= char <= '\u309F':  # Hiragana
                return self._get_font_id_for_lang("ja")
            if '\u30A0' <= char <= '\u30FF':  # Katakana
                return self._get_font_id_for_lang("ja")
            if '\u4E00' <= char <= '\u9FFF':  # Kanji
                return self._get_font_id_for_lang("ja")
        return self._get_font_id_for_lang("en")

    def _get_font_id_for_lang(self, lang: str) -> str:
        """言語からフォントIDを取得"""
        if lang in self.fonts:
            return self.fonts[lang].font_id
        return "F1"  # デフォルト

    def embed_fonts(self, doc: 'fitz.Document') -> None:
        """
        全登録フォントをPDFに埋め込み

        各ページのResourcesにフォントを登録
        """
        fitz = _get_fitz()

        for lang, font_info in self.fonts.items():
            font_path = self.get_font_path(font_info.font_id)
            if not font_path:
                continue

            for page in doc:
                # insert_font は内部で Resources への登録も行う
                xref = page.insert_font(
                    fontname=font_info.font_id,
                    fontfile=font_path,
                )
                self._font_xrefs[font_info.font_id] = xref
```

### 3.3 PdfOperatorGenerator クラス

```python
class PdfOperatorGenerator:
    """
    低レベルPDFオペレータ生成器

    PDFMathTranslate converter.py:384-385 準拠
    """

    def __init__(self, font_registry: FontRegistry):
        self.font_registry = font_registry

    def gen_op_txt(
        self,
        font_id: str,
        size: float,
        x: float,
        y: float,
        text: str,
    ) -> str:
        """
        テキスト描画オペレータを生成

        Args:
            font_id: フォントID (F1, F2, ...)
            size: フォントサイズ (pt)
            x: X座標 (PDF座標系)
            y: Y座標 (PDF座標系)
            text: 表示テキスト

        Returns:
            PDF演算子文字列

        Example:
            >>> gen_op_txt("F1", 12.0, 100.0, 500.0, "Hello")
            "/F1 12.000000 Tf 1 0 0 1 100.000000 500.000000 Tm [<48656c6c6f>] TJ "
        """
        rtxt = self.encode_text(font_id, text)
        return f"/{font_id} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "

    def encode_text(self, font_id: str, text: str) -> str:
        """
        フォントタイプに応じたテキストエンコード

        CIDフォント: 4桁hex (%04x)
        Type1/TrueType: 2桁hex (%02x)
        """
        encoding_type = self.font_registry.get_encoding_type(font_id)

        if encoding_type == "cid":
            return "".join(["%04x" % ord(c) for c in text])
        else:
            return "".join(["%02x" % ord(c) for c in text])

    def gen_op_redaction(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[float, float, float] = (1, 1, 1),
    ) -> str:
        """
        矩形塗りつぶしオペレータを生成（既存テキスト消去用）

        Args:
            x1, y1: 左下座標 (PDF座標系)
            x2, y2: 右上座標 (PDF座標系)
            color: RGB (0-1)

        Returns:
            PDF演算子文字列
        """
        r, g, b = color
        width = x2 - x1
        height = y2 - y1
        return f"q {r:f} {g:f} {b:f} rg {x1:f} {y1:f} {width:f} {height:f} re f Q "

    def gen_op_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        width: float = 1.0,
    ) -> str:
        """
        線描画オペレータを生成

        PDFMathTranslate形式準拠
        """
        return f"q {width:f} w {x1:f} {y1:f} m {x2:f} {y2:f} l S Q "
```

### 3.4 ContentStreamBuilder クラス

```python
class ContentStreamBuilder:
    """
    PDFコンテンツストリーム構築器

    複数のテキスト・グラフィックス要素を
    単一のコンテンツストリームとして構築
    """

    def __init__(self):
        self.operators: list[str] = []
        self._in_text_block = False

    def begin_text(self) -> 'ContentStreamBuilder':
        """テキストブロック開始"""
        if not self._in_text_block:
            self.operators.append("BT ")
            self._in_text_block = True
        return self

    def end_text(self) -> 'ContentStreamBuilder':
        """テキストブロック終了"""
        if self._in_text_block:
            self.operators.append("ET ")
            self._in_text_block = False
        return self

    def add_text_operator(self, op: str) -> 'ContentStreamBuilder':
        """テキストオペレータを追加"""
        if not self._in_text_block:
            self.begin_text()
        self.operators.append(op)
        return self

    def add_graphics_operator(self, op: str) -> 'ContentStreamBuilder':
        """グラフィックスオペレータを追加（テキストブロック外）"""
        if self._in_text_block:
            self.end_text()
        self.operators.append(op)
        return self

    def build(self) -> bytes:
        """コンテンツストリームをバイト列として構築"""
        if self._in_text_block:
            self.end_text()

        stream = "".join(self.operators)
        return stream.encode("latin-1")

    def apply_to_page(self, page: 'fitz.Page', doc: 'fitz.Document') -> None:
        """
        構築したストリームをページに適用

        PyMuPDF の低レベルAPIを使用してコンテンツストリームを追加

        Args:
            page: 対象ページ
            doc: PDFドキュメント
        """
        fitz = _get_fitz()
        stream_bytes = self.build()

        if not stream_bytes.strip():
            return  # 空のストリームは追加しない

        # 方法: 新規コンテンツストリームを作成し、ページに追加
        # PyMuPDF の insert_text を使わず、直接 xref 操作

        # 1. 新しいストリームオブジェクトを作成
        new_xref = doc.get_new_xref()
        doc.update_stream(new_xref, stream_bytes)

        # 2. ストリームオブジェクトの辞書を設定
        doc.xref_set_key(new_xref, "Type", "/XObject")
        doc.xref_set_key(new_xref, "Subtype", "/Form")
        doc.xref_set_key(new_xref, "FormType", "1")

        # BBox を設定 (ページ全体)
        rect = page.rect
        bbox = f"[{rect.x0} {rect.y0} {rect.x1} {rect.y1}]"
        doc.xref_set_key(new_xref, "BBox", bbox)

        # 3. ページの Contents に追加 (overlay)
        # 既存の Contents を取得
        page_xref = page.xref
        contents_str = doc.xref_get_key(page_xref, "Contents")

        if contents_str[0] == "array":
            # 既に配列の場合、追加
            # 例: "[10 0 R 20 0 R]" -> "[10 0 R 20 0 R 30 0 R]"
            arr = contents_str[1].rstrip("]") + f" {new_xref} 0 R]"
            doc.xref_set_key(page_xref, "Contents", arr)
        elif contents_str[0] == "xref":
            # 単一 xref の場合、配列に変換
            old_xref = contents_str[1]
            doc.xref_set_key(page_xref, "Contents", f"[{old_xref} {new_xref} 0 R]")
        else:
            # Contents がない場合、新規設定
            doc.xref_set_key(page_xref, "Contents", f"{new_xref} 0 R")

    def apply_to_page_simple(self, page: 'fitz.Page') -> None:
        """
        簡易版: PyMuPDF の Shape を使用してストリームを追加

        apply_to_page() が動作しない場合のフォールバック
        """
        fitz = _get_fitz()
        stream_bytes = self.build()

        if not stream_bytes.strip():
            return

        # Shape を使用してカスタムコンテンツを挿入
        shape = page.new_shape()

        # ストリームを直接挿入（PyMuPDF 1.24.0+）
        # 注意: この方法はPyMuPDFのバージョンに依存
        try:
            shape.insert_text(
                fitz.Point(0, 0),
                "",
                fontname="helv",
                fontsize=1,
            )
            shape.commit(overlay=True)

            # 実際のストリームを追記
            page._addContentObject(stream_bytes)
        except AttributeError:
            # フォールバック: 警告を出力
            print("Warning: Low-level content stream insertion not supported")
```

### 3.5 座標変換関数

```python
def convert_to_pdf_coordinates(
    box: list[float],
    page_height: float,
) -> tuple[float, float, float, float]:
    """
    yomitoku座標系からPDF座標系へ変換

    yomitoku: 原点左上、Y軸下向き
    PDF: 原点左下、Y軸上向き

    Args:
        box: [x1, y1, x2, y2] yomitoku座標 (左上, 右下)
        page_height: ページ高さ

    Returns:
        (x1, y1, x2, y2) PDF座標 (左下, 右上)
    """
    x1_img, y1_img, x2_img, y2_img = box

    # Y座標を反転
    x1_pdf = x1_img
    y1_pdf = page_height - y2_img  # 下端
    x2_pdf = x2_img
    y2_pdf = page_height - y1_img  # 上端

    return (x1_pdf, y1_pdf, x2_pdf, y2_pdf)


def calculate_text_position(
    box_pdf: tuple[float, float, float, float],
    line_index: int,
    font_size: float,
    line_height: float,
) -> tuple[float, float]:
    """
    テキスト行のPDF座標を計算

    PDFMathTranslate converter.py:519 準拠

    Args:
        box_pdf: (x1, y1, x2, y2) PDF座標 (左下, 右上)
        line_index: 行インデックス (0始まり)
        font_size: フォントサイズ
        line_height: 行高さ倍率

    Returns:
        (x, y) テキスト開始位置 (PDF座標)
    """
    x1, y1, x2, y2 = box_pdf

    x = x1
    # 上端から下方向に配置 (最初の行のベースラインは y2 - font_size)
    y = y2 - font_size - (line_index * font_size * line_height)

    return x, y
```

### 3.6 テキスト行分割関数

```python
def calculate_char_width(char: str, font_size: float, is_cjk: bool) -> float:
    """
    文字幅を計算

    Args:
        char: 文字
        font_size: フォントサイズ
        is_cjk: CJK文字か

    Returns:
        文字幅 (pt)
    """
    # CJK文字判定
    code = ord(char)
    is_fullwidth = (
        is_cjk or
        '\u3040' <= char <= '\u309F' or  # Hiragana
        '\u30A0' <= char <= '\u30FF' or  # Katakana
        '\u4E00' <= char <= '\u9FFF' or  # Kanji
        '\uFF00' <= char <= '\uFFEF'     # Fullwidth forms
    )

    if is_fullwidth:
        return font_size  # 全角
    else:
        return font_size * 0.5  # 半角


def split_text_into_lines(
    text: str,
    box_width: float,
    font_size: float,
    is_cjk: bool,
) -> list[str]:
    """
    テキストをボックス幅に収まるよう行分割

    Args:
        text: 分割対象テキスト
        box_width: ボックス幅 (pt)
        font_size: フォントサイズ
        is_cjk: CJKフォントか

    Returns:
        分割された行のリスト
    """
    if not text:
        return []

    lines = []
    current_line = ""
    current_width = 0.0

    for char in text:
        # 改行文字の処理
        if char == '\n':
            lines.append(current_line)
            current_line = ""
            current_width = 0.0
            continue

        char_width = calculate_char_width(char, font_size, is_cjk)

        if current_width + char_width > box_width and current_line:
            # 現在の行を確定して新しい行を開始
            lines.append(current_line)
            current_line = char
            current_width = char_width
        else:
            current_line += char
            current_width += char_width

    # 最後の行を追加
    if current_line:
        lines.append(current_line)

    return lines
```

### 3.7 ヘルパー関数

```python
def _is_address_on_page(address: str, page_num: int) -> bool:
    """
    アドレスが指定ページのものか判定

    Args:
        address: セルアドレス (P1_1, T2_1_0_0 等)
        page_num: ページ番号 (1始まり)

    Returns:
        該当ページの場合 True
    """
    if address.startswith("P"):
        match = re.match(r"P(\d+)_", address)
        if match:
            return int(match.group(1)) == page_num
    elif address.startswith("T"):
        match = re.match(r"T(\d+)_", address)
        if match:
            return int(match.group(1)) == page_num
    return False
```

---

## 4. メイン関数: reconstruct_pdf_low_level

```python
def reconstruct_pdf_low_level(
    original_pdf_path: str,
    translations: dict[str, str],
    cells: list[TranslationCell],
    lang_out: str,
    output_path: str,
) -> None:
    """
    低レベルPDFオペレータを使用したPDF再構築

    既存 reconstruct_pdf() を置き換え

    Args:
        original_pdf_path: 元PDFパス
        translations: {address: translated_text}
        cells: 元セル情報（座標含む）
        lang_out: 出力言語 ("ja" or "en")
        output_path: 出力PDFパス
    """
    fitz = _get_fitz()
    doc = fitz.open(original_pdf_path)

    # 1. フォント登録
    font_registry = FontRegistry()
    font_registry.register_font("ja", doc)
    font_registry.register_font("en", doc)

    # オペレータ生成器
    op_generator = PdfOperatorGenerator(font_registry)

    # セルマップ作成
    cell_map = {cell.address: cell for cell in cells}

    # 2. ページ単位で処理
    for page_num, page in enumerate(doc, start=1):
        page_height = page.rect.height
        builder = ContentStreamBuilder()

        # このページの翻訳セルを処理
        for address, translated in translations.items():
            # ページフィルタ
            if not _is_address_on_page(address, page_num):
                continue

            cell = cell_map.get(address)
            if not cell:
                continue

            # 座標変換 (yomitoku → PDF)
            box_pdf = convert_to_pdf_coordinates(cell.box, page_height)
            x1, y1, x2, y2 = box_pdf
            box_width = x2 - x1

            # 3. 既存テキスト消去（白塗り）
            redaction_op = op_generator.gen_op_redaction(x1, y1, x2, y2)
            builder.add_graphics_operator(redaction_op)

            # 4. フォント選択
            font_id = font_registry.select_font_for_text(translated)
            is_cjk = font_registry.get_is_cjk(font_id)

            # 5. フォントサイズと行高さ計算 (既存関数を使用)
            font_size = estimate_font_size(cell.box, translated)
            line_height = calculate_line_height(translated, cell.box, font_size, lang_out)

            # 6. テキスト行分割
            lines = split_text_into_lines(translated, box_width, font_size, is_cjk)

            # 7. 各行のテキストオペレータを生成
            for line_idx, line_text in enumerate(lines):
                if not line_text.strip():
                    continue

                x, y = calculate_text_position(box_pdf, line_idx, font_size, line_height)

                # ボックス内に収まるかチェック
                if y < y1:
                    break  # ボックスの下端を超えた

                text_op = op_generator.gen_op_txt(font_id, font_size, x, y, line_text)
                builder.add_text_operator(text_op)

        # 8. ページにストリームを適用
        try:
            builder.apply_to_page(page, doc)
        except Exception as e:
            print(f"Warning: apply_to_page failed for page {page_num}: {e}")
            # フォールバック: 従来の方式を試行
            builder.apply_to_page_simple(page)

    # 9. フォント埋め込み
    font_registry.embed_fonts(doc)

    # 10. 保存
    doc.subset_fonts()
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
```

---

## 5. 処理フロー図

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    reconstruct_pdf_low_level() 処理フロー                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  入力                                                                    │
│  ├── original_pdf_path: 元PDF                                           │
│  ├── translations: {address: translated_text}                          │
│  ├── cells: list[TranslationCell] (box座標含む)                         │
│  └── lang_out: 出力言語                                                  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 1. 初期化                                                          │  │
│  │    ├── FontRegistry() 作成                                         │  │
│  │    ├── register_font("ja") / register_font("en")                  │  │
│  │    ├── PdfOperatorGenerator(font_registry) 作成                    │  │
│  │    └── cell_map = {address: cell} 作成                             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              ↓                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 2. ページループ: for page_num, page in enumerate(doc)              │  │
│  │    │                                                               │  │
│  │    ├── page_height = page.rect.height                              │  │
│  │    ├── ContentStreamBuilder() 作成                                  │  │
│  │    │                                                               │  │
│  │    └── 翻訳セルループ: for address, translated in translations     │  │
│  │         │                                                          │  │
│  │         ├── _is_address_on_page() でフィルタ                        │  │
│  │         ├── cell_map から cell 取得                                 │  │
│  │         │                                                          │  │
│  │         ├── convert_to_pdf_coordinates() で座標変換                 │  │
│  │         │   [yomitoku座標] → [PDF座標]                              │  │
│  │         │                                                          │  │
│  │         ├── gen_op_redaction() で消去オペレータ生成                  │  │
│  │         │   → builder.add_graphics_operator()                      │  │
│  │         │                                                          │  │
│  │         ├── select_font_for_text() でフォント選択                   │  │
│  │         ├── estimate_font_size() でサイズ計算 (既存)                 │  │
│  │         ├── calculate_line_height() で行高さ計算 (既存)              │  │
│  │         │                                                          │  │
│  │         ├── split_text_into_lines() で行分割                        │  │
│  │         │                                                          │  │
│  │         └── 行ループ: for line_idx, line_text in lines             │  │
│  │              ├── calculate_text_position() で座標計算               │  │
│  │              ├── gen_op_txt() でテキストオペレータ生成               │  │
│  │              └── builder.add_text_operator()                        │  │
│  │                                                                     │  │
│  │    builder.apply_to_page(page, doc) でストリーム適用                 │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              ↓                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 3. 後処理                                                          │  │
│  │    ├── font_registry.embed_fonts(doc)                              │  │
│  │    ├── doc.subset_fonts()                                          │  │
│  │    └── doc.save(output_path, garbage=4, deflate=True)              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  出力: 翻訳済みPDF                                                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 既存関数との連携

### 6.1 そのまま使用する既存関数

| 関数 | 場所 | 用途 |
|------|------|------|
| `estimate_font_size(box, text)` | `pdf_translator.py:486` | フォントサイズ推定 |
| `calculate_line_height(text, box, font_size, lang_out)` | `pdf_translator.py:459` | 行高さ計算 |
| `FormulaManager.protect(text)` | `pdf_translator.py:282` | 数式保護 |
| `FormulaManager.restore(text)` | `pdf_translator.py:308` | 数式復元 |

### 6.2 廃止する既存クラス

| クラス | 理由 |
|--------|------|
| `FontManager` | `FontRegistry` に置き換え |

### 6.3 translate_pdf_batch() での呼び出し変更

```python
# 変更前 (pdf_translator.py:687-693)
reconstruct_pdf(
    original_pdf_path=pdf_path,
    translations=all_translations,
    cells=all_cells,
    lang_out=lang_out,
    output_path=output_path,
)

# 変更後
reconstruct_pdf_low_level(
    original_pdf_path=pdf_path,
    translations=all_translations,
    cells=all_cells,
    lang_out=lang_out,
    output_path=output_path,
)
```

---

## 7. テスト計画

### 7.1 単体テスト

```python
# tests/test_pdf_low_level.py

import pytest
from pdf_translator import (
    FontInfo,
    FontRegistry,
    PdfOperatorGenerator,
    ContentStreamBuilder,
    convert_to_pdf_coordinates,
    split_text_into_lines,
    calculate_text_position,
    _is_address_on_page,
)


class TestFontRegistry:
    """FontRegistry テスト"""

    def test_register_font(self):
        """フォント登録"""
        registry = FontRegistry()
        font_id = registry.register_font("ja", None)
        assert font_id == "F1"

    def test_select_font_for_text_japanese(self):
        """日本語テキストのフォント選択"""
        registry = FontRegistry()
        registry.register_font("ja", None)
        registry.register_font("en", None)

        font_id = registry.select_font_for_text("こんにちは")
        assert registry.get_is_cjk(font_id) is True

    def test_select_font_for_text_english(self):
        """英語テキストのフォント選択"""
        registry = FontRegistry()
        registry.register_font("ja", None)
        registry.register_font("en", None)

        font_id = registry.select_font_for_text("Hello")
        assert registry.get_is_cjk(font_id) is False


class TestPdfOperatorGenerator:
    """オペレータ生成テスト"""

    def test_gen_op_txt_ascii(self):
        """ASCII テキストのオペレータ生成"""
        registry = FontRegistry()
        registry.register_font("en", None)
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_txt("F1", 12.0, 100.0, 500.0, "Hello")

        assert "/F1 12.000000 Tf" in op
        assert "1 0 0 1 100.000000 500.000000 Tm" in op
        # "Hello" = 48 65 6c 6c 6f (2桁hex)
        assert "[<48656c6c6f>] TJ" in op

    def test_gen_op_txt_japanese(self):
        """日本語テキストのオペレータ生成 (CID)"""
        registry = FontRegistry()
        registry.register_font("ja", None)
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_txt("F1", 12.0, 100.0, 500.0, "あ")

        # "あ" = U+3042 = 3042 (4桁hex)
        assert "[<3042>] TJ" in op

    def test_gen_op_redaction(self):
        """矩形塗りつぶしオペレータ生成"""
        registry = FontRegistry()
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_redaction(100, 200, 300, 400)

        assert "q" in op  # 状態保存
        assert "1.000000 1.000000 1.000000 rg" in op  # 白色
        assert "re f" in op  # 矩形塗りつぶし
        assert "Q" in op  # 状態復元


class TestCoordinateConversion:
    """座標変換テスト"""

    def test_convert_to_pdf_coordinates(self):
        """yomitoku → PDF座標変換"""
        # yomitoku: (10, 20) - (100, 80) (左上 - 右下)
        # page_height = 800
        # PDF: x1=10, y1=800-80=720, x2=100, y2=800-20=780
        box = [10, 20, 100, 80]
        page_height = 800

        result = convert_to_pdf_coordinates(box, page_height)

        assert result == (10, 720, 100, 780)


class TestTextSplitting:
    """テキスト分割テスト"""

    def test_split_short_text(self):
        """短いテキスト（分割不要）"""
        lines = split_text_into_lines("Hello", 100.0, 12.0, False)
        assert lines == ["Hello"]

    def test_split_long_text(self):
        """長いテキスト（分割必要）"""
        # 幅50pt, フォント10pt, 半角5pt/文字 → 10文字/行
        lines = split_text_into_lines("ABCDEFGHIJKLMNO", 50.0, 10.0, False)
        assert len(lines) == 2
        assert lines[0] == "ABCDEFGHIJ"
        assert lines[1] == "KLMNO"

    def test_split_with_newline(self):
        """改行を含むテキスト"""
        lines = split_text_into_lines("Line1\nLine2", 100.0, 12.0, False)
        assert lines == ["Line1", "Line2"]


class TestHelpers:
    """ヘルパー関数テスト"""

    def test_is_address_on_page_paragraph(self):
        """段落アドレスのページ判定"""
        assert _is_address_on_page("P1_1", 1) is True
        assert _is_address_on_page("P1_1", 2) is False
        assert _is_address_on_page("P2_3", 2) is True

    def test_is_address_on_page_table(self):
        """テーブルアドレスのページ判定"""
        assert _is_address_on_page("T1_0_0_0", 1) is True
        assert _is_address_on_page("T1_0_0_0", 2) is False
        assert _is_address_on_page("T3_1_2_3", 3) is True
```

### 7.2 統合テスト

```python
class TestIntegration:
    """統合テスト"""

    def test_reconstruct_pdf_low_level(self, tmp_path):
        """低レベル再構築の統合テスト"""
        # テスト用PDF作成
        fitz = _get_fitz()
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((100, 100), "Original Text")
        input_path = tmp_path / "input.pdf"
        doc.save(str(input_path))
        doc.close()

        # 翻訳データ
        cells = [
            TranslationCell(
                address="P1_1",
                text="Original Text",
                box=[90, 90, 200, 120],
                page_num=1,
            )
        ]
        translations = {"P1_1": "翻訳されたテキスト"}

        # 再構築
        output_path = tmp_path / "output.pdf"
        reconstruct_pdf_low_level(
            str(input_path),
            translations,
            cells,
            "ja",
            str(output_path),
        )

        # 検証
        assert output_path.exists()
        result_doc = fitz.open(str(output_path))
        assert len(result_doc) == 1
        result_doc.close()
```

---

## 8. 移行手順

### 8.1 実装順序

1. **Step 1**: データクラス追加
   - `FontInfo` を `pdf_translator.py` に追加

2. **Step 2**: FontRegistry 実装
   - `FontRegistry` クラスを追加
   - 既存 `FontManager` は残しておく（互換性）

3. **Step 3**: ヘルパー関数追加
   - `convert_to_pdf_coordinates()`
   - `split_text_into_lines()`
   - `calculate_char_width()`
   - `calculate_text_position()`
   - `_is_address_on_page()`

4. **Step 4**: オペレータ生成クラス追加
   - `PdfOperatorGenerator`
   - `ContentStreamBuilder`

5. **Step 5**: メイン関数追加
   - `reconstruct_pdf_low_level()` を追加

6. **Step 6**: 切り替え
   - `translate_pdf_batch()` の呼び出しを変更
   - 既存 `reconstruct_pdf()` と `FontManager` を削除

### 8.2 フォールバック戦略

低レベル実装で問題が発生した場合:

```python
def reconstruct_pdf_low_level(...):
    try:
        # 低レベル実装
        ...
    except Exception as e:
        print(f"Warning: Low-level reconstruction failed: {e}")
        print("Falling back to insert_textbox method")
        # 既存の reconstruct_pdf() を呼び出し
        reconstruct_pdf(
            original_pdf_path,
            translations,
            cells,
            lang_out,
            output_path,
        )
```

---

## 9. 完了基準

### 9.1 必須要件

- [ ] `FontInfo` データクラスが追加されている
- [ ] `FontRegistry` クラスが実装されている
- [ ] `PdfOperatorGenerator` クラスが実装されている
- [ ] `ContentStreamBuilder` クラスが実装されている
- [ ] `reconstruct_pdf_low_level()` が動作する
- [ ] 日本語・英語の翻訳PDFが正しく生成される
- [ ] 単体テストが全てパスする

### 9.2 推奨要件

- [ ] 既存 `FontManager` が削除されている
- [ ] 既存 `reconstruct_pdf()` が削除されている
- [ ] 位置精度が `insert_textbox` 以上である
- [ ] パフォーマンスが既存実装と同等以上

### 9.3 文書化

- [ ] コード内ドキュメント (docstring)
- [ ] PDF_TRANSLATION_SPEC.md の更新

---

## 付録A: PDF演算子リファレンス

### テキスト演算子

| 演算子 | 説明 | 例 |
|--------|------|-----|
| BT | テキストオブジェクト開始 | `BT` |
| ET | テキストオブジェクト終了 | `ET` |
| Tf | フォント・サイズ設定 | `/F1 12 Tf` |
| Tm | テキスト行列設定 | `1 0 0 1 100 500 Tm` |
| Td | テキスト位置移動 | `10 -15 Td` |
| TJ | テキスト配列表示 | `[<48656c6c6f>] TJ` |
| Tj | 単純テキスト表示 | `<48656c6c6f> Tj` |

### グラフィックス演算子

| 演算子 | 説明 | 例 |
|--------|------|-----|
| q | グラフィックス状態保存 | `q` |
| Q | グラフィックス状態復元 | `Q` |
| rg | RGB塗りつぶし色 | `1 1 1 rg` |
| re | 矩形パス | `100 500 200 50 re` |
| f | パス塗りつぶし | `f` |
| m | パス開始点 | `100 500 m` |
| l | 線パス | `200 500 l` |
| S | パスストローク | `S` |
| w | 線幅 | `1.0 w` |

---

## 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|----------|
| 1.0 | 2025-01-XX | 初版作成 |
| 2.0 | 2025-01-XX | 不整合修正: apply_to_page実装追加、FontRegistry メソッド追加、座標変換・行分割関数追加、reconstruct_pdf_low_level 完全実装 |
