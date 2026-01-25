# 作業ログ

| Date | Task | Summary | Branch | Commit | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-01-26 01:01:24 | task-03 | 旧ドキュメントの逆翻訳テンプレート記載を整理 | `case-yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610-task-03-cleanup-docs-and-template` | `9a6b9685` | `uv sync --extra test` / `pyright` / `ruff check .` / `uv run --extra test pytest`（353 passed）; `rg "text_back_translate.txt" yakulingo`（0件） |
| 2026-01-26 00:53:26 | task-02 | 逆翻訳テンプレート選択のユニットテスト追加 | `case-yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610-task-02-back-translate-template-tests` | `16415c57` | `uv sync --extra test` / `pyright` / `ruff check .` / `uv run --extra test pytest`（353 passed） |
| 2026-01-25 23:59:41 | task-01 | 逆翻訳プロンプトを通常テンプレートに統一 | `case-yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610-task-01-unify-back-translate-prompt` | `6632f586` | `uv sync --extra test` / `pyright` / `ruff check .` / `uv run --extra test pytest`（351 passed）; `rg "text_back_translate.txt" yakulingo`（0件）; Follow-up: `AGENTS.md` / `docs/SPECIFICATION.md` に旧仕様記載あり |
| 2026-01-25 21:57:37 | task-00 | 調査結果と実装方針を確定 | `case-yakulingo-back-translation-prompt-same-as-text-translation-20260125-212610-task-00-survey` | `f81ba196` | `uv sync --extra test` / `pyright` / `ruff check .` / `uv run --extra test pytest`（351 passed） |
