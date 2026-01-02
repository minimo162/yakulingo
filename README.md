# YakuLingo - Text + File Translation

日本語と英語の双方向翻訳アプリケーション。M365 Copilotでテキストもファイルもワンクリック翻訳。

## 目次
- [特徴](#特徴)
- [対応ファイル形式](#対応ファイル形式)
- [必要環境](#必要環境)
- [インストールと起動](#インストールと起動)
- [使用方法](#使用方法)
- [設定](#設定)
- [自動更新](#自動更新)
- [トラブルシューティング](#トラブルシューティング)
- [アンインストール](#アンインストール)
- [開発者向け](#開発者向け)
- [技術スタック](#技術スタック)
- [データ保存場所](#データ保存場所)
- [ライセンス](#ライセンス)

## 特徴

YakuLingoが提供する主な機能一覧です。

- **テキスト翻訳**: 言語自動検出で即時翻訳
- **ストリーミング & 分割翻訳**: 長文は分割し、翻訳中も途中結果を表示
- **ファイル翻訳**: Excel / Word / PowerPoint / PDF / TXT を一括翻訳
- **レイアウト保持**: 原文の体裁を維持したまま出力
- **対訳出力 & 用語集エクスポート**: 翻訳ペアを対訳ファイル・CSVで保存
- **参照ファイル対応**: glossary などの用語集やスタイルガイドを利用可能
- **比較ビュー**: スタイル差分や原文との差分を確認
- **ファイルキュー**: 複数ファイルを順次/並列で翻訳
- **ダブルコピー起動**: 同じウィンドウで Ctrl+C を短時間に2回で翻訳開始（UIに結果を表示）
- **フォント自動調整**: 翻訳方向に合わせて最適なフォントを選択
- **翻訳履歴**: ローカル保存＆検索に対応
- **自動更新**: GitHub Releases から最新バージョンを取得

## 言語自動検出

入力テキストの言語を自動検出し、適切な方向に翻訳します：

| 入力言語 | 出力 |
|---------|------|
| 日本語 | 英語（3スタイル比較表示） |
| 英語・その他の言語 | 日本語（解説付き、アクションボタン付き） |

手動での言語切り替えは不要です。ひらがな・カタカナを含むテキストは日本語、それ以外は英語等として自動判定されます。

## 対応ファイル形式

| 形式 | 拡張子 | 翻訳対象 | 対訳出力 |
|------|--------|----------|----------|
| Excel | `.xlsx` `.xls` | セル、図形、グラフタイトル | 原文/訳文シート並列 |
| Word | `.docx` | 段落、表、テキストボックス（*.doc* は未対応） | 原文→訳文の段落交互 |
| PowerPoint | `.pptx` | スライド、ノート、図形 | 原文→訳文のスライド交互 |
| PDF | `.pdf` | 全ページテキスト | 原文→訳文のページ交互 |
| テキスト | `.txt` | プレーンテキスト | 原文/訳文の交互 |
| Outlook | `.msg` | メール本文（Windows + Outlook環境のみ） | - |

> **Note**: ヘッダー/フッターは全形式で翻訳対象外
> **Note**: `.xls` は xlwings（Excel）経由で処理するため、Excel がインストールされた環境が必要です。

### PDF翻訳について

PDF翻訳はPP-DocLayout-L（PaddleOCR）によるレイアウト解析を使用します：

- **高精度レイアウト検出**: 段落、表、図、数式などを自動認識（23カテゴリ対応）
- **読み順推定**: 多段組みや複雑なレイアウトでも正しい読み順で翻訳
- **テーブルセル検出**: 表内のセル境界を自動検出して適切に翻訳配置
- **埋め込みテキストのみ対応**: スキャンPDF（画像のみ）は翻訳不可
- **部分ページ翻訳**: 未選択ページは原文のまま保持

> **Note**: PDFのレイアウト解析（PP-DocLayout-L）を使用するには追加の依存関係が必要です：
> ```bash
> uv sync --extra ocr
> # または
> pip install -r requirements_pdf.txt
> ```

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.11以上（[公式サイト](https://www.python.org/downloads/)からインストール、配布版 `setup.vbs` は同梱のため不要） |
| ブラウザ | Microsoft Edge |
| M365 Copilot | 有料ライセンス または [無料版](https://m365.cloud.microsoft/chat) へのアクセス |

> **M365 Copilotについて**: YakuLingoはM365 Copilotを翻訳エンジンとして使用します。[m365.cloud.microsoft/chat](https://m365.cloud.microsoft/chat) にアクセスしてログインできることを事前に確認してください。

## インストールと起動

### 方法0: 配布版（ネットワーク共有 / zip + setup.vbs）

社内配布（ネットワーク共有）向けの最短手順です。Pythonの個別インストールは不要です。

1. 共有フォルダの `setup.vbs` をダブルクリック
2. セットアップ完了後、YakuLingo が常駐します（ログオン時にも自動起動）
3. 必要に応じてUIを開く（デスクトップ/スタートメニューの `YakuLingo`）

> **Note**: インストール先は `%LOCALAPPDATA%\\YakuLingo` です（OneDrive配下は避けます）。

### 方法1: install_deps.bat を使用（推奨）

Windows環境で最も簡単にセットアップできる方法です。Python、依存関係、Playwrightブラウザを自動でインストールします。

```bash
# リポジトリをクローン
git clone https://github.com/minimo162/yakulingo.git
cd yakulingo

# セットアップスクリプトを実行
packaging\install_deps.bat
```

**実行時の選択肢:**
```
Do you need to use a proxy server?

  [1] Yes - Use proxy (corporate network)
  [2] No  - Direct connection
  [3] No  - Direct connection (skip SSL verification)
```

| 選択肢 | 説明 | 用途 |
|-------|------|------|
| 1 | プロキシ経由で接続 | 企業ネットワーク環境 |
| 2 | 直接接続 | 通常のインターネット環境 |
| 3 | 直接接続（SSL検証スキップ） | SSL証明書エラーが発生する環境 |

> **Note**: プロキシを使用する場合（選択肢1）、プロキシサーバーのアドレスとユーザー名/パスワードの入力が求められます。

**install_deps.bat が行う処理:**
1. uv（高速パッケージマネージャー）のダウンロード
2. Python 3.11 のインストール
3. 仮想環境の作成と依存関係のインストール
4. Playwrightブラウザ（Chromium）のインストール
5. PaddleOCR（PDF翻訳用）のインストールと検証
6. 起動高速化のためのバイトコードプリコンパイル

セットアップ完了後、`YakuLingo.exe` をダブルクリックして起動します（常駐起動します。UIは必要に応じて http://127.0.0.1:8765/ を開きます）。

### 方法2: 手動インストール

```bash
# リポジトリをクローン
git clone https://github.com/minimo162/yakulingo.git
cd yakulingo

# 依存関係のインストール
# uv を使用（推奨：高速なPythonパッケージマネージャー）
# uvのインストール: https://docs.astral.sh/uv/getting-started/installation/
uv sync

# または pip を使用（uvがない場合）
pip install -r requirements.txt

# Playwrightブラウザのインストール
playwright install chromium

# PDFのレイアウト解析（PP-DocLayout-L）を使う場合（オプション）
uv sync --extra ocr
# または
pip install -r requirements_pdf.txt

# 起動（常駐バックグラウンドサービスとして起動します）
uv run python app.py

# UIを開く（任意）
# - ブラウザで http://127.0.0.1:8765/ を開く
```

### クイックスタート（最短手順）
1. `packaging\install_deps.bat` を実行（推奨）、または `uv sync` / `pip install -r requirements.txt`
2. `playwright install chromium`（install_deps.bat使用時は不要）
3. `YakuLingo.exe` または `uv run python app.py` を実行

## 初回セットアップ

YakuLingoを初めて使う際は、以下の手順でM365 Copilotにログインしてください。

### 1. Copilotログインの確認
1. Microsoft Edgeを開く
2. [m365.cloud.microsoft/chat](https://m365.cloud.microsoft/chat) にアクセス
3. 会社アカウントまたはMicrosoftアカウントでログイン
4. チャット画面が表示されることを確認

### 2. YakuLingoの起動
1. `uv run python app.py` を実行
2. UIを開く（http://127.0.0.1:8765/）または同じウィンドウで `Ctrl + C` を短時間に2回で翻訳を実行
3. ログイン画面が表示された場合は、Edgeウィンドウでログインを完了（翻訳時に接続します）

> **Note**: 初回起動時はEdgeが前面に表示されることがあります。ログイン完了後、翻訳を実行すると自動的に接続します。
> **Note**: YakuLingoは常駐型です。UIを閉じてもバックグラウンドで動作し続けます（終了は明示的に実行）。
> **Note**: The launcher (`YakuLingo.exe`) runs a watchdog and restarts the app after unexpected exits. Use the `YakuLingo 終了` shortcut or explicit shutdown to stop it.
> **Note**: ブラウザモードではUIはブラウザ（Edgeのアプリウィンドウ等）として表示され、Copilotは通常のEdgeウィンドウとして表示されます。

## 使用方法

### テキスト翻訳

1. **Text** タブを選択
2. テキストエリアに翻訳したいテキストを入力
3. **翻訳する** ボタンをクリック
4. 翻訳結果を確認
   - **日本語入力 → 英訳**: 英語訳を3スタイルで表示
   - **英語入力 → 和訳**: 日本語訳＋解説を表示
5. 必要に応じて「比較」（通常/スタイル比較/原文比較）を切り替え
6. 必要に応じて「再翻訳」や「戻し訳」「編集して戻し訳」で確認
> **Note**: バッチ上限を超える場合は「分割して翻訳」が表示され、翻訳中は途中結果がストリーミング表示されます。
> **Note**: テキスト翻訳は最大5,000文字まで（クリップボード翻訳含む）

### ファイル翻訳

1. **File** タブを選択
2. ファイルをドロップまたはクリックして選択（複数可）
3. 複数ファイルの場合、キューで順次/並列の切り替えや並べ替えが可能
4. **オプション設定**（任意）:
   - **対訳出力**: トグルをONにすると、原文と訳文を並べた対訳ファイルを生成
   - **用語集エクスポート**: トグルをONにすると、翻訳ペアをCSVで出力
5. **Translate File** ボタンをクリック（キューがある場合は一括で開始）
6. 翻訳完了ダイアログで出力ファイルを確認：
   - **翻訳ファイル**: 翻訳済みの本体ファイル
   - **対訳ファイル**: 原文と訳文を並べた対訳版（オプションON時）
   - **用語集CSV**: 翻訳ペアを抽出したCSV（オプションON時）
7. **開く** または **フォルダで表示** で出力ファイルにアクセス

### 翻訳履歴

過去のテキスト翻訳は自動的に保存されます。

**アクセス方法**:
- **Text** タブの入力欄右上にある 🕒 ボタンをクリック
- 履歴一覧から過去の翻訳を選択して再利用
- キーワード検索で履歴を絞り込み
- 出力言語・スタイル・参照ファイル有無でフィルタ
- 履歴の比較ボタンで現在の入力との差分を表示

データ保存場所：`~/.yakulingo/history.db`

### キーボードショートカット

| ショートカット | 動作 |
|--------------|------|
| `Ctrl + C` x2 (Windows) | 選択中のテキスト/ファイルを翻訳（同一ウィンドウで短時間に2回コピー。結果はUIに表示。テキストは必要な訳をコピー、ファイルはダウンロード） |

**Ctrl + C x2 の使い方**:
1. テキストの場合: 任意のアプリでテキストを選択 → 同じウィンドウで `Ctrl + C` を短時間に2回 → YakuLingo のUIに結果が表示（必要なスタイルをコピー）
2. ファイルの場合: エクスプローラーでファイルを選択 → 同じウィンドウで `Ctrl + C` を短時間に2回 → UIのファイルタブに結果が表示（必要な出力をダウンロード）
   - 対応拡張子: `.xlsx` `.xls` `.docx` `.pptx` `.pdf` `.txt` `.msg`（最大10ファイルまで）

> **Note**: 5,000文字を超えるテキストはクリップボード翻訳では処理しません。ファイル翻訳を使うか、分割してください。

- Windows 11 は「その他のオプション」に表示されます（クラシックメニュー）
- 完了後、UIに出力ファイルが表示されるので、必要なものをダウンロードします

## 設定

### 設定ファイル

- `config/settings.template.json`: デフォルト値（開発者が管理、アップデートで上書き）
- `config/user_settings.json`: ユーザーが変更した設定のみ（アップデートで保持）

#### config/settings.template.json（例）

```json
{
  "reference_files": [],
  "output_directory": null,
  "last_tab": "text",
  "max_chars_per_batch": 1000,
  "request_timeout": 600,
  "max_retries": 3,
  "bilingual_output": false,
  "export_glossary": false,
  "translation_style": "concise",
  "use_bundled_glossary": true,
  "font_size_adjustment_jp_to_en": 0.0,
  "font_size_min": 8.0,
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "ocr_batch_size": 5,
  "ocr_dpi": 300,
  "ocr_device": "auto",
  "browser_display_mode": "minimized",
  "auto_update_enabled": true,
  "auto_update_check_interval": 0,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null
}
```

#### config/user_settings.json（例）

```json
{
  "translation_style": "concise",
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "font_size_adjustment_jp_to_en": 0.0,
  "bilingual_output": false,
  "export_glossary": false,
  "use_bundled_glossary": true,
  "browser_display_mode": "minimized",
  "last_tab": "text"
}
```

#### 基本設定（よく変更する項目）

| 設定 | 説明 | デフォルト |
|------|------|----------|
| `translation_style` | ファイル翻訳のスタイル | "concise" |
| `bilingual_output` | 対訳ファイルを生成 | false |
| `export_glossary` | 用語集CSVを生成 | false |
| `use_bundled_glossary` | 同梱 `glossary.csv` を自動で参照 | true |
| `font_jp_to_en` | 英訳時の出力フォント | Arial |
| `font_en_to_jp` | 和訳時の出力フォント | MS Pゴシック |
| `browser_display_mode` | ブラウザ表示モード | "minimized" |

**翻訳スタイル**: `"standard"`（標準）, `"concise"`（簡潔）, `"minimal"`（最簡潔）

**ブラウザ表示モード**:
| 値 | 説明 |
|-----|------|
| `"minimized"` | 最小化して非表示（デフォルト） |
| `"foreground"` | 前面に表示 |
> **Note**: `side_panel` は廃止され、`minimized` と同等に扱われます。
> **Note**: Windowsではウィンドウサイズはプライマリモニターの作業領域（タスクバー除外）を基準に自動計算されます。取得できない場合は最も大きいモニターを使用します。

**用語集処理**: `use_bundled_glossary=true` の場合、同梱 `glossary.csv` をファイルとして自動添付します（デフォルト: true）。

#### 詳細設定（通常は変更不要）

| 設定 | 説明 | デフォルト |
|------|------|----------|
| `output_directory` | 出力先フォルダ（nullは入力と同じ場所） | null |
| `font_size_adjustment_jp_to_en` | JP→EN時のサイズ調整 (pt) | 0.0 |
| `font_size_min` | 最小フォントサイズ (pt) | 8.0 |
| `ocr_batch_size` | PDF処理のバッチページ数 | 5 |
| `ocr_dpi` | PDF処理の解像度 | 300 |
| `max_chars_per_batch` | Copilot送信1回あたりの最大文字数 | 1000 |
| `request_timeout` | 翻訳リクエストのタイムアウト（秒） | 600 |
| `auto_update_enabled` | 起動時の自動更新チェック | true |
| `auto_update_check_interval` | 自動更新チェック間隔（秒、0=起動毎） | 0 |

> **Note**: `ocr_*` 設定はPDF処理（レイアウト解析）に使用されます。設定名は互換性のため維持しています。

### 参照ファイル

翻訳時に参照ファイルを添付することで、一貫性のある翻訳が可能です。

**設定方法**:
1. **テキスト翻訳**: 入力欄下部の 📎 ボタンをクリックしてファイルを選択
2. **ファイル翻訳**: ファイル選択後、「参照ファイル」エリアにドラッグ＆ドロップ

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

**確認事項**:
1. Microsoft Edgeがインストールされているか確認
2. [m365.cloud.microsoft/chat](https://m365.cloud.microsoft/chat) にブラウザでアクセスしてログインできるか確認
3. YakuLingoを一度終了してから、他のEdgeウィンドウをすべて閉じる（接続の競合を避けるため）

**Edgeプロセスの完全終了方法**:
1. `Ctrl + Shift + Esc` でタスクマネージャーを開く
2. 「Microsoft Edge」を探して右クリック → 「タスクの終了」
3. バックグラウンドで動作している場合は「詳細」タブから `msedge.exe` をすべて終了
4. YakuLingoを再起動

### ファイル翻訳が失敗する

- ファイルが破損していないか確認
- ファイルサイズが50MB以下か確認
- 対応形式（.xlsx, .docx, .pptx, .pdf, .txt）か確認
- Excel/Word/PowerPointファイルが他のアプリで開かれていないか確認

### 参照ファイルのアップロード待ちで止まる

- 参照ファイル（glossary / 参考資料）を添付した場合、送信可能状態が一定時間安定するまで待機してから送信します
- 「添付処理が完了しませんでした…」が出る場合は、Edge側でアップロード完了を確認して再試行
- 通信が不安定な場合はファイルサイズを減らすか、参照ファイル数を減らしてください

### 翻訳結果が期待と異なる

- 参照ファイル（glossary.csv等）に固有名詞や専門用語を追加
- スタイルガイドや参考資料を添付して文脈を提供
- 翻訳スタイルを「標準」に変更して詳細な翻訳を取得

### 自動更新が失敗する

- プロキシ環境の場合、`pip install pywin32` でNTLM認証サポートを追加
- ネットワーク接続を確認
- ファイアウォールがGitHubへのアクセスをブロックしていないか確認

## アンインストール

- スタートメニュー > YakuLingo > 「YakuLingo アンインストール」
- 翻訳履歴も削除する場合は `~/.yakulingo` を削除

## 開発者向け

### テストの実行

```bash
# 全テスト実行（uv推奨）
uv run --extra test pytest

# カバレッジ付き
uv run --extra test pytest --cov=yakulingo --cov-report=term-missing
```

### 開発メモ

- UIチェック用のスクリーンショットは `yakulingo_ui*.png` として保存し、gitignore 対象にしています

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
├── tests/                    # テストスイート
├── prompts/                  # 翻訳プロンプト
├── config/settings.template.json  # 設定テンプレート
└── glossary.csv              # デフォルト参照ファイル
```

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| UI | NiceGUI + pywebview (Material Design 3 / Expressive) |
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
| 設定ファイル | `config/user_settings.json`（ユーザー設定） / `config/settings.template.json`（デフォルト） |
| 翻訳履歴 | `~/.yakulingo/history.db` |
| ログファイル | `~/.yakulingo/logs/startup.log` |
| 参照ファイル | `glossary.csv`（デフォルト） |

## ライセンス

MIT License
