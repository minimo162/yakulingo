# YakuLingo - Text + File Translation

## 回答言語
本リポジトリでの回答は日本語で行ってください。

日本語と英語の双方向翻訳アプリケーション。翻訳エンジンは **ローカルAI（llama.cpp `llama-server`）** のみを使用し、テキスト/ファイルをワンクリック翻訳します（サーバは `127.0.0.1` 固定・外部公開しません）。

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
- **ストリーミング & 分割翻訳**: 長文は分割し、翻訳中も途中結果を表示（ローカルAIはbest-effort・既定は途中表示ON、`YAKULINGO_DISABLE_LOCAL_STREAMING_PREVIEW=1` で無効化）
- **ファイル翻訳**: Excel / Word / PowerPoint / PDF / TXT / CSV を一括翻訳
- **レイアウト保持**: 原文の体裁を維持したまま出力
- **対訳出力 & 用語集エクスポート**: 翻訳ペアを対訳ファイル・CSVで保存
- **参照ファイル対応**: glossary などの用語集やスタイルガイドを利用可能
- **英訳は最簡潔（minimal）**: とにかく短い表現で出力（単一）
- **ファイルキュー**: 複数ファイルを順次/並列で翻訳
- **ホットキー起動**: `Ctrl + Alt + J` で選択中のテキスト/ファイルを翻訳開始（UIに結果を表示）
- **フォント自動調整**: 翻訳方向に合わせて最適なフォントを選択
- **翻訳履歴**: ローカル保存＆検索に対応
- **自動更新**: GitHub Releases から最新バージョンを取得

## 言語自動検出

入力テキストの言語を自動検出し、適切な方向に翻訳します：

| 入力言語 | 出力 |
|---------|------|
| 日本語 | 英語（最簡潔: minimal のみ） |
| 英語・その他の言語 | 日本語（訳文のみ） |

手動での言語切り替えは不要です。ひらがな・カタカナを含むテキストは日本語、それ以外は英語等として自動判定されます。

## 対応ファイル形式

| 形式 | 拡張子 | 翻訳対象 | 対訳出力 |
|------|--------|----------|----------|
| Excel | `.xlsx` `.xls` `.xlsm` | セル、図形、グラフタイトル | 原文/訳文シート並列 |
| CSV | `.csv` | Cells | N/A |
| Word | `.docx` | 段落、表、テキストボックス（*.doc* は未対応） | 原文→訳文の段落交互 |
| PowerPoint | `.pptx` | スライド、ノート、図形 | 原文→訳文のスライド交互 |
| PDF | `.pdf` | 全ページテキスト | 原文→訳文のページ交互 |
| テキスト | `.txt` | プレーンテキスト | 原文/訳文の交互 |
| Outlook | `.msg` | 件名、本文 | 原文/訳文の交互（txt） |

> **Note**: ヘッダー/フッターは全形式で翻訳対象外
> **Note**: `.xls` は xlwings（Excel）経由で処理するため、Excel がインストールされた環境が必要です。
> **Note**: `.msg` はOutlookがインストールされている場合は翻訳済み `.msg` を出力し、ない場合は `.txt` として出力します（対訳出力は常に `.txt`）。

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
| ローカルAI | `local_ai/`（llama.cpp `llama-server` + モデル）※現在の同梱はAVX2版 |

> **Note**: `packaging/install_deps.bat`（または配布ZIP）で `local_ai/` が配置されていれば、そのまま翻訳できます（サーバは `127.0.0.1` 固定）。

## インストールと起動

### 方法0: 配布版（ネットワーク共有 / zip + setup.vbs）

社内配布（ネットワーク共有）向けの最短手順です。Pythonの個別インストールは不要です。

1. 共有フォルダの `setup.vbs` をダブルクリック
2. セットアップ完了後、YakuLingo が常駐します（ログオン時にも自動起動）
3. 必要に応じてUIを開く（デスクトップの `YakuLingo` / `Ctrl + Alt + J` / タスクトレイのアイコンメニュー > `Open`）

> **Note**: インストール先は `%LOCALAPPDATA%\\YakuLingo` です（OneDrive配下は避けます）。

### 方法1: install_deps.bat を使用（推奨）

Windows環境で最も簡単にセットアップできる方法です。Pythonと依存関係を自動でインストールします（必要に応じてローカルAIランタイムも配置します）。
> **Note**: 新規インストール（`local_ai/manifest.json` が無い状態）では Vulkan が既定です。CPU(x64) にしたい場合は `set LOCAL_AI_LLAMA_CPP_VARIANT=cpu` を設定してから実行します。既存の `manifest.json` がある場合はその設定を優先し、切り替えたい場合は `set LOCAL_AI_LLAMA_CPP_VARIANT=vulkan|cpu` で上書きします。
> **Note**: `packaging/install_local_ai.ps1` は実行のたびに最新リリースを確認し、必要な場合のみ更新します。
> **Note**: ローカルAIの既定翻訳モデルは `mradermacher/translategemma-4b-it-i1-GGUF/translategemma-4b-it.i1-Q4_K_S.gguf` です。
> **Note**: ダウンロード先は `local_ai/models/translategemma-4b-it.i1-Q4_K_S.gguf` です。
> **Note**: 指示追従性向上のため、ローカルAIへ送るプロンプトは内部で2回繰り返して送信します（https://arxiv.org/abs/2512.14982）。プロンプト長は実質2倍になるため、長文では `local_ai_ctx_size` / `local_ai_max_tokens` / `local_ai_max_chars_per_batch` / `local_ai_max_chars_per_batch_file` の調整が必要になる場合があります。
> **Note**: `LOCAL_AI_MODEL_*` / `LOCAL_AI_MODEL_KIND` によるモデル切り替えはできません（`local_ai/manifest.json` は記録用で、選択には影響しません）。

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
4. PaddleOCR（PDF翻訳用）のインストールと検証
5. 起動高速化のためのバイトコードプリコンパイル
6. ローカルAIランタイム（llama.cpp + 固定モデル）のインストール（任意・大容量）

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
2. `YakuLingo.exe` または `uv run python app.py` を実行

## 初回セットアップ

### 1. ローカルAI（インストール確認）
1. `local_ai/` が存在することを確認（`packaging/install_deps.bat` を実行済み、または配布ZIPに同梱）
2. エラー時はメッセージに従って対処（例: AVX2非対応のPCでは同梱バイナリが動かない場合があるため、generic版 `llama-server` の同梱が必要です）

### 2. YakuLingoの起動
1. `uv run python app.py` を実行
2. UIを開く（http://127.0.0.1:8765/）または `Ctrl + Alt + J` で翻訳を実行（テキスト/ファイルを自動判別）

> **Note**: 起動直後はローカルAIの起動/ウォームアップ中のため、UI上部が「準備中」になります。ウォームアップ完了後に「準備完了」になります。
> **Note**: YakuLingoは常駐型です。UIを閉じてもバックグラウンドで動作し続けます（終了は明示的に実行）。
> **Note**: 常駐中はタスクバーに表示されない場合があります。UIはデスクトップの `YakuLingo`、`Ctrl + Alt + J`（またはタスクトレイのアイコンメニュー > `Open`）で開きます。
> **Note**: ランチャー（`YakuLingo.exe`）はwatchdogで予期せぬ終了時に自動再起動します。完全に停止したい場合はタスクトレイのアイコンメニュー > `Exit` を実行してください。
> **Note**: ブラウザモードではUIは既定のブラウザで表示されます。

## 使用方法

### テキスト翻訳

1. テキストエリアに翻訳したいテキストを入力（起動直後はテキスト翻訳画面です）
2. **翻訳する** ボタンをクリック
3. 翻訳結果を確認
   - **日本語入力 → 英訳**: 最簡潔（minimal）のみを表示
   - **英語入力 → 和訳**: 日本語訳を表示（訳文のみ）
4. 必要に応じて「再翻訳」や「戻し訳」「編集して戻し訳」で確認
> **Note**: バッチ上限を超える場合は「分割して翻訳」が表示され、翻訳中は途中結果がストリーミング表示されます（ローカルAIはbest-effort・既定は途中表示ON、`YAKULINGO_DISABLE_LOCAL_STREAMING_PREVIEW=1` で無効化）。
> **Note**: テキスト翻訳は最大5,000文字まで（クリップボード翻訳含む）
> **Note**: 複数段落（空行区切り）の入力にも対応しています。改行はできる限り保持されます（`\r\n` と `\n` は内部で正規化されます）。

### ファイル翻訳

1. ファイルをアプリ画面にドラッグ＆ドロップ、またはエクスプローラーでファイルを選択して `Ctrl + Alt + J`（最大10件）で追加
2. 複数ファイルの場合、キューで順次/並列の切り替えや並べ替えが可能
3. **オプション設定**（任意）:
   - **翻訳スタイル（英訳のみ）**: 現在は最簡潔（minimal）固定
   - **対訳出力**: トグルをONにすると、原文と訳文を並べた対訳ファイルを生成
   - **用語集エクスポート**: トグルをONにすると、翻訳ペアをCSVで出力
4. **翻訳する** ボタンをクリック（キューがある場合は一括で開始）
5. 翻訳完了ダイアログで出力ファイルを確認：
   - **翻訳ファイル**: 翻訳済みの本体ファイル（英訳時は最簡潔（minimal）のみを出力）
   - **対訳ファイル**: 原文と訳文を並べた対訳版（オプションON時）
   - **用語集CSV**: 翻訳ペアを抽出したCSV（オプションON時）
6. **開く** または **フォルダで表示** で出力ファイルにアクセス

### 翻訳履歴

過去のテキスト翻訳は自動的に保存されます。

**アクセス方法**:
- 左カラムの「履歴」から過去の翻訳を選択して再利用
- キーワード検索で履歴を絞り込み
- 出力言語・スタイル・参照ファイル有無でフィルタ

データ保存場所：`~/.yakulingo/history.db`

### キーボードショートカット

| ショートカット | 動作 |
|--------------|------|
| `Ctrl + Alt + J` (Windows) | 選択中のテキスト/ファイルを翻訳（結果はUIに表示。テキストは必要な訳をコピー、ファイルはダウンロード） |

**Ctrl + Alt + J の使い方**:
1. テキストの場合: 任意のアプリでテキストを選択 → `Ctrl + Alt + J` → YakuLingo のUIに結果が表示（訳文をコピー）
2. ファイルの場合: エクスプローラーでファイルを選択 → `Ctrl + Alt + J` → UIのファイル翻訳パネルに結果が表示（必要な出力をダウンロード）
   - 対応拡張子: `.xlsx` `.xls` `.xlsm` `.csv` `.docx` `.pptx` `.pdf` `.txt` `.msg`（最大10ファイルまで）

> **Note**: 5,000文字を超えるテキストはホットキー翻訳では処理しません。ファイル翻訳を使うか、分割してください。
> **Note**: Windowsではホットキー翻訳時に作業ウィンドウを優先し、YakuLingoを右側に並べることがあります。

- Windows 11 は「その他のオプション」に表示されます（クラシックメニュー）
- 完了後、UIに出力ファイルが表示されるので、必要なものをダウンロードします

## 設定

### 設定ファイル

- `config/settings.template.json`: デフォルト値（開発者が管理、アップデートで上書き）
- `config/user_settings.json`: ユーザーが変更した設定のみ（アップデートで保持）
> **Note**: `local_ai_*` はテンプレ管理で `user_settings.json` には保存されません（ユーザー変更不可）。

#### config/settings.template.json（例）

 ```json
   {
     "reference_files": [],
     "output_directory": null,
     "last_tab": "text",
     "max_chars_per_batch": 1000,
     "request_timeout": 600,
     "max_retries": 3,
    "local_ai_model_path": "local_ai/models/translategemma-4b-it.i1-Q4_K_S.gguf",
   "local_ai_server_dir": "local_ai/llama_cpp",
   "local_ai_host": "127.0.0.1",
   "local_ai_port_base": 4891,
   "local_ai_port_max": 4900,
   "local_ai_ctx_size": 2048,
   "local_ai_threads": 0,
   "local_ai_threads_batch": 0,
   "local_ai_temperature": 0.7,
   "local_ai_top_p": 0.95,
   "local_ai_top_k": 64,
   "local_ai_min_p": 0.01,
   "local_ai_repeat_penalty": 1.05,
   "local_ai_max_tokens": 1024,
   "local_ai_batch_size": 512,
   "local_ai_ubatch_size": 128,
   "local_ai_device": "auto",
    "local_ai_n_gpu_layers": "auto",
    "local_ai_flash_attn": "auto",
    "local_ai_no_warmup": true,
    "local_ai_mlock": false,
    "local_ai_no_mmap": false,
   "local_ai_vk_force_max_allocation_size": null,
   "local_ai_vk_disable_f16": false,
   "local_ai_cache_type_k": "q8_0",
   "local_ai_cache_type_v": "q8_0",
   "local_ai_max_chars_per_batch": 1000,
   "local_ai_max_chars_per_batch_file": 1000,
   "bilingual_output": false,
   "export_glossary": false,
   "translation_style": "minimal",
   "use_bundled_glossary": true,
   "font_size_adjustment_jp_to_en": 0.0,
   "font_size_min": 8.0,
   "font_jp_to_en": "Arial",
   "font_en_to_jp": "MS Pゴシック",
   "ocr_batch_size": 5,
   "ocr_dpi": 300,
   "ocr_device": "auto",
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
  "translation_style": "minimal",
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "font_size_adjustment_jp_to_en": 0.0,
  "bilingual_output": false,
  "export_glossary": false,
  "use_bundled_glossary": true,
  "last_tab": "text"
}
```

 #### 基本設定（よく変更する項目）
 
 | 設定 | 説明 | デフォルト |
  |------|------|----------|
| `translation_style` | ファイル翻訳のスタイル | "minimal" |
  | `bilingual_output` | 対訳ファイルを生成 | false |
  | `export_glossary` | 用語集CSVを生成 | false |
  | `use_bundled_glossary` | 同梱 `glossary.csv` を自動で参照 | true |
| `font_jp_to_en` | 英訳時の出力フォント | Arial |
| `font_en_to_jp` | 和訳時の出力フォント | MS Pゴシック |

**翻訳スタイル**: `"minimal"`（最簡潔）
> **Note**: 後方互換のため `"standard"` / `"concise"` は `"minimal"` として扱われます。

> **Note**: Windowsではウィンドウサイズはプライマリモニターの作業領域（タスクバー除外）を基準に自動計算されます。取得できない場合は最も大きいモニターを使用します。

**用語集処理**: `use_bundled_glossary=true` の場合、同梱 `glossary.csv` を自動で参照します（デフォルト: true）。入力文にマッチした用語のみをプロンプトへ埋め込みます（上限あり）。

 **翻訳ルール**: 廃止（補足情報は用語集CSVに集約）。
 **出力言語ガード**: 翻訳結果が期待言語（英訳=英語、和訳=日本語）でない場合は、自動再試行（可能な場合）またはエラーとして扱います。
 **不完全翻訳ガード（ローカルAI英訳）**: 「Revenue」等の極端に短い英訳は自動で再試行し、改善しない場合はエラーになります（必要なら `local_ai_max_tokens` / `local_ai_ctx_size` を調整）。
 **プロンプトSSOT**: `docs/PROMPT_TEMPLATES_SSOT.md` にテンプレの単一正をまとめています。
> **Note**: ローカルAIは参照/ルールをプロンプトへ埋め込むため、入力や参照が長いと一部省略や途中終了（JSON未完）になる場合があります。必要なら `local_ai_ctx_size` / `local_ai_max_tokens` / 参照ファイルを調整してください。

### ローカルAI推論パラメータ（推奨）

**既定モデル（Shisa v2.1 Qwen3 8B IQ4_XS）推奨値（ベースライン）**
```json
{
  "top_k": 64,
  "top_p": 0.95,
  "repetition_penalty": 1.05,
  "temperature": 0.7
}
```

**YakuLingo 設定キー対応**
- `--temp` → `local_ai_temperature`
- `--top-p` → `local_ai_top_p`
- `--top-k` → `local_ai_top_k`
- `--repeat-penalty` → `local_ai_repeat_penalty`

> **Note**: 既定値はモデルに合わせて調整します（現行: `local_ai_top_p=0.95`, `local_ai_top_k=64`）。

### Bytes（Transformers由来）設定キーについて

intent にある `Bytes { ... }` のうち、`top_k/top_p` は YakuLingo の `local_ai_top_k/local_ai_top_p` に対応します。  
一方で `cache_implementation` / `do_sample` / `transformers_version` は、現行のローカルAI経路（llama.cpp）では参照されないため **設定しても反映されません**。

- `do_sample`: llama.cpp は `temperature > 0` のサンプリング前提。決定論的にしたい場合は `local_ai_temperature=0` を検討してください
- `cache_implementation`: Transformers の KV cache 実装選択であり、llama.cpp の設定とは別概念です（YakuLingo では `local_ai_cache_type_k/v` などが該当）
- `transformers_version`: ローカルAI経路で Transformers を使用しないため、参照されません

詳細: `docs/BYTES_SETTINGS_MAPPING.md`

#### llama.cpp（llama-cli）最短手順
> **Note**: `local_ai/llama_cpp/vulkan` または `local_ai/llama_cpp/avx2` のどちらかを使います（同梱されている方）。
```bash
cd local_ai\llama_cpp\vulkan
.\llama-cli.exe -m ..\..\models\translategemma-4b-it.i1-Q4_K_S.gguf ^
  -p "Translate the following segment into Chinese, without additional explanation.\n\nIt’s on the house." ^
  -n 4096 --temp 0.7 --top-k 64 --top-p 0.95 --repeat-penalty 1.05 --no-warmup
```

**ローカルAIの速度チューニング（開発者向け）**:
- `local_ai_*` は `user_settings.json` に保存されないため、恒久的に変える場合は `config/settings.template.json` を編集します。
- 計測のみの一時上書きは `tools/bench_local_ai.py` の CLI オプションを使用します。
- 既定値は `local_ai_device=auto` / `local_ai_n_gpu_layers=auto` / `local_ai_ctx_size=2048`。Vulkan 環境ではオフロードを試行し、失敗時は安全に CPU-only にフォールバックします（強制的に CPU-only に戻す場合は `local_ai_device=none` または `local_ai_n_gpu_layers=0` を指定）。
- `local_ai_threads`: `0` は自動。CPUコアに合わせて増やすと高速化する場合があるが、過剰だと逆効果
- `local_ai_threads_batch`: `null` は未指定、`0` は自動（`local_ai_threads` と同値）。prefillの速度調整に使う
- `local_ai_ctx_size`: 大きいほど遅くなる傾向。プロンプト長に対して必要最小限で調整
- `local_ai_batch_size` / `local_ai_ubatch_size`: 対応ビルドのみ有効。大きすぎるとメモリ圧迫や不安定化
- `local_ai_device` / `local_ai_n_gpu_layers`: GPUオフロード先と層数（例: `none` / `Vulkan0`, `0` / `16` / `99` / `auto` / `all`）。`--list-devices` が空の場合は Vulkan が利用できません（CPU-onlyで運用）
- `local_ai_flash_attn`: Flash Attention（`auto` / `0` / `1`）
- `local_ai_no_warmup`: llama-server の内部 warmup を無効化（初回起動を短縮することがある）。※YakuLingoは準備完了前に軽量な ping を行います
- `local_ai_mlock` / `local_ai_no_mmap`: メモリ固定/メモリマップ無効化。メモリ消費が増え、環境によっては起動に失敗するため、失敗時は `false` に戻して再実行
- `local_ai_vk_force_max_allocation_size` / `local_ai_vk_disable_f16`: Vulkanトラブルシュート用
- `local_ai_cache_type_k` / `local_ai_cache_type_v`: KVキャッシュ型（例: `q8_0`）。既定は `q8_0`、`null` で無効化（`f16` 相当）に戻す
- `local_ai_max_chars_per_batch`: 小さくすると1回あたりの待ち時間は短くなるが、回数が増える（複数テキストをまとめて送る経路）
- `local_ai_max_chars_per_batch_file`: ファイル翻訳（ローカルAIバッチ翻訳）送信1回あたりの最大文字数（必要に応じて自動で縮退）
- `local_ai_max_tokens` を小さくすると速度が向上しますが、長文やバッチ翻訳では出力が途中で途切れる/短すぎる可能性があります（英訳が「Revenue」だけ等になった場合は増やす）
- 目安: 20秒目標の短文は `128`、速度優先は `256`、品質重視は `512`（または `null`）
- `request_timeout`: 長文時のタイムアウト回避用。小さくし過ぎると失敗しやすい
- 変更は1項目ずつ行い、下記ベンチで再計測する

**Vulkan(iGPU) クイックレシピ**:
- 準備: 新規インストールなら `packaging/install_deps.bat` で Vulkan が既定。CPU(x64) にしたい場合は `set LOCAL_AI_LLAMA_CPP_VARIANT=cpu` を設定して実行（既存 `manifest.json` がある場合はその設定を優先し、切り替えたい場合は `set LOCAL_AI_LLAMA_CPP_VARIANT=vulkan|cpu` で上書き可能）
- 確認: `local_ai/llama_cpp/vulkan/llama-cli.exe --list-devices` を実行し、`Vulkan0` などのデバイス名が表示されることを確認（何も表示されない場合は Vulkan が利用できません）
- 実行例（ベンチ）:
  ```bash
  uv run python tools/bench_local_ai.py --mode warm \
    --device <VULKAN_DEVICE> --n-gpu-layers 16 --flash-attn auto --json
  ```
- 探索: `--n-gpu-layers` を 0/8/16/…/99 で掃引（詳細は `docs/PERFORMANCE_LOCAL_AI.md`）
- トラブルシュート: `local_ai_vk_force_max_allocation_size` / `local_ai_no_warmup` / `local_ai_vk_disable_f16`
- 詳細手順: `docs/LOCAL_AI_VULKAN_IGPU_WINDOWS_AMD.md`

#### 詳細設定（通常は変更不要）

| 設定 | 説明 | デフォルト |
|------|------|----------|
| `output_directory` | 出力先フォルダ（nullは入力と同じ場所） | null |
| `font_size_adjustment_jp_to_en` | JP→EN時のサイズ調整 (pt) | 0.0 |
| `font_size_min` | 最小フォントサイズ (pt) | 8.0 |
| `ocr_batch_size` | PDF処理のバッチページ数 | 5 |
| `ocr_dpi` | PDF処理の解像度 | 300 |
| `max_chars_per_batch` | 翻訳送信1回あたりの最大文字数（互換キー） | 1000 |
| `local_ai_model_path` | ローカルAIモデル（.gguf）のパス | `local_ai/models/translategemma-4b-it.i1-Q4_K_S.gguf` |
| `local_ai_server_dir` | ローカルAIサーバ（llama-server）のディレクトリ | `local_ai/llama_cpp` |
| `local_ai_port_base` | ローカルAIのポート探索開始 | 4891 |
| `local_ai_port_max` | ローカルAIのポート探索上限 | 4900 |
| `local_ai_ctx_size` | ローカルAIのcontext size | 2048 |
| `local_ai_threads` | ローカルAIのスレッド数（0=auto） | 0 |
| `local_ai_threads_batch` | ローカルAIのprefillスレッド数（0=auto、nullで未指定） | 0 |
| `local_ai_max_chars_per_batch` | ローカルAI（テキスト翻訳/バッチ翻訳）送信1回あたりの最大文字数 | 1000 |
| `local_ai_max_chars_per_batch_file` | ローカルAI（ファイル翻訳）送信1回あたりの最大文字数（必要に応じて自動で縮退） | 1000 |
| `request_timeout` | 翻訳リクエストのタイムアウト（秒） | 600 |
| `local_ai_temperature` | ローカルAIの温度 | 0.7 |
| `local_ai_top_p` | ローカルAIのTop-P | 0.95 |
| `local_ai_top_k` | ローカルAIのTop-K | 64 |
| `local_ai_min_p` | ローカルAIのMin-P | 0.01 |
| `local_ai_repeat_penalty` | ローカルAIの繰り返しペナルティ | 1.05 |
| `local_ai_max_tokens` | ローカルAIの最大生成トークン（nullで無制限） | 1024 |
| `local_ai_batch_size` | ローカルAIのバッチサイズ（対応フラグがある場合のみ使用、nullで無効） | 512 |
| `local_ai_ubatch_size` | ローカルAIのマイクロバッチサイズ（対応フラグがある場合のみ使用、nullで無効） | 128 |
| `local_ai_device` | GPUオフロード先（`auto` / `none` / `Vulkan0` など） | `auto` |
| `local_ai_n_gpu_layers` | GPUに載せる層数（`auto` / `0` / `16` / `99` / `all`） | `auto` |
| `local_ai_flash_attn` | Flash Attention（`auto` / `0` / `1`） | `auto` |
| `local_ai_no_warmup` | warmup 無効化 | true |
| `local_ai_mlock` | メモリ固定（環境により失敗する場合はfalse） | false |
| `local_ai_no_mmap` | メモリマップ無効化（環境により失敗する場合はfalse） | false |
| `local_ai_vk_force_max_allocation_size` | Vulkanの最大割当サイズ（nullで無効） | null |
| `local_ai_vk_disable_f16` | VulkanでF16を無効化 | false |
| `local_ai_cache_type_k` | KVキャッシュ（K）の型（nullで無効） | `q8_0` |
| `local_ai_cache_type_v` | KVキャッシュ（V）の型（nullで無効） | `q8_0` |
| `auto_update_enabled` | 起動時の自動更新チェック | true |
| `auto_update_check_interval` | 自動更新チェック間隔（秒、0=起動毎） | 0 |

> **Note**: `ocr_*` 設定はPDF処理（レイアウト解析）に使用されます。設定名は互換性のため維持しています。
> **Note**: ローカルAI関連のパス（`local_ai_model_path`, `local_ai_server_dir`）は、相対パスの場合 **アプリ配置ディレクトリ基準** で解決します（CWD基準ではありません）。
> **Note**: `local_ai_host` は安全のため `127.0.0.1` に強制されます。
> **Note**: 既定モデル（`local_ai/models/translategemma-4b-it.i1-Q4_K_S.gguf`）が存在しない場合、ローカルAIは起動しません。`packaging/install_deps.bat` を実行するか、`powershell -NoProfile -ExecutionPolicy Bypass -File packaging\\install_local_ai.ps1` を再実行してください。必要なら同名ファイルを手動で `local_ai/models/` に配置してください。

### ローカルAI速度計測（ベンチ）

詳細手順（CLIベンチ/スイープ/E2E/記録テンプレ/指標の意味）: `docs/PERFORMANCE_LOCAL_AI.md`（SSOT）

**計測条件（固定）**
- 入力: `tools/bench_local_ai_input.txt`（410文字、用語集ヒット語を含む）
- 方向: JP→EN / style=minimal（英訳は minimal-only）
- 参照: `glossary.csv` の ON / OFF を両方計測
- 指標: warm（主指標）/ cold（参考）
- 生成上限: 設定の `local_ai_max_tokens` を使用（`--max-tokens` で上書き、`--max-tokens 0` で無制限）

**互換: --compare**
- `--compare` は互換オプションです（現行は英訳 minimal-only / options=1 / 追加呼び出しなし）。

**実行例**
```bash
uv run python tools/bench_local_ai.py --mode warm --with-glossary
uv run python tools/bench_local_ai.py --mode warm
uv run python tools/bench_local_ai.py --mode cold --with-glossary
```
- `--mode cold` はローカルAIサーバを停止してから実行するため、他の翻訳が動いていないときに行う
- 出力の `prompt_chars` / `prompt_build_seconds` / `translation_seconds` / `total_seconds` を記録（`warm` を主指標、`total_seconds=prompt_build_seconds+translation_seconds`）
- 追加で `input_chars` / `output_chars` / `effective_local_ai_ctx_size` / `effective_local_ai_max_tokens` / `warmup_seconds` も控えると比較がしやすい

**ボトルネック例**
- `prompt_build_seconds` が大きい: 参照ファイル埋め込みが支配（glossary ON/OFF で比較）
- `translation_seconds` が大きい: 推論が支配（threads/ctx/batch を調整）
- cold が遅い: 初回のモデルロード/サーバ起動が支配（`--mode cold` で把握）
- UIが重い: ベンチでは見えないため、体感が遅い場合は実UIで確認

**記録テンプレ**: `docs/PERFORMANCE_LOCAL_AI.md` の「記録テンプレ（例）」を参照

**ログで確認する場合**
- `~/.yakulingo/logs/startup.log` の `[TIMING] LocalAI ...` でも確認可能

### 参照ファイル

翻訳時に参照ファイルを添付することで、一貫性のある翻訳が可能です。

**設定方法**:
1. **テキスト翻訳**: 入力欄下部の 📎 ボタンをクリックしてファイルを選択
2. **ファイル翻訳**: ファイル選択後、「参照ファイル」エリアにドラッグ＆ドロップ

**対応形式**: CSV, TXT, PDF, Word, Excel, PowerPoint, Markdown, JSON（本文埋め込み・テキスト抽出。上限: 合計4,000文字 / 1ファイル2,000文字。超過は切り捨て＋警告）

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

### ローカルAIが使えない（未インストール/起動失敗）

- `local_ai/`（`llama_cpp` と `models`）があるか確認し、無ければ `packaging/install_deps.bat` を実行
- 「AVX2非対応」: 現状の同梱がAVX2版の場合、generic版 `llama-server` の同梱が必要です
- 「空きポートが見つかりませんでした（4891-4900）」: 他プロセスが使用中の可能性があるため、`local_ai_port_base` / `local_ai_port_max` を変更するか、競合プロセスを停止
- モデルのダウンロードが失敗/404: ネットワーク/プロキシ設定を確認し `packaging/install_deps.bat` を再実行するか、`powershell -NoProfile -ExecutionPolicy Bypass -File packaging\\install_local_ai.ps1` を再実行してください。必要なら `mradermacher/translategemma-4b-it-i1-GGUF` の `translategemma-4b-it.i1-Q4_K_S.gguf` を `local_ai/models/translategemma-4b-it.i1-Q4_K_S.gguf` に手動配置してください。
- ローカルAIランタイムの更新が失敗（DLLロック）: `...ggml-base.dll にアクセスできません` などが出る場合は、まず YakuLingo（タスクトレイ > `Exit`）を終了し、残っている `llama-server.exe` 等をタスクマネージャーで終了してから再実行してください。
  - 再実行: `powershell -NoProfile -ExecutionPolicy Bypass -File packaging\\install_local_ai.ps1`
  - それでも失敗する場合: PCを再起動してから再実行（または `packaging\\install_deps.bat` をやり直し）
- 詳細: `~/.yakulingo/logs/local_ai_server.log` と `~/.yakulingo/local_ai_server.json` を確認

### 翻訳が止まる／エラーから復帰したい

- 翻訳中は「キャンセル」ボタンで中断できます
- 復帰しない場合はタスクトレイのアイコンメニュー > `Exit` で一度停止してから再起動してください

### ファイル翻訳が失敗する

- ファイルが破損していないか確認
- ファイルサイズが50MB以下か確認
- 対応形式（.xlsx, .xlsm, .csv, .docx, .pptx, .pdf, .txt）か確認
- Excel/Word/PowerPointファイルが他のアプリで開かれていないか確認

### 翻訳結果が期待と異なる

- 参照ファイル（glossary.csv等）に固有名詞や専門用語を追加
- スタイルガイドや参考資料を添付して文脈を提供
- 英訳は最簡潔（minimal）固定です。短すぎる場合は入力に必要情報を含めるか、参照ファイルで補強してください。

### 自動更新が失敗する

- プロキシ環境の場合、`pip install pywin32` でNTLM認証サポートを追加
- ネットワーク接続を確認
- ファイアウォールがGitHubへのアクセスをブロックしていないか確認

## アンインストール

- スタートメニュー > `YakuLingo アンインストール`
- 翻訳履歴も削除する場合は `~/.yakulingo` を削除

## 開発者向け

### テストの実行

```bash
# 全テスト実行（uv推奨）
uv run --extra test pytest

# カバレッジ付き
uv run --extra test pytest --cov=yakulingo --cov-report=term-missing
```

### ローカルAI英訳の手動QA（短すぎる出力）

- テキスト翻訳で次を入力して翻訳:
  ```text
  当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。
  営業損失は539億円となりました。
  経常損失は213億円となりました。
  ```
- 期待: 英訳（minimal）が表示され、「Revenue」だけ等の1語出力にならない

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
├── local_ai/                 # ローカルAIランタイム（gitignore、配布ZIPに同梱）
├── tests/                    # テストスイート
├── prompts/                  # 翻訳プロンプト
├── config/settings.template.json  # 設定テンプレート
└── glossary.csv              # 同梱用語集（既定）
```

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| UI | NiceGUI + pywebview (Material Design 3 / Expressive) |
| 翻訳エンジン | ローカルAI（llama.cpp `llama-server`・OpenAI互換API） |
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
| ローカルAI状態 | `~/.yakulingo/local_ai_server.json` |
| ローカルAIログ | `~/.yakulingo/logs/local_ai_server.log` |
| 同梱用語集 | `glossary.csv`（既定） |

## ライセンス

MIT License
（配布物にローカルAIを同梱する場合、`local_ai/llama_cpp/LICENSE`（llama.cpp）および `local_ai/models/LICENSE`（モデル）のライセンスも同梱されます）
