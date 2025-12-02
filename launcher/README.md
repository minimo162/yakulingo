# YakuLingo Native Launcher

軽量なネイティブランチャー（C言語製）

## 特徴

- **起動速度**: VBS より高速（~10KB の exe）
- **コンソールなし**: 黒い窓が一切表示されない
- **多重起動防止**: HTTP でポートチェック
- **ポータブル対応**: pyvenv.cfg のパスを自動修正

## ビルド方法

### 方法1: MinGW-w64（推奨）

```bat
REM MinGW-w64 をインストール後
build.bat
```

### 方法2: Visual Studio

```bat
REM Developer Command Prompt から
build.bat
```

### 方法3: 手動コンパイル

```bat
REM MinGW
gcc -mwindows -O2 -s launcher.c -o YakuLingo.exe -lwinhttp -lshlwapi

REM MSVC
cl /O2 /MT launcher.c /Fe:YakuLingo.exe /link winhttp.lib shlwapi.lib user32.lib /SUBSYSTEM:WINDOWS
```

## 使用方法

1. `build.bat` でビルド
2. 生成された `YakuLingo.exe` をアプリケーションのルートディレクトリにコピー
3. `YakuLingo.exe` をダブルクリックで起動

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
| ファイルサイズ | ~4KB | ~15KB |
| コンソール表示 | なし | なし |
| セキュリティソフト | 警告されることあり | 問題なし |
