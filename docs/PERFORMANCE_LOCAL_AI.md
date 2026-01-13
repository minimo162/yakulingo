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
  - 同梱する場合: 新規インストールは Vulkan(x64) が既定。CPU版にしたい場合は `LOCAL_AI_LLAMA_CPP_VARIANT=cpu` を設定して `packaging/install_deps.bat` を実行（既存 `manifest.json` がある場合はその設定を優先し、切り替えは `LOCAL_AI_LLAMA_CPP_VARIANT` で上書き）
  - Vulkan が起動しない/ドライバ起因で失敗する場合も、同様に `LOCAL_AI_LLAMA_CPP_VARIANT=cpu` を指定して再インストールする（または `packaging/install_local_ai.ps1` を再実行する）
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
> **Note**: 既定値は `local_ai_device=none` / `local_ai_n_gpu_layers=0` / `local_ai_ctx_size=2048`。長文や安定性を優先したい場合は `local_ai_ctx_size=4096`（さらに必要なら `8192`）を指定します。Vulkan(iGPU) を使う場合は `Vulkan0` / `99`（または `auto` / `all`）を設定します。速度優先で `-ngl 16` にする場合は `local_ai_n_gpu_layers=16` を指定します。
> **Note**: プロキシ環境では `NO_PROXY=127.0.0.1,localhost` を自動補完し、ローカル API がプロキシ経由にならないようにします。

## パラメータスイープ設計（短時間）
- 変更対象は 1〜2 個に絞り、他の条件（モデル/入力文/参照ファイル/実行環境）を固定する
- 4〜6 条件の小さなマトリクスで実行し、1条件あたりの計測は短時間で終わる範囲にする
- 上書きを使う場合は `--restart-server` を付け、反映済みの状態で比較する
- JSON 出力は `run-id` を付けて `/work/<case-id>/.tmp/` に保存する

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

# ケース運用（保存先を /work/<case-id>/.tmp/ に統一）
uv run python tools/bench_local_ai.py --mode warm --out /work/<case-id>/.tmp/bench_local_ai.json
```

### JSONの server メタデータ（オフロード確認）
`--json` 出力には `server` セクションが含まれ、**実際にどのサーバ/バイナリで動いたか**を確認できます。
CPU-only と Vulkan(iGPU) の切り替えが意図通り反映されているかの検証に使います。

主なキー:
- `server_dir_config`: `--server-dir` など設定に入った値（未指定なら既定）
- `server_dir_resolved`: 実際に解決されたサーバディレクトリ
- `model_path_config` / `model_path_resolved`: 設定値と解決済みモデルパス
- `server_state`: 既存の状態ファイル内容（存在しない場合は `null`）
- `runtime`: 実行中サーバの情報（`host`/`port`/`server_variant` など。起動していない場合は `null`）
- `llama_cli_path` / `llama_cli_version`: `llama-cli` の検出結果（見つからない場合は `null`）

> **Note**: `server_state` は環境依存です。状態ファイルが無い/読めない場合は `null` になります。

### オフロード適用の確認（ログ）
サーバ起動時のログに、**実際に適用された** `--device` / `-ngl` が出力されます。
起動ログ（例: `~/.yakulingo/logs/startup.log`）またはコンソール出力で次の行を確認してください。

```
Local AI offload flags: --device <value> / -ngl <value>
```

- `unsupported`: 対象バイナリが該当フラグをサポートしていない
- `not-set`: 設定上は値があるが、今回の起動では適用されなかった

### 設定上書き例（local_ai_*）
以下はベンチ用の**一時上書き**です（永続化されません）。
> **Note**: 上書き値を変えた場合は `--restart-server` を付けて再起動し、設定が確実に反映された状態で計測します。
```bash
# threads / ctx / batch / ubatch の上書き
uv run python tools/bench_local_ai.py --mode warm \
  --threads 6 --ctx-size 8192 --batch-size 512 --ubatch-size 128 --json

# モデル・サーバディレクトリの指定
uv run python tools/bench_local_ai.py --mode warm \
  --model-path local_ai/models/HY-MT1.5-1.8B-Q4_K_M.gguf \
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

### CPU-only の速度チューニング（一般）
CPU-only では、`local_ai_ctx_size` が大きいほど KV キャッシュが増えて **遅くなりやすい**ため、まず `ctx` を下げて比較します。
（入力文が長すぎて失敗/劣化する場合は `ctx` を戻します）

```bash
# ctx 比較（同一条件で JSON を保存）
uv run python tools/bench_local_ai.py --mode warm --restart-server --warmup-runs 1 \
  --server-dir local_ai/llama_cpp/avx2 --device none --n-gpu-layers 0 --flash-attn auto \
  --batch-size 512 --ubatch-size 128 \
  --ctx-size 2048 --json --out .tmp/bench_cpu_ctx_2048.json

uv run python tools/bench_local_ai.py --mode warm --restart-server --warmup-runs 1 \
  --server-dir local_ai/llama_cpp/avx2 --device none --n-gpu-layers 0 --flash-attn auto \
  --batch-size 512 --ubatch-size 128 \
  --ctx-size 4096 --json --out .tmp/bench_cpu_ctx_4096.json
```

傾向（同一入力・同一モデル・同一環境で比較）:
- `ctx=2048` は `warmup_seconds` と `translation_seconds` が短くなりやすい
- `batch/ubatch` は大きすぎると遅くなることがあるため、まずは既定の `512/128` を基準に比較する

### llama-bench 比較スクリプト（tools/bench_llama_bench_compare.py）
CPU-only と Vulkan(iGPU) の `llama-bench` を**同一コマンドで2回実行**し、pp/tg の行と条件を JSON/Markdown で保存します。
CPU-only 側は `--device none -ngl 0` を固定で使い、Vulkan 側は `--device`/`--n-gpu-layers` の指定値を使います。

```bash
# JSON出力（既定: .tmp/llama_bench_compare.json）
uv run python tools/bench_llama_bench_compare.py --format json

# Markdown出力（共有用）
uv run python tools/bench_llama_bench_compare.py --format markdown \
  --out .tmp/llama_bench_compare.md
```

主要オプション:
- `--server-dir`（既定: `local_ai/llama_cpp`。配下の `avx2`/`vulkan` を自動選択）
- `--cpu-server-dir` / `--gpu-server-dir`（明示指定したい場合）
- `--model-path`（モデルのパス）
- `--pg`（`pp,tg` の指定。例: `2048,256`）
- `-r` / `--repeat`（繰り返し回数）
- `--device`（Vulkan 側のデバイス。例: `Vulkan0`）
- `--n-gpu-layers`（Vulkan 側の -ngl 値。例: `all`/`99`/`16`）
- `--extra-args`（`llama-bench` の追加引数。例: `-b 2048 -ub 512 -fa 0`）

```bash
uv run python tools/bench_llama_bench_compare.py \
  --server-dir local_ai/llama_cpp \
  --model-path local_ai/models/HY-MT1.5-1.8B-Q4_K_M.gguf \
  --pg 2048,256 -r 3 \
  --device Vulkan0 --n-gpu-layers all \
  --extra-args -b 2048 -ub 512 -fa 0
```

> **Note**: 出力の `pp_lines` / `tg_lines` に速度行が入ります。`returncode` が非0の場合は `stderr` と `command` を確認してください。

### iGPU(UMA) 実測チューニングのポイント（Ryzen 5 PRO 6650U）
UMA 環境では「全層オフロード（`-ngl 99`）」が最速とは限らず、メモリ帯域/共有メモリの影響で中間値の方が速いことがあります。
今回の実測（`ctx=4096`/`flash_attn=auto`）では、`-ngl 16` が CPU-only を上回る最速でした。`flash_attn=0` は遅くなるため非推奨です。

```bash
# Vulkan(iGPU) warm のチューニング例（再現用）
uv run python tools/bench_local_ai.py --mode warm --warmup-runs 1 --restart-server \
  --server-dir local_ai/llama_cpp/vulkan --device Vulkan0 --n-gpu-layers 16 \
  --ctx-size 4096 --flash-attn auto --json
```

永続的に固定したい場合は、`config/settings.template.json` の `local_ai_n_gpu_layers` と
`local_ai_ctx_size` を調整して反映します。

```powershell
# -ngl の探索（PowerShell例）
$values = 0, 8, 16, 24, 32, 40, 99
foreach ($v in $values) {
  uv run python tools/bench_local_ai.py --mode warm `
    --device Vulkan0 --n-gpu-layers $v --flash-attn auto --json
}
```

### KVキャッシュ型の比較（`ctx=4096` / `-ngl 16` / `flash_attn=auto`）
KVキャッシュの量子化は、速度よりもメモリ圧/安定性の調整として有効な場合があります。今回の実測では以下の傾向でした。
- Vulkan(iGPU): `f16` が最速で、`q8_0` / `q4_0` はわずかに遅い
- CPU-only: `q4_0` が最速で、`f16` / `q8_0` より短時間

> **Note**: 既定は `q8_0` です。`f16` 相当へ戻す場合は `local_ai_cache_type_k` / `local_ai_cache_type_v` を `null` にします。
> **Note**: 入力文と warm 条件を固定した 1 回計測のため、環境差/再現性の確認は複数回計測で行ってください。
> **Note**: メモリ不足が疑われる場合は、速度低下があっても `q8_0` を優先し、安定性を確認します。

### バッチ分割のデフォルト
- `local_ai_max_chars_per_batch`: 1000
- `local_ai_max_chars_per_batch_file`: 1000
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

## 参考（過去メモ）: AgentCPM-Explore / Shisa（Qwen3）推奨パラメータ
> **Note**: 現行の固定モデル（HY-MT）に対する推奨値ではありません。Qwen3 系を検証していた頃のメモとして残しています。

- Qwen3 は温度0の決定論的生成で繰り返しが起きやすいため、サンプリング（Temperature > 0）が推奨されていました。
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
- run-id:
- 実行日時:
- モード: warm | cold
- 入力: パス/文字数/参照ファイル有無
- 条件: モデル/サーバ/`local_ai_*`/実行環境
- コマンド:
- translation_seconds:
- total_seconds:
- prompt_chars:
- output_chars:
- local_ai_threads / ctx / batch / ubatch:
- 精度メモ: 簡易指標（後続タスクで追加）+ 人手確認の所見
- 備考:
