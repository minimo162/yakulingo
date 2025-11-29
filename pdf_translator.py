"""
PDF Translation Module
Translates PDF documents using yomitoku for layout analysis and Copilot for translation.

Based on:
- yomitoku: Japanese-specialized OCR and layout analysis
- PDFMathTranslate: PDF reconstruction approach

Features:
- Batch processing for large PDFs
- Formula protection ({v*} placeholders)
- Dynamic line height compression
- Dual font support (Japanese/English)
"""

import re
import gc
import unicodedata
from pathlib import Path
from typing import Iterator, Optional, Callable
from dataclasses import dataclass, field

import numpy as np

# Lazy imports for optional dependencies
_pypdfium2 = None
_fitz = None
_yomitoku = None
_torch = None


def _get_pypdfium2():
    """Lazy import pypdfium2"""
    global _pypdfium2
    if _pypdfium2 is None:
        import pypdfium2 as pdfium
        _pypdfium2 = pdfium
    return _pypdfium2


def _get_fitz():
    """Lazy import PyMuPDF"""
    global _fitz
    if _fitz is None:
        import fitz
        _fitz = fitz
    return _fitz


def _get_yomitoku():
    """Lazy import yomitoku"""
    global _yomitoku
    if _yomitoku is None:
        from yomitoku import DocumentAnalyzer
        from yomitoku.data.functions import load_pdf
        _yomitoku = {'DocumentAnalyzer': DocumentAnalyzer, 'load_pdf': load_pdf}
    return _yomitoku


def _get_torch():
    """Lazy import torch"""
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


# =============================================================================
# Constants
# =============================================================================
BATCH_SIZE = 5  # Pages per batch
DPI = 200       # Fixed DPI for precision
MAX_CHARS_PER_REQUEST = 6000  # Copilot token limit

# Font configuration (Windows)
FONT_CONFIG = {
    "ja": {
        "name": "MS-PMincho",
        "path": "C:/Windows/Fonts/msmincho.ttc",
        "fallback": "msgothic.ttc",
    },
    "en": {
        "name": "Arial",
        "path": "C:/Windows/Fonts/arial.ttf",
        "fallback": "times.ttf",
    },
}

# Language-specific line height (PDFMathTranslate reference)
LANG_LINEHEIGHT_MAP = {
    "ja": 1.1,
    "en": 1.2,
}
DEFAULT_LINE_HEIGHT = 1.1

# Formula font pattern (PDFMathTranslate reference)
DEFAULT_VFONT_PATTERN = (
    r"(CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|"
    r"TeX-|rsfs|txsy|wasy|stmary|"
    r".*Mono|.*Code|.*Ital|.*Sym|.*Math)"
)

# Unicode categories for formula detection
FORMULA_UNICODE_CATEGORIES = ["Lm", "Mn", "Sk", "Sm", "Zl", "Zp", "Zs"]


# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class TranslationCell:
    """Single translation unit"""
    address: str           # P{page}_{order} or T{page}_{table}_{row}_{col}
    text: str              # Original text
    box: list[float]       # [x1, y1, x2, y2]
    direction: str = "horizontal"
    role: str = "text"
    page_num: int = 1


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
    is_cjk: bool           # CJKフォントか


@dataclass
class PdfTranslationResult:
    """PDF translation result"""
    success: bool = False
    output_path: Optional[Path] = None
    page_count: int = 0
    cell_count: int = 0
    error_message: str = ""


# =============================================================================
# Phase 1: PDF Loading (yomitoku compatible)
# =============================================================================
def get_total_pages(pdf_path: str) -> int:
    """Get total page count"""
    pdfium = _get_pypdfium2()
    pdf = pdfium.PdfDocument(pdf_path)
    total = len(pdf)
    pdf.close()
    return total


def iterate_pdf_pages(
    pdf_path: str,
    batch_size: int = BATCH_SIZE,
    dpi: int = DPI,
) -> Iterator[tuple[int, list[np.ndarray]]]:
    """
    Stream PDF pages in batches.

    Args:
        pdf_path: Path to PDF file
        batch_size: Pages per batch
        dpi: Resolution (fixed at 200)

    Yields:
        (batch_start_page, list[np.ndarray]): Batch start index and BGR images
    """
    pdfium = _get_pypdfium2()
    pdf = pdfium.PdfDocument(pdf_path)
    total_pages = len(pdf)

    for batch_start in range(0, total_pages, batch_size):
        batch_end = min(batch_start + batch_size, total_pages)
        batch_images = []

        for page_idx in range(batch_start, batch_end):
            page = pdf[page_idx]
            bitmap = page.render(scale=dpi / 72)
            img = bitmap.to_numpy()
            # RGB to BGR (OpenCV compatible)
            img = img[:, :, ::-1].copy()
            batch_images.append(img)

        yield batch_start, batch_images

    pdf.close()


def load_pdf_document(pdf_path: str, dpi: int = DPI) -> list[np.ndarray]:
    """
    Load entire PDF as images (for small PDFs).

    Note: For large PDFs, use iterate_pdf_pages() instead.
    """
    yomitoku = _get_yomitoku()
    return yomitoku['load_pdf'](pdf_path, dpi=dpi)


# =============================================================================
# Phase 2: Layout Analysis (yomitoku)
# =============================================================================
def get_device(config_device: str = "cpu") -> str:
    """
    Determine execution device.

    Args:
        config_device: "cpu" or "cuda"

    Returns:
        Actual device to use
    """
    if config_device == "cuda":
        torch = _get_torch()
        if torch.cuda.is_available():
            return "cuda"
        else:
            print("Warning: CUDA not available, falling back to CPU")
            return "cpu"
    return "cpu"


def analyze_document(img: np.ndarray, device: str = "cpu", reading_order: str = "auto"):
    """
    Analyze document layout using yomitoku.

    Args:
        img: BGR image (numpy array)
        device: "cpu" or "cuda"
        reading_order: "auto", "left2right", "top2bottom", "right2left"

    Returns:
        DocumentAnalyzerSchema with paragraphs, tables, figures, words
    """
    yomitoku = _get_yomitoku()
    analyzer = yomitoku['DocumentAnalyzer'](
        configs={},
        device=device,
        visualize=False,
        ignore_meta=False,
        reading_order=reading_order,
        split_text_across_cells=False,
    )
    results, _, _ = analyzer(img)
    return results


# =============================================================================
# Phase 3: Formula Protection (PDFMathTranslate compatible)
# =============================================================================
def vflag(font: str, char: str, vfont: str = None, vchar: str = None) -> bool:
    """
    Check if character is a formula.

    PDFMathTranslate converter.py:156-177 compatible.
    """
    # Rule 1: CID notation
    if re.match(r"\(cid:", char):
        return True

    # Rule 2: Font-based detection
    font_pattern = vfont if vfont else DEFAULT_VFONT_PATTERN
    if re.match(font_pattern, font):
        return True

    # Rule 3: Character class detection
    if vchar:
        if re.match(vchar, char):
            return True
    else:
        if char and unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
            return True

    return False


class FormulaManager:
    """
    Manages formula protection and restoration.

    PDFMathTranslate converter.py:175-181 compatible.
    """

    def __init__(self):
        self.var: list[str] = []        # Protected formulas
        self.varl: list[list] = []      # Formula lines
        self.varf: list[float] = []     # Y offsets
        self.vlen: list[float] = []     # Widths
        self._formula_count = 0

    def protect(self, text: str) -> str:
        """
        Protect formulas with {vN} placeholders.

        Simple implementation: Detects LaTeX-like patterns.
        Full implementation would use font analysis.
        """
        # Pattern: inline math $...$, display math $$...$$
        patterns = [
            (r'\$\$([^$]+)\$\$', True),   # Display math
            (r'\$([^$]+)\$', True),        # Inline math
            (r'\\[a-zA-Z]+\{[^}]*\}', True),  # LaTeX commands
        ]

        result = text
        for pattern, _ in patterns:
            matches = list(re.finditer(pattern, result))
            for match in reversed(matches):
                formula = match.group(0)
                placeholder = f"{{v{self._formula_count}}}"
                self.var.append(formula)
                self._formula_count += 1
                result = result[:match.start()] + placeholder + result[match.end():]

        return result

    def restore(self, text: str) -> str:
        """
        Restore {vN} placeholders to original formulas.

        PDFMathTranslate converter.py:409-420 compatible.
        """
        pattern = r"\{\s*v([\d\s]+)\}"

        def replacer(match):
            vid = int(match.group(1).replace(" ", ""))
            if 0 <= vid < len(self.var):
                return self.var[vid]
            return match.group(0)

        return re.sub(pattern, replacer, text, flags=re.IGNORECASE)


# =============================================================================
# Phase 3.5: Low-Level PDF Classes (PDFMathTranslate準拠)
# =============================================================================
class FontRegistry:
    """
    フォント登録・管理

    PDFMathTranslate high_level.py:187-203 準拠
    CJK言語対応（日本語/英語/中国語簡体字/韓国語）
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
            lang: 言語コード ("ja", "en", "zh-CN", "ko")

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

    def embed_fonts(self, doc) -> None:
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


class ContentStreamReplacer:
    """
    PDFコンテンツストリーム置換器

    PDFMathTranslate high_level.py 準拠
    - 既存コンテンツを保持しつつ、翻訳テキストを上書き
    """

    def __init__(self, doc, font_registry: FontRegistry):
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

    def apply_to_page(self, page) -> None:
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

    def _register_font_resources(self, page) -> None:
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


# =============================================================================
# Phase 3.6: Low-Level PDF Helper Functions
# =============================================================================
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


# =============================================================================
# Phase 4: Translation Data Preparation
# =============================================================================
def prepare_translation_cells(
    results,
    page_num: int,
    include_headers: bool = False,
) -> list[TranslationCell]:
    """
    Convert yomitoku results to translation cells.

    Args:
        results: DocumentAnalyzerSchema
        page_num: Page number (1-based)
        include_headers: Include page header/footer

    Returns:
        List of TranslationCell
    """
    cells = []

    # Paragraphs
    for para in sorted(results.paragraphs, key=lambda p: p.order):
        if not include_headers and para.role in ["page_header", "page_footer"]:
            continue

        if para.contents.strip():
            cells.append(TranslationCell(
                address=f"P{page_num}_{para.order}",
                text=para.contents,
                box=para.box,
                direction=para.direction,
                role=para.role,
                page_num=page_num,
            ))

    # Tables
    for table in results.tables:
        for cell in table.cells:
            if cell.contents.strip():
                cells.append(TranslationCell(
                    address=f"T{page_num}_{table.order}_{cell.row}_{cell.col}",
                    text=cell.contents,
                    box=cell.box,
                    direction="horizontal",
                    role="table_cell",
                    page_num=page_num,
                ))

    return cells


def split_cells_for_translation(
    cells: list[TranslationCell],
    max_chars: int = MAX_CHARS_PER_REQUEST,
) -> list[list[TranslationCell]]:
    """
    Split cells into chunks for Copilot token limit.
    """
    chunks = []
    current_chunk = []
    current_chars = 0

    for cell in cells:
        cell_chars = len(cell.text) + len(cell.address) + 2
        if current_chars + cell_chars > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0
        current_chunk.append(cell)
        current_chars += cell_chars

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def format_cells_as_tsv(cells: list[TranslationCell]) -> str:
    """Format cells as TSV for Copilot prompt"""
    return "\n".join(f"{cell.address}\t{cell.text}" for cell in cells)


# =============================================================================
# Phase 5: PDF Reconstruction (PyMuPDF)
# =============================================================================
class FontManager:
    """Dual font system (Japanese: MS P Mincho, English: Arial)"""

    def __init__(self, lang_out: str):
        self.lang_out = lang_out
        self.font_config = FONT_CONFIG.get(lang_out, FONT_CONFIG["en"])
        self.font_id = {}

    def get_font_name(self) -> str:
        return self.font_config["name"]

    def get_font_path(self) -> Optional[str]:
        import os
        path = self.font_config["path"]
        if os.path.exists(path):
            return path
        fallback = self.font_config.get("fallback")
        if fallback:
            fallback_path = f"C:/Windows/Fonts/{fallback}"
            if os.path.exists(fallback_path):
                return fallback_path
        return None

    def embed_fonts(self, doc) -> None:
        """Embed fonts in all pages"""
        fitz = _get_fitz()
        font_path = self.get_font_path()
        font_name = self.get_font_name()

        if font_path:
            for page in doc:
                self.font_id[font_name] = page.insert_font(
                    fontname=font_name,
                    fontfile=font_path,
                )

    def select_font(self, text: str) -> str:
        """Select font based on text content"""
        for char in text:
            if '\u3040' <= char <= '\u309F':  # Hiragana
                return FONT_CONFIG["ja"]["name"]
            if '\u30A0' <= char <= '\u30FF':  # Katakana
                return FONT_CONFIG["ja"]["name"]
            if '\u4E00' <= char <= '\u9FFF':  # Kanji
                return FONT_CONFIG["ja"]["name"]
        return FONT_CONFIG["en"]["name"]


def calculate_line_height(
    translated_text: str,
    box: list[float],
    font_size: float,
    lang_out: str,
) -> float:
    """
    Calculate line height with dynamic compression.

    PDFMathTranslate converter.py:512-515 compatible.
    """
    x1, y1, x2, y2 = box
    height = y2 - y1

    line_height = LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    # Estimate lines needed
    chars_per_line = max(1, (x2 - x1) / (font_size * 0.5))
    lines_needed = max(1, len(translated_text) / chars_per_line)

    # Dynamic compression (5% steps)
    while (lines_needed + 1) * font_size * line_height > height and line_height >= 1.0:
        line_height -= 0.05

    return max(line_height, 1.0)


def estimate_font_size(box: list[float], text: str) -> float:
    """Estimate appropriate font size for box"""
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1

    # Simple heuristic: base on box height and text length
    max_font_size = height * 0.8
    chars_per_line = max(1, len(text) / max(1, height / 14))
    width_based_size = width / max(1, chars_per_line) * 1.8

    return min(max_font_size, width_based_size, 12)


def reconstruct_pdf(
    original_pdf_path: str,
    translations: dict[str, str],
    cells: list[TranslationCell],
    lang_out: str,
    output_path: str,
) -> None:
    """
    Reconstruct PDF with translated text.

    Args:
        original_pdf_path: Original PDF path
        translations: {address: translated_text}
        cells: Original cells with box info
        lang_out: Output language ("ja" or "en")
        output_path: Output PDF path
    """
    fitz = _get_fitz()
    doc = fitz.open(original_pdf_path)
    font_manager = FontManager(lang_out)

    # Embed fonts
    font_manager.embed_fonts(doc)

    # Build cell lookup by address
    cell_map = {cell.address: cell for cell in cells}

    for page_num, page in enumerate(doc, start=1):
        for address, translated in translations.items():
            # Filter by page
            if address.startswith("P"):
                match = re.match(r"P(\d+)_", address)
                if match and int(match.group(1)) != page_num:
                    continue
            elif address.startswith("T"):
                match = re.match(r"T(\d+)_", address)
                if match and int(match.group(1)) != page_num:
                    continue
            else:
                continue

            if address not in cell_map:
                continue

            cell = cell_map[address]
            box = cell.box

            # Create rect
            rect = fitz.Rect(box[0], box[1], box[2], box[3])

            # Redact original text (white fill)
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

            # Calculate font size and line height
            font_size = estimate_font_size(box, translated)
            line_height = calculate_line_height(translated, box, font_size, lang_out)

            # Select font
            font_name = font_manager.select_font(translated[0] if translated else "A")
            font_path = font_manager.get_font_path()

            # Insert translated text
            try:
                page.insert_textbox(
                    rect,
                    translated,
                    fontname=font_name,
                    fontfile=font_path,
                    fontsize=font_size,
                    align=fitz.TEXT_ALIGN_LEFT,
                )
            except Exception as e:
                print(f"  Warning: Failed to insert text at {address}: {e}")

    # Subset fonts
    doc.subset_fonts()

    # Save
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


# 移行フラグ（将来的に削除）
USE_LOW_LEVEL_OPERATORS = False


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
                    line_height_val = calculate_line_height(translated, cell.box, font_size, lang_out)

                    # 7. テキスト行分割
                    lines = split_text_into_lines(translated, box_width, font_size, is_cjk)

                    # 8. 各行のテキストオペレータを生成
                    for line_idx, line_text in enumerate(lines):
                        if not line_text.strip():
                            continue

                        x, y = calculate_text_position(box_pdf, line_idx, font_size, line_height_val)

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


# =============================================================================
# Main Pipeline
# =============================================================================
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
    use_low_level: bool = None,
) -> PdfTranslationResult:
    """
    Batch PDF translation pipeline.

    Args:
        pdf_path: Input PDF path
        output_path: Output PDF path
        lang_in: Input language ("ja" or "en")
        lang_out: Output language ("ja", "en", "zh-CN", "ko")
        translation_engine: TranslationEngine instance
        progress_callback: (current_page, total_pages, phase) callback
        cancel_check: Cancellation check callback
        batch_size: Pages per batch
        device: "cpu" or "cuda"
        reading_order: Layout analysis reading order
        include_headers: Include headers/footers
        glossary_path: Path to glossary CSV
        use_low_level: 低レベルオペレータを使用するか
                       None の場合は USE_LOW_LEVEL_OPERATORS を使用

    Returns:
        PdfTranslationResult
    """
    try:
        # Get total pages
        total_pages = get_total_pages(pdf_path)
        all_translations = {}
        all_cells = []

        # Phase 1-4: Batch processing
        for batch_start, batch_images in iterate_pdf_pages(pdf_path, batch_size):
            for i, img in enumerate(batch_images):
                page_num = batch_start + i + 1

                # Cancel check
                if cancel_check and cancel_check():
                    return PdfTranslationResult(
                        success=False,
                        error_message="Cancelled by user"
                    )

                # Progress: Layout analysis
                if progress_callback:
                    progress_callback(page_num, total_pages, "layout")

                # Layout analysis
                results = analyze_document(img, device=device, reading_order=reading_order)

                # Prepare translation cells
                cells = prepare_translation_cells(results, page_num, include_headers)
                all_cells.extend(cells)

                # Progress: Translation
                if progress_callback:
                    progress_callback(page_num, total_pages, "translation")

                # Translate (split by token limit)
                if cells:
                    for chunk in split_cells_for_translation(cells):
                        if cancel_check and cancel_check():
                            return PdfTranslationResult(
                                success=False,
                                error_message="Cancelled by user"
                            )

                        tsv_data = format_cells_as_tsv(chunk)

                        # Get prompt for direction
                        prompt_file = Path(__file__).parent / (
                            "prompt_pdf_jp_to_en.txt" if lang_in == "ja"
                            else "prompt_pdf_en_to_jp.txt"
                        )
                        prompt_header = prompt_file.read_text(encoding="utf-8")

                        # Translate via engine
                        cell_dicts = [{"address": c.address, "text": c.text} for c in chunk]
                        result = translation_engine.translate(
                            prompt_header=prompt_header,
                            japanese_cells=cell_dicts,
                            glossary_path=glossary_path,
                        )
                        all_translations.update(result.translations)

            # Memory cleanup after batch
            del batch_images
            gc.collect()

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

        return PdfTranslationResult(
            success=True,
            output_path=Path(output_path),
            page_count=total_pages,
            cell_count=len(all_translations),
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return PdfTranslationResult(
            success=False,
            error_message=str(e)
        )


def get_output_path(input_path: str) -> str:
    """
    Generate output path for translated PDF.

    Example: document.pdf -> document_translated.pdf
    """
    path = Path(input_path)
    return str(path.parent / f"{path.stem}_translated{path.suffix}")
