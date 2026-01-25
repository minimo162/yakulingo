# タスク一覧

Status: TODO | DOING | DONE | BLOCKED | SKIP

| ID | Status | Summary | Branch | Commit |
| --- | --- | --- | --- | --- |
| task-00 | DONE | 現状調査（Copilotバッチ翻訳での数値ルール未適用の可能性を確認、再現条件の確定） | `case-yakulingo-dynamic-glossary-billion-notation-check-20260126-010738-task-00-survey` | `e0654bba` |
| task-01 | DONE | 回帰テスト追加（`BatchTranslator`/Copilot経路で `billion` が残る→`oku`化されることを固定） | `case-yakulingo-dynamic-glossary-billion-notation-check-20260126-010738-task-01-batch-oku-regression` | `5148c0d5` |
| task-02 | DONE | 修正実装（`BatchTranslator`/Copilot経路にもJP→EN数値の自動補正＋数値ルール再試行を適用） | `case-yakulingo-dynamic-glossary-billion-notation-check-20260126-010738-task-02-batch-numeric-retry` | `9e219a77` |
| task-03 | DONE | 動的用語集の改善（インライン用語集で数値系を優先し、取りこぼしを防止） | `case-yakulingo-dynamic-glossary-billion-notation-check-20260126-010738-task-03-inline-glossary-priority` | `b36b9b27` |
| task-04 | TODO | 仕上げ（typecheck/lint/full tests、回帰確認、ドキュメント最小更新） | `TBD` | `TBD` |

## タスク詳細
- `task-00.md`
- `task-01.md`
- `task-02.md`
- `task-03.md`
- `task-04.md`
