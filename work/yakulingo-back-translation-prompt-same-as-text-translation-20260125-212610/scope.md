# スコープ

## 触る（予定）
- `yakulingo/ui/app.py` の `_back_translate`（逆翻訳）処理：プロンプトテンプレート選択と生成
- `prompts/text_translate_to_jp.txt` / `prompts/text_translate_to_en_compare.txt`：逆翻訳が参照する通常テンプレート（原則テンプレート自体は変更しない）
- `tests/`：逆翻訳が「通常のテキスト翻訳テンプレート」を使うことのユニットテスト追加（UI/E2Eではなくロジック層で担保）

## 触らない（禁止）
- ファイル翻訳系（`yakulingo/processors/*`、`prompts/file_translate_*`）
- UIレイアウト/スタイル（`yakulingo/ui/components/*`、`yakulingo/ui/styles.css`）※逆翻訳のプロンプト変更に付随する最小限の文言修正を除く
- 既存の他ケース（`work/*` の本ケース以外）
- 配布/アップデート/インストーラ関連（`packaging/*`、`yakulingo/services/updater.py`）

## ねらい（要点）
- 逆翻訳専用テンプレート（`prompts/text_back_translate.txt`）を基準にせず、通常のテキスト翻訳テンプレートに統一する。
- 逆翻訳の方向（英→日 / 日→英）は、入力テキスト（逆翻訳対象）の言語検出に基づき、通常テキスト翻訳と同じ規則で決定する。
- 参照ファイル（用語集等）の添付・警告集約は現状維持する。

