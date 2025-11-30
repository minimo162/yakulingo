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

## 対応ファイル形式

| 形式 | 拡張子 | 翻訳対象 |
|------|--------|----------|
| Excel | `.xlsx` `.xls` | セル、図形、グラフタイトル |
| Word | `.docx` `.doc` | 段落、表、テキストボックス |
| PowerPoint | `.pptx` `.ppt` | スライド、ノート、図形 |
| PDF | `.pdf` | 全ページテキスト |

> **Note**: ヘッダー/フッターは全形式で翻訳対象外

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| ブラウザ | Microsoft Edge |
| ネットワーク | M365 Copilotへのアクセス |

> **Note**: Python は `setup.bat` で自動インストールされます

## インストールと起動

### 1. セットアップ

```
setup.bat
```

以下が自動的にインストールされます：
- Python 3.11
- 依存パッケージ
- Playwright ブラウザ

### 2. 起動

```
★run.bat
```

ブラウザで `http://localhost:8765` が自動的に開きます。

## 使用方法

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

### キーボードショートカット

| ショートカット | 動作 |
|--------------|------|
| `Ctrl + Enter` | 翻訳実行 (Text タブ) |
| `Ctrl + Shift + C` | 結果をコピー |
| `Ctrl + L` | 言語方向の切り替え |
| `Escape` | 翻訳キャンセル |

## 設定

### config/settings.json

```json
{
  "reference_files": ["glossary.csv"],
  "output_directory": null,
  "last_direction": "jp_to_en",
  "max_batch_size": 50,
  "request_timeout": 120,
  "max_retries": 3
}
```

### 用語集 (glossary.csv)

```csv
# YakuLingo - Glossary File
# Format: source_term,translated_term
(億円),(oku)
(千円),(k yen)
営業利益,Operating Profit
```

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

## 開発者向け

### 手動インストール

```bash
# 依存関係のインストール
uv sync

# Playwrightブラウザのインストール
playwright install chromium

# 起動
python app.py
```

### テストの実行

```bash
# 全テスト実行
pytest

# カバレッジ付き
pytest --cov=yakulingo --cov-report=term-missing
```

### 配布パッケージの作成

```bash
make_distribution.bat
```

### ディレクトリ構造

```
YakuLingo/
├── setup.bat                 # セットアップスクリプト
├── ★run.bat                  # 起動スクリプト
├── app.py                    # エントリーポイント
├── yakulingo/            # メインパッケージ
│   ├── ui/                   # UIコンポーネント
│   ├── services/             # サービス層
│   ├── processors/           # ファイルプロセッサ
│   ├── config/               # 設定管理
│   └── models/               # データモデル
├── tests/                    # テストスイート
├── prompts/                  # 翻訳プロンプト
├── config/settings.json      # アプリ設定
└── glossary.csv              # デフォルト用語集
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
