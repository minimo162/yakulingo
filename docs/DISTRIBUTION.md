# YakuLingo 配布ガイド

## 概要

YakuLingoはネットワーク共有フォルダからのワンクリックセットアップに対応しています。  
セットアップ後は GitHub Releases 経由の自動更新が利用されます。

## 配布パッケージの作成

### 前提条件

開発環境で `packaging/install_deps.bat` を実行し、以下のフォルダが存在することを確認します。

> **Note**: 新規インストールでは Vulkan(x64) が既定です。CPU版を同梱したい場合は `set LOCAL_AI_LLAMA_CPP_VARIANT=cpu` を設定して `packaging/install_deps.bat` を実行します。

- `.venv` (Python 仮想環境)
- `.uv-python` (Python 本体)
- `.playwright-browsers` (ブラウザ)
- `local_ai` (ローカルAI: llama.cpp `llama-server` + 同梱モデル `local_ai/models/translategemma-4b-it.i1-Q4_K_S.gguf` + LICENSE/manifest)
  - `packaging/make_distribution.bat` は `local_ai` 配下の追加 `.gguf*` を除外してコピーし、同梱モデルのみを含めます。

### 実行

```batch
packaging\make_distribution.bat
```

### 出力物

```
YakuLingo_YYYYMMDD.zip    # 配布ZIP
share_package/            # 共有フォルダ用パッケージ
├── setup.vbs             # ユーザーが実行するファイル
├── YakuLingo_*.zip       # 配布パッケージ
├── README.html           # ユーザー向けガイド
└── .scripts/
    └── setup.ps1
```

## 共有フォルダへの配置

1. `share_package/` の中身を共有フォルダにコピー

```
\\server\share\YakuLingo\
├── setup.vbs
├── YakuLingo_YYYYMMDD.zip
├── README.html
└── .scripts\
```

2. ユーザーに読み取り権限を付与

### 更新方法

1. 新しい ZIP を共有フォルダにコピー
2. 古い ZIP を削除

> **Note**: 既存ユーザーは自動更新で更新されるため、共有フォルダの更新は新規/再インストール用です。

## ユーザー向けインストール手順

1. `\\server\share\YakuLingo` を開く
2. `setup.vbs` をダブルクリック
3. セットアップ完了まで待機
4. 完了後、YakuLingo が常駐起動
5. UI を開く: デスクトップの `YakuLingo`（または `Ctrl + Alt + J` / タスクトレイのアイコンメニュー > `Open`）
6. 終了する: タスクトレイのアイコンメニュー > `Exit`
7. アンインストール: スタートメニュー > `YakuLingo アンインストール`

## インストール先

```
%LOCALAPPDATA%\YakuLingo\
```

## 作成されるショートカット/スクリプト

- スタートメニュー
  - `YakuLingo アンインストール`
- デスクトップ
  - `YakuLingo` (UIを開く)
- スタートアップ
  - `YakuLingo` (ログオン時に常駐起動)
- インストール先に生成される補助スクリプト
  - `YakuLingo_OpenUI.ps1`
  - `YakuLingo_Resident.ps1`
  - `YakuLingo_Exit.ps1`
  - `YakuLingo_Uninstall.ps1`

> **Note**: デスクトップに `YakuLingo` ショートカットを作成します（UIを開く用）。

## setup.ps1 の処理概要

1. 実行中の YakuLingo を検出して終了を促す（必要に応じてプロセス停止）
2. 既存インストールの削除
3. ZIP をローカルにコピーして展開
4. `%LOCALAPPDATA%\YakuLingo` に配置
5. ユーザーデータの復元
6. ショートカット作成と常駐起動
7. 常駐起動後、`/api/setup-status` で準備完了を確認（ランチャーがローカルで確認）

## ユーザーデータの保持/更新

| データ | 動作 |
|--------|------|
| `config/user_settings.json` | バックアップして復元（ユーザー設定を保持） |
| `config/settings.template.json` | 新バージョンで上書き（デフォルト設定） |
| `glossary.csv` | 既存を保持し、新しい既定版は `glossary.dist.csv` として保存 |
| `prompts/translation_rules.txt` | 既存を保持し、新しい既定版は `translation_rules.dist.txt` として保存 |

> **Note**: setup.vbs は既存の用語集・翻訳ルールを上書きしません。

## 環境フォルダの扱い

setup.vbs はクリーンインストールを行い、環境フォルダも上書きします。

- `.venv` (Python 仮想環境)
- `.uv-python` (Python 本体)
- `.playwright-browsers` (ブラウザ)
- `local_ai`（ローカルAIランタイム。配布ZIPに同梱され、クリーンインストールでは上書きされます）

> **Note**: GitHub Releases 経由の自動更新では環境フォルダは保持されます。

## 自動更新

1. アプリ起動時に GitHub Releases API をチェック
2. 新バージョンがあれば通知
3. **更新** を選択するとダウンロード/インストール
4. 再起動後に反映

### 依存関係変更時 (REQUIRES_REINSTALL)

リリースノートに `[REQUIRES_REINSTALL]` が含まれる場合:

- 自動更新ではなく setup.vbs の再実行を案内
- 共有フォルダの最新パッケージで再インストール
  - 例: `.venv` / `.uv-python` / `.playwright-browsers` / `local_ai` の更新が必要な場合（自動更新では更新されない）

## データ保存場所

| データ | 場所 | 更新時 |
|--------|------|--------|
| アプリ設定（ユーザー） | `%LOCALAPPDATA%\YakuLingo\config\user_settings.json` | 保持 |
| アプリ設定（デフォルト） | `%LOCALAPPDATA%\YakuLingo\config\settings.template.json` | 上書き |
| 翻訳履歴 | `%USERPROFILE%\.yakulingo\history.db` | 保持 |
| ローカルAI状態 | `%USERPROFILE%\.yakulingo\local_ai_server.json` | 保持 |
| ローカルAIログ | `%USERPROFILE%\.yakulingo\logs\local_ai_server.log` | 保持 |
| 用語集 | `%LOCALAPPDATA%\YakuLingo\glossary.csv` | 保持/差分は `.dist` |

## アンインストール

- スタートメニュー > `YakuLingo アンインストール`
- 翻訳履歴も削除する場合は `%USERPROFILE%\.yakulingo` を削除

## トラブルシューティング

### setup.vbs が実行できない

PowerShell から直接実行します。

```powershell
powershell -ExecutionPolicy Bypass -File ".scripts\setup.ps1"
```

### ZIP が見つからない

- `YakuLingo*.zip` が共有フォルダにあるか確認

### アクセス拒否

- 共有フォルダへの読み取り権限を確認

### 自動更新が動作しない

- GitHub へのネットワーク接続を確認
- プロキシ環境の場合は `pywin32` の有無を確認
- 共有フォルダからの再インストールを案内

## システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| PowerShell | 5.1 以上 |
| ネットワーク | 共有フォルダへのアクセス |
| 自動更新 | GitHub へのアクセス（任意） |
| ローカルAI | `local_ai/` 同梱（現状はAVX2版。AVX2非対応PCではCopilot利用、またはgeneric版同梱が必要） |
