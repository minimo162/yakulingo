# Scope

## 目的
ローカルAIの既定モデルを `dahara1/shisa-v2.1-qwen3-8b-UD-japanese-imatrix/shisa-v2.1-qwen3-8B-IQ4_XS.gguf` に切り替え、設定・インストーラ・配布スクリプト・ドキュメントの参照を整合させる。

## 触る（In scope）
- 既定値（アプリ設定SSOT）
  - `yakulingo/config/settings.py` の `local_ai_model_path` 既定値
  - `config/settings.template.json` の `local_ai_model_path` 既定値
- ローカルAIインストール（固定モデルの差し替え）
  - `packaging/install_local_ai.ps1` の固定モデル repo/file
  - `packaging/install_deps_step7_local_ai.bat` の表示文言（固定モデル名）
- 配布（固定モデル同梱の参照更新）
  - `packaging/make_distribution.bat` の `FIXED_MODEL_GGUF`
- ドキュメント（既定モデル参照の更新）
  - `README.md`
  - `docs/*`（既定モデル名/パスを列挙した箇所）
- テスト（既定値整合）
  - `tests/test_settings_template_defaults.py`（テンプレと AppSettings の一致）

## 触らない（Out of scope）
- 翻訳品質/速度の改善、プロンプト設計変更、ストリーミング挙動変更
- 「モデル選択を可変にする」新機能（UI追加・設定追加・env追加）
- llama.cpp のチューニング（`ctx/batch/ngl/fa` 等の最適化）やベンチ改善
- 既存の文字化け/エンコーディング問題の包括的修正（本件に直接関係しない範囲）
- 既定以外の追加モデル同梱や複数モデル管理（固定モデル方針は維持）

## スコープ根拠
- 変更の本質は「固定の既定モデル名」を差し替えること。挙動変更ではなく参照整合に限定することで、リスクとレビュー負荷を最小化する。
