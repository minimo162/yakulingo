# Local AI ベンチマーク（SSOT）

ローカルAI（llama.cpp `llama-server`）の性能計測と再現手順は、`docs/PERFORMANCE_LOCAL_AI.md` を単一の参照元（SSOT）とします。
このファイルは「最短で走らせるための入口」として残しています。

## 依存関係

```bash
uv sync --extra test
```

## クイック実行

### 1) PromptBuilder ミニベンチ（サーバ不要）

```bash
uv run python tools/bench_local_prompt_builder.py --runs 30 --json --out .tmp/bench_prompt_builder.json
```

### 2) Local AI ベンチ（warm / cold）

```bash
uv run python tools/bench_local_ai.py --mode warm --json --out .tmp/bench_local_ai_warm.json
uv run python tools/bench_local_ai.py --mode cold --json --out .tmp/bench_local_ai_cold.json
```

### 3) E2E（アプリ起動→翻訳完了）

```bash
uv run --extra test python tools/e2e_local_ai_speed.py
```

## 詳細手順（SSOT）
- CLIベンチ（オプション/JSON/比較）: `docs/PERFORMANCE_LOCAL_AI.md`
- スイープ（複数条件の連続実行）: `docs/PERFORMANCE_LOCAL_AI.md`（`tools/bench_local_ai_sweep_7b.py`）
- 記録テンプレ/環境変数/注意点: `docs/PERFORMANCE_LOCAL_AI.md`

