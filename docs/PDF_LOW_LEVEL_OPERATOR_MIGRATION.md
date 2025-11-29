# PDF低レベルオペレータ生成への移行仕様書

## 概要

本仕様書は、現在の`PyMuPDF insert_textbox`ベースのPDF再構築を、**PDFMathTranslate準拠**の低レベルPDFオペレータ生成方式へ移行するための設計・実装ガイドラインを定義する。

### 移行の目的

| 項目 | 現状 (insert_textbox) | 移行後 (PDFMathTranslate準拠) |
|------|----------------------|-------------------------------|
| 位置精度 | 文字単位の丸め誤差あり | ピクセルレベルの精度 |
| フォント混在 | 同一textbox内は単一フォント | 同一行内で自由に切替可能 |
| CJK対応 | 折り返し制限あり | 完全対応 |
| 数式統合 | 別処理が必要 | シームレスに統合 |

### 参照ドキュメント

- [PDFMathTranslate converter.py](https://github.com/PDFMathTranslate/PDFMathTranslate/blob/main/pdf2zh/converter.py)
- [PDFMathTranslate high_level.py](https://github.com/PDFMathTranslate/PDFMathTranslate/blob/main/pdf2zh/high_level.py)
- [Adobe PDF Reference 1.7](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf)

---

## 1. 座標系について

### 1.1 座標系の違い

本移行において、以下の座標系の違いを理解することが重要：

| 座標系 | 原点 | Y軸方向 | 使用箇所 |
|--------|------|---------|----------|
| yomitoku | 左上 | 下向き↓ | 入力: `TranslationCell.box` |
| PyMuPDF高レベルAPI | 左上 | 下向き↓ | `page.insert_textbox()`, `fitz.Rect()` |
| PDF低レベル (Tm) | 左下 | 上向き↑ | `gen_op_txt()` の座標 |

### 1.2 変換の必要性

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  yomitoku box              PyMuPDF Rect           PDF Tm座標    │
│  [x1, y1, x2, y2]          (変換不要)             (Y軸反転必要) │
│                                                                 │
│  ┌────────────┐            ┌────────────┐         ┌────────────┐│
│  │(x1,y1)     │            │(x0,y0)     │         │            ││
│  │   ↓Y       │    ===     │   ↓Y       │   ≠≠≠   │   ↑Y       ││
│  │      (x2,y2)│            │      (x1,y1)│         │(x,y)       ││
│  └────────────┘            └────────────┘         └────────────┘│
│                                                                 │
│  既存コード: そのまま使用   低レベル実装: convert_to_pdf_coordinates() │
│                             で変換が必要                          │
└─────────────────────────────────────────────────────────────────┘
```

**重要**:
- 既存の `reconstruct_pdf()` は PyMuPDF の `insert_textbox()` を使用するため座標変換不要
- 新規の `reconstruct_pdf_low_level()` は PDF低レベルオペレータを使用するため **Y軸反転が必要**

---

## 2. PDFMathTranslate アーキテクチャ

### 2.1 コンテンツストリーム置換方式

PDFMathTranslateは**既存のコンテンツストリームを置換**する方式を採用：

```python
# PDFMathTranslate high_level.py
page.page_xref = doc_zh.get_new_xref()
doc_zh.update_stream(page.page_xref, b"")  # 初期化
doc_zh.update_stream(obj_id, ops_new.encode())  # 新しい内容を設定
```

### 2.2 オペレータ生成関数

```python
# PDFMathTranslate converter.py:384-385
def gen_op_txt(font, size, x, y, rtxt):
    """rtxt は既にhexエンコード済み"""
    return f"/{font} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "
```

### 2.3 テキストエンコーディング（raw_string）

```python
# PDFMathTranslate converter.py - フォント種別によるエンコード
def raw_string(self, fcur, cstk):
    if fcur == self.noto_name:
        # Notoフォント: グリフIDを使用
        return "".join(["%04x" % self.noto.has_glyph(ord(c)) for c in cstk])
    elif isinstance(self.fontmap[fcur], PDFCIDFont):
        # CIDフォント: Unicodeコードポイント
        return "".join(["%04x" % ord(c) for c in cstk])
    else:
        # Single-byte フォント
        return "".join(["%02x" % ord(c) for c in cstk])
```

---

## 3. 既存コードとの統合

### 3.1 既存の定数・クラスとの関係

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
├── class PdfOperatorGenerator     # 新規: PDFMathTranslate準拠
├── class ContentStreamReplacer    # 新規: ストリーム置換
├── convert_to_pdf_coordinates()   # 新規
├── split_text_into_lines()        # 新規
├── _is_address_on_page()          # 新規
└── reconstruct_pdf_low_level()    # 新規: reconstruct_pdfを置き換え
```

### 3.2 必要なimport追加

```python
# pdf_translator.py の先頭に追加
from typing import Iterator, Optional, Callable, Any, Union
from dataclasses import dataclass, field
```

---

## 4. 実装仕様

### 4.1 FontInfo データクラス

```python
@dataclass
class FontInfo:
    """
    フォント情報

    PDFMathTranslate high_level.py:187-203 準拠
    """
    font_id: str           # PDF内部ID (F1, F2, ...)
    family: str            # フォントファミリ名 (表示用)
    path: str              # フォントファイルパス
    fallback: Optional[str]  # フォールバックパス
    encoding: str          # "cid" or "simple"
    is_cjk: bool          # CJKフォントか
```

### 4.2 FontRegistry クラス

```python
class FontRegistry:
    """
    フォント登録・管理

    PDFMathTranslate high_level.py:187-203 準拠
    """

    # デフォルトフォント定義 (Windows)
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
        "zh-CN": FontInfo(
            font_id="F3",
            family="SimSun",
            path="C:/Windows/Fonts/simsun.ttc",
            fallback="C:/Windows/Fonts/msyh.ttc",  # Microsoft YaHei
            encoding="cid",
            is_cjk=True,
        ),
        "ko": FontInfo(
            font_id="F4",
            family="Malgun Gothic",
            path="C:/Windows/Fonts/malgun.ttf",
            fallback="C:/Windows/Fonts/batang.ttc",
            encoding="cid",
            is_cjk=True,
        ),
    }

    def __init__(self):
        self.fonts: dict[str, FontInfo] = {}
        self._font_xrefs: dict[str, int] = {}
        self._counter = 0

    def register_font(self, lang: str) -> str:
        """
        フォントを登録しIDを返す

        Args:
            lang: 言語コード ("ja", "en", "noto")

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
                if font_info.path and os.path.exists(font_info.path):
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

    def select_font_for_text(self, text: str, target_lang: str = "ja") -> str:
        """
        テキスト内容から適切なフォントIDを選択

        CJK言語対応版

        Args:
            text: 対象テキスト
            target_lang: ターゲット言語 ("ja", "en", "zh-CN", "ko")
                         漢字の判定に使用

        Returns:
            フォントID
        """
        for char in text:
            # 日本語固有: ひらがな・カタカナ
            if '\u3040' <= char <= '\u309F':  # Hiragana
                return self._get_font_id_for_lang("ja")
            if '\u30A0' <= char <= '\u30FF':  # Katakana
                return self._get_font_id_for_lang("ja")
            # 韓国語固有: ハングル
            if '\uAC00' <= char <= '\uD7AF':  # Hangul Syllables
                return self._get_font_id_for_lang("ko")
            if '\u1100' <= char <= '\u11FF':  # Hangul Jamo
                return self._get_font_id_for_lang("ko")
            # CJK統合漢字: ターゲット言語に従う
            if '\u4E00' <= char <= '\u9FFF':  # CJK Unified Ideographs
                return self._get_font_id_for_lang(target_lang)
        return self._get_font_id_for_lang("en")

    def _get_font_id_for_lang(self, lang: str) -> str:
        """言語からフォントIDを取得"""
        if lang in self.fonts:
            return self.fonts[lang].font_id
        return "F1"

    def embed_fonts(self, doc: 'fitz.Document') -> None:
        """
        全登録フォントをPDFに埋め込み

        PDFMathTranslate high_level.py 準拠

        Note:
            page.insert_font() は各ページにフォントを埋め込む
            xref は最初のページで取得し保持する
        """
        for lang, font_info in self.fonts.items():
            font_path = self.get_font_path(font_info.font_id)
            if not font_path:
                continue

            # 各ページにフォントを埋め込み
            for page_idx, page in enumerate(doc):
                xref = page.insert_font(
                    fontname=font_info.font_id,
                    fontfile=font_path,
                )
                # 最初のページでのみxrefを保存（全ページで同じxrefが返される）
                if page_idx == 0:
                    self._font_xrefs[font_info.font_id] = xref
```

### 4.3 PdfOperatorGenerator クラス

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
        rtxt: str,
    ) -> str:
        """
        テキスト描画オペレータを生成

        PDFMathTranslate converter.py:384-385 完全準拠

        Args:
            font_id: フォントID (F1, F2, ...)
            size: フォントサイズ (pt)
            x: X座標 (PDF座標系)
            y: Y座標 (PDF座標系)
            rtxt: **既にhexエンコード済み**のテキスト

        Returns:
            PDF演算子文字列
        """
        return f"/{font_id} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "

    def raw_string(self, font_id: str, text: str) -> str:
        """
        フォントタイプに応じたテキストエンコード

        PDFMathTranslate converter.py raw_string() 準拠

        Args:
            font_id: フォントID
            text: エンコードするテキスト

        Returns:
            hexエンコード済み文字列
        """
        encoding_type = self.font_registry.get_encoding_type(font_id)

        if encoding_type == "cid":
            # CIDフォント: Unicodeコードポイント (4桁hex)
            return "".join(["%04x" % ord(c) for c in text])
        else:
            # Single-byte フォント (2桁hex)
            return "".join(["%02x" % ord(c) for c in text])

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

### 4.4 ContentStreamReplacer クラス

```python
class ContentStreamReplacer:
    """
    PDFコンテンツストリーム置換器

    PDFMathTranslate high_level.py 準拠
    - 既存コンテンツを保持しつつ、翻訳テキストを上書き
    """

    def __init__(self, doc: 'fitz.Document', font_registry: 'FontRegistry'):
        self.doc = doc
        self.font_registry = font_registry
        self.operators: list[str] = []
        self._in_text_block = False
        self._used_fonts: set[str] = set()  # 使用されたフォントIDを追跡

    def begin_text(self) -> 'ContentStreamReplacer':
        """テキストブロック開始"""
        if not self._in_text_block:
            self.operators.append("BT ")
            self._in_text_block = True
        return self

    def end_text(self) -> 'ContentStreamReplacer':
        """テキストブロック終了"""
        if self._in_text_block:
            self.operators.append("ET ")
            self._in_text_block = False
        return self

    def add_operator(self, op: str) -> 'ContentStreamReplacer':
        """オペレータを追加"""
        self.operators.append(op)
        return self

    def add_text_operator(self, op: str, font_id: str = None) -> 'ContentStreamReplacer':
        """
        テキストオペレータを追加（自動でBT/ET管理）

        Args:
            op: オペレータ文字列
            font_id: 使用するフォントID（リソース登録用）
        """
        if not self._in_text_block:
            self.begin_text()
        self.operators.append(op)

        # 使用フォントを追跡
        if font_id:
            self._used_fonts.add(font_id)

        return self

    def add_redaction(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[float, float, float] = (1, 1, 1),
    ) -> 'ContentStreamReplacer':
        """
        矩形塗りつぶし（既存テキスト消去用）

        Args:
            x1, y1: 左下座標 (PDF座標系)
            x2, y2: 右上座標 (PDF座標系)
            color: RGB (0-1)
        """
        if self._in_text_block:
            self.end_text()

        r, g, b = color
        width = x2 - x1
        height = y2 - y1
        op = f"q {r:f} {g:f} {b:f} rg {x1:f} {y1:f} {width:f} {height:f} re f Q "
        self.operators.append(op)
        return self

    def build(self) -> bytes:
        """コンテンツストリームをバイト列として構築"""
        if self._in_text_block:
            self.end_text()

        stream = "".join(self.operators)
        return stream.encode("latin-1")

    def apply_to_page(self, page: 'fitz.Page') -> None:
        """
        構築したストリームをページに適用

        PDFMathTranslate high_level.py 準拠
        - 既存コンテンツに新しいストリームを追加（overlay）
        - 使用フォントをページリソースに登録

        Args:
            page: 対象ページ
        """
        stream_bytes = self.build()

        if not stream_bytes.strip():
            return

        # PDFMathTranslate方式: 新しいコンテンツストリームを作成して追加
        # 既存コンテンツは保持される

        # 1. 新しいストリームオブジェクトを作成
        new_xref = self.doc.get_new_xref()
        self.doc.update_stream(new_xref, stream_bytes)

        # 2. ページの Contents に追加
        page_xref = page.xref
        contents_info = self.doc.xref_get_key(page_xref, "Contents")

        if contents_info[0] == "array":
            # 既に配列の場合、末尾に追加
            arr_str = contents_info[1]
            new_arr = arr_str.rstrip("]") + f" {new_xref} 0 R]"
            self.doc.xref_set_key(page_xref, "Contents", new_arr)
        elif contents_info[0] == "xref":
            # 単一xrefの場合、配列に変換
            old_xref = int(contents_info[1].split()[0])
            self.doc.xref_set_key(
                page_xref,
                "Contents",
                f"[{old_xref} 0 R {new_xref} 0 R]"
            )
        else:
            # Contentsがない場合、新規設定
            self.doc.xref_set_key(page_xref, "Contents", f"{new_xref} 0 R")

        # 3. フォントリソースをページに登録
        self._register_font_resources(page)

    def _register_font_resources(self, page: 'fitz.Page') -> None:
        """
        使用フォントをページの /Resources/Font に登録

        Note:
            page.insert_font() で埋め込み済みの場合、PyMuPDFが
            自動的にリソースを登録するため、通常は不要。
            ただし低レベル操作で追加したストリームでフォントを
            使用する場合は明示的な登録が必要な場合がある。
        """
        if not self._used_fonts:
            return

        page_xref = page.xref

        # 現在のリソース辞書を取得
        resources_info = self.doc.xref_get_key(page_xref, "Resources")

        # Font辞書が既に存在するか確認
        # embed_fonts() で insert_font() を呼び出していれば
        # PyMuPDFが自動的にフォントリソースを設定済み
        # この関数は追加の検証/デバッグ用として残す

        for font_id in self._used_fonts:
            font_xref = self.font_registry._font_xrefs.get(font_id)
            if font_xref:
                # フォントが埋め込み済みであることを確認
                # （実際のリソース登録はembed_fonts時に行われる）
                pass

    def clear(self) -> None:
        """オペレータリストをクリア"""
        self.operators = []
        self._in_text_block = False
        self._used_fonts.clear()
```

### 4.5 座標変換関数

```python
def convert_to_pdf_coordinates(
    box: list[float],
    page_height: float,
) -> tuple[float, float, float, float]:
    """
    yomitoku座標系からPDF座標系へ変換

    yomitoku: 原点左上、Y軸下向き (画像座標系)
    PDF: 原点左下、Y軸上向き

    Args:
        box: [x1, y1, x2, y2] yomitoku座標 (左上, 右下)
        page_height: ページ高さ

    Returns:
        (x1, y1, x2, y2) PDF座標 (左下, 右上)
    """
    x1_img, y1_img, x2_img, y2_img = box

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

    PDFMathTranslate converter.py 準拠

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
    # 上端から下方向に配置
    # PDFMathTranslate: y = y2 + dy - (lidx * size * line_height)
    y = y2 - font_size - (line_index * font_size * line_height)

    return x, y
```

### 4.6 テキスト行分割関数

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
    is_fullwidth = (
        is_cjk or
        '\u3040' <= char <= '\u309F' or  # Hiragana
        '\u30A0' <= char <= '\u30FF' or  # Katakana
        '\u4E00' <= char <= '\u9FFF' or  # Kanji
        '\uFF00' <= char <= '\uFFEF'     # Fullwidth forms
    )

    if is_fullwidth:
        return font_size
    else:
        return font_size * 0.5


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
        if char == '\n':
            lines.append(current_line)
            current_line = ""
            current_width = 0.0
            continue

        char_width = calculate_char_width(char, font_size, is_cjk)

        if current_width + char_width > box_width and current_line:
            lines.append(current_line)
            current_line = char
            current_width = char_width
        else:
            current_line += char
            current_width += char_width

    if current_line:
        lines.append(current_line)

    return lines
```

### 4.7 ヘルパー関数

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

## 5. メイン関数: reconstruct_pdf_low_level

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

    PDFMathTranslate準拠の実装（CJK対応）

    Args:
        original_pdf_path: 元PDFパス
        translations: {address: translated_text}
        cells: 元セル情報（座標含む）
        lang_out: 出力言語 ("ja", "en", "zh-CN", "ko")
        output_path: 出力PDFパス

    Raises:
        FileNotFoundError: 元PDFが存在しない場合
        Exception: PDF処理中のエラー
    """
    fitz = _get_fitz()
    doc = fitz.open(original_pdf_path)

    try:
        # 1. フォント登録（CJK全言語対応）
        font_registry = FontRegistry()
        font_registry.register_font("ja")
        font_registry.register_font("en")
        font_registry.register_font("zh-CN")
        font_registry.register_font("ko")

        # オペレータ生成器
        op_generator = PdfOperatorGenerator(font_registry)

        # セルマップ作成
        cell_map = {cell.address: cell for cell in cells}

        # 2. フォント埋め込み（ページループの前に実行）
        font_registry.embed_fonts(doc)

        # 3. ページ単位で処理
        for page_num, page in enumerate(doc, start=1):
            page_height = page.rect.height
            replacer = ContentStreamReplacer(doc, font_registry)

            # このページの翻訳セルを処理
            for address, translated in translations.items():
                if not _is_address_on_page(address, page_num):
                    continue

                cell = cell_map.get(address)
                if not cell:
                    continue

                try:
                    # 座標変換 (yomitoku → PDF)
                    box_pdf = convert_to_pdf_coordinates(cell.box, page_height)
                    x1, y1, x2, y2 = box_pdf
                    box_width = x2 - x1

                    # 4. 既存テキスト消去（白塗り）
                    replacer.add_redaction(x1, y1, x2, y2)

                    # 5. フォント選択（ターゲット言語を考慮）
                    font_id = font_registry.select_font_for_text(translated, lang_out)
                    is_cjk = font_registry.get_is_cjk(font_id)

                    # 6. フォントサイズと行高さ計算 (既存関数を使用)
                    font_size = estimate_font_size(cell.box, translated)
                    line_height = calculate_line_height(translated, cell.box, font_size, lang_out)

                    # 7. テキスト行分割
                    lines = split_text_into_lines(translated, box_width, font_size, is_cjk)

                    # 8. 各行のテキストオペレータを生成
                    for line_idx, line_text in enumerate(lines):
                        if not line_text.strip():
                            continue

                        x, y = calculate_text_position(box_pdf, line_idx, font_size, line_height)

                        if y < y1:
                            break  # ボックスの下端を超えた

                        # PDFMathTranslate準拠: 先にエンコードしてからgen_op_txt
                        rtxt = op_generator.raw_string(font_id, line_text)
                        text_op = op_generator.gen_op_txt(font_id, font_size, x, y, rtxt)
                        replacer.add_text_operator(text_op, font_id)

                except Exception as e:
                    print(f"  Warning: Failed to process cell {address}: {e}")
                    continue

            # 9. ページにストリームを適用
            replacer.apply_to_page(page)

        # 10. 保存 (PDFMathTranslate: garbage=3, deflate=True)
        doc.subset_fonts(fallback=True)
        doc.save(output_path, garbage=3, deflate=True)

    finally:
        doc.close()
```

---

## 6. 処理フロー図

```
┌─────────────────────────────────────────────────────────────────────────┐
│     reconstruct_pdf_low_level() - PDFMathTranslate準拠 (CJK対応)         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 1. 初期化                                                          │  │
│  │    ├── FontRegistry() 作成                                         │  │
│  │    ├── register_font("ja"/"en"/"zh-CN"/"ko") ← CJK全言語対応       │  │
│  │    ├── PdfOperatorGenerator(font_registry) 作成                    │  │
│  │    └── cell_map = {address: cell} 作成                             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              ↓                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 2. フォント埋め込み（ページループの前に実行）                       │  │
│  │    └── font_registry.embed_fonts(doc) ← 全フォントを先に埋め込み   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              ↓                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 3. ページループ                                                     │  │
│  │    │                                                               │  │
│  │    ├── ContentStreamReplacer(doc) 作成                              │  │
│  │    │                                                               │  │
│  │    └── 翻訳セルループ                                               │  │
│  │         │                                                          │  │
│  │         ├── convert_to_pdf_coordinates() で座標変換                 │  │
│  │         │                                                          │  │
│  │         ├── add_redaction() で白塗り                                │  │
│  │         │                                                          │  │
│  │         ├── select_font_for_text(text, lang_out) でフォント選択    │  │
│  │         ├── estimate_font_size() / calculate_line_height()         │  │
│  │         ├── split_text_into_lines() で行分割                        │  │
│  │         │                                                          │  │
│  │         └── 行ループ                                                │  │
│  │              ├── raw_string() でhexエンコード ← PDFMathTranslate準拠│  │
│  │              ├── gen_op_txt() でオペレータ生成                      │  │
│  │              └── add_text_operator()                                │  │
│  │                                                                     │  │
│  │    replacer.apply_to_page(page) でストリーム適用                    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              ↓                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ 4. 後処理                                                          │  │
│  │    ├── doc.subset_fonts(fallback=True)  ← PDFMathTranslate準拠     │  │
│  │    └── doc.save(output_path, garbage=3, deflate=True)              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 7. PDFMathTranslate との対応表

| PDFMathTranslate | 本仕様書 | 状態 |
|------------------|---------|------|
| `gen_op_txt(font, size, x, y, rtxt)` | `gen_op_txt(font_id, size, x, y, rtxt)` | ✅ 完全準拠 |
| `raw_string(fcur, cstk)` | `raw_string(font_id, text)` | ✅ 完全準拠 |
| CIDフォント: `%04x % ord(c)` | `%04x % ord(c)` | ✅ 同一 |
| Single-byte: `%02x % ord(c)` | `%02x % ord(c)` | ✅ 同一 |
| `doc.update_stream(xref, ops.encode())` | `doc.update_stream(new_xref, stream_bytes)` | ✅ 同一 |
| `subset_fonts(fallback=True)` | `subset_fonts(fallback=True)` | ✅ 同一 |
| `garbage=3, deflate=True` | `garbage=3, deflate=True` | ✅ 同一 |

### 7.1 CJK対応フォント

| 言語 | フォントID | フォントファミリ | エンコード |
|------|-----------|-----------------|-----------|
| 日本語 (ja) | F1 | MS-PMincho | CID (4桁hex) |
| 英語 (en) | F2 | Arial | Simple (2桁hex) |
| 中国語簡体字 (zh-CN) | F3 | SimSun | CID (4桁hex) |
| 韓国語 (ko) | F4 | Malgun Gothic | CID (4桁hex) |

---

## 8. テスト計画

### 8.1 単体テスト

```python
# tests/test_pdf_low_level.py

import pytest
from pdf_translator import (
    FontInfo,
    FontRegistry,
    PdfOperatorGenerator,
    ContentStreamReplacer,
    convert_to_pdf_coordinates,
    split_text_into_lines,
    calculate_text_position,
    _is_address_on_page,
)


class TestFontRegistry:
    """FontRegistry テスト"""

    def test_register_font(self):
        """フォント登録テスト"""
        registry = FontRegistry()
        font_id = registry.register_font("ja")
        assert font_id == "F1"

    def test_register_font_idempotent(self):
        """同じ言語を2回登録しても同じIDが返る"""
        registry = FontRegistry()
        font_id1 = registry.register_font("ja")
        font_id2 = registry.register_font("ja")
        assert font_id1 == font_id2

    def test_select_font_for_text_japanese(self):
        """日本語テキストで日本語フォントが選択される"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")

        font_id = registry.select_font_for_text("こんにちは")
        assert registry.get_is_cjk(font_id) is True

    def test_select_font_for_text_english(self):
        """英語テキストで英語フォントが選択される"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")

        font_id = registry.select_font_for_text("Hello")
        assert registry.get_is_cjk(font_id) is False

    def test_select_font_for_text_korean(self):
        """韓国語テキストで韓国語フォントが選択される"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")
        registry.register_font("ko")

        # ハングル文字 "안녕하세요" (Hello in Korean)
        font_id = registry.select_font_for_text("안녕하세요")
        font_info = registry.get_font_by_id(font_id)
        assert font_info.family == "Malgun Gothic"

    def test_select_font_for_text_chinese_with_target_lang(self):
        """漢字テキストでターゲット言語に応じたフォントが選択される"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")
        registry.register_font("zh-CN")

        # 漢字のみのテキスト "中文" - target_langによって異なるフォントが選択される
        font_id_ja = registry.select_font_for_text("中文", target_lang="ja")
        font_id_zh = registry.select_font_for_text("中文", target_lang="zh-CN")

        font_info_ja = registry.get_font_by_id(font_id_ja)
        font_info_zh = registry.get_font_by_id(font_id_zh)

        assert font_info_ja.family == "MS-PMincho"
        assert font_info_zh.family == "SimSun"

    def test_get_encoding_type(self):
        """エンコードタイプの取得テスト"""
        registry = FontRegistry()
        ja_id = registry.register_font("ja")
        en_id = registry.register_font("en")
        zh_id = registry.register_font("zh-CN")
        ko_id = registry.register_font("ko")

        assert registry.get_encoding_type(ja_id) == "cid"
        assert registry.get_encoding_type(en_id) == "simple"
        assert registry.get_encoding_type(zh_id) == "cid"
        assert registry.get_encoding_type(ko_id) == "cid"


class TestPdfOperatorGenerator:
    """オペレータ生成テスト - PDFMathTranslate準拠"""

    def test_raw_string_cid(self):
        """CIDフォントのエンコード"""
        registry = FontRegistry()
        ja_id = registry.register_font("ja")
        gen = PdfOperatorGenerator(registry)

        # "あ" = U+3042
        rtxt = gen.raw_string(ja_id, "あ")
        assert rtxt == "3042"

    def test_raw_string_simple(self):
        """Single-byteフォントのエンコード"""
        registry = FontRegistry()
        en_id = registry.register_font("en")
        gen = PdfOperatorGenerator(registry)

        # "A" = 0x41
        rtxt = gen.raw_string(en_id, "A")
        assert rtxt == "41"

    def test_gen_op_txt(self):
        """PDFMathTranslate形式のオペレータ生成"""
        registry = FontRegistry()
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_txt("F1", 12.0, 100.0, 500.0, "3042")

        assert "/F1 12.000000 Tf" in op
        assert "1 0 0 1 100.000000 500.000000 Tm" in op
        assert "[<3042>] TJ" in op


class TestCoordinateConversion:
    """座標変換テスト"""

    def test_convert_to_pdf_coordinates(self):
        box = [10, 20, 100, 80]
        page_height = 800

        result = convert_to_pdf_coordinates(box, page_height)

        assert result == (10, 720, 100, 780)


class TestTextSplitting:
    """テキスト分割テスト"""

    def test_split_short_text(self):
        lines = split_text_into_lines("Hello", 100.0, 12.0, False)
        assert lines == ["Hello"]

    def test_split_long_text(self):
        lines = split_text_into_lines("ABCDEFGHIJKLMNO", 50.0, 10.0, False)
        assert len(lines) == 2

    def test_split_with_newline(self):
        lines = split_text_into_lines("Line1\nLine2", 100.0, 12.0, False)
        assert lines == ["Line1", "Line2"]
```

### 8.2 統合テスト

```python
class TestIntegration:
    """統合テスト"""

    def test_reconstruct_pdf_low_level(self, tmp_path):
        """PDFMathTranslate準拠の再構築テスト"""
        fitz = _get_fitz()

        # テスト用PDF作成
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

## 9. 移行手順

### 9.1 実装順序

1. **Step 1**: データクラス追加
   - `FontInfo` を追加

2. **Step 2**: FontRegistry 実装
   - `FontRegistry` クラスを追加
   - NotoフォントのグリフID取得対応

3. **Step 3**: オペレータ生成クラス追加
   - `PdfOperatorGenerator` (PDFMathTranslate準拠)
   - `ContentStreamReplacer`

4. **Step 4**: ヘルパー関数追加
   - 座標変換、テキスト分割など

5. **Step 5**: メイン関数追加
   - `reconstruct_pdf_low_level()`

6. **Step 6**: 切り替え
   - `translate_pdf_batch()` の呼び出しを変更

### 9.2 translate_pdf_batch() 切り替え方法

移行期間中は、フラグによる切り替えを実装：

```python
# pdf_translator.py

# 移行フラグ（将来的に削除）
USE_LOW_LEVEL_OPERATORS = False


def translate_pdf_batch(
    pdf_path: str,
    output_path: str,
    lang_in: str,
    lang_out: str,
    translation_engine,
    progress_callback: Callable[[int, int, str], None] = None,
    cancel_check: Callable[[], bool] = None,
    batch_size: int = BATCH_SIZE,
    device: str = "cpu",
    reading_order: str = "auto",
    include_headers: bool = False,
    glossary_path: Path = None,
    use_low_level: bool = None,  # 追加: 明示的な切り替え
) -> PdfTranslationResult:
    """
    ...既存のドキュメント...

    Args:
        ...
        use_low_level: 低レベルオペレータを使用するか
                       None の場合は USE_LOW_LEVEL_OPERATORS を使用
    """
    # ... 既存の処理 ...

    # Phase 5: PDF reconstruction
    if progress_callback:
        progress_callback(total_pages, total_pages, "reconstruction")

    # 切り替えロジック
    _use_low_level = use_low_level if use_low_level is not None else USE_LOW_LEVEL_OPERATORS

    if _use_low_level:
        reconstruct_pdf_low_level(
            original_pdf_path=pdf_path,
            translations=all_translations,
            cells=all_cells,
            lang_out=lang_out,
            output_path=output_path,
        )
    else:
        reconstruct_pdf(
            original_pdf_path=pdf_path,
            translations=all_translations,
            cells=all_cells,
            lang_out=lang_out,
            output_path=output_path,
        )

    # ...
```

### 9.3 移行チェックリスト

```
□ Step 1: FontInfo データクラスを追加
□ Step 2: FontRegistry クラスを追加
  □ register_font() 実装
  □ embed_fonts() 実装
  □ select_font_for_text(text, target_lang) 実装（CJK対応）
□ Step 3: PdfOperatorGenerator クラスを追加
  □ gen_op_txt() 実装
  □ raw_string() 実装（CID/Simple対応）
□ Step 4: ContentStreamReplacer クラスを追加
  □ add_text_operator() 実装（font_id追跡付き）
  □ add_redaction() 実装
  □ apply_to_page() 実装（フォントリソース登録付き）
□ Step 5: ヘルパー関数を追加
  □ convert_to_pdf_coordinates() 実装
  □ calculate_text_position() 実装
  □ split_text_into_lines() 実装
  □ _is_address_on_page() 実装
□ Step 6: reconstruct_pdf_low_level() を追加
  □ CJK全言語（ja/en/zh-CN/ko）のフォント登録
  □ embed_fonts() をページループ前に配置
  □ エラーハンドリング付きで実装
  □ 単体テスト作成
□ Step 7: translate_pdf_batch() に切り替えフラグを追加
□ Step 8: テスト実行
  □ 単体テストがパス
  □ 統合テストがパス
  □ 実PDFで動作確認（日本語/英語/中国語/韓国語）
□ Step 9: USE_LOW_LEVEL_OPERATORS = True に変更
□ Step 10: 旧コード (reconstruct_pdf, FontManager) を削除
```

---

## 10. 完了基準

### 10.1 必須要件

- [ ] `FontInfo` データクラスが追加されている
- [ ] `FontRegistry` クラスが実装されている（CJK全言語対応）
- [ ] `PdfOperatorGenerator` が PDFMathTranslate準拠
- [ ] `ContentStreamReplacer` が実装されている
- [ ] `reconstruct_pdf_low_level()` が動作する
- [ ] 単体テストが全てパスする

### 10.2 PDFMathTranslate準拠チェック

- [ ] `gen_op_txt(font, size, x, y, rtxt)` 形式
- [ ] `raw_string()` でCID/Simple別エンコード
- [ ] `subset_fonts(fallback=True)`
- [ ] `garbage=3, deflate=True` で保存

### 10.3 CJK対応チェック

- [ ] 日本語 (ja): MS-PMincho
- [ ] 英語 (en): Arial
- [ ] 中国語簡体字 (zh-CN): SimSun
- [ ] 韓国語 (ko): Malgun Gothic
- [ ] `select_font_for_text(text, target_lang)` でターゲット言語を考慮

---

## 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|----------|
| 1.0 | 2025-01-XX | 初版作成 |
| 2.0 | 2025-01-XX | 不整合修正 |
| 3.0 | 2025-01-XX | PDFMathTranslate完全準拠: raw_string追加、NotoグリフID対応、ContentStreamReplacerに変更 |
| 4.0 | 2025-11-29 | 既存メソッドとの不整合修正: 座標系説明追加、register_font()からdoc引数削除、embed_fonts()のxref修正、apply_to_page()にフォントリソース登録追加、エラーハンドリング追加、テストコード修正、移行手順詳細化 |
| 5.0 | 2025-11-29 | CJK言語対応: zh-CN (SimSun), ko (Malgun Gothic) 追加、Notoフォント削除、select_font_for_text()にtarget_lang引数追加、embed_fonts()をページループ前に移動、テストケース追加 |
