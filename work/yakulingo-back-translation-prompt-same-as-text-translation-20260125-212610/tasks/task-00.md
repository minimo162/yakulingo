# task-00: 現状調査と実装方針確定

## 目的
逆翻訳（Back-translate）が現在どのテンプレートで動いているかを把握し、「通常のテキスト翻訳のプロンプトと同じ」にするための最小変更方針を確定する。

## 想定所要時間
15–45分

## 作業範囲
- 逆翻訳の実装経路（`yakulingo/ui/app.py` の `_back_translate`）とプロンプトテンプレートの参照箇所を確認
- 通常のテキスト翻訳テンプレート（`prompts/text_translate_to_jp.txt` / `prompts/text_translate_to_en_compare.txt`）の入出力形式とプレースホルダを確認
- 統一方式（テンプレート選択ロジック／既存の言語検出の利用／参照ファイルの扱い）を決める

## 手順
1. `rg "text_back_translate.txt"` で参照箇所を確認し、逆翻訳がUI側でテンプレートを直読みしている現状を確認する
2. 通常テキスト翻訳のテンプレートを確認し、逆翻訳で必要なプレースホルダ（`{input_text}` / `{reference_section}`）が揃っていることを確認する
3. 「逆翻訳の方向決定」が通常テキスト翻訳と同じ規則になるよう、入力テキスト（逆翻訳対象）の言語検出に基づくテンプレート選択案を確定する
4. 方針が `scope.md` と乖離する場合は、先に `work/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/scope.md` を更新して合意を取る

## 調査結果（事実）
- 逆翻訳は `yakulingo/ui/app.py` の `_back_translate` で `prompts/text_back_translate.txt` を直読みしている。
- テンプレート内の `{input_text}`（互換の `{text}`）と `{reference_section}` を置換して送信している。
- 通常のテキスト翻訳テンプレートは以下（いずれも `{input_text}` / `{reference_section}` を持つ）:
  - 英→日: `prompts/text_translate_to_jp.txt`（出力は `Translation:` ラベル形式）
  - 日→英: `prompts/text_translate_to_en_compare.txt`（`[minimal]` + `Translation:` ラベル形式）
- 受信後の抽出は `yakulingo/ui/utils.py:parse_translation_result()` を利用しており、`Translation:` 形式なら本文抽出、ラベル無しなら全文を採用する。

## 決定事項（実装方針）
- 逆翻訳専用テンプレート（`prompts/text_back_translate.txt`）への依存を廃止し、通常テンプレートに統一する。
- 逆翻訳の方向は、逆翻訳対象テキスト（`text_override` があればそれ、なければ `option.text`）のローカル言語検出に基づき、通常テキスト翻訳と同じ規則で決定する。
  - 日本語と判定 → 英訳（`prompts/text_translate_to_en_compare.txt`）
  - 日本語以外と判定 → 和訳（`prompts/text_translate_to_jp.txt`）
- 参照ファイル（用語集等）の添付/`{reference_section}` 生成、警告通知、ストリーミングプレビューの挙動は現状維持する。
- テンプレート取得は可能な限り `TranslationService` 側の `PromptBuilder`（キャッシュ/フォールバック）を利用し、UI側でのファイル直読みは避ける（必要なら最小限の後方互換フォールバックのみ）。
- `prompts/text_back_translate.txt` の削除・非推奨化は `task-03` で判断する（現時点では残す）。

## DoD
- 実装方針（どのテンプレートを使う/どう選ぶ/フォールバック）を1つに確定できている
- `work/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/tasks/index.md` が更新されている（必要ならタスク分割も反映）
