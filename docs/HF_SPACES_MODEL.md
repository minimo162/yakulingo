# HF Spaces（ZeroGPU）: 翻訳モデル選定

## 前提
- 目的: Hugging Face Spaces（ZeroGPU）で「日本語 ↔ 英語」のテキスト翻訳デモを公開する。
- 制約:
  - ZeroGPU は GPU が常時使えるとは限らない（GPU 非利用時の挙動を決める必要がある）
  - コールドスタート（初回モデルDL/ロード）を許容しつつ、デモとして成立させる
  - 依存関係は Spaces でインストール可能な範囲に限定する

## 採用モデル（決定）
- GGUF: `mradermacher/translategemma-27b-it-i1-GGUF`
  - file: `translategemma-27b-it.i1-Q4_K_M.gguf`

## 実行方式（決定）
- 既定: `llama-server`（llama.cpp の事前ビルド済みバイナリ）で GGUF を実行して翻訳する
- CUDA を使う場合: PyTorch/Transformers バックエンドを使う（`YAKULINGO_SPACES_BACKEND=transformers`）
- ZeroGPU（動的GPU割当）前提で、翻訳処理は `@spaces.GPU` の内側で実行する（`size` / `duration` は環境変数で指定）
- 量子化は GGUF のファイルで決まる（例: `...-Q4_K_M.gguf`）
- GPU が使えない場合:
  - 既定は「エラーで案内」（CPU 実行は遅くなり得るため）
  - デバッグ用途で CPU 許可フラグを用意する（`YAKULINGO_SPACES_ALLOW_CPU=1`）
  - NOTE: 現状、llama.cpp の Linux 事前ビルドは Vulkan 版が中心のため、環境によっては GPU が見えず
    `ggml_vulkan: No devices found` で起動できない場合があります。その場合は `YAKULINGO_SPACES_N_GPU_LAYERS=0` を設定してください。

## 実装方針（実装済み）
- GGUF は HF Hub から初回ダウンロードしてキャッシュする（`HF_HOME` を推奨）
- `huggingface_hub.hf_hub_download` で `.gguf` を取得する
- llama.cpp の GitHub Releases から `llama-server` のアーカイブをダウンロードしてキャッシュする（`HF_HOME` 推奨）
- `llama-server` をサブプロセスで起動し、OpenAI 互換 API（`/v1/models` / `/v1/completions`）で推論する
- 方向ごとにプロンプトを組み立て（JP→EN / EN→JP）、出力は「翻訳文のみ」を要求する
- 出力の後処理（余計な前置き/コードフェンス/ラベル/`<start_of_turn>` 等）を実装する
- 入力ガード:
  - 文字数上限（既定: 2,000 文字）を設ける
  - 超過時は UI で短縮を促す

## 推奨の環境変数（Spaces）
- `HF_HOME`（キャッシュ先。永続ストレージを使う場合はそこへ）
- `HF_HUB_DISABLE_TELEMETRY=1`
- `YAKULINGO_SPACES_GGUF_REPO_ID`（既定: `mradermacher/translategemma-27b-it-i1-GGUF`）
- `YAKULINGO_SPACES_GGUF_FILENAME`（既定: `translategemma-27b-it.i1-Q4_K_M.gguf`）
- `YAKULINGO_SPACES_N_GPU_LAYERS`（既定: `-1`）
  - `-1`: 可能な限り GPU にオフロード（内部的には `999` 相当として扱います）
  - `0`: CPU のみ
- `YAKULINGO_SPACES_N_CTX`（既定: `4096`）
- `YAKULINGO_SPACES_TEMPERATURE`（既定: `0.0`）
- `YAKULINGO_SPACES_MAX_NEW_TOKENS`（既定: `256`）
- `YAKULINGO_SPACES_ALLOW_CPU=1`（デバッグ用途。非推奨）
- `YAKULINGO_SPACES_LLAMA_CPP_REPO`（既定: `ggerganov/llama.cpp`）
- `YAKULINGO_SPACES_LLAMA_CPP_ASSET_SUFFIX`（既定: `bin-ubuntu-vulkan-x64.tar.gz`）
- `YAKULINGO_SPACES_LLAMA_CPP_URL`（任意。直接 URL 指定）
- `YAKULINGO_SPACES_LLAMA_DEVICE`（任意。`--device` 上書き）
- `YAKULINGO_SPACES_LLAMA_SERVER_PORT`（任意。既定: `8090`）
- `YAKULINGO_SPACES_LLAMA_SERVER_STARTUP_TIMEOUT`（任意。既定: `120`）
- `YAKULINGO_SPACES_BACKEND=transformers`（CUDA を使う場合）
- `YAKULINGO_SPACES_HF_MODEL_ID`（既定: `google/translategemma-27b-it`）
- `YAKULINGO_SPACES_HF_LOAD_IN_4BIT`（既定: `1`。失敗する場合は `0`）
- `HF_TOKEN`（モデルが gated / 同意が必要な場合）

## 推奨（ZeroGPU）
- Python は `3.12.12` を推奨（本リポジトリは Python 3.11+ 前提のため）

## ライセンス / 利用条件
- Hugging Face のモデルカードを SSOT とする（Spaces 公開前に必ず確認）
- gated / 同意が必要な場合は、Spaces の Secret に `HF_TOKEN` を設定する
  - 1) モデルページで利用条件に同意し、必要ならアクセス申請を行う
  - 2) Hugging Face のアクセストークン（read で可）を発行する
  - 3) Space の Settings → Variables and secrets → Secrets に `HF_TOKEN` を追加する
  - 4) Space を再起動する（ビルド/起動時にモデルをダウンロードします）
