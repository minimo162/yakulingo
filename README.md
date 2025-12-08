# YakuLingo - Text + File Translation

日本語と英語の双方向翻訳アプリケーション。M365 Copilotを使用してテキストとファイルを翻訳します。

## 特徴

| 機能 | 説明 |
|------|------|
| **テキスト翻訳** | テキストを入力して即座に翻訳（言語自動検出） |
| **ファイル翻訳** | Excel/Word/PowerPoint/PDF/TXT の一括翻訳 |
| **レイアウト保持** | 翻訳後もファイルの体裁を維持 |
| **対訳出力** | 原文と訳文を並べた対訳ファイルを自動生成 |
| **用語集エクスポート** | 翻訳ペアをCSVで出力（用語管理に活用） |
| **参照ファイル** | 用語集・スタイルガイド・参考資料による一貫した翻訳（同梱glossaryの有効/無効を切替可能） |
| **フォント自動調整** | 翻訳方向に応じた適切なフォント選択 |
| **翻訳履歴** | 過去の翻訳をローカルに保存・検索 |
| **自動更新** | GitHub Releases経由で最新版に自動更新 |

## 言語自動検出

入力テキストの言語をM365 Copilotで自動検出し、適切な方向に翻訳します：

| 入力言語 | 出力 |
|---------|------|
| 日本語 | 英語（スタイル設定可、インライン調整可） |
| その他 | 日本語（解説付き、アクションボタン付き） |

手動での言語切り替えは不要です。

## 対応ファイル形式

| 形式 | 拡張子 | 翻訳対象 | 対訳出力 |
|------|--------|----------|----------|
| Excel | `.xlsx` `.xls` | セル、図形、グラフタイトル | 原文/訳文シート並列 |
| Word | `.docx` | 段落、表、テキストボックス | 原文→訳文の段落交互 |
| PowerPoint | `.pptx` | スライド、ノート、図形 | 原文→訳文のスライド交互 |
| PDF | `.pdf` | 全ページテキスト | 原文→訳文のページ交互 |
| テキスト | `.txt` | プレーンテキスト | 原文/訳文の交互 |

> **Note**: ヘッダー/フッターは全形式で翻訳対象外

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| ブラウザ | Microsoft Edge |
| ネットワーク | M365 Copilotへのアクセス |

## インストールと起動

```bash
# リポジトリをクローン
git clone https://github.com/minimo162/yakulingo.git
cd yakulingo

# 依存関係のインストール（uv推奨）
uv sync

# または pip を使用
pip install -r requirements.txt

# Playwrightブラウザのインストール
playwright install chromium

# 起動
python app.py
```

> **Note**: Python 3.11以上が必要です

## 使用方法

### テキスト翻訳

1. **Text** タブを選択
2. テキストエリアに翻訳したいテキストを入力
3. **翻訳する** ボタンをクリック（または `Ctrl + Enter`）
4. 翻訳結果が表示される
   - **日本語入力時（英訳）**：英語訳 + インライン調整オプション
   - **その他入力時（和訳）**：日本語訳 + 解説 + [英文をチェック][要点を教えて]ボタン
5. インライン入力欄で追加のリクエストが可能（例: 「もっとカジュアルに」「返信の下書きを書いて」）

### ファイル翻訳

1. **File** タブを選択
2. ファイルをドロップまたはクリックして選択
3. **Translate File** ボタンをクリック
4. 翻訳完了ダイアログで出力ファイルを確認：
   - **翻訳ファイル**: 翻訳済みの本体ファイル
   - **対訳ファイル**: 原文と訳文を並べた対訳版
   - **用語集CSV**: 翻訳ペアを抽出したCSV
5. **開く** または **フォルダで表示** で出力ファイルにアクセス

### 翻訳履歴

過去の翻訳は自動的に保存されます：
- 履歴から再翻訳が可能
- キーワード検索対応

データ保存場所：`~/.yakulingo/history.db`

### キーボードショートカット

| ショートカット | 動作 |
|--------------|------|
| `Ctrl + Enter` | 翻訳実行 |

## 設定

### config/settings.json

```json
{
  "reference_files": ["glossary.csv"],
  "output_directory": null,
  "last_tab": "text",
  "window_width": 1400,
  "window_height": 850,
  "max_chars_per_batch": 7000,
  "request_timeout": 120,
  "max_retries": 3,
  "bilingual_output": false,
  "export_glossary": false,
  "translation_style": "concise",
  "text_translation_style": "concise",
  "use_bundled_glossary": false,
  "font_size_adjustment_jp_to_en": 0.0,
  "font_size_min": 6.0,
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "ocr_batch_size": 5,
  "ocr_dpi": 200,
  "ocr_device": "auto",
  "auto_update_enabled": true,
  "auto_update_check_interval": 86400,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null,
  "skipped_version": null,
  "onboarding_completed": false
}
```

| 設定 | 説明 | デフォルト |
|------|------|----------|
| `bilingual_output` | 対訳ファイルを生成 | false |
| `export_glossary` | 用語集CSVを生成 | false |
| `translation_style` | ファイル翻訳のスタイル (`standard`/`concise`/`minimal`) | "concise" |
| `text_translation_style` | テキスト翻訳のスタイル (`standard`/`concise`/`minimal`) | "concise" |
| `use_bundled_glossary` | 同梱 `glossary.csv` を常に利用 | false |
| `font_jp_to_en` | 英訳時の出力フォント（全形式共通） | Arial |
| `font_en_to_jp` | 和訳時の出力フォント（全形式共通） | MS Pゴシック |
| `font_size_adjustment_jp_to_en` | JP→EN時のサイズ調整 (pt) | 0.0 |
| `font_size_min` | 最小フォントサイズ (pt) | 6.0 |
| `ocr_batch_size` | PDFレイアウト解析のバッチページ数 | 5 |
| `ocr_dpi` | PDFレイアウト解析の解像度 | 200 |
| `auto_update_enabled` | 起動時の自動更新チェックを有効化 | true |
| `auto_update_check_interval` | 更新チェック間隔（秒） | 86400 |
| `max_chars_per_batch` | Copilot送信1回あたりの最大文字数 | 7000 |
| `request_timeout` | 翻訳リクエストのタイムアウト（秒） | 120 |
| `output_directory` | 出力先フォルダ（nullは入力と同じ） | null |
| `window_width` / `window_height` | ウィンドウ初期サイズ | 1400 / 850 |

**翻訳スタイル**: `"standard"`（標準）, `"concise"`（簡潔）, `"minimal"`（最簡潔）

### 参照ファイル

翻訳時に参照ファイルを添付することで、一貫性のある翻訳が可能です。

**対応形式**: CSV, TXT, PDF, Word, Excel, PowerPoint, Markdown, JSON

**デフォルト (glossary.csv)**:
```csv
# YakuLingo - Glossary File
# Format: source_term,translated_term
(億円),(oku)
(千円),(k yen)
営業利益,Operating Profit
```

**活用例**:
- 用語集（専門用語の統一）
- スタイルガイド（文体・表現の指針）
- 参考訳文（過去の翻訳例）
- 仕様書（背景情報の提供）

## 自動更新

アプリケーション起動時に新しいバージョンを自動チェックします：

1. 新バージョン検出時、通知が表示される
2. **更新** をクリックでダウンロード・インストール
3. アプリケーション再起動で更新完了

> **Note**: Windows認証プロキシ環境でも動作します（pywin32が必要）

## トラブルシューティング

### Copilotに接続できない

1. Microsoft Edgeがインストールされているか確認
2. M365 Copilotへのアクセス権があるか確認
3. 別のEdgeプロセスが起動中の場合は終了

### ファイル翻訳が失敗する

- ファイルが破損していないか確認
- ファイルサイズが50MB以下か確認
- 対応形式（.xlsx, .docx, .pptx, .pdf, .txt）か確認

### 翻訳結果が期待と異なる

- 参照ファイル（glossary.csv等）に固有名詞を追加
- スタイルガイドや参考資料を添付して文脈を提供

### 自動更新が失敗する

- プロキシ環境の場合、pywin32がインストールされているか確認
- ネットワーク接続を確認

## 開発者向け

### テストの実行

```bash
# 全テスト実行（uv推奨）
uv run --extra test pytest

# カバレッジ付き
uv run --extra test pytest --cov=yakulingo --cov-report=term-missing
```

### 配布パッケージの作成

```bash
packaging\make_distribution.bat
```

### ディレクトリ構造

```
YakuLingo/
├── app.py                    # エントリーポイント
├── yakulingo/                # メインパッケージ
│   ├── ui/                   # UIコンポーネント
│   ├── services/             # サービス層（翻訳、更新）
│   ├── processors/           # ファイルプロセッサ
│   ├── storage/              # データ永続化（履歴）
│   ├── config/               # 設定管理
│   └── models/               # データモデル
├── packaging/                # 配布・ビルド関連
│   ├── launcher/             # ネイティブランチャー（Rust製）
│   └── installer/            # ネットワーク共有インストーラ
├── tests/                    # テストスイート（26ファイル）
├── prompts/                  # 翻訳プロンプト
├── config/settings.template.json  # 設定テンプレート
└── glossary.csv              # デフォルト参照ファイル
```

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| UI | NiceGUI + pywebview (Material Design 3) |
| 翻訳エンジン | M365 Copilot (Playwright) |
| Excel処理 | xlwings (Windows/macOS) / openpyxl (フォールバック) |
| Word処理 | python-docx |
| PowerPoint処理 | python-pptx |
| PDF処理 | PyMuPDF + pdfminer.six + PP-DocLayout-L (レイアウト解析) |
| データ保存 | SQLite (翻訳履歴) |
| 自動更新 | GitHub Releases API |

## データ保存場所

| データ | 場所 |
|--------|------|
| 設定ファイル | `config/settings.json` |
| 翻訳履歴 | `~/.yakulingo/history.db` |
| 参照ファイル | `glossary.csv`（デフォルト） |

## ライセンス

MIT License
