# task-03: ストリーミング出力を3回分に連結し、3回目を最終表示

見積: 30–60分

## ゴール
- intentの通り、ストリーミング表示を次の形で実現する。
  - 1回目のストリーミング出力を維持したまま
  - 2回目の出力をその下に続け
  - さらに3回目の出力を続ける
  - 完了後、3回目を最終出力として表示（結果カード/コピー/履歴）

## 変更範囲（ファイル）
- 触る:
  - `yakulingo/ui/app.py`（ストリーミングon_chunkの組み立て、完了後の状態遷移）
  - `yakulingo/ui/components/text_panel.py`（必要なら3回分の静的表示も対応）
  - `yakulingo/models/types.py`（3回分の保持とUI参照）
- 触らない:
  - translation backend/server

## 実装方針（推奨）
- 2回目/3回目のon_chunkは「前段の確定全文 + 区切り + 当該段のpartial」を返す関数にする。
- 完了後は、ストリーミングプレビューに依存せず、結果表示が3回分を表示できるようにする（少なくとも3回目が主結果）。

## 手順
1. UI側で“パス1全文/パス2全文”を確定させるタイミングを定義
2. 2回目/3回目用の`build_preview_text`合成関数を導入
3. 完了後の`TextTranslationResult`をUIで表示し、3回目を“最終訳”として扱う

## 検証
- `uv run --extra test pyright`
- `uv run --extra test ruff check .`
- `uv run --extra test pytest`

## DoD（完了条件）
- ストリーミング表示が3回分の縦連結になっている
- 完了後、3回目が結果として表示/コピー/履歴に使われる
- typecheck/lint/testが全て通る
