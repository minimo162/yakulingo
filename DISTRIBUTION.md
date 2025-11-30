# 配布手順

Excel日英翻訳ツールの配布手順です。

## システム要件

### ユーザー側の要件
- **OS**: Windows 10/11
- **ブラウザ**: Microsoft Edge
- **アカウント**: M365 Copilot アクセス権
- **アプリ**: Microsoft Excel

---

## 方法1: スクリプト配布（推奨）

### 配布パッケージ

```
ExcelTranslator/
├── translate.py          # メインスクリプト
├── ui.py                 # UI
├── prompt.txt            # プロンプト
├── pyproject.toml        # 依存関係定義
├── setup.bat             # インストーラー（uvを自動ダウンロード）
└── run.bat               # 実行用バッチ
```

### インストール手順（ユーザー）

1. フォルダを任意の場所にコピー
2. `setup.bat` をダブルクリック（初回のみ、約2-3分）
   - uv（高速パッケージマネージャ）を自動ダウンロード
   - Python 3.11 を自動インストール
   - 依存関係を自動インストール
   - Playwright ブラウザを自動インストール
3. `run.bat` をダブルクリックして起動

### setup.bat の動作

1. `uv.exe` をダウンロード（Astral社の高速パッケージマネージャ）
2. Python 3.11 をローカルインストール（システム汚染なし）
3. `.venv` 仮想環境を作成
4. `pyproject.toml` から依存関係をインストール
5. Playwright の Chromium ブラウザをインストール

**メリット:**
- Pythonのシステムインストール不要
- すべてローカルフォルダ内で完結
- クリーンアンインストール可能（フォルダ削除のみ）

---

## 方法2: .exe ファイルで配布

### ビルド手順（開発者）

1. **必要なツールをインストール**
   ```bash
   pip install pyinstaller
   ```

2. **ビルド実行**
   ```bash
   python build_exe.py
   ```

3. **出力ファイル**
   ```
   dist/
   └── ExcelTranslator.exe  ← 配布するファイル
   ```

4. **配布パッケージ作成**
   ```
   ExcelTranslator/
   ├── ExcelTranslator.exe
   ├── prompt.txt
   └── README.txt
   ```

### インストール手順（ユーザー）

1. `ExcelTranslator` フォルダを任意の場所にコピー
2. `ExcelTranslator.exe` をダブルクリック
3. 初回起動時にM365 Copilotにログイン

---

## 初回セットアップガイド（ユーザー向け）

### 1. Microsoft Edgeの確認
- Edge がインストールされていることを確認

### 2. M365 Copilot へのログイン
- 初回起動時にログイン画面が表示されます
- 会社のアカウントでログインしてください

### 3. 使い方
1. Excelで翻訳したいセルを選択
2. `Ctrl+Shift+E` を押す（またはアプリから「Start Translation」）
3. 翻訳完了を待つ

---

## トラブルシューティング

### Q: setup.batが失敗する
- インターネット接続を確認
- ウイルス対策ソフトが `uv.exe` をブロックしていないか確認
- 管理者権限で実行してみる
- **社内プロキシ環境の場合**: 下記「プロキシ設定」を参照

### Q: 社内プロキシ環境でsetup.batが動かない

setup.batは以下の順序で自動的にプロキシ対応を試みます：

1. **プロキシサーバー検出** - 自動検出 or 配布者が事前設定
2. **Windows認証で接続試行** - NTLM/Kerberos認証を自動使用
3. **失敗時のみID/パスワード入力** - ユーザーに入力を要求

```
============================================================
Proxy Authentication Required
Server: proxy.yourcompany.co.jp:8080
============================================================
Username (or press Enter to skip): tanaka
Password (input will be hidden):
********
[INFO] Credentials configured.
```

**配布者向け**: 自動検出できない場合は、setup.batの以下の行を編集：

```batch
:: set PROXY_SERVER=proxy.yourcompany.co.jp:8080
```
↓
```batch
set PROXY_SERVER=proxy.yourcompany.co.jp:8080
```

**補足**:
- プロキシサーバーは自動検出または事前設定（ユーザー入力不要）
- パスワードはマスク表示され、ファイルに保存されません
- Windows認証環境では、多くの場合ID/パスワード入力も不要

### Q: run.batで起動しない
- まず `setup.bat` を実行したか確認
- `.venv` フォルダが存在するか確認

### Q: Edgeが起動しない
- Microsoft Edge がインストールされているか確認
- 既に開いているEdgeを閉じてから再試行

### Q: Copilotにログインできない
- M365 Copilot のアクセス権があるか確認
- 会社のIT部門に問い合わせ

---

## アンインストール

フォルダを削除するだけでOK（レジストリ等は汚しません）

---

## セキュリティ注意事項

1. **認証情報**: ログイン情報はEdgeプロファイルに保存
2. **データ送信**: 翻訳テキストはM365 Copilotに送信
3. **ローカル保存**: 翻訳履歴はローカルに保存されません
