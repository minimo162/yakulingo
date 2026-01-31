# 作業ログ

| 日時 | タスク | ブランチ | コミットSHA | メモ |
|---|---|---|---|---|
| 2026-02-01 | 00 | case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-00-spec | aea1df27 | 調査結果と最終方針を task-00.md に追記。`uv run --extra test pyright` / `ruff` / `pytest` 成功。 |
| 2026-02-01 | 01 | case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-01-mode-routing | 195fc55a | 旧モード値（3pass/backtranslation/review）を standard にマッピングし、standard が戻し訳へ流れないようルーティング変更。`uv run --extra test pyright` / `ruff` / `pytest` 成功。 |
| 2026-02-01 | 02 | case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-02-remove-backtranslation | ee27b191 | 戻し訳（backtranslation）/3pass パイプラインを廃止（APIは NotImplemented に）。concise は 2pass（翻訳→書き換え）に変更。`uv run --extra test pyright` / `ruff` / `pytest` 成功。 |
