# task-01: 「標準/簡潔」トグル（デフォルト標準）＋設定SSOT

見積: 30–60分

## ゴール
- テキスト翻訳UIに **「標準」「簡潔」** の切替ボタンを実装する。
- デフォルトは **標準**。
- 切替状態はSSOTとして保持し、再起動後も一貫した挙動になるようにする（設定に保存）。

## 変更範囲（ファイル）
- 触る:
  - `yakulingo/ui/components/text_panel.py`（トグルUI）
  - `yakulingo/ui/app.py`（状態の保持・ハンドラ配線）
  - `yakulingo/config/settings.py` / `config/settings.template.json`（テキスト翻訳モード設定の追加）
- 触らない:
  - `yakulingo/processors/**`（ファイル翻訳）
  - `yakulingo/processors/pdf_*`（PDF/OCR）

## 実装方針（推奨）
- `AppSettings`に `text_translation_mode` を追加（`standard`/`concise`）。
- `create_text_input_panel()`に `text_translation_mode` と `on_text_mode_change` を渡す。
- 出力言語が英語/日本語どちらでもトグルは表示する（intentが英訳/和訳どちらも対象のため）。

## 手順
1. `config/settings.template.json`に`text_translation_mode: "standard"`を追加
2. `yakulingo/config/settings.py`に同フィールド/ユーザー保存キーを追加（正規化: 不正値は`standard`）
3. `yakulingo/ui/app.py`で設定読み込み→UIへ値を渡し、変更ハンドラで保存
4. `yakulingo/ui/components/text_panel.py`に2値トグルUIを追加（segmented button想定）

## 検証
- `uv run --extra test pyright`
- `uv run --extra test ruff check .`
- `uv run --extra test pytest`

## DoD（完了条件）
- UI上で「標準/簡潔」が切替でき、デフォルトが標準
- 設定ファイルに保存され、再起動後も選択が維持される
- typecheck/lint/testが全て通る
