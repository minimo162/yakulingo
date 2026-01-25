# task-01: 逆翻訳プロンプトを通常テンプレートに統一

## 目的
逆翻訳（Back-translate）が専用テンプレート（`prompts/text_back_translate.txt`）を読まないようにし、通常のテキスト翻訳テンプレートと同一のテンプレートを使う。

## 想定所要時間
30–60分

## 実装方針（仮）
- 逆翻訳対象テキストを言語検出し、通常テキスト翻訳と同じ規則で出力言語（=使用テンプレート）を決める。
  - 日本語判定 → `prompts/text_translate_to_en_compare.txt`
  - 非日本語判定 → `prompts/text_translate_to_jp.txt`
- 参照ファイルの扱い（添付/`{reference_section}` 生成）は現状維持。

## 手順（案）
1. ブランチ作成: `case/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/task-01`
2. `yakulingo/ui/app.py` の `_back_translate` 内で、テンプレート選択を上記方針に切り替える
3. `rg "text_back_translate.txt"` が0件になることを確認（参照排除）
4. canonical commands を実行して回帰がないことを確認

## DoD
- 逆翻訳のテンプレートが「通常テキスト翻訳テンプレート」と一致している（専用テンプレートに依存しない）
- `pyright` / `ruff check .` / `uv run --extra test pytest` がすべて成功
- `main` へmerge→ブランチ削除→削除証明→`work/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/tasks/index.md` 更新

