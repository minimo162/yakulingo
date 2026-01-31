# 設計メモ（task-00）

## 目的（intentの解釈）
- 誤訳回避のため、テキスト翻訳を「原文→翻訳→戻し訳→修正翻訳」の3パスで行う。
- 簡潔モードの場合は、修正翻訳の後に「さらに簡略化」を追加して最終結果とする。
- ワークフロー中に生成される文章はストリーミング表示し、最後に最終結果を確定表示する。

## 用語
- **source**: 入力原文（ユーザーが貼り付けた文章）
- **target**: 翻訳先言語（JP→ENならEN、EN→JPならJP）
- **pass1（translation）**: source → target（初回の翻訳文）
- **pass2（back-translation）**: pass1(target) → source（戻し訳）
- **pass3（revision）**: source + pass1 + pass2 → target（修正した翻訳文 = 通常最終）
- **pass4（extra concise; concise mode only）**: pass3(target) → target（さらに簡略化 = concise最終）

## 既存実装の前提（現状）
- `TextTranslationResult` は `passes: list[TextTranslationPass]` を既に持ち、複数パスの出力保持が可能（UI側で `_render_pass_context_cards(...)` が描画）。
- UI側のストリーミング表示は `state.text_streaming_preview` という「単一の途中テキスト」を描画する作り（パス識別なし）。
- Service側は `on_chunk: Callable[[str], None] | None` を広く利用しているため、破壊的変更は避ける必要がある。

## 仕様（確定）
### 1) パスの定義（固定）
- pass1: source → target（翻訳文）
- pass2: pass1 → source（戻し訳）
- pass3: source + pass1 + pass2 → target（修正翻訳文）
- pass4（concise modeのみ）: pass3 → target（追加簡略化）

### 2) 最終結果（SSOT）
- 通常モード：`final_text = pass3`
- 簡潔モード：`final_text = pass4`（失敗時は `final_text = pass3` へフォールバック）
- いずれの場合も `TextTranslationResult.final_text` をUIの最終表示に使う（`translation_text` と一致させるのは現仕様通り）。

### 3) 中間生成物の表示
- pass1 / pass2 / pass3 / pass4 はすべて `TextTranslationResult.passes` に入れ、UIの「コンテキストカード」（既存の `_render_pass_context_cards`）でコピー可能にする。
- 表示名（UIラベル）は pass index だけでなく、役割（翻訳/戻し訳/修正/簡潔）で出す（UIタスクで確定）。

### 4) 失敗時のフォールバック（ユーザー体験優先）
- pass1 が成功していれば、pass2/3/4 が失敗しても `TextTranslationResult` は返す（例外でUIを落とさない）。
  - pass2失敗：pass3はスキップし、最終=pass1（警告メタデータ）
  - pass3失敗：最終=pass1（警告メタデータ）
  - pass4失敗（concise）：最終=pass3（警告メタデータ）
- 返却結果には `metadata` に以下を入れる（キーはタスク実装で固定）：
  - `pipeline: "3pass"` / `pipeline: "3pass+concise"`
  - `pipeline_failed_at_pass: int | None`
  - `pipeline_warning: str | None`（UI通知用の短文）

## ストリーミング契約（UI/Service間）
### 方針
- 既存 `on_chunk(text_chunk: str)` は**後方互換のため維持**する。
- 新規に `on_event(event)` を追加し、3パスをパス単位で識別できるようにする（推奨）。

### イベント（案：後続タスクで型を確定）
- `TextTranslationStreamEvent`（新規、models/types.py 追加候補）
  - `pass_index: int`（1..4）
  - `role: str`（"translation" | "back_translation" | "revision" | "extra_concise"）
  - `kind: str`（"chunk" | "pass_start" | "pass_end"）
  - `chunk: str`（kind=="chunk" のときのみ、追加分）
  - `text_so_far: str`（UIが差分管理しない場合に利用。重い場合は省略可）

### 互換性（on_chunk との共存）
- 新パイプラインでは `on_event` を主に使う。
- `on_chunk` が渡されている場合は「現在アクティブなパスのchunk」を流す（従来の `state.text_streaming_preview` を更新するだけでも最低限動く）。
  - UI側が `on_event` 対応した後は `on_chunk` を「最終パスのみ」へ縮退する選択肢もあるが、task-00時点では決めない（互換優先）。

## 既存モード（standard/concise）との整合
- **解釈（推奨）**：
  - `text_translation_mode="standard"`: 3パスを実行し、最終はpass3
  - `text_translation_mode="concise"`: 3パス + pass4 を実行し、最終はpass4（失敗時pass3）
- 段階導入のため、当初は「新3パスモード」を別モード名で追加する案もあるが、intentに忠実に進めるなら上記が自然。
  - 実装影響が大きい場合は、task-02開始時点で “既存挙動の温存方針” を再確認する（スコープ外の設定大改修はしない）。

## プロンプトのSSOT（PromptBuilder）
- 戻し訳（pass2）：既存 `prompts/text_back_translate.txt` をベースにしつつ、出力は「戻し訳本文のみ」へ寄せる（UI/後続処理が扱いやすい）。
- 修正翻訳（pass3）：入力に source / pass1 / pass2 を含め、出力は「修正済み翻訳文のみ」（ラベル・解説なし）。
- 追加簡略化（pass4）：既存 `build_concise_rewrite_prompt` を再利用し、pass4用の強度（さらに短く）を指定できる形に整理する。

## テスト戦略（task-05で実装）
- Serviceの3パス呼び出し順・フォールバック・`passes`/`final_text` の整合をユニットテストで固定。
- ストリーミングは「イベントが pass_index 付きで飛ぶ」ことをモックで検証（UIは状態更新の純関数化ができればユニットテスト）。
