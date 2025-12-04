# YakuLingo Native Launcher

軽量なネイティブランチャー（Rust製）

## 特徴

- **起動速度**: VBS より高速
- **コンソールなし**: 黒い窓が一切表示されない
- **多重起動防止**: TCP でポートチェック
- **ポータブル対応**: pyvenv.cfg のパスを自動修正

## ビルド方法

### 方法1: GitHub Actions（推奨・インストール不要）

1. GitHub の **Actions** タブを開く
2. **Build Launcher** ワークフローを選択
3. **Run workflow** をクリック
4. 完了後、**Artifacts** から `YakuLingo-Launcher.zip` をダウンロード

### 方法2: ローカルでビルド

```bat
REM Rust をインストール後 (https://rustup.rs/)
build.bat
```

### 方法3: 手動コンパイル

```bat
cd launcher
cargo build --release
copy target\release\yakulingo-launcher.exe YakuLingo.exe
```

## 使用方法

1. `YakuLingo.exe` をアプリケーションのルートディレクトリにコピー
2. `YakuLingo.exe` をダブルクリックで起動

## 必要なディレクトリ構造

```
YakuLingo/
├── YakuLingo.exe      ← ランチャー
├── app.py
├── .venv/
│   └── Scripts/
│       └── pythonw.exe
├── .uv-python/
│   └── cpython-3.xx-windows-x86_64/
└── .playwright-browsers/
```

## VBS との比較

| 項目 | VBS | Native Launcher |
|------|-----|-----------------|
| 起動速度 | ~200ms | ~10ms |
| ファイルサイズ | ~4KB | ~200KB |
| コンソール表示 | なし | なし |
| セキュリティソフト | 警告されることあり | 問題なし |
