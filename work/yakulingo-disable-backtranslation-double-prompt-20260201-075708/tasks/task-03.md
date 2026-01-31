# Task 03: プロンプト二重送信を送信直前に適用（LocalAIClient中心）

## 目的

- intent の代替案「プロンプトを二重に送る」を実装する（`prompt + "\\n\\n" + prompt`）。
- 実装は送信直前（`LocalAIClient`）に集約し、呼び出し側の改修を最小化する。

## 変更対象（想定）

- `yakulingo/services/local_ai_client.py`
  - 既存の `repeat_prompt` パラメータの適用方針を決め、翻訳系リクエストで有効化する
- 必要なら設定:
  - `yakulingo/config/settings.py`
  - `config/settings.template.json`

## 実装方針（ガード）

- 二重化は「翻訳品質向上」のための固定仕様としつつ、もし副作用（プロンプト長制限/コスト増）が大きい場合に備え、設定で無効化できる余地を検討する（検討した結果はこのタスク内で確定）。
- プロンプト長チェックがある場合は、二重化後の長さで判定する（安全側）。
- ウォームアップや内部診断など、品質目的ではない呼び出しは二重化しない。

## テスト観点

- 送信ペイロードに二重化されたプロンプトが入ること（ユニットテストで検証）
- `strip_prompt_echo()` 等のプロンプトエコー除去が二重化で壊れないこと

## DoD

- typecheck: `uv run --extra test pyright`
- lint: `uv run --extra test ruff check .`
- tests: `uv run --extra test pytest`
- PR-merge → ブランチ削除（remote+local）→ 削除証明

