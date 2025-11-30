# YakuLingo 配布ガイド

## 概要

YakuLingoはネットワーク共有フォルダからのワンクリックセットアップに対応しています。
インストール後は、GitHub Releases経由で自動更新されます。

## 配布パッケージの作成

### 前提条件

開発環境で先に `install_deps.bat` を実行し、以下のフォルダが存在すること：
- `.venv` (Python仮想環境)
- `.uv-python` (Python本体)
- `.playwright-browsers` (ブラウザ)

### 実行

```batch
make_distribution.bat
```

### 出力物

```
YakuLingo_YYYYMMDD.zip    # 配布用ZIP
share_package/            # 共有フォルダ用パッケージ
├── setup.bat             # ユーザーが実行するファイル
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
├── setup.bat
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
2. `setup.bat` をダブルクリック
3. `Y` を入力して確認
4. 完了後、デスクトップのショートカットから起動

### インストール先

```
%LOCALAPPDATA%\YakuLingo\
```

### 作成されるショートカット

- デスクトップ: `YakuLingo.lnk`
- スタートメニュー: `YakuLingo.lnk`

## セットアップの動作

setup.ps1は以下を実行：

1. 既存インストールがあれば設定ファイルをバックアップ
2. ZIPをローカルにコピー・展開
3. `%LOCALAPPDATA%\YakuLingo` にファイル配置
4. 設定ファイルを復元
5. ショートカット作成

### 環境フォルダの扱い

以下のフォルダは初回のみコピーされ、更新時はスキップ：
- `.venv` (Python仮想環境)
- `.uv-python` (Python本体)
- `.playwright-browsers` (ブラウザ)

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
| **ファイル** | `app.py`, `pyproject.toml`, `uv.lock`, `uv.toml`, `run.bat`, `README.md` |
| **保持（上書きしない）** | `glossary.csv`, `config/settings.json` |
| **保持（更新対象外）** | `.venv/`, `.uv-python/`, `.playwright-browsers/` |

### プロキシ環境での動作

- Windowsシステムプロキシ設定を自動検出
- NTLM認証プロキシ対応（pywin32が必要）

### 管理者向け情報

自動更新はGitHubリポジトリのReleasesから取得します。
社内ネットワークでGitHubへのアクセスがブロックされている場合：
- 共有フォルダからの手動更新を案内してください
- または、プロキシ設定でGitHubへのアクセスを許可してください

## データの保存場所

ユーザーデータは以下の場所に保存されます：

| データ | 場所 | 更新時の扱い |
|--------|------|-------------|
| アプリ設定 | `%LOCALAPPDATA%\YakuLingo\config\settings.json` | 保持 |
| 翻訳履歴 | `%USERPROFILE%\.yakulingo\history.db` | 保持 |
| 用語集 | `%LOCALAPPDATA%\YakuLingo\glossary.csv` | 保持 |

> **Note**: 翻訳履歴はアプリケーションフォルダ外に保存されるため、アンインストール後も残ります

## トラブルシューティング

### setup.batが実行できない

```
powershell -ExecutionPolicy Bypass -File ".scripts\setup.ps1"
```

### ZIPが見つからないエラー

- `YakuLingo*.zip` が共有フォルダにあるか確認

### アクセス拒否エラー

- 共有フォルダへの読み取り権限を確認

### 自動更新が動作しない

- GitHubへのネットワーク接続を確認
- プロキシ環境の場合、pywin32がインストールされているか確認
- 共有フォルダからの手動更新を試行

## アンインストール

手動で以下を削除：

1. `%LOCALAPPDATA%\YakuLingo`
2. デスクトップの `YakuLingo.lnk`
3. スタートメニューの `YakuLingo.lnk`

### 翻訳履歴も削除する場合

4. `%USERPROFILE%\.yakulingo`

## システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| PowerShell | 5.1以上（Windows標準） |
| ネットワーク | 共有フォルダへのアクセス |
| 自動更新 | GitHubへのアクセス（オプション） |
