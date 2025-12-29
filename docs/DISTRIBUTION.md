# YakuLingo 配布ガイド

## 概要

YakuLingoはネットワーク共有フォルダからのワンクリックセットアップに対応しています。
インストール後は、GitHub Releases経由で自動更新されます。

## 配布パッケージの作成

### 前提条件

開発環境で先に `packaging/install_deps.bat` を実行し、以下のフォルダが存在すること：
- `.venv` (Python仮想環境)
- `.uv-python` (Python本体)
- `.playwright-browsers` (ブラウザ)

### 実行

```batch
packaging\make_distribution.bat
```

### 出力物

```
YakuLingo_YYYYMMDD.zip    # 配布用ZIP
share_package/            # 共有フォルダ用パッケージ
├── setup.vbs             # ユーザーが実行するファイル
├── YakuLingo_*.zip       # 配布パッケージ
├── README.txt            # 管理者向けガイド
└── .scripts/             # 内部スクリプト
    └── setup.ps1
```

## 共有フォルダへの配置

### 手順

1. `share_package/` の内容を共有フォルダにコピー

```
\\server\share\YakuLingo\
├── setup.vbs
├── YakuLingo_YYYYMMDD.zip
├── README.txt
└── .scripts\
```

2. ユーザーに読み取り権限を付与

### 更新時

1. 新しいZIPファイルを共有フォルダにコピー
2. 古いZIPファイルを削除
   - setup.ps1は自動的に最新のZIPを使用

> **Note**: インストール済みのユーザーは自動更新機能で更新されるため、共有フォルダの更新は新規インストール用のみ

## ユーザー向けインストール手順

1. `\\server\share\YakuLingo` を開く
2. `setup.vbs` をダブルクリック
3. セットアップ完了を待つ
4. 完了後、YakuLingoが自動的に起動（常駐）
5. 普段の使い方:
   - テキストを選択して 同じウィンドウで `Ctrl+C` を短時間に2回 → YakuLingo のUIに結果が表示（必要な訳をコピー）
   - エクスプローラーでファイルを選択して 同じウィンドウで `Ctrl+C` を短時間に2回 → UIのファイルタブに結果が表示（必要な出力をダウンロード）
   - エクスプローラーでファイルを右クリック → `YakuLingoで翻訳` → 翻訳を開始（Windows 11 は「その他のオプション」に表示）
6. UIを開く: デスクトップ / スタートメニューの `YakuLingo`
7. 終了する: スタートメニュー > `YakuLingo` > `YakuLingo 終了`

### インストール先

```
%LOCALAPPDATA%\YakuLingo\
```

### 作成されるショートカット

- デスクトップ: `YakuLingo.lnk`（UIを開く）
- スタートメニュー: `YakuLingo\YakuLingo.lnk`（UIを開く）
- スタートメニュー: `YakuLingo\YakuLingo 終了.lnk`（常駐を終了）
- スタートアップ: `YakuLingo.lnk`（ログオン時に常駐を自動起動）

### 追加される統合（配布版setup.vbs）

- Explorer: 対応ファイルの右クリックに `YakuLingoで翻訳` を追加（Windows 11 は「その他のオプション」側）

## セットアップの動作

setup.ps1は以下を実行：

1. **実行中プロセスの検出**: YakuLingoが実行中の場合、再インストールを中止してエラー表示
2. 既存インストールがあれば**全てのファイルを削除**（環境フォルダ含む）
3. ZIPをローカルにコピー・展開（robocopyスキップ時は警告表示）
4. `%LOCALAPPDATA%\YakuLingo` にファイル配置
5. **ユーザーデータの復元**: `config/user_settings.json` は保持（復元）、`glossary.csv` は差分があればバックアップして更新
6. ショートカット作成（デスクトップ / スタートメニュー / スタートアップ / 終了）
7. Explorer右クリックメニュー登録（対応拡張子に `YakuLingoで翻訳` を追加）
8. YakuLingoを起動（常駐 + UIを開く）

### ユーザーデータの保持/更新処理

| データ | 動作 |
|--------|----------|
| `config/user_settings.json` | 既存ファイルをバックアップ → 展開後に復元（ユーザー設定は保持） |
| `config/settings.template.json` | 新バージョンで上書き（デフォルト設定） |
| `glossary.csv` | 新旧・旧版（`glossary_old.csv`）と比較し、カスタマイズ検出時はデスクトップへ `glossary_backup_YYYYMMDD*.csv` を作成してから上書き |

> **Note**: `glossary.csv` は自動マージではなく「比較 → 必要ならバックアップ → 上書き」です（意図せず用語集が消えるのを防ぐため）。

### 環境フォルダの扱い

setup.vbsは常にクリーンインストールを行い、環境フォルダも含めて上書きします：
- `.venv` (Python仮想環境) → **上書き**
- `.uv-python` (Python本体) → **上書き**
- `.playwright-browsers` (ブラウザ) → **上書き**

> **Note**: GitHub Releases経由の自動アップデートでは環境フォルダは保持されます。
> setup.vbsは初回インストールまたは依存関係変更時のクリーンインストール用です。

## 自動更新機能

### 仕組み

1. アプリケーション起動時にGitHub Releases APIをチェック
2. 新バージョンがあれば通知を表示
3. ユーザーが更新を選択すると自動ダウンロード・インストール
4. 再起動後に新バージョンが有効化

### 更新対象ファイル

自動更新では以下のファイルのみ更新され、環境フォルダは保持されます：

| 種類 | 対象 |
|------|------|
| **ディレクトリ** | `yakulingo/`, `prompts/`, `config/` |
| **ファイル** | `app.py`, `pyproject.toml`, `uv.lock`, `uv.toml`, `YakuLingo.exe`, `README.md`, `glossary.csv` |
| **保持（更新対象外）** | `.venv/`, `.uv-python/`, `.playwright-browsers/` |

> **Note**: `config/settings.template.json` は上書きされますが、`config/user_settings.json` は保持されます。

### プロキシ環境での動作

- Windowsシステムプロキシ設定を自動検出
- NTLM認証プロキシ対応（pywin32が必要）

### 依存関係変更時（[REQUIRES_REINSTALL]）

リリースノートに `[REQUIRES_REINSTALL]` が含まれている場合：
- 自動更新ではなく、setup.vbs での再セットアップを案内
- ユーザーに「共有フォルダの setup.vbs を実行してください」と表示
- setup.vbs は環境フォルダを含めてクリーンインストールを実行

**リリース作成時**: 依存関係（pyproject.toml）を変更した場合は、リリースノートに `[REQUIRES_REINSTALL]` を含めてください。

### 管理者向け情報

自動更新はGitHubリポジトリのReleasesから取得します。
社内ネットワークでGitHubへのアクセスがブロックされている場合：
- 共有フォルダからの手動更新を案内してください
- または、プロキシ設定でGitHubへのアクセスを許可してください

## データの保存場所

ユーザーデータは以下の場所に保存されます：

| データ | 場所 | 更新時の扱い |
|--------|------|-------------|
| アプリ設定（ユーザー） | `%LOCALAPPDATA%\YakuLingo\config\user_settings.json` | 保持 |
| アプリ設定（デフォルト） | `%LOCALAPPDATA%\YakuLingo\config\settings.template.json` | 上書き |
| 翻訳履歴 | `%USERPROFILE%\.yakulingo\history.db` | 保持 |
| 用語集 | `%LOCALAPPDATA%\YakuLingo\glossary.csv` | 上書き（カスタマイズ検出時はデスクトップへバックアップ） |

> **Note**: 翻訳履歴はアプリケーションフォルダ外に保存されるため、アンインストール後も残ります。
> 用語集をカスタマイズしている場合、更新時にデスクトップへバックアップが作成されます。

## トラブルシューティング

### setup.vbsが実行できない

PowerShellから直接実行：
```
powershell -ExecutionPolicy Bypass -File ".scripts\setup.ps1"
```

### ZIPが見つからないエラー

- `YakuLingo*.zip` が共有フォルダにあるか確認

### アクセス拒否エラー

- 共有フォルダへの読み取り権限を確認

### Explorerの右クリックメニューが表示されない

- Windows 11 は右クリック後の「その他のオプション」に表示されます（クラシックメニュー）
- 反映しない場合は、エクスプローラーを再起動（サインアウト/再起動でも可）
- それでも出ない場合は、もう一度 `setup.vbs` を実行して上書きインストール

### 自動更新が動作しない

- GitHubへのネットワーク接続を確認
- プロキシ環境の場合、pywin32がインストールされているか確認
- 共有フォルダからの手動更新を試行

## アンインストール

手動で以下を削除：

1. `%LOCALAPPDATA%\YakuLingo`
2. デスクトップの `YakuLingo.lnk`
3. スタートメニューの `YakuLingo` フォルダ
4. スタートアップの `YakuLingo.lnk`

### 統合（右クリック）の削除（任意）

右クリックメニューを消したい場合は、ユーザーのレジストリ（HKCU）から以下を削除します：

- Explorer右クリック: `Software\\Classes\\SystemFileAssociations\\.<ext>\\shell\\YakuLingoTranslate`（`<ext>`: `.xlsx` `.xls` `.docx` `.doc` `.pptx` `.ppt` `.pdf` `.txt` `.msg`）

### 翻訳履歴も削除する場合

5. `%USERPROFILE%\.yakulingo`

## システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| PowerShell | 5.1以上（Windows標準） |
| ネットワーク | 共有フォルダへのアクセス |
| 自動更新 | GitHubへのアクセス（オプション） |
