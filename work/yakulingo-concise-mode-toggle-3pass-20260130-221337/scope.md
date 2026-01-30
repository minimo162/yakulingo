# scope

## 触る（このケースで変更してよい範囲）
- `yakulingo/ui/app.py`：テキスト翻訳のUIイベント（スタイル切替、3回出力の最終結果の扱い、履歴保存・コピーボタンの参照先）
- `yakulingo/ui/components/text_panel.py`：入力側の「標準/簡潔」ボタン、結果表示（1回目/2回目/3回目の表示と最終出力の明確化）
- `yakulingo/services/translation_service.py`：テキスト翻訳パイプライン（1回目翻訳→同一言語の簡潔化リライト×2、キャンセル伝播、ストリーミング連結）
- `yakulingo/services/prompt_builder.py`：簡潔化（abbreviation多用）用の“同一言語リライト”プロンプト生成（英語/日本語）
- `prompts/`：必要なら簡潔化リライト用テンプレート追加（既存のプロンプト設計に合わせる）
- `yakulingo/models/types.py`：3回分の出力を保持するためのデータ構造追加（`TextTranslationResult`の拡張 or メタデータ追加）
- `yakulingo/config/settings.py` + `config/settings.template.json`：テキスト翻訳のモード（標準/簡潔）を保持するSSOT（※ファイル翻訳の`translation_style`とは分離して衝突回避）
- `tests/`：新挙動（3回出力、最終出力の選択、ストリーミング連結、キャンセル）のテスト追加/更新

## 触らない（このケースのスコープ外）
- ファイル翻訳（Excel/Word/PPT/PDF/TXT）の抽出/適用ロジック：`yakulingo/processors/**`
- PDFレイアウト解析・OCR周辺：`yakulingo/processors/pdf_*`
- 自動アップデート/配布/インストーラ：`yakulingo/services/updater.py`, `packaging/**`
- ローカルAIサーバ起動・モデル配布の仕組み：`yakulingo/services/local_llama_server.py`, `local_ai/**`

## ねらい（なぜこの範囲か）
- intentは「テキスト翻訳UIの標準/簡潔切替」と「翻訳結果を同一言語で2回リライトして3回目を最終表示」に集中しているため、UI/サービス/プロンプト/型/テストに限定する。
- 既存のファイル翻訳やPDF機能は影響範囲が広く、回帰リスクが高いので触らない。

## 既知の注意点（実装時の論点）
- 既存の`settings.translation_style`は“ファイル翻訳SSOT= minimal”に正規化されるため、テキスト側の「標準/簡潔」トグルは別キーとして分離する必要がある（衝突回避）。
- ストリーミングプレビューは「最新テキストで上書き」設計のため、2回目/3回目は“1回目全文 + 区切り + 2回目(部分) …”の合成で表示を維持する。
