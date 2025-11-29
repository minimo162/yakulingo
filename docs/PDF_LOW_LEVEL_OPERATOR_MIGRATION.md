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

### 1.3 フォントエンコーディング

```python
# CIDフォント (日本語等のマルチバイト) - 4桁hex
def encode_cid(text: str) -> str:
    return "".join(["%04x" % ord(c) for c in text])

# Type1/TrueType (ASCII) - 2桁hex
def encode_simple(text: str) -> str:
    return "".join(["%02x" % ord(c) for c in text])
```

---

## 2. アーキテクチャ設計

### 2.1 クラス構成

```
pdf_translator.py
├── class PdfOperatorGenerator      # 新規: 低レベルオペレータ生成
│   ├── gen_op_txt()               # テキストオペレータ生成
│   ├── gen_op_line()              # 線描画オペレータ生成
│   ├── encode_text()              # フォント別エンコード
│   └── calculate_position()       # 座標計算
│
├── class FontRegistry              # 新規: フォント登録・管理
│   ├── register_font()            # フォント登録
│   ├── get_font_id()              # フォントID取得
│   ├── get_encoding_type()        # エンコードタイプ判定
│   └── embed_fonts()              # フォント埋め込み
│
├── class ContentStreamBuilder     # 新規: コンテンツストリーム構築
│   ├── add_text()                 # テキスト追加
│   ├── add_redaction()            # 既存テキスト消去
│   ├── build()                    # ストリーム構築
│   └── apply_to_page()            # ページに適用
│
└── class FontManager              # 既存: 互換性のため維持
```

### 2.2 処理フロー

```
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 5: PDF再構築 (改修後)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. FontRegistry初期化                                          │
│     ├── 使用フォントをスキャン                                    │
│     ├── CID/Type1判定                                           │
│     └── フォントIDマッピング作成                                  │
│                                                                 │
│  2. ページ単位処理                                               │
│     ├── 既存テキスト消去 (白塗り矩形)                             │
│     │                                                           │
│     ├── ContentStreamBuilder初期化                               │
│     │   └── "BT " で開始                                        │
│     │                                                           │
│     ├── 翻訳セル毎に処理                                         │
│     │   ├── 座標計算 (calculate_position)                       │
│     │   ├── フォント選択・エンコード                              │
│     │   ├── gen_op_txt() でオペレータ生成                        │
│     │   └── ストリームに追加                                     │
│     │                                                           │
│     └── " ET" で終了                                            │
│                                                                 │
│  3. PDFに書き込み                                                │
│     ├── page.set_contents() でストリーム設定                      │
│     ├── フォント埋め込み                                         │
│     └── 保存 (deflate, garbage collection)                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 実装仕様

### 3.1 PdfOperatorGenerator クラス

```python
class PdfOperatorGenerator:
    """
    低レベルPDFオペレータ生成器

    PDFMathTranslate converter.py:384-385 準拠
    """

    def __init__(self, font_registry: 'FontRegistry'):
        self.font_registry = font_registry

    def gen_op_txt(
        self,
        font: str,
        size: float,
        x: float,
        y: float,
        text: str,
    ) -> str:
        """
        テキスト描画オペレータを生成

        Args:
            font: フォント名 (FontRegistry登録名)
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
        rtxt = self.encode_text(font, text)
        return f"/{font} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "

    def encode_text(self, font: str, text: str) -> str:
        """
        フォントタイプに応じたテキストエンコード

        CIDフォント: 4桁hex (%04x)
        Type1/TrueType: 2桁hex (%02x)
        """
        encoding_type = self.font_registry.get_encoding_type(font)

        if encoding_type == "cid":
            return "".join(["%04x" % ord(c) for c in text])
        else:
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
        return f"{width:f} w {x1:f} {y1:f} m {x2:f} {y2:f} l S "
```

### 3.2 FontRegistry クラス

```python
@dataclass
class FontInfo:
    """フォント情報"""
    name: str              # 登録名 (F1, F2, ...)
    family: str            # フォントファミリ名
    path: Optional[str]    # フォントファイルパス
    encoding: str          # "cid" or "simple"
    is_cjk: bool          # CJKフォントか


class FontRegistry:
    """
    フォント登録・管理

    PDFMathTranslate high_level.py:187-203 準拠
    """

    # デフォルトフォント定義
    DEFAULT_FONTS = {
        "ja": FontInfo(
            name="F1",
            family="MS-PMincho",
            path="C:/Windows/Fonts/msmincho.ttc",
            encoding="cid",
            is_cjk=True,
        ),
        "en": FontInfo(
            name="F2",
            family="Arial",
            path="C:/Windows/Fonts/arial.ttf",
            encoding="simple",
            is_cjk=False,
        ),
        "noto": FontInfo(
            name="F3",
            family="NotoSansCJK",
            path=None,  # 動的解決
            encoding="cid",
            is_cjk=True,
        ),
    }

    def __init__(self):
        self.fonts: dict[str, FontInfo] = {}
        self.font_objects: dict[str, Any] = {}  # PyMuPDF Font objects
        self._counter = 0

    def register_font(
        self,
        lang: str,
        doc: 'fitz.Document',
    ) -> str:
        """
        フォントを登録しIDを返す

        Returns:
            フォントID (F1, F2, ...)
        """
        if lang in self.fonts:
            return self.fonts[lang].name

        self._counter += 1
        font_id = f"F{self._counter}"

        font_info = self.DEFAULT_FONTS.get(lang, self.DEFAULT_FONTS["en"])
        font_info = FontInfo(
            name=font_id,
            family=font_info.family,
            path=font_info.path,
            encoding=font_info.encoding,
            is_cjk=font_info.is_cjk,
        )

        self.fonts[lang] = font_info
        return font_id

    def get_encoding_type(self, font_id: str) -> str:
        """フォントIDからエンコードタイプを取得"""
        for font_info in self.fonts.values():
            if font_info.name == font_id:
                return font_info.encoding
        return "simple"

    def embed_fonts(self, doc: 'fitz.Document') -> None:
        """
        全登録フォントをPDFに埋め込み
        """
        fitz = _get_fitz()

        for lang, font_info in self.fonts.items():
            if font_info.path and Path(font_info.path).exists():
                for page in doc:
                    page.insert_font(
                        fontname=font_info.name,
                        fontfile=font_info.path,
                    )
```

### 3.3 ContentStreamBuilder クラス

```python
class ContentStreamBuilder:
    """
    PDFコンテンツストリーム構築器

    複数のテキスト・グラフィックス要素を
    単一のコンテンツストリームとして構築
    """

    def __init__(self, page: 'fitz.Page'):
        self.page = page
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

    def add_redaction(
        self,
        rect: tuple[float, float, float, float],
        color: tuple[float, float, float] = (1, 1, 1),
    ) -> 'ContentStreamBuilder':
        """
        矩形領域を塗りつぶし（既存テキスト消去用）

        Args:
            rect: (x1, y1, x2, y2)
            color: RGB (0-1)
        """
        if self._in_text_block:
            self.end_text()

        x1, y1, x2, y2 = rect
        r, g, b = color

        # グラフィックス状態保存 → 色設定 → 矩形描画 → 状態復元
        op = f"q {r:f} {g:f} {b:f} rg {x1:f} {y1:f} {x2-x1:f} {y2-y1:f} re f Q "
        self.operators.append(op)
        return self

    def build(self) -> bytes:
        """コンテンツストリームをバイト列として構築"""
        if self._in_text_block:
            self.end_text()

        stream = "".join(self.operators)
        return stream.encode("latin-1")

    def apply_to_page(self) -> None:
        """
        構築したストリームをページに適用

        Note:
            既存コンテンツに追記する形式
        """
        fitz = _get_fitz()

        # 既存コンテンツ取得
        xref = self.page.xref

        # 新しいコンテンツを追加
        stream_bytes = self.build()

        # PyMuPDFでページコンテンツを更新
        # insert_textbox の代わりに直接ストリームを操作
        self.page.insert_text(
            fitz.Point(0, 0),
            "",  # ダミー
            overlay=True,
        )

        # TODO: PyMuPDFの低レベルAPIでストリームを直接設定
        # doc.xref_set_key(xref, "Contents", ...)
```

### 3.4 座標計算関数

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

    PDF座標系:
        - 原点は左下
        - Y軸は上方向が正

    Args:
        box: [x1, y1, x2, y2] (左下, 右上)
        line_index: 行インデックス (0始まり)
        font_size: フォントサイズ
        line_height: 行高さ倍率
        dy: Y方向オフセット

    Returns:
        (x, y) PDF座標
    """
    x1, y1, x2, y2 = box

    x = x1
    # 上端から下方向に配置
    y = y2 + dy - (line_index * font_size * line_height)

    return x, y


def calculate_char_width(
    char: str,
    font_size: float,
    is_cjk: bool,
) -> float:
    """
    文字幅を計算

    Args:
        char: 文字
        font_size: フォントサイズ
        is_cjk: CJK文字か

    Returns:
        文字幅 (pt)
    """
    if is_cjk:
        # 全角文字は font_size と同等
        return font_size
    else:
        # 半角文字は約0.5倍
        return font_size * 0.5
```

---

## 4. 移行手順

### 4.1 フェーズ1: 基盤クラス実装

**対象ファイル**: `pdf_translator.py`

1. `FontRegistry` クラスを実装
2. `PdfOperatorGenerator` クラスを実装
3. 既存の `FontManager` との互換性確保
4. 単体テスト作成

**期待される成果物**:
- 新規クラス3つ
- 単体テスト

### 4.2 フェーズ2: ContentStreamBuilder実装

1. `ContentStreamBuilder` クラスを実装
2. 矩形塗りつぶし (redaction) 機能
3. テキストオペレータ追加機能
4. ストリーム構築・適用機能

**技術的課題**:
- PyMuPDFでのコンテンツストリーム直接操作
- 既存コンテンツとの統合方法

### 4.3 フェーズ3: reconstruct_pdf() 書き換え

現在の実装:
```python
def reconstruct_pdf(...):
    # ...
    page.insert_textbox(rect, translated, ...)  # 高レベルAPI
```

移行後:
```python
def reconstruct_pdf(...):
    font_registry = FontRegistry()
    op_generator = PdfOperatorGenerator(font_registry)

    for page_num, page in enumerate(doc, start=1):
        builder = ContentStreamBuilder(page)

        for address, translated in translations.items():
            # 座標計算
            x, y = calculate_text_position(box, line_idx, font_size, line_height)

            # オペレータ生成
            op = op_generator.gen_op_txt(font_id, font_size, x, y, translated)
            builder.add_text_operator(op)

        builder.apply_to_page()

    font_registry.embed_fonts(doc)
```

### 4.4 フェーズ4: テスト・検証

1. **単体テスト**
   - オペレータ生成の正確性
   - エンコーディングの正確性
   - 座標計算の正確性

2. **統合テスト**
   - 日本語PDF翻訳
   - 英語PDF翻訳
   - 数式を含むPDF
   - 表を含むPDF

3. **比較検証**
   - 既存 (insert_textbox) vs 新規 (低レベル)
   - 位置精度の計測
   - フォント表示の確認

---

## 5. PyMuPDF低レベルAPI詳細

### 5.1 コンテンツストリーム操作

```python
import fitz

doc = fitz.open("input.pdf")
page = doc[0]

# 方法1: insert_text の overlay 使用
# (内部でストリームに追記)
page.insert_text(point, text, fontname=font, fontsize=size)

# 方法2: xref 経由で直接操作
xref = page.xref
contents_xref = doc.xref_get_key(xref, "Contents")

# 方法3: clean_contents で最適化後に取得
page.clean_contents()
stream = page.read_contents()

# 方法4: TextWriter を使用 (推奨)
tw = fitz.TextWriter(page.rect)
tw.append(pos, text, font=fitz.Font(fontfile=path), fontsize=size)
tw.write_text(page)
```

### 5.2 推奨アプローチ: TextWriter

PyMuPDFドキュメントでは、精密なテキスト配置には `TextWriter` クラスが推奨されている。

```python
def reconstruct_with_textwriter(
    page: 'fitz.Page',
    translations: dict[str, str],
    cells: list[TranslationCell],
    font_registry: FontRegistry,
) -> None:
    """
    TextWriterを使用したPDF再構築

    insert_textbox より精密な位置制御が可能
    """
    fitz = _get_fitz()

    tw = fitz.TextWriter(page.rect)

    for address, translated in translations.items():
        cell = cell_map.get(address)
        if not cell:
            continue

        box = cell.box
        font_info = font_registry.get_font_for_text(translated)

        # フォントオブジェクト取得
        font = fitz.Font(fontfile=font_info.path)

        # 位置計算
        pos = fitz.Point(box[0], box[3])  # 左上

        # テキスト追加
        tw.append(
            pos,
            translated,
            font=font,
            fontsize=estimate_font_size(box, translated),
        )

    # ページに書き込み
    tw.write_text(page)
```

### 5.3 ハイブリッドアプローチ

最も実用的なアプローチとして、以下を推奨：

1. **矩形塗りつぶし**: `page.draw_rect()` を使用（現状維持）
2. **テキスト挿入**: `TextWriter` を使用（精度向上）
3. **低レベルオペレータ**: 特殊ケース（数式等）のみ

```python
def reconstruct_pdf_hybrid(
    original_pdf_path: str,
    translations: dict[str, str],
    cells: list[TranslationCell],
    lang_out: str,
    output_path: str,
) -> None:
    """
    ハイブリッドPDF再構築

    - 通常テキスト: TextWriter (高精度)
    - 矩形消去: draw_rect (現状維持)
    - 特殊ケース: 低レベルオペレータ (必要時)
    """
    fitz = _get_fitz()
    doc = fitz.open(original_pdf_path)
    font_registry = FontRegistry()

    # フォント登録
    font_registry.register_font("ja", doc)
    font_registry.register_font("en", doc)

    cell_map = {cell.address: cell for cell in cells}

    for page_num, page in enumerate(doc, start=1):
        tw = fitz.TextWriter(page.rect)

        for address, translated in translations.items():
            # ページフィルタ
            if not _is_address_on_page(address, page_num):
                continue

            cell = cell_map.get(address)
            if not cell:
                continue

            box = cell.box
            rect = fitz.Rect(box)

            # 1. 既存テキスト消去
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

            # 2. フォント選択
            font_info = font_registry.select_font_for_text(translated)
            font = fitz.Font(fontfile=font_info.path)

            # 3. テキスト追加
            font_size = estimate_font_size(box, translated)
            pos = fitz.Point(box[0], box[1] + font_size)

            tw.append(pos, translated, font=font, fontsize=font_size)

        # ページに書き込み
        tw.write_text(page)

    # フォント埋め込み・最適化
    doc.subset_fonts()
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
```

---

## 6. リスクと対策

### 6.1 技術的リスク

| リスク | 影響度 | 対策 |
|--------|--------|------|
| PyMuPDF APIの制限 | 高 | TextWriter使用、段階的移行 |
| フォントエンコード不整合 | 中 | 広範なテストケース |
| 座標系の誤差 | 中 | PDFMathTranslate実装を厳密に参照 |
| パフォーマンス劣化 | 低 | ベンチマーク実施、最適化 |

### 6.2 移行戦略

**推奨**: 段階的移行（ハイブリッドアプローチ）

1. **Phase A**: `TextWriter` への移行（低リスク・高効果）
2. **Phase B**: 特殊ケースの低レベル対応
3. **Phase C**: 完全な低レベル実装（必要に応じて）

---

## 7. テスト計画

### 7.1 テストケース

```python
# tests/test_pdf_low_level.py

class TestPdfOperatorGenerator:
    """オペレータ生成テスト"""

    def test_gen_op_txt_ascii(self):
        """ASCII テキストのオペレータ生成"""
        registry = FontRegistry()
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_txt("F1", 12.0, 100.0, 500.0, "Hello")

        assert "/F1 12.000000 Tf" in op
        assert "1 0 0 1 100.000000 500.000000 Tm" in op
        assert "[<48656c6c6f>] TJ" in op

    def test_gen_op_txt_japanese(self):
        """日本語テキストのオペレータ生成 (CID)"""
        registry = FontRegistry()
        registry.register_font("ja", None)
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_txt("F1", 12.0, 100.0, 500.0, "こんにちは")

        # CIDは4桁hex
        assert "[<" in op
        assert len(op.split("<")[1].split(">")[0]) == 5 * 4  # 5文字 × 4桁


class TestContentStreamBuilder:
    """コンテンツストリーム構築テスト"""

    def test_text_block(self):
        """テキストブロックの開始・終了"""
        # ...

    def test_redaction(self):
        """矩形塗りつぶし"""
        # ...


class TestIntegration:
    """統合テスト"""

    def test_japanese_pdf_translation(self):
        """日本語PDF翻訳の精度検証"""
        # ...

    def test_position_accuracy(self):
        """位置精度の比較検証"""
        # insert_textbox vs TextWriter
        # ...
```

### 7.2 ベンチマーク

```python
def benchmark_reconstruction_methods():
    """再構築方式のパフォーマンス比較"""

    methods = {
        "insert_textbox": reconstruct_pdf_current,
        "textwriter": reconstruct_pdf_textwriter,
        "low_level": reconstruct_pdf_low_level,
    }

    results = {}
    for name, func in methods.items():
        start = time.time()
        for _ in range(10):
            func(pdf_path, translations, cells, lang_out, output_path)
        elapsed = time.time() - start
        results[name] = elapsed / 10

    return results
```

---

## 8. 完了基準

### 8.1 必須要件

- [ ] `TextWriter` ベースの再構築が動作する
- [ ] 日本語・英語の翻訳PDFが正しく生成される
- [ ] 既存テストが全てパスする
- [ ] 位置精度が `insert_textbox` 以上である

### 8.2 推奨要件

- [ ] 低レベルオペレータ生成クラスが実装されている
- [ ] 数式を含むPDFが正しく処理される
- [ ] パフォーマンスが既存実装と同等以上

### 8.3 文書化

- [ ] コード内ドキュメント (docstring)
- [ ] 移行ガイド更新
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
| Tc | 文字間隔 | `0.5 Tc` |
| Tw | 単語間隔 | `1.0 Tw` |
| TL | 行送り | `14 TL` |
| T* | 次行へ移動 | `T*` |

### グラフィックス演算子

| 演算子 | 説明 | 例 |
|--------|------|-----|
| q | グラフィックス状態保存 | `q` |
| Q | グラフィックス状態復元 | `Q` |
| rg | RGB塗りつぶし色 | `1 1 1 rg` |
| RG | RGBストローク色 | `0 0 0 RG` |
| re | 矩形パス | `100 500 200 50 re` |
| f | パス塗りつぶし | `f` |
| S | パスストローク | `S` |
| m | パス開始点 | `100 500 m` |
| l | 線パス | `200 500 l` |
| w | 線幅 | `1.0 w` |

---

## 付録B: 参考実装 (PDFMathTranslate抜粋)

```python
# PDFMathTranslate converter.py より抜粋・簡略化

def gen_op_txt(font, size, x, y, rtxt):
    """テキストオペレータ生成"""
    return f"/{font} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "

def raw_string(self, fcur, cstk):
    """フォント別エンコード"""
    if fcur == self.noto_name:
        # Notoフォント: グリフID使用
        return "".join(["%04x" % self.noto.has_glyph(ord(c)) for c in cstk])
    elif isinstance(self.fontmap[fcur], PDFCIDFont):
        # CIDフォント: 4桁hex
        return "".join(["%04x" % ord(c) for c in cstk])
    else:
        # 通常フォント: 2桁hex
        return "".join(["%02x" % ord(c) for c in cstk])

# 座標計算 (概念)
x = x0  # 行の左端
y = y2 + dy - (lidx * size * line_height)  # 上端から下方向
```

---

## 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|----------|
| 1.0 | 2025-01-XX | 初版作成 |
