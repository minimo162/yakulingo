# Local AI パフォーマンス計測手順

## 目的
ローカルAI翻訳の高速化を、再現可能な手順と数値で確認できる状態にする。

## 事前準備
- `local_ai/` に `llama.cpp` の `llama-server` とモデル（.gguf）があること
- 依存関係の準備（未実施なら）
  - `uv sync`
  - `uv sync --extra test`
  - `playwright install chromium`（E2E計測を使う場合）

## Vulkan(iGPU) 事前確認（Windows）
- Vulkan 版 llama.cpp バイナリを用意（GitHub Releases の Windows x64 (Vulkan) など）
  - 同梱する場合: `LOCAL_AI_LLAMA_CPP_VARIANT=vulkan` を設定して `packaging/install_deps.bat` を実行
  - 展開先の例: `local_ai/llama_cpp/vulkan/`
- 展開したフォルダでデバイスを確認
```powershell
.\llama-cli.exe --version
.\llama-cli.exe --list-devices
```
- `Vulkan0` が表示されれば iGPU が認識されている

## 計測の流れ（推奨）
1. CLIベンチで warm / cold をそれぞれ実行し、JSONを保存
2. E2E計測で「アプリ起動→翻訳完了」の時間を取得
3. 設定値と実行環境を揃え、改善前後で数値を比較する

比較時に揃える項目:
- モデル/サーバ、`local_ai_*` の設定値、入力文
- 実行環境（CPU/メモリ、電源設定、バックグラウンド負荷）
> **Note**: CPU-only と Vulkan(iGPU) 比較では、`local_ai_threads` / `local_ai_ctx_size` / `local_ai_batch_size` / `local_ai_ubatch_size` と入力文を固定し、`device` / `-ngl` / `-fa` など GPU 関連だけを変える。
> **Note**: `local_ai_*` は `user_settings.json` には保存されません。恒久的な変更は `config/settings.template.json` を更新し、ベンチの一時上書きは CLI で行います。
> **Note**: 既定値は `local_ai_device=Vulkan0` / `local_ai_n_gpu_layers=99`。CPU-only に戻す場合は `none` / `0` を設定します。
> **Note**: プロキシ環境では `NO_PROXY=127.0.0.1,localhost` を自動補完し、ローカル API がプロキシ経由にならないようにします。

## CLIベンチ（tools/bench_local_ai.py）

### Warm / Cold の実行
```bash
# warm（既存サーバ再利用）
uv run python tools/bench_local_ai.py --mode warm --json

# cold（ローカルAIサーバを停止してから計測）
uv run python tools/bench_local_ai.py --mode cold --json
```

### 記録する指標
- `translation_seconds`: 推論にかかった時間
- `total_seconds`: プロンプト構築 + 推論（single のみ）
- `prompt_chars`: プロンプト文字数（single のみ）
- `prompt_build_seconds`: プロンプト構築時間（single のみ）
- `warmup_seconds[]`: ウォームアップ実行時間
- `output_chars`: 出力文字数
- `options`: 3スタイル比較時の件数
- `settings.*`: 有効化された `local_ai_*` の値

### JSON 出力
```bash
# stdout にJSON（既存出力は維持され、最後にJSONが出力される）
uv run python tools/bench_local_ai.py --mode warm --json

# JSONをファイルに保存
uv run python tools/bench_local_ai.py --mode warm --out .tmp/bench_local_ai.json
```

### 設定上書き例（local_ai_*）
以下はベンチ用の**一時上書き**です（永続化されません）。
> **Note**: 上書き値を変えた場合は `--restart-server` を付けて再起動し、設定が確実に反映された状態で計測します。
```bash
# threads / ctx / batch / ubatch の上書き
uv run python tools/bench_local_ai.py --mode warm \
  --threads 6 --ctx-size 8192 --batch-size 512 --ubatch-size 128 --json

# モデル・サーバディレクトリの指定
uv run python tools/bench_local_ai.py --mode warm \
  --model-path local_ai/models/shisa-v2.1-qwen3-8B-UD-Q4_K_XL.gguf \
  --server-dir local_ai/llama_cpp --json

# max_tokens を無効化（0以下でNone扱い）
uv run python tools/bench_local_ai.py --mode warm --max-tokens 0 --json

# Vulkan(iGPU) 用の一時上書き
uv run python tools/bench_local_ai.py --mode warm \
  --device Vulkan0 --n-gpu-layers 99 --flash-attn auto --no-warmup --json
```

### CPU-only vs Vulkan(iGPU) 比較（同一入力）
CPU-only と Vulkan を同条件で比較する場合は、`--server-dir` と `--device`/`--n-gpu-layers` を明示します。
> **Note**: 上書き条件での比較は `--restart-server` を付けて反映させます。
```bash
# CPU-only warm/cold（avx2 バイナリ + device none）
uv run python tools/bench_local_ai.py --mode warm --restart-server \
  --server-dir local_ai/llama_cpp/avx2 --device none --n-gpu-layers 0 --flash-attn auto \
  --json --out .tmp/bench_cpu_warm.json

uv run python tools/bench_local_ai.py --mode cold --restart-server \
  --server-dir local_ai/llama_cpp/avx2 --device none --n-gpu-layers 0 --flash-attn auto \
  --json --out .tmp/bench_cpu_cold.json

# Vulkan(iGPU) warm/cold（vulkan バイナリ + Vulkan0）
uv run python tools/bench_local_ai.py --mode warm --restart-server \
  --server-dir local_ai/llama_cpp/vulkan --device Vulkan0 --n-gpu-layers 99 --flash-attn auto \
  --json --out .tmp/bench_vk_warm.json

uv run python tools/bench_local_ai.py --mode cold --restart-server \
  --server-dir local_ai/llama_cpp/vulkan --device Vulkan0 --n-gpu-layers 99 --flash-attn auto \
  --json --out .tmp/bench_vk_cold.json
```

```powershell
# -ngl の探索（PowerShell例）
$values = 0, 8, 16, 24, 32, 40, 99
foreach ($v in $values) {
  uv run python tools/bench_local_ai.py --mode warm `
    --device Vulkan0 --n-gpu-layers $v --flash-attn auto --json
}
```

### バッチ分割のデフォルト
- `local_ai_max_chars_per_batch`: 1000
- `local_ai_max_chars_per_batch_file`: 800
- 値を上げるとバッチ数は減るが、プロンプトが長すぎる場合は自動分割（`LOCAL_PROMPT_TOO_LONG`）にフォールバックする

## 速度に効く主な設定
- `local_ai_threads`: CPUスレッド数（`0` は自動）
- `local_ai_ctx_size`: コンテキスト長（長すぎると遅くなる）
- `local_ai_batch_size` / `local_ai_ubatch_size`: llama.cpp のバッチ設定
- `local_ai_max_chars_per_batch` / `local_ai_max_chars_per_batch_file`: 翻訳分割の文字数上限
- `local_ai_max_tokens`: 応答上限（0以下でNone扱い、推論時間に影響）

## Vulkan(iGPU) トラブルシュート
- `ErrorOutOfDeviceMemory` / `Requested buffer size exceeds ...`
  - `local_ai_vk_force_max_allocation_size` を設定（例: `536870912`=512MiB）
  - 併せて `local_ai_n_gpu_layers` / `local_ai_ctx_size` を下げる
- 初期化や warmup で不具合が出る
  - `local_ai_no_warmup = true` を試す（CLIなら `--no-warmup`）
- 出力が文字化け/意味不明になる
  - `local_ai_vk_disable_f16 = true` を試す（CLIなら `--vk-disable-f16`）

## Shisa / Qwen3 推奨パラメータ（README準拠）
- Qwen3は温度0の決定論的生成で繰り返しが起きやすいため、サンプリング（Temperature > 0）が推奨されています。
- 推奨値（既定値）:
  - `local_ai_temperature = 0.7`
  - `local_ai_top_p = 0.8`
  - `local_ai_top_k = 20`
  - `local_ai_min_p = 0.01`（0.0 で無効化したい場合は `0.0` を指定）
  - `local_ai_repeat_penalty = 1.05`

## アプリ起動を含む計測（E2E / Playwright）
```bash
uv run --extra test python tools/e2e_local_ai_speed.py
```
- JSON出力: `app_start_seconds`, `page_ready_seconds`, `local_ai_ready_seconds`, `translation_seconds`, `total_seconds`, `elapsed_badge_seconds`
  - 追加情報: `translation_seconds_source`, `translation_elapsed_logged`, `translation_prep_seconds_logged`, `local_ai_warmup_seconds_logged`, `streaming_preview_disabled`, `app_log_path`
- 主要オプション: `--url`, `--timeout`, `--startup-timeout`, `--translation-timeout`, `--text`, `--headed`, `--out`, `--disable-streaming-preview`
- ストリーミング表示を無効化: `--disable-streaming-preview`（ローカルAIの途中表示更新を抑止）
- ローカルAIの既定はストリーミング表示OFF（有効化する場合は `YAKULINGO_DISABLE_LOCAL_STREAMING_PREVIEW=0`）
- ログ出力: `--app-log` でアプリのstdout/stderrを保存（未指定なら `.tmp/` に自動保存）
- 事前条件: `local_ai/` が利用可能、PlaywrightのChromiumが導入済み
- ケース運用では `--out` / `--app-log` を `/work/<case-id>/.tmp/` 配下に指定する

## アプリ起動を含む計測（手動テンプレ）

1. `uv run python app.py` でアプリを起動
2. バックエンドを「ローカルAI」に切り替え
   - 直後に軽いウォームアップが非同期で走る（`[TIMING] LocalAI warmup`）
3. 固定の入力文（例: `tools/bench_local_ai_input.txt` の内容）を貼り付け
4. 翻訳を実行し、完了までの経過時間を記録
5. warm / cold の差分や、改善前後の比較を記録

## よくある失敗と回避策
- AVX2未対応CPU: 同梱のAVX2版 `llama-server` が起動しない場合は別ビルドが必要
- モデルパス不備: `local_ai_model_path` の指定ミスで起動失敗
- 初回の重さ: 初回はモデルロード/ウォームアップで遅くなりやすい
- Playwright未導入: `playwright install chromium` を先に実行
- ポート競合: `127.0.0.1:8765` またはローカルAIポートが使用中だと起動に失敗
- ウイルス対策の干渉: 初回起動やPlaywright起動時に遅延する場合がある

## 記録テンプレ（例）
- 実行日時: 
- モード: warm | cold
- コマンド: 
- translation_seconds: 
- total_seconds: 
- prompt_chars: 
- local_ai_threads / ctx / batch / ubatch: 
- 備考:
