# AgentCPM-Explore（openbmb/AgentCPM-Explore）導入方針メモ（過去メモ）

本書は過去に「ローカルAIモデルを openbmb/AgentCPM-Explore に切り替える」ことを検討した設計メモです。

## 現行仕様（重要）
- ローカルAIの既定翻訳モデル: `mradermacher/translategemma-12b-it-i1-GGUF/translategemma-12b-it.i1-IQ3_XXS.gguf`
- 配置先（既定）: `local_ai/models/translategemma-12b-it.i1-IQ3_XXS.gguf`
- 使用するモデルは `local_ai_model_path` で指定する（配布版は既定モデルのみ同梱）。

以降の内容は「過去メモ」として残しています（運用手順/SSOTとしては使用しないでください）。

## 結論（採用する唯一の導入フロー）

- **エンドユーザー向けの公式フローは「変換済みGGUF（4bit）を配布し、`packaging/install_local_ai.ps1` はそれをダウンロードする」**とする。
- **HF→GGUF変換 + 4bit量子化は“メンテナ向けのビルド手順”として実行し、成果物（GGUF）を配布物に載せる。**

理由:
- `install_local_ai.ps1` は現在も「llama.cppバイナリ + GGUFモデルのダウンロード」で完結しており、ここに PyTorch/Transformers 依存を持ち込むと配布と運用が大幅に重くなるため。
- 変換/量子化はモデルサイズが大きく、実行環境差（GPU/CPU、RAM、Python環境）による失敗確率が高いため、**配布前に一度だけ作って検証済み成果物を配る**ほうが安定するため。

## 互換性メモ（最低限の確認）

`openbmb/AgentCPM-Explore` の `config.json` から、少なくとも以下が確認できる:
- `architectures`: `Qwen3ForCausalLM`
- `model_type`: `qwen3`

当時このリポジトリは「Shisa v2.1 Qwen3」をローカルAIで扱っており、`docs/PERFORMANCE_LOCAL_AI.md` でも Qwen3 前提の推奨パラメータが記載されていたため、**モデル系統としては既存の運用方針（llama.cpp + GGUF + 量子化 + チューニング）と整合**すると判断した。

## 現状のローカルAI実装（リポジトリ内のSSOT）

- インストール: `packaging/install_local_ai.ps1`
  - llama.cpp（`llama-server.exe`）を `local_ai/llama_cpp/(avx2|vulkan)/` に配置
  - モデル（GGUF）を Hugging Face から `local_ai/models/` に配置
  - `local_ai/manifest.json` を生成（llama.cppとモデルの由来/ハッシュを追跡）
- 起動: `yakulingo/services/local_llama_server.py`
  - `local_ai_model_path` を解決し、`llama-server` 引数を構築して起動/再利用
- 設定: `config/settings.template.json` / `yakulingo/config/settings.py`
  - `local_ai_*` はテンプレ管理（ユーザー保存しない方針）
- 計測: `tools/bench_local_ai.py` / `tools/e2e_local_ai_speed.py` / `docs/PERFORMANCE_LOCAL_AI.md`

## 変換/量子化（メンテナ向け）方針

### 目的
`openbmb/AgentCPM-Explore`（HF形式）から、YakuLingo がそのまま起動できる 4bit GGUF（llama.cpp対応）を作り、配布する。

### 成果物（例）
- `AgentCPM-Explore-<revision>-Q4_K_M.gguf`（推奨。`<revision>` はHFのcommit SHA等）
  - 実運用では「固定ファイル名（例: `AgentCPM-Explore-Q4_K_M.gguf`）」を別途用意してもよいが、まずは再現性優先で revision を含める。

### 依存と責務分離
- 変換（HF→GGUF）は Python 依存が重い（PyTorch/Transformers等）ため、**配布・エンドユーザーインストールの必須要件にしない**。
- 量子化は `llama-quantize(.exe)`（llama.cpp同梱）を利用できるため、**成果物生成の最終段**として使う。

### 実装予定（次タスクでやること）
- メンテナ向けに「HF→GGUF→4bit量子化」を再実行可能にするスクリプトを追加し、生成物の命名・配置・ハッシュ計算を標準化する。
- （過去案）`install_local_ai.ps1` の既定モデルを AgentCPM-Explore の配布GGUFへ切り替え、`manifest.json` に追跡情報を残す。

### ツール（task-02で追加）
- （過去案）`tools/hf_to_gguf_quantize.py` を使用して、HFモデル（ローカルディレクトリ推奨）→ f16 GGUF → 4bit GGUF を生成する。
  - 量子化は同梱 `local_ai/llama_cpp/*/llama-quantize(.exe)` を使用する。
  - llama.cpp の変換スクリプトは、`local_ai/manifest.json` の `llama_cpp.release_tag` と揃える（無い場合は `master`）。

## インストール側の方針（エンドユーザー向け）

- `packaging/install_local_ai.ps1` は引き続き「モデルGGUFのダウンロード」で完結させる。
- （過去案）既存の `LOCAL_AI_MODEL_REPO` / `LOCAL_AI_MODEL_FILE` を用いて、モデル配布先を切り替えられる状態を維持する。
- 切り替え初期は互換性/性能の揺れがあり得るため、旧モデルへのロールバック手段（環境変数指定・設定戻し）をドキュメント化する。

## 未決事項（このタスクでは決めない）

- 量子化方式（例: `Q4_K_M` vs `Q4_K_S` など）の最終選定
- 既定 `local_ai_*` の具体値（ベンチ結果に基づき task-05 で確定）
- 配布先（GitHub Releases / Hugging Face のどちらをSSOTにするか）
