# Task 00: 現状調査と仕様確定（戻し訳廃止 + プロンプト二重送信）

## 目的

- 現状の「戻し訳（backtranslation）」機能の入口/出口/依存を洗い出し、削除対象を確定する。
- 代替施策「プロンプトを `prompt \\n\\n prompt` の形で二重送信」を、どの呼び出し経路に適用するかを確定する。

## スコープ

- 対象: `translation_service.py` / `prompt_builder.py` / `local_ai_client.py` / 設定（`settings.py`・テンプレ）/ UI（`text_panel.py`）/ 関連テスト / prompts。
- スコープ外: それ以外の改善（性能、別品質施策、UIの大規模改修）。

## 進め方（チェックリスト）

1) 戻し訳に言及する箇所の一覧化（`rg "backtranslation|back translation|戻し訳"`）
2) 設定（`text_translation_mode` 等）でのモード定義と実使用の確認
3) `TranslationService.translate_text_with_style_comparison()` のモード分岐と既存挙動確認
4) プロンプト二重送信の受け口があるか確認（`LocalAIClient` の `repeat_prompt`）
5) 最終方針を `task-00.md` に追記（このタスク内で確定する）

## 仕様（このタスクで確定すべき結論）

- 「戻し訳」機能は **ユーザーに露出する機能・内部のパイプライン・テンプレ・テストを含めて廃止**する。
- 代替として、**翻訳要求のプロンプト本文を二重化**して送る（`prompt + "\\n\\n" + prompt`）。
- 二重化は **送信直前の単一箇所に集約**し、呼び出し元の分散改修を避ける。
- 既存設定や履歴メタデータの互換性が必要な場合は、「旧値を受け取っても壊れない」範囲での吸収に留める。

## DoD

- 変更対象ファイル/テンプレ/テストの「触る・触らない」が `scope.md` と一致している。
- task-01 以降で削除・更新する対象が、このタスクの一覧に含まれている。
- 次タスク（task-01〜）に落とし込める粒度の決定事項が書かれている。

## 実行コマンド（参照）

- 参照検索: `rg -n "backtranslation|back translation|戻し訳" yakulingo prompts tests -S`

## 調査結果（SSOT）

### 戻し訳（backtranslation）の入口/出口

- 入口（ルーティング）:
  - `yakulingo/services/translation_service.py` の `translate_text_with_style_comparison()` で、`text_translation_mode` が `standard|3pass|backtranslation|review` の場合に `translate_text_with_backtranslation_review()` にルーティングされる。
- パイプライン本体:
  - `yakulingo/services/translation_service.py` に `translate_text_with_backtranslation_review()` が存在し、3pass（translation → back translation → revision）を実装している。
- 設定:
  - `yakulingo/config/settings.py` の `AppSettings.text_translation_mode` が `standard` 既定で、コメント上も「standard は戻し訳チェック/3pass」を示している。
- UI:
  - `yakulingo/ui/components/text_panel.py` に pass 表示ラベル（例: `back_translation` を「戻し訳」と表示）が存在する。

### 戻し訳関連のプロンプト/テンプレ

- `yakulingo/services/prompt_builder.py`
  - `build_back_translation_prompt()`（pass2）
  - `build_translation_revision_prompt()`（pass3）
- `prompts/`
  - `text_back_translate.txt`
  - `text_back_translate_to_en.txt`
  - `text_back_translate_to_jp.txt`
  - `text_translate_revision_to_en.txt`
  - `text_translate_revision_to_jp.txt`

### 戻し訳に依存するテスト（例）

- `tests/test_text_translation_mode_standard_routes_to_backtranslation_review_task00.py`
- `tests/test_text_backtranslation_review_pipeline_task02.py`
- `tests/test_text_streaming_events_task03.py`
- `tests/test_text_concise_mode_pipeline_task05.py`（文字列に「戻し訳（pass2）」が含まれることを期待）
- `tests/test_prompt_builder_3pass_prompts_task01.py`

### 「プロンプト二重送信」の実装可能性（受け口の有無）

- `yakulingo/services/local_ai_client.py` に `repeat_prompt` の受け口が既にある:
  - `_repeat_prompt_twice()` と `_sent_prompt()` が `prompt + "\\n\\n" + prompt` 形式を実装している。
  - ただし現状は `translate_single()` / `translate_sync()` 等の呼び出しで `repeat_prompt=False` がハードコードされており、実質無効。

## 最終方針（このタスクで確定）

1) **戻し訳機能は全面廃止**（UI露出・3passパイプライン・テンプレ・PromptBuilder API・関連テストまで含む）。  
2) 代替として、**翻訳リクエストのプロンプト本文を二重化して送信**する（`prompt + "\\n\\n" + prompt`）。  
3) 二重化は **送信直前の単一箇所に集約**する。具体的には `LocalAIClient` の翻訳系エントリポイント（`translate_single()` / `translate_sync()`）で有効化し、下位（`_chat_completions*` / `_completions*`）へ `repeat_prompt=True` を伝播する。  
4) **ウォームアップ等の非翻訳呼び出しは二重化しない**（品質目的ではないため）。  
5) 互換性: 旧 `text_translation_mode` 値（`standard|3pass|backtranslation|review` 等）が残っていても壊れないよう、**後続タスクで安全側にマッピング**する（戻し訳には戻さない）。
