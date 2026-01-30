# task-00: 現状把握と設計の確定

見積: 15–45分

## ゴール
- intentを実装可能な形に分解し、**実装SSOT（データ構造/呼び出し順/表示仕様）**を確定する。
- “cross-case contamination”回避のため、変更範囲を`scope.md`に固定し、以後のタスクが迷走しない状態にする。

## 追加で読むべき箇所（確認観点）
- `yakulingo/ui/app.py`：`_translate_text()`、`_create_text_streaming_preview_on_chunk()`、結果保存/履歴追加
- `yakulingo/ui/components/text_panel.py`：ストリーミング表示の条件、結果表示の構造
- `yakulingo/services/translation_service.py`：`translate_text_with_style_comparison()`、`translate_text_with_options()`、キャンセルイベント
- `yakulingo/services/prompt_builder.py`：simple prompt/テンプレの方針（テキスト翻訳がどの経路を使うか）
- `yakulingo/models/types.py`：`TextTranslationResult`/`TranslationOption`の保持項目
- `yakulingo/config/settings.py`：既存設定の正規化（`translation_style`が常に`minimal`化される点）

## 設計で確定させること（決める）
1. **UIトグルのSSOT**
   - 既存`settings.translation_style`はファイル翻訳SSOTの都合で永続化が`minimal`固定
   - テキスト専用に **`text_translation_mode: "standard" | "concise"`** を追加してSSOTとする（ファイル翻訳の`translation_style`とは完全分離）
   - UIは「標準 / 簡潔」の2値トグルのみ（デフォルト: `standard`）
2. **3回出力のデータ保持**
   - **Bを採用**：`TextTranslationResult`を拡張し、3回分の出力を明示フィールドで保持する（テスト容易性とUI側の単純化を優先）
   - 追加案（最小）
     - `passes: list[TextTranslationPass]`
     - `final_text: str`（= 標準モードはpass1、簡潔モードはpass3）
     - `TextTranslationPass`は `index: int`（1..3）, `text: str`, `mode: "translation" | "rewrite"` を持つ
   - `translation_text`（既存の単一表示用）との整合:
     - intent準拠の“最終出力”を返すため、**`translation_text`は常に`final_text`を指す**（UI/履歴/コピーボタンの主参照）
3. **ストリーミング表示仕様**
   - 1回目: 既存通り（部分出力）
   - 2回目: `1回目(確定全文) + 区切り + 2回目(部分)`
   - 3回目: `1回目全文 + 区切り + 2回目全文 + 区切り + 3回目(部分)`
   - 区切り表現（確定）: `\n\n---\n\n`
   - 連結ルール（確定）
     - “確定全文”は各パス完了時点の正規化済み最終文字列を指す
     - ストリーミングは **常に「前段までの確定全文 + 区切り + 当該段の最新partial」** を表示する（＝1回目の表示が消えない）
4. **最終出力の定義**
   - 標準モード: 1回目の翻訳結果を最終出力
   - 簡潔モード: 3回目の簡潔化結果を最終出力（履歴/コピー/表示の主結果）

## 追加で確定した仕様（task-01〜03の前提）
### パス構成
- `standard`モード: pass1のみ（通常翻訳）
- `concise`モード: pass1（通常翻訳）→ pass2（同一言語の簡潔化リライト）→ pass3（同一言語の簡潔化リライト）

### パス1（通常翻訳）のスタイル
- intentの「デフォルトは標準」を満たすため、pass1は“標準”の出力に寄せる。
- 実装方針:
  - 出力が英語（日本語→英訳）: `style="standard"` を明示指定して1回目を生成
  - 出力が日本語（英語等→和訳）: 既存の“translation only”経路を1回目として扱う（ここでは`standard`相当）

### パス2/3（同一言語リライト）の要件
- 入力: 直前パスの訳文（原文ではない）
- 出力: **同一言語**（英語なら英語のみ、日本語なら日本語のみ）
- スタイル: abbreviationを多用した簡潔文（英語は特に強める。日本語は過度な英文化を避けつつ短文化）
- 形式: 本文のみ（ラベル/見出し/解説/マーカー禁止）

## 未確定点（このケース内で質問として固定）
- 日本語出力（和訳）の“abbreviation多用”をどの程度許容するか（例: KPI/FY/QoQなどの英字略語は残す／積極的に入れる／原則日本語短文化のみ、など）

## 成果物
- `tasks/task-01.md`〜`task-06.md`の前提が揃う設計メモ（このtask内ではコード変更なし）
- 仕様の未確定点が残る場合は、**質問を明文化**して以後のタスクに持ち込まない

## DoD（完了条件）
- 設計判断（上記1〜4）が“このケース内で”矛盾なく確定している
- 以後のタスクで触るファイル/触らないファイルが`scope.md`と整合している
