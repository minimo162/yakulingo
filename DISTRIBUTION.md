# YakuLingo 配布ガイド

## 概要

YakuLingoはネットワーク共有フォルダからのワンクリックセットアップに対応しています。

## 配布パッケージの作成

開発環境で以下を実行：

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

## トラブルシューティング

### setup.batが実行できない

```
powershell -ExecutionPolicy Bypass -File ".scripts\setup.ps1"
```

### ZIPが見つからないエラー

- `YakuLingo*.zip` が共有フォルダにあるか確認

### アクセス拒否エラー

- 共有フォルダへの読み取り権限を確認

## アンインストール

手動で以下を削除：

1. `%LOCALAPPDATA%\YakuLingo`
2. デスクトップの `YakuLingo.lnk`
3. スタートメニューの `YakuLingo.lnk`

## システム要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| PowerShell | 5.1以上（Windows標準） |
| ネットワーク | 共有フォルダへのアクセス |
