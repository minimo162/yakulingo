# docs ディレクトリ整理方針

このリポジトリの `docs/` は、用途ごとに次の2系統に分けて管理する。

## 1. 翻訳アプリ本体のドキュメント

配置場所:
- `docs/` 直下

対象例:
- `docs/SPECIFICATION.md`
- `docs/DISTRIBUTION.md`
- `docs/PROMPT_TEMPLATES_SSOT.md`

## 2. RunPod 検証・運用ドキュメント

配置場所:
- `docs/runpod/`

対象:
- RunPod 構築手順
- 2週間評価計画/結果
- Day1 チェックリスト/作業ログ
- 引き継ぎメモ/デモ成功条件

新規ドキュメント追加ルール:
- 翻訳アプリ本体に直接関係するものは `docs/` 直下へ追加する
- RunPod 検証・運用専用のものは `docs/runpod/` に追加する
