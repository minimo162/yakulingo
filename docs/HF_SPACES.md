# Hugging Face Spaces（ZeroGPU）デプロイ手順（訳リンゴ・デモ）

## 目的
このリポジトリにはデスクトップ向け（NiceGUI）とは別に、Hugging Face Spaces 上で動く **テキスト翻訳デモ** を同梱しています。

- デモ UI: `spaces/app.py`（Gradio）
- 翻訳バックエンド: `spaces/translator.py`（Transformers / MarianMT）

## できること / できないこと
### できること
- 日本語 ⇄ 英語のテキスト翻訳（自動判定）

### できないこと（本デモでは非対応）
- Excel / Word / PowerPoint / PDF 等のファイル翻訳
- デスクトップアプリ（NiceGUI + native window）としての配布

## 手順（推奨）
### 1) Space を作成
1. Hugging Face で Spaces を作成
2. SDK: **Gradio** を選択
3. Hardware: **ZeroGPU** を選択（利用可能な場合）

### 2) この GitHub リポジトリを接続
1. Space 設定から GitHub 連携でこのリポジトリを指定（既定ブランチ: `main`）
2. App file を `spaces/app.py` に設定

> NOTE: UI の項目名は変更されることがあります。要点は「Gradio SDK」「ZeroGPU」「app_file=spaces/app.py」です。

### 3) （任意）永続ストレージを有効化
モデルは初回起動時にダウンロードされます。永続ストレージが使える場合はキャッシュを残すと安定します。

推奨:
- `HF_HOME=/data/.huggingface`

## 環境変数（推奨）
Space の Variables/Secrets に以下を設定します。

### 必須（推奨）
- `HF_HUB_DISABLE_TELEMETRY=1`

### 任意（キャッシュ）
- `HF_HOME=/data/.huggingface`（永続ストレージがある場合）

### 任意（モデル差し替え）
- `YAKULINGO_SPACES_MODEL_JA_EN`（既定: `Helsinki-NLP/opus-mt-ja-en`）
- `YAKULINGO_SPACES_MODEL_EN_JA`（既定: `Helsinki-NLP/opus-tatoeba-en-ja`）

### 任意（入力制限・生成設定）
- `YAKULINGO_SPACES_MAX_CHARS`（既定: 2000）
- `YAKULINGO_SPACES_MAX_NEW_TOKENS`（既定: 256）
- `YAKULINGO_SPACES_NUM_BEAMS`（既定: 4）

## 依存関係
- Spaces（Linux）向けの追加依存は `requirements.txt` に Linux 限定で追記しています。
- ローカルでデモだけ動かしたい場合は `spaces/requirements.txt` を利用してください。

## ローカルでの動作確認
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r spaces/requirements.txt
python spaces/app.py
```

## ZeroGPU の注意点（よくある詰まり）
- 初回起動はモデルダウンロードで時間がかかります（数分かかる場合あり）
- GPU が使えないタイミングでは CPU 実行になります（処理が遅くなることがあります）
- メモリ不足/タイムアウトが出る場合:
  - 入力を短くする
  - `YAKULINGO_SPACES_MAX_NEW_TOKENS` を下げる
  - `YAKULINGO_SPACES_MAX_CHARS` を下げる

