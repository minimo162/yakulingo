# HF Spaces（ZeroGPU）で CUDA 版 llama.cpp（llama-server）を「事前ビルド」で使う

## 目的
GGUF（例: TranslateGemma の `.gguf`）を **CUDA でオフロード**して実行したい場合、
ZeroGPU 環境では Vulkan デバイスが列挙できないことがあるため、Vulkan 版 `llama-server` が使えない場合があります。

このドキュメントでは、**CUDA 版 `llama-server` を事前ビルドして配布**し、Space 側はそれをダウンロードして使う手順をまとめます。

## 前提
- Space の Hardware は **ZeroGPU**
- Space の Secrets に `HF_TOKEN` を設定済み（モデルが gated の場合）
- 本リポジトリの Space は `spaces/app.py`

## 方針（重要）
- Space 内で `llama.cpp` をビルドしない（ビルド時間・失敗率が高い）
- 代わりに、**CUDA 版 `llama-server` を外部でビルドしてアーカイブ化**し、Space 起動時にダウンロードして使う

## 1) CUDA 版 llama.cpp（llama-server）をビルドする（GitHub Actions）
このリポジトリには、CUDA 版 `llama-server` を Linux 向けにビルドして成果物を作る workflow を同梱しています。

- workflow: `.github/workflows/build_llama_cpp_cuda_linux.yml`

実行方法（概要）:
1. GitHub の Actions で `build_llama_cpp_cuda_linux` を開く
2. `Run workflow` から実行
   - `cuda_architectures` は既定で `80;86;89;90`（H200 含む）になっています。
3. 成果物（`.tar.gz`）をダウンロード
4. それを **GitHub Releases 等の「外部から直接ダウンロードできるURL」**に置く

> NOTE: Actions の artifacts の URL は長期安定・公開URLとしては扱いづらいので、
> Space から直接取得する用途では GitHub Releases 等に置くことを推奨します。

## 2) Space で CUDA 版 llama-server を使う設定
Space の Variables/Secrets に以下を設定します。

### 必須（バックエンド固定）
- `YAKULINGO_SPACES_BACKEND=gguf`  
  - CUDA が見えている環境では既定で Transformers を選ぶため、GGUF（llama-server）を使う場合は固定します。

### 必須（CUDA 版 llama-server の URL）
- `YAKULINGO_SPACES_LLAMA_CPP_URL=<あなたが置いた .tar.gz のURL>`

### 推奨
- `YAKULINGO_SPACES_LLAMA_DEVICE=auto`
  - `llama-cli --list-devices` で列挙された `CUDA0` などのデバイス名を自動選択します。
- `YAKULINGO_SPACES_N_GPU_LAYERS=999`
  - 可能な限り GPU にオフロード（内部的に `999` 相当を推奨値として扱います）
- `HF_HOME=/data/.huggingface`（永続ストレージがある場合）

### 参考（モデル）
- `YAKULINGO_SPACES_GGUF_REPO_ID` / `YAKULINGO_SPACES_GGUF_FILENAME`

## よくあるエラー
### `--list-devices` が空 / `invalid device`
- Vulkan 版バイナリを使っている（ZeroGPU で Vulkan が見えない）可能性があります。
- CUDA 版バイナリを使う場合は `YAKULINGO_SPACES_LLAMA_CPP_URL` を CUDA 版に差し替え、
  `YAKULINGO_SPACES_LLAMA_DEVICE=auto` を設定してください。

### 起動はするが遅すぎる
- GPU が割り当てられていない可能性があります。Hardware が ZeroGPU になっているか確認してください。
- それでも GPU が来ない場合は queue 待ちが発生することがあります（ZeroGPU の仕様）。
