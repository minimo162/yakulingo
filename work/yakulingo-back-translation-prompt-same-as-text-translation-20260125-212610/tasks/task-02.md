# task-02: ユニットテスト追加（逆翻訳プロンプト統一）

## 目的
「逆翻訳が通常テキスト翻訳と同じテンプレートを使う」ことをテストで固定し、将来の変更で戻らないようにする。

## 想定所要時間
30–60分

## 方針（仮）
- UI（NiceGUI）を直接テストしない。ロジック層に最小の分離点を作り、そこをユニットテストで担保する。
  - 例: 「入力テキスト→選択されるテンプレート名/パス/内容」を返す小さな関数やメソッドを `yakulingo/services/` 側に配置し、テスト対象にする。

## 手順（案）
1. ブランチ作成: `case/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/task-02`
2. テスト対象の分離点を実装（最小限）
3. `tests/` に日本語入力・英語入力それぞれで期待するテンプレートが選ばれることを追加
4. canonical commands を実行

## DoD
- 逆翻訳テンプレート選択がテストで固定されている（日本語→英、英語→日）
- `pyright` / `ruff check .` / `uv run --extra test pytest` がすべて成功
- `main` へmerge→ブランチ削除→削除証明→`work/yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610/tasks/index.md` 更新

