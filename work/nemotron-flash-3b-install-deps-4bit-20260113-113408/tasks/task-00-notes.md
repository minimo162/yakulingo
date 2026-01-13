# task-00 設計メモ（Nemotron切替）

## 現状導線（最短経路）
- 依存導入: `packaging/install_deps.bat`
  - Step 7 でローカルAI導入（llama.cpp + optional model）
  - Step 7 は `packaging/install_local_ai.ps1` を呼び出す
- ローカルAI導入: `packaging/install_local_ai.ps1`
  - `local_ai/llama_cpp/(vulkan|avx2)/llama-server.exe` を配置
  - `local_ai/models/*.gguf` を配置（または HF→GGUF→4bit 生成）
  - `local_ai/manifest.json` を生成（llama.cpp と model の追跡情報）
- アプリ起動: `yakulingo/services/local_llama_server.py`
  - `local_ai_model_path` を解決して llama-server 引数を構築・起動・再利用
- 翻訳呼び出し: `yakulingo/services/local_ai_client.py`
  - OpenAI互換のリクエスト（JSON）を投げ、JSON整形/抽出で結果をパース

## Nemotron切替で変える場所（差分点）
1) **インストール時の既定モデル**
   - `packaging/install_deps.bat` Step 7 の説明文（モデル名）
   - `packaging/install_deps.bat` から `packaging/install_local_ai.ps1` に渡す既定 env（repo/kind/quant/base_name）
   - `packaging/install_local_ai.ps1` の「env/manifest が無い場合」の既定値
2) **アプリ既定設定**
   - `config/settings.template.json` と `yakulingo/config/settings.py` の `local_ai_model_path`
3) **ローカルAI出力安定性**
   - `yakulingo/services/local_ai_client.py` の stop sequences と JSON抽出ロジック
   - `prompts/local_*.txt`（JSON出力を崩さない指示・例）
4) **性能チューニング**
   - `local_ai_*`（ctx/batch/ubatch、sampling、max_tokens、cache_type_k/v、GPU設定）
   - 計測: `tools/bench_local_ai.py` / `tools/e2e_local_ai_speed.py` と `docs/PERFORMANCE_LOCAL_AI.md`
5) **ドキュメント**
   - `README.md` の「既定モデル」記載
   - ローカルAI関連メモ（AgentCPM/Qwen3 前提の章の扱い）

## 決定（暫定・task-02/05 で検証前提）
> 本タスクではモデルダウンロード/ベンチはしないため、後続で検証して確定する。

### 既定モデル（新規インストール）
- HF repo: `nvidia/Nemotron-Flash-3B-Instruct`
- 変換モード: `LOCAL_AI_MODEL_KIND=hf`（HF→GGUF→4bit の既存導線を活用）
- 量子化: `LOCAL_AI_MODEL_QUANT=Q4_K_M`（暫定）
- ベース名: `LOCAL_AI_MODEL_BASE_NAME=Nemotron-Flash-3B-Instruct`
- 生成/配置されるGGUF（アプリ既定と一致させる）:
  - `local_ai/models/Nemotron-Flash-3B-Instruct.Q4_K_M.gguf`

### install_local_ai.ps1 側の注意点（task-02 で対応）
- 現状 `kind=hf` の場合に `openbmb/AgentCPM-Explore` へ寄せる特殊処理があるため、Nemotron に置き換える必要がある。
- `kind=hf` の場合、`modelFile` は基本的に「ローカルに置くGGUF名」を指す（HF上のファイル名ではない）ため、`local_ai_model_path` と一致させるのが安全。

### stop sequence（task-04 で確定）
- 現状: `</s>`, `<|end|>`
- Nemotron での終端トークンは要確認（候補: `<|eot_id|>`, `</s>`, `<|end|>` など）
- 方針: **JSONが途中で切れない**ことを優先し、必要なら stop を縮小/変更する（モデル依存のため実測で確定）。

### 推奨パラメータ（task-05 で確定）
- 現状の既定値は Qwen3 系の推奨が混在しているため、Nemotron で再チューニングが必要。
- 方針: `docs/PERFORMANCE_LOCAL_AI.md` のベンチ手順に従い、cold/warm と E2E を揃えて決める。

## 既知の不確実性（フォローアップ）
- Nemotron のアーキテクチャが `tools/hf_to_gguf_quantize.py` と同梱 llama.cpp の変換スクリプトで変換可能か（失敗時は task-02 で最小修正 or 別導線が必要）。
- VRAM/UMA制約（Vulkan/iGPU）と `ctx/batch/ubatch` の最適点。
