# 配布ガイド

## 管理者向け：配布用ZIPの作成手順

### 1. セットアップ実行
```
setup.bat をダブルクリック
```

### 2. 動作確認
```
★run.bat をダブルクリック
```

### 3. ZIP作成

**含めるファイル:**
- `★run.bat`
- `setup.bat`
- `translate.py`
- `prompt.txt`
- `pyproject.toml`
- `uv.toml`
- `README.md`
- `.uv-cache/`
- `.uv-python/`
- `.playwright-browsers/`

**除外するファイル:**
- `.edge-profile/` （ログイン情報）
- `.venv/`
- `.git/`
- `uv.lock`
- `__pycache__/`
- `DISTRIBUTION.md`
- `AGENTS.md`
- `LICENSE`

---

## 利用者向け

1. ZIPを展開
2. `★run.bat` をダブルクリック
3. 初回のみM365 Copilotにログイン
