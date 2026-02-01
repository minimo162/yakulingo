# タスク一覧

ステータスは `TODO | DOING | DONE | BLOCKED | SKIP` のいずれか。

| ID | Status | 概要（1行） | ブランチ名 | コミットSHA |
|---:|:---:|---|---|---|
| 00 | DONE | 現状調査と仕様確定（戻し訳廃止 + プロンプト二重送信の適用範囲） | `case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-00-spec` | `aea1df27` |
| 01 | DONE | 設定/モード/ルーティングから戻し訳モードを廃止（互換考慮） | `case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-01-mode-routing` | `195fc55a` |
| 02 | DONE | 翻訳サービスから3pass戻し訳パイプラインを削除し、呼び出し元を更新 | `case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-02-remove-backtranslation` | `ee27b191` |
| 03 | DONE | プロンプト二重送信を送信直前に適用（LocalAIClient中心） | `case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-03-double-prompt` | `b419e398` |
| 04 | DONE | 戻し訳用プロンプト/テンプレート/PromptBuilderを整理し、テストを更新 | `case-yakulingo-disable-backtranslation-double-prompt-20260201-075708-04-prompt-cleanup` | `4009f433` |
| 05 | TODO | UI表示（戻し訳/パス）を整理し、設定UIの選択肢を更新 | `case/yakulingo-disable-backtranslation-double-prompt-20260201-075708/task-05` | `<SHA>` |
| 06 | TODO | 統合リグレッション（typecheck/lint/full tests）と仕上げ | `case/yakulingo-disable-backtranslation-double-prompt-20260201-075708/task-06` | `<SHA>` |
