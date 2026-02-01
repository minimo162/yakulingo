# Hugging Face Spaces（ZeroGPU）デプロイ手順（訳リンゴ・デモ）

## 目的
このリポジトリにはデスクトップ向け（NiceGUI）とは別に、Hugging Face Spaces 上で動く **テキスト翻訳デモ** を同梱しています。

- デモ UI: `spaces/app.py`（Gradio）
- 翻訳バックエンド: `spaces/translator.py`（Transformers / `google/translategemma-27b-it`）
- ZeroGPU（動的GPU割当）前提で、翻訳処理は `@spaces.GPU` で実行します（GPU が必要な処理の実行時に GPU を要求し、完了後に解放）。

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

> NOTE: ZeroGPU のホスティングは、個人アカウントは PRO、組織は Team/Enterprise 等が必要です（ZeroGPU が選べない場合は契約/権限を確認してください）。
>
> NOTE: ZeroGPU の Python は `3.10.13` / `3.12.12` が選べます。本リポジトリは Python 3.11+ 前提のため、**`3.12.12` を推奨**します。

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

### 必須（場合による）
- `HF_TOKEN`（モデルが gated / 同意が必要な場合は Secret に設定）

### 任意（キャッシュ）
- `HF_HOME=/data/.huggingface`（永続ストレージがある場合）

### 任意（モデル差し替え）
- `YAKULINGO_SPACES_MODEL_ID`（既定: `google/translategemma-27b-it`）

### 任意（量子化）
- `YAKULINGO_SPACES_QUANT`（既定: `4bit`）
  - 例: `4bit` / `8bit` / `none`

### 任意（ZeroGPU: GPU size / duration）
- `YAKULINGO_SPACES_ZEROGPU_SIZE`（既定: `large`）
  - `large`: Half NVIDIA H200（70GB）
  - `xlarge`: Full NVIDIA H200（141GB、クォータ消費 2×）
- `YAKULINGO_SPACES_ZEROGPU_DURATION`（既定: `120`）
  - `@spaces.GPU(duration=...)` の設定値（秒）
  - ZeroGPU の既定は 60 秒のため、重い初回ロード等でタイムアウトする場合は調整してください
  - なるべく短い duration を指定すると、ZeroGPU の待ち行列で有利になる場合があります

### 任意（入力制限・生成設定）
- `YAKULINGO_SPACES_MAX_CHARS`（既定: 2000）
- `YAKULINGO_SPACES_MAX_NEW_TOKENS`（既定: 256）

### デバッグ用途（非推奨）
- `YAKULINGO_SPACES_ALLOW_CPU=1`
  - GPU が無い場合でも実行を試みます（27B は非常に遅い/失敗しやすいので非推奨）。

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

## ZeroGPU 公式仕様メモ（抜粋）
- ZeroGPU は **Gradio SDK 専用**（本デモは Gradio 前提）
- 対応バージョン（例）:
  - Gradio 4+
  - Python 3.10.13 / 3.12.12
  - PyTorch 2.1.0〜latest（広範）
- `torch.compile` は ZeroGPU では非対応（本デモは未使用）
- GPU 利用は日次クォータ制（閲覧者のアカウント種別で優先度/上限が変わる）
- Usage tiers（例。日次クォータ/優先度）:
  - 未ログイン: 2分 / 低
  - Free: 3.5分 / 中
  - PRO: 25分 / 最優先
  - Team: 25分 / 最優先
  - Enterprise: 45分 / 最優先
- Hosting limitations（例）:
  - 個人（PRO）: ZeroGPU Spaces 最大 10
  - 組織（Enterprise Hub）: 最大 50

## ZeroGPU の注意点（よくある詰まり）
- 初回起動はモデルダウンロードで時間がかかります（数分かかる場合あり）
- GPU が使えないタイミングがあり得ます（CPU での 27B 実行は現実的に遅くなるため、原則はエラーで案内する想定）
- メモリ不足/タイムアウトが出る場合:
  - 入力を短くする
  - `YAKULINGO_SPACES_MAX_NEW_TOKENS` を下げる
  - `YAKULINGO_SPACES_MAX_CHARS` を下げる
  - `YAKULINGO_SPACES_QUANT=4bit` を確認する
