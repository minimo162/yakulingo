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
  - `local_ai_server_dir` に `.../vulkan` を直指定した場合も Vulkan として扱われる（`runtime.server_variant` で確認）
- 展開したフォルダでデバイスを確認
```powershell
.\llama-cli.exe --version
.\llama-cli.exe --list-devices
```
- `Vulkan0` などが表示されれば iGPU が認識されている（何も表示されない場合は Vulkan が利用できません）

## 計測の流れ（推奨）
1. CLIベンチで warm / cold をそれぞれ実行し、JSONを保存
2. E2E計測で「アプリ起動→翻訳完了」の時間を取得
3. 設定値と実行環境を揃え、改善前後で数値を比較する

比較時に揃える項目:
- モデル/サーバ、`local_ai_*` の設定値、入力文
- 実行環境（CPU/メモリ、電源設定、バックグラウンド負荷）
- **EN→JP（和訳）は訳文のみ**に変更済み。改善前後を比較する際は同じプロンプトバージョンを使い、出力文字数の差が `translation_seconds` に影響しないか確認する。
> **Note**: CPU-only と Vulkan(iGPU) 比較では、`local_ai_threads` / `local_ai_ctx_size` / `local_ai_batch_size` / `local_ai_ubatch_size` と入力文を固定し、`device` / `-ngl` / `-fa` など GPU 関連だけを変える。
> **Note**: `local_ai_*` は `user_settings.json` には保存されません。恒久的な変更は `config/settings.template.json` を更新し、ベンチの一時上書きは CLI で行います。
> **Note**: 既定値は `local_ai_device=none` / `local_ai_n_gpu_layers=0` / `local_ai_ctx_size=2048`。長文や安定性を優先したい場合は `local_ai_ctx_size=4096`（さらに必要なら `8192`）を指定します。Vulkan(iGPU) を使う場合は `llama-cli.exe --list-devices` で表示されるデバイス名（例: `Vulkan0`）と `local_ai_n_gpu_layers`（例: `99` / `16` / `auto` / `all`）を設定します。
> **Note**: プロキシ環境では `NO_PROXY=127.0.0.1,localhost` を自動補完し、ローカル API がプロキシ経由にならないようにします。
> **Note**: Vulkan 設定の反映確認は、ベンチ JSON の `runtime.server_variant` と `~/.yakulingo/logs/startup.log` の `Local AI offload flags` で確認できます。

## 7B向けチューニング優先順位（まず試す）
この項は 7B / Q4_K_M を前提にした **短時間で効きやすい順**のガイドです。iGPU/UMA 環境では特に「実測が前提」になります。

優先順位:
1. **Vulkan(iGPU) オフロード**: `local_ai_device` / `local_ai_n_gpu_layers`（`--device` / `-ngl`）を調整し、CPU-only と比較
2. **スレッド**: `local_ai_threads` / `local_ai_threads_batch`（`-t` / `-tb`）
3. **バッチ**: `local_ai_batch_size` / `local_ai_ubatch_size`（`-b` / `-ub`）
4. **ctx と KV キャッシュ**: `local_ai_ctx_size` / `local_ai_cache_type_k` / `local_ai_cache_type_v`（`-c` / `-ctk` / `-ctv`）
5. **Flash Attention**: `local_ai_flash_attn`（`-fa`）
6. **mmap / mlock**: `local_ai_mlock` / `local_ai_no_mmap`（`--mlock` / `--no-mmap`）

UMA(iGPU) 注意点:
- `-ngl` を上げるほど GPU 側のメモリ/帯域を消費するため、**最大値が最速とは限りません**。
- `-ngl 0`（CPU-only）と `-ngl` 中間値（例: 8/16/24/32/99）を同一条件で比較してください。

### まず試すレシピ（短時間）
1. CPU-only と Vulkan(iGPU) を同一入力で比較（`--device none` vs `--device <VULKAN_DEVICE>`）
2. Vulkan 側で `-ngl` を 0/8/16/24/32/99 などでスイープ
3. `-t` / `-tb` を物理コア数と論理コア数で比較（翻訳は `-tb` が効きやすい）
4. 入力が長い場合は `-b` / `-ub` を調整して prefill を短縮

> **Note**: ここでの「まず試す」は **実測に使える最低限の探索**です。結果が出たら `tools/bench_local_ai.py` の JSON を保存して比較してください。
> **Note**: ビルド要素（GGML_NATIVE/BLAS 等）は配布方針に依存します。自前ビルドで検証する場合に限り、別途メモとして扱ってください。

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
- `similarity` / `similarity_by_style`: `--gold` 指定時の簡易類似度（SequenceMatcher）
- `git.*`: リポジトリの commit / dirty（取得できる範囲）
- `runtime.*`: OS / CPUコア数（physical/logical）
- `versions.*`: `llama-server` / `llama-cli` の `--version`（取得できる範囲）

### JSON 出力
```bash
# stdout にJSON（既存出力は維持され、最後にJSONが出力される）
uv run python tools/bench_local_ai.py --mode warm --json

# JSONをファイルに保存
uv run python tools/bench_local_ai.py --mode warm --out .tmp/bench_local_ai.json

# ケース運用（保存先を /work/<case-id>/.tmp/ に統一）
uv run python tools/bench_local_ai.py --mode warm --out /work/<case-id>/.tmp/bench_local_ai.json
```

### 追加オプション（タグ/出力保存/簡易精度）
- `--tag`: JSON出力に任意ラベルを追加する
- `--save-output`: 翻訳出力を保存する（`--compare` 時は `[style]` 区切りのテキスト）
- `--gold`: 参照訳テキストを指定し、簡易類似度をJSONに追加する

```bash
uv run python tools/bench_local_ai.py --mode warm \
  --tag ctx2048 \
  --gold /work/<case-id>/.tmp/gold.txt \
  --save-output /work/<case-id>/.tmp/output.txt \
  --json --out /work/<case-id>/.tmp/bench_local_ai.json
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
  --model-path local_ai/models/HY-MT1.5-7B-Q4_K_M.gguf \
  --server-dir local_ai/llama_cpp --json

# max_tokens を無効化（0以下でNone扱い）
uv run python tools/bench_local_ai.py --mode warm --max-tokens 0 --json

# Vulkan(iGPU) 用の一時上書き
uv run python tools/bench_local_ai.py --mode warm \
  --device <VULKAN_DEVICE> --n-gpu-layers 99 --flash-attn auto --no-warmup --json

# threads-batch / mlock / no-mmap の上書き（効果比較）
uv run python tools/bench_local_ai.py --mode warm --restart-server \
  --threads 6 --threads-batch 12 \
  --mlock --no-mmap --json
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

# Vulkan(iGPU) warm/cold（vulkan バイナリ + device 指定）
uv run python tools/bench_local_ai.py --mode warm --restart-server \
  --server-dir local_ai/llama_cpp/vulkan --device <VULKAN_DEVICE> --n-gpu-layers 99 --flash-attn auto \
  --json --out .tmp/bench_vk_warm.json

uv run python tools/bench_local_ai.py --mode cold --restart-server \
  --server-dir local_ai/llama_cpp/vulkan --device <VULKAN_DEVICE> --n-gpu-layers 99 --flash-attn auto \
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
- `--device`（Vulkan 側のデバイス。例: `Vulkan0`。`--list-devices` を参照）
- `--n-gpu-layers`（Vulkan 側の -ngl 値。例: `all`/`99`/`16`）
- `--extra-args`（`llama-bench` の追加引数。例: `-b 2048 -ub 512 -fa 0`）

```bash
uv run python tools/bench_llama_bench_compare.py \
  --server-dir local_ai/llama_cpp \
  --model-path local_ai/models/HY-MT1.5-7B-Q4_K_M.gguf \
  --pg 2048,256 -r 3 \
  --device <VULKAN_DEVICE> --n-gpu-layers all \
  --extra-args -b 2048 -ub 512 -fa 0
```

> **Note**: 出力の `pp_lines` / `tg_lines` に速度行が入ります。`returncode` が非0の場合は `stderr` と `command` を確認してください。

### 7B向け短時間スイープ（tools/bench_local_ai_sweep_7b.py）
`tools/bench_local_ai.py` を **複数条件で連続実行**し、JSON とサマリ（Markdown）をまとめて出力します。
結果は環境依存のため、**ケース運用では `/work/<case-id>/.tmp/` 配下へ保存し、リポジトリにはコミットしません**。

```bash
uv run python tools/bench_local_ai_sweep_7b.py \
  --preset quick \
  --out-dir /work/<case-id>/.tmp/sweep-7b-YYYYmmdd-HHMMSS
```

プリセットの使い分け:
- `quick`: CPU-only と Vulkan(iGPU) の最小比較（`cpu_base` / `vk_ngl_full` / `vk_ngl_main` + 可能なら `*_tb_logical`）。まず動作確認と大枠の速度差を見る。
- `cpu`: CPU-only の短時間探索（`threads` / `threads_batch` / `ctx` / `batch` / `ubatch`）。入力は短め（`tools/bench_local_ai_input_short.txt`）で warm 中心。
- `vulkan`: Vulkan(iGPU) の短時間探索（`device` / `-ngl` / `flash_attn` / `cache_type` / `vk_*`）。入力は短め（`tools/bench_local_ai_input_short.txt`）で warm 中心。
- `full`: `quick` に加えて `batch/ubatch`・`ctx`・`cache-type`・`flash-attn`・`mlock/no-mmap` など探索系を含めた総当たりに近い比較。

> **Note**: `cpu` プリセットでは、`cpu_b256_ub64`（`-b 256 -ub 64`）が `cpu_base`（512/128）より僅差で速く出る場合があります。差は小さいため、まずは `cpu_base` を基準に実測で判断してください。

失敗時の確認ポイント（最小）:
- 各 run の `*.json` の `runtime.server_variant` で CPU/Vulkan の実際の起動状態を確認する
- `~/.yakulingo/logs/startup.log` の `Local AI offload flags` で `--device` / `-ngl` が反映されたか確認する
- `*.log.txt` と `local_ai_server.log`（生成されていれば）でエラー詳細を確認する
- `llama-cli.exe --list-devices` が空の場合、`--device Vulkan0` 等が無効になり、Vulkan の実行が失敗する（CPU-onlyで運用）

> **Note**: Vulkan(iGPU) で `ErrorOutOfDeviceMemory` が出る場合は、`--vk-force-max-allocation-size` を併用します（例: `268435456`=256MiB）。
> **Note**: 中断時に再実行する場合は `--resume`、各 run の上限時間は `--run-timeout-seconds` で指定できます。

出力:
- `summary.md`（比較用の表）
- `summary.json`（メタ情報 + 行データ）
- `*.json`（各 run の `tools/bench_local_ai.py` JSON）
- `*.log.txt`（各 run の stdout/stderr）

### iGPU(UMA) 実測チューニングのポイント（Ryzen 5 PRO 6650U）
UMA 環境では「全層オフロード（`-ngl 99`）」が最速とは限らず、メモリ帯域/共有メモリの影響で中間値の方が速いことがあります。
今回の実測（`ctx=4096`/`flash_attn=auto`）では、`-ngl 16` が CPU-only を上回る最速でした。`flash_attn=0` は遅くなるため非推奨です。

```bash
# Vulkan(iGPU) warm のチューニング例（再現用）
uv run python tools/bench_local_ai.py --mode warm --warmup-runs 1 --restart-server \
  --server-dir local_ai/llama_cpp/vulkan --device <VULKAN_DEVICE> --n-gpu-layers 16 \
  --ctx-size 4096 --flash-attn auto --json
```

永続的に固定したい場合は、`config/settings.template.json` の `local_ai_n_gpu_layers` と
`local_ai_ctx_size` を調整して反映します。

```powershell
# -ngl の探索（PowerShell例）
$values = 0, 8, 16, 24, 32, 40, 99
foreach ($v in $values) {
  uv run python tools/bench_local_ai.py --mode warm `
    --device <VULKAN_DEVICE> --n-gpu-layers $v --flash-attn auto --json
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
- `local_ai_max_chars_per_batch`: 1000（既定の分割上限）
- `local_ai_max_chars_per_batch_file`: 1000（ファイル翻訳の分割上限。`*_file` が優先される）
- 値を上げるとバッチ数は減るが、プロンプトが長すぎる場合は自動分割（`LOCAL_PROMPT_TOO_LONG`）にフォールバックする

## 速度に効く主な設定
- `local_ai_device` / `local_ai_n_gpu_layers`: Vulkan(iGPU) オフロード設定（`--device` / `-ngl`）
- `local_ai_threads`: CPUスレッド数（`0` は自動）
- `local_ai_threads_batch`: prefill スレッド数（`null` は未指定、`0` は自動）
- `local_ai_batch_size` / `local_ai_ubatch_size`: llama.cpp のバッチ設定
- `local_ai_ctx_size`: コンテキスト長（長すぎると遅くなる）
- `local_ai_cache_type_k` / `local_ai_cache_type_v`: KVキャッシュ型（`null` は既定の `f16` 相当）
- `local_ai_flash_attn`: Flash Attention（`auto`/`0`/`1`）
- `local_ai_mlock` / `local_ai_no_mmap`: メモリ安定化（環境により失敗する場合はオフ）
- `local_ai_max_chars_per_batch` / `local_ai_max_chars_per_batch_file`: 翻訳分割の文字数上限
- `local_ai_max_tokens`: 応答上限（0以下でNone扱い、推論時間に影響）

## YakuLingo 設定キー ↔ llama.cpp フラグ対応
以下は `llama-server` 実行時に付与される代表的な対応表です（`--help` に存在するフラグのみ付与）。

| 設定キー | llama.cpp フラグ | 反映条件/備考 |
| --- | --- | --- |
| `local_ai_device` | `--device` | `none` でCPU-only。Vulkanバイナリ時に適用 |
| `local_ai_n_gpu_layers` | `-ngl` / `--n-gpu-layers` | `0` でCPU-only。Vulkanバイナリ時に適用 |
| `local_ai_threads` | `-t` / `--threads` | `0` 以下は自動（物理コア数を優先） |
| `local_ai_threads_batch` | `-tb` / `--threads-batch` | `null` は未指定、`0` は自動（`threads` と同値） |
| `local_ai_batch_size` | `-b` / `--batch-size` | 正の値のみ付与 |
| `local_ai_ubatch_size` | `-ub` / `--ubatch-size` | 正の値のみ付与 |
| `local_ai_ctx_size` | `-c` / `--ctx-size` | 正の値のみ付与 |
| `local_ai_cache_type_k` | `-ctk` / `--cache-type-k` | Vulkan時のみ。`null` は未指定 |
| `local_ai_cache_type_v` | `-ctv` / `--cache-type-v` | Vulkan時のみ。`null` は未指定 |
| `local_ai_flash_attn` | `-fa` / `--flash-attn` | Vulkan時のみ。`auto` は未指定、`0/1` を付与 |
| `local_ai_no_warmup` | `--no-warmup` | Vulkan時のみ |
| `local_ai_mlock` | `--mlock` | 対応時のみ付与 |
| `local_ai_no_mmap` | `--no-mmap` | 対応時のみ付与 |
| `local_ai_max_tokens` | `--n-predict` / `-n` | 0以下は未指定 |

> **Note**: `--no-repack` は既定最適化を無効化するため、通常は使いません。
> **Note**: 非対応フラグは `unsupported` としてログに出力されます。

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
  - `local_ai_top_p = 0.6`
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

## パラメータスイープ結果（case: yakulingo-benchmark-translation-speed-accuracy-20260114-073842）

- 実行条件: warm / `--restart-server` / 入力 `tools/bench_local_ai_input.txt`（410 chars）/ style=concise / Vulkan
- 出力保存先: `/work/yakulingo-benchmark-translation-speed-accuracy-20260114-073842/.tmp/bench_*.json`
- 簡易類似度: baseline 出力（`output_base.txt`）を `--gold` として比較

| tag | ctx | max_chars | max_tokens | translation_seconds | output_chars | similarity(→base) |
| --- | --- | --- | --- | --- | --- | --- |
| base | 2048 | 1000 | 1024 | 3.26 | 389 | - |
| ctx4096 | 4096 | 1000 | 1024 | 10.40 | 1549 | 0.298 |
| chars600 | 2048 | 600 | 1024 | 10.92 | 1588 | 0.357 |
| tok512 | 2048 | 1000 | 512 | 10.08 | 1478 | 0.315 |
| tok256 | 2048 | 1000 | 256 | 8.96 | 1344 | 0.398 |
| tok0 | 2048 | 1000 | 1024 | 10.05 | 1558 | 0.387 |

気づき:
- 出力文字数の増減が大きく、`translation_seconds` との単純比較は難しい（base は短文出力）
- `ctx=4096` は時間増・出力増の傾向。`max_tokens=256` は最短で、相対類似度は最も高い
- `--max-tokens 0` は有効値に反映されず、実質 `1024` のまま（tok0 は無効扱い）

既定値への反映:
- 出力長の振れ幅が大きく、速度/精度の改善が明確とは言い切れないため既定値は据え置き

E2E 指標（1回）:
- `app_start_seconds`: 10.37
- `translation_seconds`: 14.78（log: 14.17）
- `total_seconds`: 36.90
- JSON: `/work/yakulingo-benchmark-translation-speed-accuracy-20260114-073842/.tmp/e2e_local_ai_speed.json`

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
