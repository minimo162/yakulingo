# task-02: インストーラの固定モデルを新モデルへ更新（install_local_ai.ps1 / step7）

## 目標（30–60分）
ローカルAIインストーラが固定でダウンロードするモデルを、SSOT の Hugging Face repo/file に切り替える。

- 新固定モデル（SSOT）:
  - repo: `dahara1/shisa-v2.1-qwen3-8b-UD-japanese-imatrix`
  - file: `shisa-v2.1-qwen3-8B-IQ4_XS.gguf`

## 手順
1. ブランチ作成  
   - `case/<CASE_ID>/task-02-installer-fixed-model`
2. 固定モデル定義の更新
   - `packaging/install_local_ai.ps1` の `$defaultModelRepo` / `$defaultModelFile`
   - `packaging/install_deps_step7_local_ai.bat` の表示文言（モデル名/説明）
3. URL妥当性（軽量チェック）
   - `https://huggingface.co/<repo>/resolve/main/<file>` が解決できること（HEAD/GET で 200）
4. 品質ゲート（rules.md の canonical commands）
   - `uv run pyright`
   - `uv run ruff check .`
   - `uv run --extra test pytest`
5. PR → `main` マージ
6. ブランチ削除（remote + local）と削除証明

## DoD
- インストーラが新 repo/file を参照する（固定モデル方針は維持）
- `pyright` / `ruff` / `pytest` がパス
- ブランチ削除（remote + local）と削除証明がログに残っている

## 変更対象（このタスクで触る）
- `packaging/install_local_ai.ps1`
- `packaging/install_deps_step7_local_ai.bat`
