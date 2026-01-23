# Local AI パフォーマンス計測手順

## 目的
ローカルAI翻訳の高速化を、再現可能な手順と数値で確認できる状態にする。

## 事前準備
- `local_ai/` に `llama.cpp` の `llama-server` とモデル（.gguf）があること
- 依存関係の準備（未実施なら）
  - `uv sync`
  - `uv sync --extra test`
  - `playwright install chromium`（E2E計測を使う場合）

## 計測ログの有効化（任意）
追加の詳細計測（プロンプト生成・TTFT・リトライ集計）を出したい場合は、環境変数 `YAKULINGO_LOCAL_AI_TIMING=1` を設定して起動する。

- 出力先: `~/.yakulingo/logs/startup.log`（DEBUG）
- 追加されるログ例:
  - `[TIMING] LocalPromptBuilder.build_reference_embed ...`
  - `[TIMING] LocalPromptBuilder.build_batch ...`
  - `[TIMING] LocalPromptBuilder.build_text_to_en_single ...`
  - `[TIMING] LocalPromptBuilder.build_text_to_jp ...`
  - `[TIMING] BatchTranslator.prompt_build ...`
  - `[TIMING] BatchTranslator.retries ...`
  - `[TIMING] LocalAI ttft_streaming ...`

## プロンプト生成ミニベンチ（サーバ不要）
ローカルAIサーバを起動せず、プロンプト生成（特に glossary マッチング）のコストだけを測る。

```powershell
uv run python tools/bench_local_prompt_builder.py --glossary-rows 20000 --input-chars 800 --items 12 --runs 50
```

## プロンプト長（prompt_chars）比較（サーバ不要）
プロンプト短縮の効果（prompt_chars の減少）を、サーバ無しで再現可能に確認する。

```powershell
# 現在のブランチ/コミットで計測（サンプル入力で build_* の文字数を出力）
uv run python tools/audit_local_prompt_lengths.py
```

このケース（`yakulingo-local-ai-prompt-rules-compress-20260121-160322`）の比較例:
- baseline: `58f5e90b`（task-00）
- after: `722e5115`（task-04）

結果（Built prompts / no reference files）:
- `build_text_to_en_single`: 1031 → 563
- `build_text_to_jp`: 556 → 258
- `build_batch (to_en)`: 1849 → 1602

> **Note**: task-03 で「入力に応じた翻訳ルール注入」を導入しているため、短文では特に `translation_rules` が短くなります（数値/単位ルール等は必要時のみ）。

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
> **Note**: 既定値は `local_ai_device=auto` / `local_ai_n_gpu_layers=auto` / `local_ai_ctx_size=2048` / `local_ai_no_warmup=true`。Vulkan 環境ではオフロードを試行し、失敗時は安全に CPU-only にフォールバックします（強制的に CPU-only に戻す場合は `local_ai_device=none` または `local_ai_n_gpu_layers=0` を指定）。
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

### スモーク（最小）
```bash
# まず動くか（JSON不要の最小スモーク）
uv run python tools/bench_local_ai.py --mode warm

# 互換: --compare（TranslationService 経由。現行は英訳 minimal-only / 追加呼び出しなし）
uv run python tools/bench_local_ai.py --mode warm --compare --json

# 同梱用語集を添付（reference embed の確認）
uv run python tools/bench_local_ai.py --mode warm --with-glossary
```

### 記録する指標
- `translation_seconds`: 推論にかかった時間
- `total_seconds`: プロンプト構築 + 推論（single のみ）
- `prompt_chars`: プロンプト文字数（single のみ）
- `prompt_build_seconds`: プロンプト構築時間（single のみ）
- `warmup_seconds[]`: ウォームアップ実行時間
- `translate_single_calls_translation`: 本計測での推論呼び出し回数（`1` が理想）
- `output_chars`: 出力文字数
- `options`: `--compare` 時の件数（現行は `1` / `minimal` のみ）
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
- `--save-output`: 翻訳出力を保存する（`--compare` 時は `[minimal]` 見出し付きのテキスト）
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
  --model-path local_ai/models/DASD-4B-Thinking.IQ4_XS.gguf \
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
  --model-path local_ai/models/DASD-4B-Thinking.IQ4_XS.gguf \
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
- `local_ai_max_chars_per_batch_file`: 1000（互換キー。現行のファイル翻訳は一単位翻訳のため未使用）
- 値を上げるとバッチ数は減るが、プロンプトが長すぎる場合は自動分割（`LOCAL_PROMPT_TOO_LONG`）にフォールバックする

## 速度に効く主な設定
- `local_ai_device` / `local_ai_n_gpu_layers`: Vulkan(iGPU) オフロード設定（`--device` / `-ngl`）
- `local_ai_threads`: CPUスレッド数（`0` は自動）
- `local_ai_threads_batch`: prefill スレッド数（既定: `0`=自動。`null` で未指定。CPU使用率が上がる可能性あり）
- `local_ai_batch_size` / `local_ai_ubatch_size`: llama.cpp のバッチ設定
- `local_ai_ctx_size`: コンテキスト長（長すぎると遅くなる）
- `local_ai_cache_type_k` / `local_ai_cache_type_v`: KVキャッシュ型（`null` は既定の `f16` 相当）
- `local_ai_flash_attn`: Flash Attention（`auto`/`0`/`1`）
- `local_ai_mlock` / `local_ai_no_mmap`: メモリ安定化（環境により失敗する場合はオフ）
- `local_ai_max_chars_per_batch` / `local_ai_max_chars_per_batch_file`: 翻訳分割の文字数上限（`*_file` は互換キー。現行のファイル翻訳は未使用）
- `local_ai_max_tokens`: 応答上限（0以下でNone扱い、推論時間に影響）

## YakuLingo 設定キー ↔ llama.cpp フラグ対応
以下は `llama-server` 実行時に付与される代表的な対応表です（`--help` に存在するフラグのみ付与）。

| 設定キー | llama.cpp フラグ | 反映条件/備考 |
| --- | --- | --- |
| `local_ai_device` | `--device` | `none` でCPU-only。Vulkanバイナリ時に適用 |
| `local_ai_n_gpu_layers` | `-ngl` / `--n-gpu-layers` | `0` でCPU-only。Vulkanバイナリ時に適用 |
| `local_ai_threads` | `-t` / `--threads` | `0` 以下は自動（物理コア数を優先） |
| `local_ai_threads_batch` | `-tb` / `--threads-batch` | 既定は `0`（自動=`threads` と同値）。`null` は未指定 |
| `local_ai_batch_size` | `-b` / `--batch-size` | 正の値のみ付与 |
| `local_ai_ubatch_size` | `-ub` / `--ubatch-size` | 正の値のみ付与 |
| `local_ai_ctx_size` | `-c` / `--ctx-size` | 正の値のみ付与 |
| `local_ai_cache_type_k` | `-ctk` / `--cache-type-k` | Vulkan時のみ。`null` は未指定 |
| `local_ai_cache_type_v` | `-ctv` / `--cache-type-v` | Vulkan時のみ。`null` は未指定 |
| `local_ai_flash_attn` | `-fa` / `--flash-attn` | Vulkan時のみ。`auto` は未指定、`0/1` を付与 |
| `local_ai_no_warmup` | `--no-warmup` | 対応時のみ（CPU/Vulkan）。`true` のとき付与 |
| `local_ai_mlock` | `--mlock` | 対応時のみ付与 |
| `local_ai_no_mmap` | `--no-mmap` | 対応時のみ付与 |
| `local_ai_max_tokens` | `--n-predict` / `-n` | 0以下は未指定 |

> **Note**: `--no-repack` は既定最適化を無効化するため、通常は使いません。
> **Note**: 非対応フラグは `unsupported` としてログに出力されます。

### task-05: `local_ai_no_warmup` を既定で有効化
YakuLingo は翻訳実行時に `llama-server` を起動するため、サーバの起動時 warmup がユーザー待ち時間に含まれます。
`local_ai_no_warmup=true`（`--no-warmup`）で、初回の待ち時間を短縮できます。

計測（CPU-only / `avx2` / 入力 `tools/bench_local_ai_input_short.txt` 217 chars / `temperature=0` / `ctx=2048` / `b=512` / `ub=128`）:
- cold（warmup 有効）: `translation_seconds=53.37s`
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/bench_task05_cold_cpu_warmup_on.json`
- cold（`--no-warmup`）: `translation_seconds=51.22s`（約 -4%）
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/bench_task05_cold_cpu_no_warmup.json`

再現コマンド（cold）:
```bash
uv run python tools/bench_local_ai.py --mode cold --restart-server \
  --server-dir local_ai/llama_cpp/avx2 --device none --n-gpu-layers 0 \
  --ctx-size 2048 --batch-size 512 --ubatch-size 128 --temperature 0 \
  --out /work/<case-id>/.tmp/cold_warmup_on.json

uv run python tools/bench_local_ai.py --mode cold --restart-server \
  --server-dir local_ai/llama_cpp/avx2 --device none --n-gpu-layers 0 \
  --ctx-size 2048 --batch-size 512 --ubatch-size 128 --temperature 0 \
  --no-warmup --out /work/<case-id>/.tmp/cold_no_warmup.json
```

### task-08: `local_ai_threads_batch` 既定値（`0`=auto）を有効化
`threads-batch` は prefill（入力処理）を狙う設定で、翻訳のように入力が長い場合に効きやすいことがあります。

> **Note**: ここは過去記録（当時: style=concise）。現行の英訳は minimal-only です。

計測（warm / `--restart-server` / 入力 `tools/bench_local_ai_input.txt` 410 chars / style=concise）:
- before（`local_ai_threads_batch=null`）: warmup=151.32s / translation=54.88s / output=1267 chars
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/bench_task08_before_warm_retry.json`
- after（`local_ai_threads_batch=0`）: warmup=171.75s / translation=59.78s / output=1316 chars
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/bench_task08_after_warm.json`

> **Note**: `output_chars=2` の計測は不正（推論失敗/早期終了の可能性）として比較から除外しました。

### task-09: tg（生成）改善候補（flash-attn）を少数だけ実測
task-06 の所見（pp は速いが tg が同等）を受け、tg に効く可能性がある `flash-attn` を `llama-bench` で比較しました。

計測（`tools/bench_llama_bench_compare.py` / `pg=512,128` / `r=3`）:
- baseline（`-fa` 未指定=既定）: GPU `tg128`=5.62 t/s / `pp512`=65.18 t/s
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/llama_bench_compare_tg_baseline.json`
- `flash-attn=1`: GPU `tg128`=5.85 t/s（+約4%）/ `pp512`=67.32 t/s
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/llama_bench_compare_tg_fa1.json`

> **Note**: `pg=2048,256` は Vulkan(iGPU) で `ErrorOutOfDeviceMemory` が出る場合があり、比較は `pg=512,128` に縮小しました。
> **Note**: 効果は小さく、`pp512+tg128` では差が逆転する場合があるため、アプリ側の実測（CLI/E2E）で確認してください。

## Vulkan(iGPU) トラブルシュート
- `ErrorOutOfDeviceMemory` / `Requested buffer size exceeds ...`
  - `local_ai_vk_force_max_allocation_size` を設定（例: `536870912`=512MiB）
  - 併せて `local_ai_n_gpu_layers` / `local_ai_ctx_size` を下げる
- 初期化や warmup で不具合が出る
  - `local_ai_no_warmup = true` を試す（CLIなら `--no-warmup`）
- 出力が文字化け/意味不明になる
  - `local_ai_vk_disable_f16 = true` を試す（CLIなら `--vk-disable-f16`）

## 参考（過去メモ）: AgentCPM-Explore / Shisa（Qwen3）推奨パラメータ
> **Note**: 現行の既定モデル（DASD-4B-Thinking）に対する推奨値ではありません。Qwen3 系を検証していた頃のメモとして残しています。

- Qwen3 は温度0の決定論的生成で繰り返しが起きやすいため、サンプリング（Temperature > 0）が推奨されていました。
- 推奨値（参考: 検証当時）:
  - `local_ai_temperature = 0.7`
  - `local_ai_top_p = 0.6`
  - `local_ai_top_k = 20`
  - `local_ai_min_p = 0.01`（0.0 で無効化したい場合は `0.0` を指定）
  - `local_ai_repeat_penalty = 1.05`

## アプリ起動を含む計測（E2E / Playwright）
```bash
uv run --extra test python tools/e2e_local_ai_speed.py
```
- JSON出力: `app_start_seconds`, `page_ready_seconds`, `local_ai_ready_seconds`, `ttft_seconds`, `ttlc_seconds`, `total_seconds`, `elapsed_badge_seconds`
  - `translation_seconds` は後方互換のため `ttlc_seconds` と同値
  - 追加情報: `translation_seconds_source`, `translation_elapsed_logged`, `translation_prep_seconds_logged`, `local_ai_warmup_seconds_logged`, `streaming_preview_disabled`, `app_log_path`
- 主要オプション: `--url`, `--timeout`, `--startup-timeout`, `--translation-timeout`, `--text`, `--headed`, `--out`, `--disable-streaming-preview`
- ストリーミング表示を無効化: `--disable-streaming-preview`（ローカルAIの途中表示更新を抑止）
- ローカルAIの既定はストリーミング表示ON（無効化する場合は `YAKULINGO_DISABLE_LOCAL_STREAMING_PREVIEW=1`）
- ログ出力: `--app-log` でアプリのstdout/stderrを保存（未指定なら `.tmp/` に自動保存）
- 事前条件: `local_ai/` が利用可能、PlaywrightのChromiumが導入済み
- プロキシ環境: `tools/e2e_local_ai_speed.py` のHTTP ready判定は `127.0.0.1` / `localhost` をプロキシ無視でアクセスする（外部URL指定時は除く）
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

## ケース記録（case: yakulingo-llama-speedup-20260115）

- 環境: Windows / Ryzen 5 PRO 6650U（6C/12T）/ iGPU Radeon 660M（UMA）/ llama.cpp Vulkan 7738
- 条件: warm / `--restart-server` / 入力 `tools/bench_local_ai_input.txt`（410 chars）/ style=concise / glossary=off

> **Note**: ここは過去記録（当時: style=concise）。現行の英訳は minimal-only です。

### CLIベンチ（warm）
- before（CPU-only）: translation_seconds 50.93 / warmup_seconds 146.43 / output_chars 1305
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/bench_cpu_warm.json`
  - 設定: device=none, n_gpu_layers=0, server_variant=vulkan
- after（defaults auto/auto）: translation_seconds 56.36 / warmup_seconds 83.62 / output_chars 1333
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/bench_after_warm.json`
  - 設定: device=auto, n_gpu_layers=auto, server_variant=vulkan

### E2E（Playwright）
- before: stage=wait_http / exit_code=11 / total_seconds 0.60
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/e2e_before.json`
- after: stage=wait_http / exit_code=0 / total_seconds 123.32（`--disable-streaming-preview`）
  - JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/e2e_after.json`
  - app log: `/work/yakulingo-llama-speedup-20260115/.tmp/e2e_after_app.log`

## パラメータスイープ結果（case: yakulingo-llama-speedup-20260115）

- 実行条件: warm / `--restart-server` / 入力 `tools/bench_local_ai_input.txt`（410 chars）/ style=concise / llama.cpp Vulkan（b7738）
- 出力保存先: `/work/yakulingo-llama-speedup-20260115/.tmp/bench_*.json`
- デバイス: `Vulkan0`（AMD Radeon(TM) Graphics, UMA）

> **Note**: ここは過去記録（当時: style=concise）。現行の英訳は minimal-only です。

| kind | device | -ngl | warmup_seconds | translation_seconds | output_chars | notes |
| --- | --- | --- | --- | --- | --- | --- |
| cpu-only | none | 0 | 146.43 | 50.93 | 1305 | - |
| vk | Vulkan0 | 8 | 42.29 | 107.07 | 1298 | - |
| vk | Vulkan0 | 16 | 137.22 | 101.57 | 1334 | - |
| vk | Vulkan0 | 24 | 41.56 | 95.08 | 1308 | - |
| vk | Vulkan0 | 32 | 94.92 | 0.57 | 2 | 出力が極端に短く、計測として不正（要調査） |
| vk | Vulkan0 | 99 | 85.93 | 0.50 | 2 | 出力が極端に短く、計測として不正（要調査） |

気づき:
- 今回の条件では、Vulkan(iGPU) オフロードは CPU-only より遅かった（`-ngl 0` が最速）。
- `-ngl 32/99` は出力が 2 chars となり、推論失敗/早期終了の可能性がある。

E2E:
- `tools/e2e_local_ai_speed.py` は stage=wait_http / exit code=11 で失敗（ログが空のため要調査）。
- JSON: `/work/yakulingo-llama-speedup-20260115/.tmp/e2e_before.json`

## pp/tg 切り分け結果（case: yakulingo-llama-speedup-20260115）

- 出力保存先: `/work/yakulingo-llama-speedup-20260115/.tmp/llama_bench_compare_after.json`
- 実行条件: `llama-bench` / `-pg 2048,256` / `-r 3` / model（当時のモデル）

| backend | ngl | pp512 (t/s) | tg128 (t/s) | pp2048+tg256 (t/s) |
| --- | ---: | ---: | ---: | ---: |
| CPU | 0 | 20.47 ± 0.92 | 5.76 ± 0.33 | 15.70 ± 0.31 |
| Vulkan(iGPU) | 99（default） | 62.67 ± 4.66 | 5.69 ± 0.21 | 27.97 ± 0.35 |

所見:
- pp は Vulkan が大幅に高速だが、tg はほぼ同等 → この環境では tg がボトルネックになりやすい
- `--n-gpu-layers auto/all` は `llama-bench` 側が非対応のため、比較ツールでは `-ngl` 未指定（既定=99）として実行

## ケース記録（case: yakulingo-local-ai-streaming-speedup-20260119-063004）

- 環境: Windows-10 / llama.cpp avx2 7718（db79dc06b）/ model=translategemma-4b-it.IQ4_XS.gguf（当時。現行既定: DASD-4B-Thinking.IQ4_XS.gguf）
- 条件: style=minimal / glossary=off / server_variant=avx2（CPU-only）

### CLIベンチ（tools/bench_local_ai.py）
- warm（short: 217 chars）: warmup_seconds 9.83 / translation_seconds 8.61 / output_chars 747
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/bench_warm_short.json`
- warm（medium: 410 chars）: warmup_seconds 36.07 / translation_seconds 18.31 / output_chars 1341
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/bench_warm_medium.json`
- cold（short: 217 chars）: translation_seconds 57.58 / total_seconds 57.66 / output_chars 785
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/bench_cold_short.json`

### E2E（tools/e2e_local_ai_speed.py）
- run1: `ttft_seconds=36.71` / `ttlc_seconds=56.66`
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/e2e_task06_ttft_enabled.json`
  - app log: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/e2e_task06_ttft_enabled_app.log`
- run2: `ttft_seconds=1.03` / `ttlc_seconds=21.94`
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/e2e_task06_ttft_enabled_run2.json`
  - app log: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/e2e_task06_ttft_enabled_run2_app.log`
- 参考（旧）: stage=run_e2e（Translate button did not become enabled within 10s）
  - JSON: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/e2e_disabled.json`（`--disable-streaming-preview`）
  - app log: `/work/yakulingo-local-ai-streaming-speedup-20260119-063004/.tmp/e2e_disabled_app.log`

### 成功基準（このケースの最低ライン）
- 体感（TTFT）: 「翻訳」クリック→プレビュー初回更新を **1回目/2回目**で記録し、改善を確認できること（E2E出力: `ttft_seconds`）
- 実時間（TTLC）: 上記 input（short/medium, warm）の `translation_seconds` を **悪化させない（+5%以内）**
- 体感の既定: ローカルAI使用時にストリーミングプレビューが見えること（既定ON化は task-01）

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
