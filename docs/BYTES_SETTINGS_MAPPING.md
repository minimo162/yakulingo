# Bytes 設定ブロックの適用先（YakuLingo）

## 結論（先に）
intent にある `Bytes { ... }` は、Hugging Face Transformers の `generation_config.json`（または `GenerationConfig`）由来のキー構成に近いが、**現行の YakuLingo ローカルAI実装は llama.cpp（OpenAI互換 `/v1/chat/completions`）であり Transformers を直接使用していない**。  
そのため **`top_k` / `top_p` のみが既存設定へ素直に対応**し、他のキーは **現状は適用先がない（＝無視される）**。

## 調査結果（適用ポイント）
- ローカルAIの推論パラメータ送信: `yakulingo/services/local_ai_client.py`（`LocalAIClient._build_chat_payload()`）
- ローカルAIの設定（既定値/バリデーション）: `yakulingo/config/settings.py`（`AppSettings.local_ai_*`）
- 既定値テンプレート: `config/settings.template.json`
- Transformers の直接利用: リポジトリ内に import/依存として存在しない（`TRANSFORMERS_OFFLINE` 環境変数を設定している箇所はあるが、Transformers 自体は使っていない）

## キー別の対応表

| Bytes key | intent 値 | 現行実装での扱い | 適用先（ある場合） | 備考 |
|---|---:|---|---|---|
| `top_k` | `64` | **対応可能** | `AppSettings.local_ai_top_k` → `payload["top_k"]` | llama.cpp のサンプリング設定として送信される |
| `top_p` | `0.95` | **対応可能** | `AppSettings.local_ai_top_p` → `payload["top_p"]` | 同上 |
| `do_sample` | `true` | **直接の対応なし** | （なし） | llama.cpp は温度>0でサンプリング前提。サンプリング無効化は通常 `temperature=0` 相当だが、`do_sample` というキーは送れない |
| `cache_implementation` | `"hybrid"` | **直接の対応なし** | （なし） | Transformers の KV キャッシュ実装選択に近い。llama.cpp 側には同名の設定はない（YakuLingo では `local_ai_cache_type_k/v` など別概念の設定がある） |
| `transformers_version` | `"4.57.3"` | **対応なし** | （なし） | 現行ローカルAI経路は Transformers を使わないため、固定・参照する箇所がない |

## 方針（このケースの後続タスクへの前提）
1. `top_k/top_p` は **YakuLingo の `local_ai_top_k/local_ai_top_p`** にマップして反映する（既定値/README/テスト更新は task-03 で実施）。
2. `do_sample/cache_implementation/transformers_version` は **現状のローカルAI（llama.cpp）経路では適用不可**として扱い、必要なら docs 側で「非対応（無視される）」を明記する。
3. 将来 Transformers ベースのローカル推論バックエンドを追加する場合に限り、上記キー群の再評価（適用先追加）を行う。
