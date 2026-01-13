# タスク一覧

ステータス: `TODO` | `DOING` | `DONE` | `BLOCKED` | `SKIP`

| Task | Status | Summary | Branch | Commit |
|------|--------|---------|--------|--------|
| task-00 | DONE | 現状導線の再確認と差分設計を確定 | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-00-design-notes | ef001c084c47f82a2382baddd34e7d17e76a380d |
| task-01 | DONE | `install_deps.bat` Step 7 を Nemotron デフォルトに更新 | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-01-installer-defaults | 744021eea51c2cc1cb3b7c43785c84e28ca180fc |
| task-02 | DONE | `install_local_ai.ps1` のデフォルトモデルを Nemotron に更新 | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-02-install-local-ai-defaults | f8d941e69393c898e1d934b2c557d671d7dbf6c1 |
| task-03 | DONE | アプリ既定設定（`local_ai_model_path` 等）を Nemotron に更新 | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-03-app-default-model | e79b0489972f8909a048ad3b7d8b4390233adcc4 |
| task-07 | DONE | `install_deps.bat` Step 7 の [1] で落ちる問題を修正 | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-07-step7-choice1-crash | 7c4def27888e0dc75da2854306984e4e33bcd649 |
| task-08 | DONE | Step 7 を別ファイルへ分離（install_deps.bat を薄くする） | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-08-step7-split | 7e7cfb2eb7b27a1ea5bef46b726435bb2b741a63 |
| task-09 | DONE | Step 7 の [1] で落ちる原因を特定して修正（落ちない/理由表示） | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-09-step7-choice1-fix | bb379d5ff08a82868326caabba1958dcb61f3357 |
| task-10 | DONE | Step 7 単体実行でもプロキシ選択を可能にする | case-nemotron-flash-3b-install-deps-4bit-20260113-113408-task-10-step7-proxy-choice | 57ba029357fa351629267bfd2a4912774f0b2b4f |
| task-04 | TODO | ローカルAIの出力安定性（stop/JSON）を Nemotron 前提で調整 | (TBD) | (TBD) |
| task-05 | TODO | 計測と最適化（`local_ai_*` 既定値・ドキュメント） | (TBD) | (TBD) |
| task-06 | TODO | 配布・運用ドキュメント更新（導入/ロールバック/互換性） | (TBD) | (TBD) |
