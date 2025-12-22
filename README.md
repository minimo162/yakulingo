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
- [開発者向け](#開発者向け)
- [技術スタック](#技術スタック)
- [データ保存場所](#データ保存場所)
- [ライセンス](#ライセンス)

## 特徴

YakuLingoが提供する主な機能一覧です。

- **テキスト翻訳**: 言語自動検出で即時翻訳
- **ファイル翻訳**: Excel / Word / PowerPoint / PDF / TXT を一括翻訳
- **レイアウト保持**: 原文の体裁を維持したまま出力
- **対訳出力 & 用語集エクスポート**: 翻訳ペアを対訳ファイル・CSVで保存
- **参照ファイル対応**: glossary などの用語集やスタイルガイドを利用可能
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

### PDF翻訳について

PDF翻訳はPP-DocLayout-L（PaddleOCR）によるレイアウト解析を使用します：

- **高精度レイアウト検出**: 段落、表、図、数式などを自動認識（23カテゴリ対応）
- **読み順推定**: 多段組みや複雑なレイアウトでも正しい読み順で翻訳
- **テーブルセル検出**: 表内のセル境界を自動検出して適切に翻訳配置
- **埋め込みテキストのみ対応**: スキャンPDF（画像のみ）は翻訳不可
- **部分ページ翻訳**: 未選択ページは原文のまま保持

> **Note**: PDF翻訳機能を使用するには追加の依存関係が必要です：
> ```bash
> pip install -r requirements_pdf.txt
> ```

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.11以上（[公式サイト](https://www.python.org/downloads/)からインストール） |
| ブラウザ | Microsoft Edge |
| M365 Copilot | 有料ライセンス または [無料版](https://m365.cloud.microsoft/chat) へのアクセス |

> **M365 Copilotについて**: YakuLingoはM365 Copilotを翻訳エンジンとして使用します。[m365.cloud.microsoft/chat](https://m365.cloud.microsoft/chat) にアクセスしてログインできることを事前に確認してください。

## インストールと起動

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

セットアップ完了後、`YakuLingo.exe` をダブルクリックして起動します。

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

# PDF翻訳機能を使用する場合（オプション）
pip install -r requirements_pdf.txt

# 起動（デスクトップアプリとして自動で立ち上がります）
python app.py
```

### クイックスタート（最短手順）
1. `packaging\install_deps.bat` を実行（推奨）、または `uv sync` / `pip install -r requirements.txt`
2. `playwright install chromium`（install_deps.bat使用時は不要）
3. `YakuLingo.exe` または `python app.py` を実行

## 初回セットアップ

YakuLingoを初めて使う際は、以下の手順でM365 Copilotにログインしてください。

### 1. Copilotログインの確認
1. Microsoft Edgeを開く
2. [m365.cloud.microsoft/chat](https://m365.cloud.microsoft/chat) にアクセス
3. 会社アカウントまたはMicrosoftアカウントでログイン
4. チャット画面が表示されることを確認

### 2. YakuLingoの起動
1. `python app.py` を実行
2. YakuLingoが自動的にEdgeに接続
3. ログイン画面が表示された場合は、Edgeウィンドウでログインを完了

> **Note**: 初回起動時はEdgeが前面に表示されることがあります。ログイン完了後、YakuLingoが自動的に接続します。
> **Note**: 終了時は、YakuLingoまたはCopilot(Edge)のどちらかのウィンドウを閉じればOKです。
> **Note**: ブラウザモードではUIウィンドウは `YakuLingo (UI)` として表示され、Copilotは通常のEdgeウィンドウとして表示されます。

## 使用方法

### テキスト翻訳

1. **Text** タブを選択
2. テキストエリアに翻訳したいテキストを入力
3. **翻訳する** ボタンをクリック（または `Ctrl + Enter`）
4. 翻訳結果を確認
   - **日本語入力 → 英訳**: 英語訳を3スタイルで表示
   - **英語入力 → 和訳**: 日本語訳＋解説を表示し、[英文をチェック] / [要点を教えて] ボタンを利用可能
5. 翻訳後に追加リクエスト
   - **英訳時**: 「アレンジした英文をチェック」入力欄で確認依頼
   - **和訳時**: [英文をチェック] / [要点を教えて] ボタン、または「返信文を作成」入力欄で追加入力
> **Note**: テキスト翻訳は最大5,000文字まで（クリップボード翻訳含む）

### ファイル翻訳

1. **File** タブを選択
2. ファイルをドロップまたはクリックして選択
3. **オプション設定**（任意）:
   - **対訳出力**: トグルをONにすると、原文と訳文を並べた対訳ファイルを生成
   - **用語集エクスポート**: トグルをONにすると、翻訳ペアをCSVで出力
4. **Translate File** ボタンをクリック
5. 翻訳完了ダイアログで出力ファイルを確認：
   - **翻訳ファイル**: 翻訳済みの本体ファイル
   - **対訳ファイル**: 原文と訳文を並べた対訳版（オプションON時）
   - **用語集CSV**: 翻訳ペアを抽出したCSV（オプションON時）
6. **開く** または **フォルダで表示** で出力ファイルにアクセス

### 翻訳履歴

過去のテキスト翻訳は自動的に保存されます。

**アクセス方法**:
- **Text** タブの入力欄右上にある 🕒 ボタンをクリック
- 履歴一覧から過去の翻訳を選択して再利用
- キーワード検索で履歴を絞り込み

データ保存場所：`~/.yakulingo/history.db`

### キーボードショートカット

| ショートカット | 動作 |
|--------------|------|
| `Ctrl + Enter` | テキスト入力欄で翻訳実行 |
| `Ctrl + Alt + J` (Windows) | 他のアプリで選択中のテキストを翻訳（グローバルホットキー） |

**Ctrl + Alt + J の使い方**:
1. 任意のアプリケーション（メール、ブラウザ、Word等）でテキストを選択
2. `Ctrl + Alt + J` を押す
3. YakuLingoが自動的にテキストを取得して翻訳

> **Note**: 5,000文字を超えるテキストは自動的にファイル翻訳モードで処理されます

## 設定

### config/settings.json

```json
{
  "reference_files": [],
  "output_directory": null,
  "last_tab": "text",
  "max_chars_per_batch": 4000,
  "request_timeout": 600,
  "max_retries": 3,
  "bilingual_output": false,
  "export_glossary": false,
  "translation_style": "concise",
  "use_bundled_glossary": false,
  "font_size_adjustment_jp_to_en": 0.0,
  "font_size_min": 6.0,
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "ocr_batch_size": 5,
  "ocr_dpi": 300,
  "ocr_device": "auto",
  "browser_display_mode": "side_panel",
  "auto_update_enabled": true,
  "auto_update_check_interval": 86400,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null
}
```

#### 基本設定（よく変更する項目）

| 設定 | 説明 | デフォルト |
|------|------|----------|
| `translation_style` | ファイル翻訳のスタイル | "concise" |
| `bilingual_output` | 対訳ファイルを生成 | false |
| `export_glossary` | 用語集CSVを生成 | false |
| `font_jp_to_en` | 英訳時の出力フォント | Arial |
| `font_en_to_jp` | 和訳時の出力フォント | MS Pゴシック |
| `browser_display_mode` | ブラウザ表示モード | "side_panel" |
| `auto_update_enabled` | 起動時の自動更新チェック | true |

**翻訳スタイル**: `"standard"`（標準）, `"concise"`（簡潔）, `"minimal"`（最簡潔）

**ブラウザ表示モード**:
| 値 | 説明 |
|-----|------|
| `"side_panel"` | アプリの横にパネルとして表示（デフォルト、翻訳経過が見える） |
| `"minimized"` | 最小化して非表示 |
| `"foreground"` | 前面に表示 |
> **Note**: 画面が狭い場合（作業領域幅 < 1310px）は `side_panel` を自動的に `minimized` へフォールバックし、アプリは1パネル（フル幅）で起動します。
> **Note**: Windowsではウィンドウサイズはプライマリモニターの作業領域（タスクバー除外）を基準に自動計算されます。取得できない場合は最も大きいモニターを使用します。

**用語集処理**: 用語集は常にファイルとして添付されます（用語集が増えても対応可能）。

#### 詳細設定（通常は変更不要）

| 設定 | 説明 | デフォルト |
|------|------|----------|
| `output_directory` | 出力先フォルダ（nullは入力と同じ場所） | null |
| `use_bundled_glossary` | 同梱 `glossary.csv` を常に利用 | false |
| `font_size_adjustment_jp_to_en` | JP→EN時のサイズ調整 (pt) | 0.0 |
| `font_size_min` | 最小フォントサイズ (pt) | 6.0 |
| `ocr_batch_size` | PDF処理のバッチページ数 | 5 |
| `ocr_dpi` | PDF処理の解像度 | 300 |
| `max_chars_per_batch` | Copilot送信1回あたりの最大文字数 | 4000 |
| `request_timeout` | 翻訳リクエストのタイムアウト（秒） | 600 |

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
3. YakuLingo起動前に、他のEdgeウィンドウをすべて閉じる

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
├── tests/                    # テストスイート（33ファイル）
├── prompts/                  # 翻訳プロンプト（14ファイル）
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
| ログファイル | `~/.yakulingo/logs/startup.log` |
| 参照ファイル | `glossary.csv`（デフォルト） |

## ライセンス

MIT License
