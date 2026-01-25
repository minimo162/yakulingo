# スコープ

## 目的
- 「動的用語集（プロンプト内の抽出/生成グロッサリー、または数値ヒント）」が期待どおり機能せず、英訳で `billion/bn/trillion` 表記が混入する事象を調査し、原因を特定して修正する。

## 触る（変更対象）
- `yakulingo/services/translation_service.py`
  - JP→EN の数値ルール（`oku/k/▲->()`）の検出・ヒント生成・自動補正・再試行の流れ
  - Copilot/Local の経路差分（特にバッチ翻訳/ファイル翻訳側）
- `yakulingo/services/prompt_builder.py`
  - 参照CSVからの「マッチした用語」抽出（インライン用語集）の選定ロジック/上限（必要なら）
- `yakulingo/services/local_ai_prompt_builder.py`
  - 生成グロッサリー（動的用語集）と既存グロッサリーの重複排除、JP→EN 数値ヒントの生成（必要なら）
- `tests/`
  - 上記の挙動を固定する回帰テスト（billion混入の再現→防止）

## 触らない（変更対象外）
- UI（`yakulingo/ui/**`、`yakulingo/ui/styles.css`）: 表示/操作系の変更は今回の目的外。
- 各ファイルプロセッサ本体（`yakulingo/processors/**`）: 翻訳適用の体裁・レイアウト保持は触らない。
- アップデータ/配布（`yakulingo/services/updater.py`、`packaging/**`）: 関係なし。
- 既存の他ケース（`work/**` の他ディレクトリ）: クロスケース汚染防止のため変更禁止。

## 期待するアウトカム
- JP→EN で `billion/bn/trillion` が残らない（少なくとも「億」系の代表ケースで確実に防止）。
- 動的用語集/数値ヒントが必要なときに確実に効く（効かないときは安全に再試行/自動補正にフォールバック）。
- 変更は最小で、既存テストの意図を崩さない。
