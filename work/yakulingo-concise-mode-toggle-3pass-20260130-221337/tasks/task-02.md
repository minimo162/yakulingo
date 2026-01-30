# task-02: 3段パイプライン（翻訳→簡潔化×2）＋キャンセル/エラー設計

見積: 30–60分

## ゴール
- 簡潔モード時に、以下を **同一リクエスト内で順次実行** できるようにする。
  1. 1回目: 通常の翻訳（英訳/和訳）
  2. 2回目: 1回目の訳文を同一言語で“abbreviation多用”の簡潔文へ変換
  3. 3回目: 2回目の文を同一言語でさらに簡潔化（同上）
- 3回目を最終出力として返す（UI/履歴/コピーの基準）。
- キャンセル（`TranslationCancelledError`）が途中段でも効く。

## 変更範囲（ファイル）
- 触る:
  - `yakulingo/services/translation_service.py`
  - `yakulingo/services/prompt_builder.py`（必要なら）
  - `yakulingo/models/types.py`（3回分の保持）
- 触らない:
  - file processors / PDF / updater

## 実装方針（推奨）
- 追加API例:
  - `TranslationService.translate_text_with_concise_mode(...)` を新設し、既存`translate_text_with_style_comparison()`から分岐
- 各パスは `translate_single` を用い、出力の正規化（prompt echo除去、空/不一致のガード）を共通化
- 3回分の出力を`TextTranslationResult`に保持（UIが表示できるように）

## 手順
1. “簡潔モード”判定をUIからサービス呼び出しに渡す（引数 or 設定参照）
2. 1回目を既存経路で取得（ストリーミングは既存`on_chunk`）
3. 2回目/3回目は「同一言語のリライト」プロンプトで再実行
4. 途中キャンセル/エラー時の戻り値を決める（例: 失敗した時点の最新成功結果を返す/エラー扱い）

## 検証
- `uv run --extra test pyright`
- `uv run --extra test ruff check .`
- `uv run --extra test pytest`

## DoD（完了条件）
- 簡潔モードで3回呼び出される（ログ/テストで確認可能）
- 3回目が最終出力として返る
- 途中キャンセルが即時に効く
- typecheck/lint/testが全て通る
