# YakuLingo - Text + File Translation

日本語と英語の双方向翻訳アプリケーション。M365 Copilotを使用してテキストとファイルを翻訳します。

## 特徴

| 機能 | 説明 |
|------|------|
| **テキスト翻訳** | テキストを入力して即座に翻訳 |
| **ファイル翻訳** | Excel/Word/PowerPoint/PDF の一括翻訳 |
| **レイアウト保持** | 翻訳後もファイルの体裁を維持 |
| **参考ファイル** | 用語集・参考資料による一貫した翻訳 |
| **フォント自動調整** | 翻訳方向に応じた適切なフォント選択 |

## 対応言語

- 日本語 ↔ 英語（双方向）

## 対応ファイル形式

| 形式 | 拡張子 | 翻訳対象 |
|------|--------|----------|
| Excel | `.xlsx` `.xls` | セル、図形、グラフタイトル |
| Word | `.docx` `.doc` | 段落、表、テキストボックス |
| PowerPoint | `.pptx` `.ppt` | スライド、ノート、図形 |
| PDF | `.pdf` | 全ページテキスト |

> **Note**: ヘッダー/フッターは全形式で翻訳対象外

## 使用方法

### クイックスタート

```bash
# 起動
python app.py
```

ブラウザで `http://localhost:8765` が自動的に開きます。

### テキスト翻訳

1. **Text** タブを選択
2. 左側のテキストエリアに翻訳したいテキストを入力
3. **Translate** ボタンをクリック
4. 右側に翻訳結果が表示される

### ファイル翻訳

1. **File** タブを選択
2. ファイルをドロップまたはクリックして選択
3. **Translate File** ボタンをクリック
4. 翻訳完了後、**Download** でファイルを取得

### 言語切り替え

- テキストエリア間の **⇄** ボタンをクリックで方向切り替え
- 日本語 → 英語 / 英語 → 日本語

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.11+ |
| ブラウザ | Microsoft Edge |
| ネットワーク | M365 Copilotへのアクセス |

## インストール

### 1. 依存関係のインストール

```bash
# uv を使用する場合（推奨）
uv sync

# pip を使用する場合
pip install -r requirements.txt
```

### 2. Playwrightブラウザのインストール

```bash
playwright install chromium
```

### 3. 起動

```bash
python app.py
```

## ディレクトリ構造

```
YakuLingo/
├── app.py                    # エントリーポイント
├── ecm_translate/            # メインパッケージ
│   ├── ui/                   # NiceGUI UIコンポーネント (M3デザイン)
│   ├── services/             # サービス層
│   ├── processors/           # ファイルプロセッサ
│   ├── config/               # 設定管理
│   └── models/               # データモデル
├── tests/                    # テストスイート
├── prompts/                  # 翻訳プロンプト
│   ├── translate_jp_to_en.txt
│   └── translate_en_to_jp.txt
├── docs/                     # ドキュメント
│   └── SPECIFICATION.md      # 詳細仕様書
├── config/
│   └── settings.json         # アプリ設定
├── glossary.csv              # デフォルト用語集
└── ★run.bat                  # 起動スクリプト (Windows)
```

## 設定

### config/settings.json

```json
{
  "reference_files": ["glossary.csv"],
  "output_directory": null,
  "start_with_windows": false,
  "last_direction": "jp_to_en",
  "max_batch_size": 50,
  "request_timeout": 120,
  "max_retries": 3
}
```

### 用語集 (glossary.csv)

```csv
Japanese,English
株式会社,Corp.
営業利益,Operating Profit
前年比,YOY
```

## 数値表記ルール

翻訳時に以下の数値表記が自動変換されます：

| 日本語 | 英語 |
|--------|------|
| 4,500億円 | 4,500 oku yen |
| 12,000 | 12k |
| ▲50 | (50) |

## トラブルシューティング

### Copilotに接続できない

1. Microsoft Edgeがインストールされているか確認
2. M365 Copilotへのアクセス権があるか確認
3. 別のEdgeプロセスが起動中の場合は終了

### ファイル翻訳が失敗する

- ファイルが破損していないか確認
- ファイルサイズが50MB以下か確認
- 対応形式（.xlsx, .docx, .pptx, .pdf）か確認

### 翻訳結果が期待と異なる

- 用語集（glossary.csv）に固有名詞を追加
- 参考ファイルを添付して文脈を提供

## キーボードショートカット

| ショートカット | 動作 |
|--------------|------|
| `Ctrl + Enter` | 翻訳実行 (Text タブ) |
| `Ctrl + Shift + C` | 結果をコピー |
| `Ctrl + L` | 言語方向の切り替え |
| `Escape` | 翻訳キャンセル |

## 開発

### テストの実行

```bash
# 全テスト実行
pytest

# カバレッジ付き
pytest --cov=ecm_translate --cov-report=term-missing

# 特定のテストファイル
pytest tests/test_translation_service.py -v
```

### 配布パッケージの作成

```bash
# Windows環境で実行
make_distribution.bat
```

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| UI | NiceGUI (Material Design 3) |
| 翻訳エンジン | M365 Copilot (Playwright) |
| Excel処理 | openpyxl |
| Word処理 | python-docx |
| PowerPoint処理 | python-pptx |
| PDF処理 | PyMuPDF |

## ライセンス

MIT License

## バージョン

20251127 (2.0.0)
