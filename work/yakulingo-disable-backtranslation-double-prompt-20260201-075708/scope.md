# スコープ

## 触る（このケースで変更対象にする）

目的（intent.md）を満たすために、以下の「戻し訳（back translation / backtranslation）」に直接関係する箇所、ならびに「プロンプト二重送信」を実現する箇所のみを触る。

- テキスト翻訳の戻し訳パイプライン（3pass / backtranslation review）関連
  - `yakulingo/services/translation_service.py`
  - `yakulingo/ui/components/text_panel.py`（戻し訳/パス表示やラベル）
  - `yakulingo/config/settings.py`（`text_translation_mode` 等の設定）
- 戻し訳用プロンプトテンプレート・ビルダー
  - `yakulingo/services/prompt_builder.py`
  - `prompts/text_back_translate*.txt`
  - `prompts/text_translate_revision_to_*.txt`
  - `prompts/text_back_translate.txt`（存在する場合）
- 戻し訳に依存するテスト
  - `tests/test_*backtranslation*.py` 等（リポジトリ内で戻し訳に言及するテスト）
- 「プロンプト二重送信」の実装（送信直前の1箇所に集約）
  - `yakulingo/services/local_ai_client.py`（既に `repeat_prompt` の受け口があるため、ここを主戦場にする想定）
  - 必要なら `config/settings.template.json` / `yakulingo/config/settings.py` にON/OFF設定を追加（ただしスコープ外拡張はしない）

## 触らない（明示的にスコープ外）

次は本件の目的に直接関係しないため触らない（副作用やリグレッションの原因になりやすい）。

- ファイル翻訳の各プロセッサ（`yakulingo/processors/*`）のロジック全般
- UIの見た目改善・デザイン変更（戻し訳廃止に伴う表示整理「のみ」は許容）
- 翻訳品質に関する別アプローチ（追加の再ランキング、複数サンプル生成、自己評価など）
- 設定の大規模整理や名称変更（互換性破壊の可能性が高い）
- 既存のローカルAIサーバ管理・起動維持ロジック（本件はプロンプト内容に限定）

## 根拠（なぜこのスコープか）

- intent の主語は「戻し訳機能の廃止」と「代替としてプロンプト二重送信」なので、戻し訳に関係するコード・テンプレート・UI・テストを最小集合で整理し、送信直前で二重化を実装するのが最短距離。
- 送信直前を1箇所にすることで、テキスト/バッチ/ストリーミング等の呼び出し元に改修を波及させにくく、リスクを下げられる。
