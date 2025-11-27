# 配布手順

Excel日英翻訳ツールの配布手順です。

## システム要件

### ユーザー側の要件
- **OS**: Windows 10/11
- **ブラウザ**: Microsoft Edge
- **アカウント**: M365 Copilot アクセス権
- **アプリ**: Microsoft Excel

---

## 方法1: .exe ファイルで配布（推奨）

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

## 方法2: Pythonスクリプトで配布

### パッケージ内容

```
ExcelTranslator/
├── translate.py      # メインスクリプト
├── ui.py             # UI
├── prompt.txt        # プロンプト
├── requirements.txt  # 依存関係
├── install.bat       # インストーラー
└── run.bat           # 実行用バッチ
```

### install.bat の内容

```batch
@echo off
echo Installing Excel Translator...

python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed!
    pause
    exit /b 1
)

pip install -r requirements.txt
playwright install chromium

echo Installation complete!
pause
```

### run.bat の内容

```batch
@echo off
cd /d "%~dp0"
python translate.py
```

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

### Q: 起動しない
- Python 3.10以上がインストールされているか確認
- `pip install -r requirements.txt` を実行

### Q: Edgeが起動しない
- Microsoft Edge がインストールされているか確認
- 既に開いているEdgeを閉じてから再試行

### Q: Copilotにログインできない
- M365 Copilot のアクセス権があるか確認
- 会社のIT部門に問い合わせ

---

## セキュリティ注意事項

1. **認証情報**: ログイン情報はEdgeプロファイルに保存
2. **データ送信**: 翻訳テキストはM365 Copilotに送信
3. **ローカル保存**: 翻訳履歴はローカルに保存されません
