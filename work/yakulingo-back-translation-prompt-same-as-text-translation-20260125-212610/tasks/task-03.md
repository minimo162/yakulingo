# task-03: 後片付け（参照排除確認・テンプレート整理）

## 目的
逆翻訳専用テンプレート（`prompts/text_back_translate.txt`）への参照が残らない状態を担保し、今後の混乱を防ぐ。

## 想定所要時間
15–45分

## 手順（案）
1. `rg "text_back_translate.txt"` / `rg "Back Translation Request"` 等で参照が残っていないことを確認
2. `prompts/text_back_translate.txt` の扱いを決める（残す/非推奨化/削除）
   - 互換性・配布物への影響が不明な場合は「残す（未使用）」を選ぶ
3. 必要なら最小限のドキュメント更新（本ケースの `scope.md` 追記など）で意図を明文化
4. canonical commands を実行

## DoD
- 逆翻訳が専用テンプレートに依存しないことが確認できている
- `pyright` / `ruff check .` / `uv run --extra test pytest` がすべて成功
- `main` へmerge→ブランチ削除→削除証明→`work/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/tasks/index.md` 更新

