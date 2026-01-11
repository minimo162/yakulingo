# Local AI パフォーマンス計測手順

## 目的
ローカルAI翻訳の高速化を、再現可能な手順と数値で確認できる状態にする。

## 事前準備
- `local_ai/` に `llama.cpp` の `llama-server` とモデル（.gguf）があること
- 依存関係の準備（未実施なら）
  - `uv sync`
  - `uv sync --extra test`
  - `playwright install chromium`（E2E計測を使う場合）

## 計測の流れ（推奨）
1. CLIベンチで warm / cold をそれぞれ実行し、JSONを保存
2. E2E計測で「アプリ起動→翻訳完了」の時間を取得
3. 設定値と実行環境を揃え、改善前後で数値を比較する

比較時に揃える項目:
- モデル/サーバ、`local_ai_*` の設定値、入力文
- 実行環境（CPU/メモリ、電源設定、バックグラウンド負荷）

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

## アプリ起動を含む計測（E2E / Playwright）
```bash
uv run --extra test python tools/e2e_local_ai_speed.py
```
- JSON出力: `app_start_seconds`, `translation_seconds`, `total_seconds`, `elapsed_badge_seconds`
  - 追加情報: `translation_seconds_source`, `translation_elapsed_logged`, `app_log_path`
- 主要オプション: `--url`, `--timeout`, `--startup-timeout`, `--translation-timeout`, `--text`, `--headed`, `--out`
- ログ出力: `--app-log` でアプリのstdout/stderrを保存（未指定なら `.tmp/` に自動保存）
- 事前条件: `local_ai/` が利用可能、PlaywrightのChromiumが導入済み

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
