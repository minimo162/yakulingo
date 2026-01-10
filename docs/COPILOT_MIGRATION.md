# Copilot廃止に向けた差分棚卸しと段階移行案

## 背景
- Copilotモードを「いきなり削除」せず、Local AIモードへ段階的に寄せる。
- 既存ユーザー影響を抑えるため、`copilot_enabled` でUI上のCopilotを非表示/無効化できるようにする。

## 差分棚卸し（UI/体験）
| 項目 | Copilot | Local AI | 差分/備考 |
|---|---|---|---|
| バックエンド切替ボタン | あり | あり | `copilot_enabled=false` でCopilotボタン非表示 |
| 状態表示 | 接続/ログイン/GPTモード | llama-server起動/READY | ステータス文言と遷移が異なる |
| ブラウザ表示モード | あり（Edge） | なし | `browser_display_mode` はCopilot専用 |
| ログイン補助/ガード | あり | なし | `login_overlay_guard` はCopilot専用 |
| トレイ表示 | backend-aware | backend-aware | task-05で統一済み |
| 起動時の準備 | Edge起動/接続 | llama-server起動/接続 | 起動フローと失敗時の案内が異なる |
| ストリーミング表示 | あり | あり | LocalはSSE解析、CopilotはUI取得 |

## 差分棚卸し（サービス/翻訳）
| 項目 | Copilot | Local AI | 差分/備考 |
|---|---|---|---|
| テキスト翻訳 | `text_translate_*` | `local_text_translate_*_json` | LocalはJSON出力前提 |
| ファイル翻訳 | `file_translate_*` | `local_batch_translate_*_json` | LocalはJSONバッチ（BatchTranslator） |
| 参照ファイル | 添付（Copilot） | プロンプト埋め込み | Localは文字数制限/省略あり |
| フォローアップ/戻し訳 | Copilotテンプレート | Copilotテンプレート | Local専用テンプレート未整備（品質/安定性リスク） |
| ストリーミング | UI/ページ取得 | SSEチャンク解析 | Localは `_wrap_local_streaming_on_chunk` |
| エラー/リトライ | Copilot接続状態 | LocalAIError/再起動 | 失敗時のUI/ログ差あり |

## 段階移行案（案）
1. フェーズ0: Copilotを残したまま無効化スイッチを追加（`copilot_enabled`）。既存ユーザーの設定は保持。
2. フェーズ1: Local AIの不足機能を補完（フォローアップ/戻し訳のローカル専用テンプレート整備、品質評価）。
3. フェーズ2: 新規インストールはLocal AIを既定にし、Copilotは設定でのみ有効化可能にする。
4. フェーズ3: Copilot非推奨化（ドキュメント/設定で告知、依存関係の整理）。
5. フェーズ4: Copilot関連コード/依存を削除（移行後のメジャーバージョンで実施）。

## 関連ファイル
- `yakulingo/config/settings.py`（`copilot_enabled`）
- `config/settings.template.json`
- `yakulingo/ui/app.py`（バックエンド切替UI/起動フロー）
- `yakulingo/services/translation_service.py`
- `yakulingo/services/local_ai_prompt_builder.py`
