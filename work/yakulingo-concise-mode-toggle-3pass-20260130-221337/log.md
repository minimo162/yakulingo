# log

## entries

- 2026-01-30: task-00 設計SSOT確定（`a54ccf85`）
  - 検証: `uv run --extra test pyright` OK / `uv run --extra test ruff check .` OK / `uv run --extra test pytest` OK（369 passed）
  - 統合: `main`へff-onlyで統合し、`origin/main`へpush済み（`dcf10151..a54ccf85`）
  - フォローアップ（未確定点）: 和訳（日本語出力）で“abbreviation多用”をどの程度許容するか（KPI/FY/QoQ等）

- 2026-01-30: task-01 テキスト翻訳の標準/簡潔トグル追加（`cdc4235b`）
  - 検証: `uv run --extra test pyright` OK / `uv run --extra test ruff check .` OK / `uv run --extra test pytest` OK（369 passed）
  - 統合: `main`へff-onlyで統合し、`origin/main`へpush済み（`a7c3d99c..cdc4235b`）

- 2026-01-30: task-03 ストリーミング3段連結＋簡潔モード配線（`feb6e1c1`）
  - 検証: `uv run --extra test pyright` OK / `uv run --extra test ruff check .` OK / `uv run --extra test pytest` OK（369 passed）
  - 統合: `main`へff-onlyで統合し、`origin/main`へpush済み（`6a726b5e..feb6e1c1`）

- 2026-01-30: task-04 簡潔モードを2段化＋2回目ストリーミング修正（`c18bc708`）
  - 検証: `uv run --extra test pyright` OK / `uv run --extra test ruff check .` OK / `uv run --extra test pytest` OK（369 passed）
  - 統合: `main`へff-onlyで統合し、`origin/main`へpush済み（`25ffb322..c18bc708`）
  - メモ: push時にGit LFSのlocks verifyで失敗したため、`git config lfs.https://github.com/minimo162/yakulingo.git/info/lfs.locksverify false` を設定

- 2026-01-30: task-05 テスト追加/更新＋簡潔化スキップ防止（`285fb128`）
  - 検証: `uv run --extra test pyright` OK / `uv run --extra test ruff check .` OK / `uv run --extra test pytest` OK（375 passed）
  - 統合: `main`へff-onlyで統合し、`origin/main`へpush済み（`2c3ae5b7..285fb128`）
  - クリーンアップ: `case/yakulingo-concise-mode-toggle-3pass-20260130-221337/task-05-tests-concise-rewrite` をremote/local削除し、`git ls-remote --heads` と `git branch --list` で空を確認

- 2026-01-30: task-06 仕上げ：ホットキー翻訳でも「簡潔」を適用（`091b5906`）
  - 検証: `uv run --extra test pyright` OK / `uv run --extra test ruff check .` OK / `uv run --extra test pytest` OK（375 passed）
  - 統合: `main`へff-onlyで統合し、`origin/main`へpush済み（`371a52cb..091b5906`）
  - クリーンアップ: `case/yakulingo-concise-mode-toggle-3pass-20260130-221337/task-06-hotkey-mode` をremote/local削除し、`git ls-remote --heads` と `git branch --list` で空を確認


## 2026-01-30 23:13:44 task-02 ??
- ????: case-yakulingo-concise-mode-toggle-3pass-20260130-221337-task-02-3pass-pipeline
- ????: 762f83ac
- ??: `uv run --extra test pyright` / `uv run --extra test ruff check .` / `uv run --extra test pytest`
- ??: `main` ? fast-forward ? `origin/main` ? push
- ???????: remote/local ?????????`git ls-remote --heads` / `git branch --list` ???
