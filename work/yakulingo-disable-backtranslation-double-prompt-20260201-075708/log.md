# 作業ログ

| 日時 | タスク | ブランチ | コミットSHA | メモ |
|---|---|---|---|---|
| 2026-02-01 | 00 | case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-00-spec | aea1df27 | 調査結果と最終方針を task-00.md に追記。`uv run --extra test pyright` / `ruff` / `pytest` 成功。 |
| 2026-02-01 | 01 | case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-01-mode-routing | 195fc55a | 旧モード値（3pass/backtranslation/review）を standard にマッピングし、standard が戻し訳へ流れないようルーティング変更。`uv run --extra test pyright` / `ruff` / `pytest` 成功。 |
| 2026-02-01 | 02 | case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-02-remove-backtranslation | ee27b191 | 戻し訳（backtranslation）/3pass パイプラインを廃止（APIは NotImplemented に）。concise は 2pass（翻訳→書き換え）に変更。`uv run --extra test pyright` / `ruff` / `pytest` 成功。 |
| 2026-02-01 | 03 | case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-03-double-prompt | b419e398 | LocalAIClient の送信直前でプロンプトを二重化（既定ON、`repeat_prompt_twice` で無効化可）。`strip_prompt_echo()` も二重プロンプトのエコーを除去可能に。`uv run --extra test pyright` / `ruff` / `pytest` 成功。 |

## Task 04（2026-02-01）
- PR: #1187（merge: 6bf6e34b）
- ブランチ: case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-04-prompt-cleanup（commit: 4009f433）
- 検証: `uv run --extra test pyright` / `uv run --extra test ruff check .` / `uv run --extra test pytest`（全て成功）
- Cleanup: 作業ブランチを remote+local 削除（`git ls-remote --heads origin <branch>` / `git branch --list <branch>` ともに空）

## Task 05（2026-02-01）
- PR: #1189（merge: 8dca8189）
- ブランチ: case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-05-ui-cleanup（commit: a415da79）
- 検証: `uv run --extra test pyright` / `uv run --extra test ruff check .` / `uv run --extra test pytest`（全て成功）
- Cleanup: 作業ブランチを remote+local 削除（`git ls-remote --heads origin <branch>` / `git branch --list <branch>` ともに空）
