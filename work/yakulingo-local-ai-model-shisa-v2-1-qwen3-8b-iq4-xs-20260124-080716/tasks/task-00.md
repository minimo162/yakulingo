# task-00: ケースファイル（work/配下）を main に取り込む

## 目標（15–30分）
このケース配下の管理ファイル（`intent.md`/`scope.md`/`rules.md`/`tasks/*`/`log.md`）を `main` に取り込み、以降のタスクをブランチ運用で進められる状態にする。

## 手順
1. ブランチ作成  
   - `case/<CASE_ID>/task-00-case-scaffold`
2. `work/<CASE_ID>/` 配下の追加ファイルをコミット対象に含める
3. コミット（日本語短文）
4. 品質ゲート（rules.md の canonical commands）
   - `uv run pyright`
   - `uv run ruff check .`
   - `uv run --extra test pytest`
5. PR → `main` マージ
6. ブランチ削除（remote + local）と削除証明

## DoD
- `work/<CASE_ID>/` 一式が `main` に存在する
- `pyright` / `ruff` / `pytest` がパス
- ブランチ削除（remote + local）と削除証明がログに残っている

## 変更対象（このタスクで触る）
- `work/<CASE_ID>/` のみ
