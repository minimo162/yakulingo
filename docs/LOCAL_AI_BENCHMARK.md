# ローカルAI速度計測（ベースライン）

ローカルAI（llama.cpp `llama-server`）経路のボトルネックを定量化するための手順です。

## 前提

- リポジトリルートで実行する
- 依存関係を揃える: `uv sync --extra test`

## 1) プロンプト生成（サーバ不要）

`LocalPromptBuilder` のホットパス（用語集/参照ファイル埋め込み）を計測します。

```bash
uv run python tools/bench_local_prompt_builder.py --runs 30
uv run python tools/bench_local_prompt_builder.py --runs 30 --json --out .tmp/bench_prompt.json
```

観点:
- `build_reference_embed (cold first)` が大きい場合は「初回のみ」のコスト（キャッシュ/読み込み）が支配的
- `build_batch`/`build_text_to_en_3style` が大きい場合は「毎回」のCPUコストが支配的

## 2) 翻訳（llama-server 経由）

### warm / cold

```bash
uv run python tools/bench_local_ai.py --mode warm --json --out .tmp/bench_local_ai_warm.json
uv run python tools/bench_local_ai.py --mode cold --json --out .tmp/bench_local_ai_cold.json
```

観点:
- `prompt_build_seconds` は通常小さい（≒0）ので、主に `translation_seconds` が支配的
- cold が遅い場合は `ensure_ready`（起動/再利用）や初回ロードが支配的

### GPU が不安定な場合（CPU-only で安定化）

Vulkan 等で `ConnectionResetError`/OOM が出る場合は、まず CPU-only で安定化した上で比較します。

```bash
uv run python tools/bench_local_ai.py --mode warm --restart-server --device none --json
uv run python tools/bench_local_ai.py --mode cold --device none --json
```

## 3) 条件を揃えるためのポイント

- 入力は `tools/bench_local_ai_input.txt` を固定（または `--input` で同一ファイルを指定）
- モデル/サーバ設定の比較は `--out` のJSONを保存して差分を見る
- 参照ファイル込みの比較は `--with-glossary`（同梱 `glossary.csv`）や `--reference` を利用

