# AI ハンドオフドキュメント

## マツダ経理部 ローカルLLMデモプロジェクト

> このドキュメントは、プロジェクトの全経緯・決定事項・技術仕様を別のAIに引き継ぐためのものです。

-----

## 1. プロジェクト概要

### 1-1: 目的

マツダ経理部 連結財務グループにおいて、ローカルLLMの業務活用（翻訳・コーディング支援）の有用性を実証し、IT部門にオンプレミスGPUサーバーの購入を提案する。

### 1-2: ユーザープロフィール

- **所属:** マツダ 経理部 連結財務グループ
- **業務:** 四半期連結決算。約90社の子会社・関連会社からPKG（パッケージ）ファイルを収集・集計し、連結財務諸表を作成
- **技術力:** Python、VBA、Power Automate等のプログラミング・自動化スキルあり。USCPA受験勉強中
- **言語:** 日本語ネイティブ、英語も業務で使用（海外子会社対応）

### 1-3: 戦略全体像

```text
Phase 1: 自費デモ（~¥12,000）
  → RunPod（クラウドGPU）で翻訳アプリ＋コーディングデモ
  → 同僚にURL共有して使ってもらう + 画面録画

Phase 2: 上司プレゼン
  → デモ結果 + コスト比較で「オンプレGPUサーバーが必要」と提案

Phase 3: IT部門予算申請（¥300,000〜500,000）
  → オンプレGPUサーバー購入 → データが社外に出ない完全ローカル運用
```

-----

## 2. 背景と経緯（意思決定の過程）

### 2-1: なぜ既存ツール（M365 Copilot）では不十分か

マツダではM365 Copilotが導入済み。Microsoftのセキュリティ基準が適用されるため、極秘情報以外の機密情報も入力できる規定。

しかしCopilotには以下の限界がある：

- **翻訳:** Excelの大量セル翻訳に非対応（手作業が必要）
- **コーディング支援:** 専用のコーディングエージェント機能がない
- **カスタマイズ:** 業務固有の用語辞書・ワークフローへの対応が限定的

### 2-2: なぜ外部API（Gemini、Cerebras等）ではダメか

検討した外部サービス: Cerebras、Groq、SambaNova、Google AI Studio、Gemini API

却下理由：

- マツダのセキュリティポリシー上、未承認サービスへの機密データ送信は不可
- SOC2等の認証があっても、IT部門の個別承認が必要
- 無料枠の制限（レート制限、モデル変更リスク）

### 2-3: なぜローカルLLM + オンプレが最終目標か

- データが社外に**一切出ない** → IT部門の承認が容易
- ランニングコストが電気代のみ → Copilotライセンス不要
- カスタマイズ自由（ファインチューニング、RAG、用語辞書）
- Apache 2.0ライセンス → 法的リスクゼロ

### 2-4: なぜRunPodでデモするのか

オンプレサーバーの購入前に、ローカルLLMの実力を低コストで実証する必要がある。RunPodなら：

- A100 80GBが$1.19/hrで使える
- 2週間デモで~$78（¥12,000）
- auto HTTPS URL → 同僚がブラウザからアクセスできる
- 比較したVast.aiより信頼性・手軽さで勝る

-----

## 3. 技術的決定事項

### 3-1: モデル選定

**メインモデル: GPT-OSS-Swallow-120B-RL-v0.1**

- 開発: 東京科学大学 岡崎・横田研究室 + 産総研（AIST）
- ベース: OpenAI gpt-oss-120b に日本語継続事前学習 + Reasoning SFT + RLVR
- リリース: 2026/2/20（直近リリース）
- ライセンス: Apache 2.0

選定理由:

1. 120B以下のオープンLLMで日本語タスク最高性能（平均0.642）
2. MT-Bench 0.916（クローズドモデル含め最高値）
3. JamC-QA（日本語知識）: 元モデルから+11.4pt向上
4. コミュニティ評価: 「RAGやn8nの自動化のフロー制御にはGPT-OSS-120Bが最も適している。日本語のニュアンスの汲み取りや指示は一番うまい」
5. MoE（Mixture of Experts）アーキテクチャで効率的
6. 「日本の大学が作った日本語特化モデル」→ 上司プレゼンでのストーリー性

**量子化: IQ4_XS（66.2GB）**

- 提供元: mmnga-o（HuggingFace）、imatrix日本語データセット最適化済み
- A100 80GBに余裕で搭載可（13GB+をKVキャッシュに使える）
- Q4_K_S（80.9GB）はA100 80GBでギリギリのため回避

**翻訳用サブモデル: Qwen3-30B-A3B（~18GB）**

- Swallowと同時ロード不可（VRAM不足）
- Ollamaが自動的にモデルを切り替えてロード

**フォールバック: gpt-oss:120b（Ollama公式）**

- SwallowのHarmonyテンプレート設定に問題がある場合の保険
- 同じMoEアーキテクチャ、同じVRAM消費

### 3-2: Harmonyテンプレート

GPT-OSSは独自の「Harmony」チャットテンプレートを使用：

- 制御トークン: `<|start|>`, `<|end|>`, `<|message|>`, `<|channel|>`
- 推論出力は `analysis` チャンネル（非表示）、最終回答は `final` チャンネル
- ロール階層: system > developer > user > assistant > tool

Ollama公式の `gpt-oss:120b` にはテンプレートが組み込み済みだが、カスタムGGUF（Swallow）では手動設定が必要。

**テンプレート設定手順:**

1. `ollama pull gpt-oss:120b` で公式モデルを取得
2. `ollama show gpt-oss:120b --modelfile` でテンプレートを抽出
3. SwallowのGGUFパスと抽出したテンプレートを組み合わせてModelfileを作成
4. `ollama create gpt-oss-swallow:120b -f Modelfile-swallow` で登録

### 3-3: コーディングエージェント

**決定: Claude Code（Codexから変更）**

変更理由:

- SwallowがClaude Codeで動作確認済み（コミュニティ報告: 「Claude Codeとの連携も問題なし」）
- セットアップが環境変数3つのみ（Codexはconfig.toml編集 + バグ回避が必要）
- Codex CLIにはリモートOllama接続バグあり（Issue #8240、プロバイダー名を “ollama” 以外にする回避策が必要）
- ユーザーがClaude Codeに慣れている

接続設定:

```bash
export ANTHROPIC_BASE_URL="https://{pod-id}-11434.proxy.runpod.net"
export ANTHROPIC_API_KEY="認証トークン"  # Nginx認証と兼用
export ANTHROPIC_MODEL="gpt-oss-swallow:120b"
claude
```

将来（オンプレ移行後）: Codex CLI（Apache 2.0）に切り替える選択肢あり（全社配布時のライセンス的自由度）

### 3-4: 翻訳Webアプリ

- フレームワーク: NiceGUI（Python）
- 用途: 同僚がブラウザから日本語→英語翻訳を実行
- バックエンド: 同一Pod上のOllama（localhost:11435）に直接接続
- 認証: Nginx Basic認証（ブラウザのログインダイアログ）
- ポート: NiceGUI自体はlocalhost:8081で起動、Nginxが:8080で受けて転送

-----

## 4. インフラ構成

### 4-1: RunPod Pod

- **GPU:** A100 PCIe 80GB（$1.19/hr）
- **Volume Disk:** 100GB（$0.07/GB/月 = $7/月）
- **Expose Ports:** 11434, 8080
- **Container Image:** RunPodデフォルト（Ubuntu + CUDA）

### 4-2: ポート構成とセキュリティ

```text
外部:11434 → Nginx（x-api-key認証）→ Ollama（localhost:11435）
外部:8080  → Nginx（Basic認証）   → NiceGUI（localhost:8081）
```

|対象|外部ポート|認証方式|内部転送先|
|---|---:|---|---|
|Ollama API|11434|x-api-key ヘッダー|localhost:11435|
|翻訳アプリ|8080|Basic認証（htpasswd）|localhost:8081|

**Nginx設定ファイル:** `/workspace/nginx-auth-proxy.conf`

- Ollama API: Claude Codeが送信する `x-api-key` ヘッダー（= ANTHROPIC_API_KEY の値）を検証
- 翻訳アプリ: `auth_basic` でブラウザのログインダイアログ表示。WebSocket対応（Upgrade/Connectionヘッダー転送）はNiceGUI動作に必須

**認証情報の保存先:**

- Ollamaトークン: `/workspace/.auth_token`
- Basic認証: `/workspace/.htpasswd`

### 4-3: セキュリティポリシー

**データ取り扱いルール:**

マツダのデータ分類:

- 極秘（Top Secret）→ Copilotにも入力不可
- 機密（Confidential）→ Copilot OK（MS基準保護）、RunPod NG
- 社外秘（Internal）→ Copilot OK、RunPod グレー
- 一般（Public）→ 制限なし

RunPod（未承認サービス）に送信できるのは一般情報のみ:

- ✅ 勘定科目名（売上高、営業利益等）
- ✅ 汎用的な業務フロー説明
- ✅ コーディング指示文（「Excelを読み込んで合計するPythonを書いて」）
- ❌ 実際の財務数値、未公開決算データ
- ❌ PKGファイルの実データ
- ❌ 子会社の詳細情報

このセキュリティ制約は上司プレゼンでの**武器**になる:
「クラウドではデータを外に出す必要がある → だからオンプレが必要」

-----

## 5. コスト分析

### 5-1: 2週間デモ

|項目|費用|
|---|---:|
|Week 1: 自己検証 A100×15h|$18|
|Week 2: 同僚デモ A100×45h|$53|
|Volume Disk 100GB × 1ヶ月|$7|
|**合計**|**~$78（¥12,000）**|

### 5-2: 上司への比較資料

|方式|月額|年額|
|---|---:|---:|
|RunPod常時利用（9h×22日）|¥35,000|¥420,000|
|**オンプレGPUサーバー（一括）**|—|**¥300,000〜500,000**|

オンプレなら**1年で元が取れる**。ランニングコストは電気代のみ。

-----

## 6. 作成済みファイル

|ファイル|内容|場所|
|---|---|---|
|**runpod-setup-guide.md**|Step 1〜9の完全セットアップ手順書|成果物として存在|

### runpod-setup-guide.md の構成

- **Step 1:** RunPodアカウント作成
- **Step 2:** クレジット追加（$25）
- **Step 3:** A100 80GB Podデプロイ（Expose Ports設定含む）
- **Step 4:** Ollamaインストール
- **Step 5:** GPT-OSS-Swallow-120Bセットアップ
  - 5-1: 公式gpt-oss:120bからHarmonyテンプレート抽出
  - 5-2: Swallow GGUFダウンロード（IQ4_XS, ~66GB）
  - 5-3: Modelfile作成（FROM Swallow GGUF + 公式テンプレート）
  - 5-4: カスタムモデル登録
  - 5-5: ストレージ節約（公式モデル削除、オプション）
  - 5-6: Qwen3-30B-A3B（翻訳用、オプション）
- **Step 6:** 動作テスト（ターミナル + API + テンプレート検証）
- **Step 7:** セキュリティ設定（Nginx認証プロキシ）
  - 7-1: Nginx + apache2-utilsインストール
  - 7-2: 認証情報作成（x-api-keyトークン + Basic認証htpasswd）
  - 7-3: Nginx設定（2つのserverブロック: Ollama API + 翻訳アプリ）
  - 7-4: 認証の動作テスト
  - 7-5: NiceGUIの起動ポート説明（localhost:8081）
- **Step 8:** Claude Code接続設定
  - 8-1: インストール（npm）
  - 8-2: 環境変数設定（Windows PowerShell/cmd、Mac/Linux対応）
  - 8-3: 起動方法
  - 8-4: 永続化（ユーザー環境変数 / .bashrc）
  - 8-5: VS Code拡張連携
- **Step 9:** Podの停止と再開（start.shスクリプト含む）
- **トラブルシューティング:** 分割GGUF、テンプレート問題、ポート問題、メモリ不足、Claude Code接続、Pod再起動後のモデル消失
- **費用まとめ + 実施ロードマップ + モデル情報**

-----

## 7. 実施ロードマップと現在のステータス

### Phase 1: RunPodセットアップ（Day 1-2）— 未着手

- [ ] RunPodアカウント作成、$25クレジット追加
- [ ] A100 PCIe 80GB Pod デプロイ
- [ ] Ollama インストール
- [ ] 公式 gpt-oss:120b から Harmony テンプレート抽出
- [ ] GPT-OSS-Swallow-120B GGUF ダウンロード（66.2GB, 20-40min）
- [ ] Modelfile作成、カスタムモデル登録
- [ ] 動作テスト（ターミナル + API）
- [ ] Nginx認証プロキシ設定、トークン生成

### Phase 2: ツール開発（Day 3-5）— 未着手

- [ ] Claude Code → RunPod Ollama 接続テスト
- [ ] NiceGUI翻訳Webアプリ開発・デプロイ（port 8081、Nginx経由で8080公開）
- [ ] コーディングデモシナリオ作成（PKGバッチ処理等）
- [ ] 画面録画環境準備

### Phase 3: 同僚デモ（Week 2）— 未着手

- [ ] 翻訳アプリURL + Basic認証情報を同僚に共有
- [ ] 使用状況モニタリング、フィードバック収集
- [ ] コーディングデモ画面録画
- [ ] 1-2分ハイライト動画作成

### Phase 4: 上司プレゼン — 未着手

- [ ] 翻訳アプリ使用実績まとめ
- [ ] コーディングデモ動画
- [ ] コスト比較資料（クラウド vs オンプレ）
- [ ] セキュリティ比較（Copilot vs クラウドGPU vs オンプレ）
- [ ] IT部門GPUサーバー予算申請

-----

## 8. 上司プレゼンのキーメッセージ

### ストーリーライン

1. **現状の課題:** 連結決算で90社のPKG処理に膨大な手作業。翻訳も手動。
2. **Copilotの限界:** 翻訳・コーディング支援には機能不足。
3. **デモ結果:** ローカルLLMで翻訳品質◎、コーディング支援◎を実証。
4. **セキュリティ:** クラウドでは機密データを扱えない → オンプレが必須。
5. **コスト:** ¥300K〜500Kの一括投資で1年で元が取れる。
6. **モデルの信頼性:** 日本の大学（東京科学大学）が開発、Apache 2.0、日本語性能最高。

### キラーフレーズ

- 「日本の大学が作った日本語特化モデルが、ChatGPTより日本語が上手い」
- 「データが社外に一切出ない。IT部門の承認もCopilotより容易」
- 「初期費用¥40万、ランニングコストは電気代のみ。1年で元が取れる」

-----

## 9. 技術的な注意事項・ハマりポイント

### 9-1: GGUF分割ファイル

大きなGGUFは `*-split-a.gguf`, `*-split-b.gguf` 等に分割されることがある。Modelfileでは最初のパート（`-split-a`）を指定すればOllamaが自動結合する。

### 9-2: Harmonyテンプレートの互換性

Swallow GGUFに公式gpt-oss:120bのテンプレートが正しく適用できるかは検証が必要。出力がおかしい場合（文字化け、制御トークンが見える等）は公式 `gpt-oss:120b` にフォールバック。

### 9-3: Claude Codeの環境変数

- `ANTHROPIC_BASE_URL` には `/v1` を**付けない**（Claude Codeが自動付与）
- `ANTHROPIC_API_KEY` の値がNginxの `x-api-key` 認証にそのまま使われる

### 9-4: NiceGUIのWebSocket

NiceGUIはWebSocketを使用するため、Nginxプロキシで `Upgrade` / `Connection` ヘッダーの転送が必須。設定済みの `nginx-auth-proxy.conf` に含まれている。

### 9-5: Ollamaのモデル自動切替

SwallowとQwen3は同時にVRAMにロードできない。Ollamaはリクエストされたモデルを自動ロード/アンロードするので、切り替え時に数十秒の待ち時間が発生する。

### 9-6: Pod Stop/Start vs Terminate

- **Stop/Start:** pod-idが変わらない。Volume Disk上のデータも保持。GPU課金停止、ストレージ課金のみ継続。
- **Terminate:** Podが完全削除される。Volume Diskは別途削除しない限り残るが、pod-idは変わる。

### 9-7: 推論レベル制御

GPT-OSSはシステムプロンプトで推論レベルを制御可能:

- `Reasoning: low` → 高速な一般対話
- `Reasoning: medium` → バランス（デフォルト）
- `Reasoning: high` → 深い分析

-----

## 10. 次にAIに頼む可能性が高いタスク

1. **NiceGUI翻訳Webアプリの開発**
   - Excel/CSVアップロード → 指定列を日本語→英語翻訳 → ダウンロード
   - Ollamaバックエンド（localhost:11435、Nginx経由ではなく直接）
   - ポート: localhost:8081で起動
   - デザイン: シンプル、同僚が迷わないUI
2. **コーディングデモシナリオの作成**
   - PKGファイルバッチ処理のPythonスクリプト生成デモ
   - Excel読み込み → 集計 → 異常値検出のデモ
   - Claude Code + Swallowでの画面録画シナリオ
3. **上司プレゼン資料の作成**
   - PowerPointまたはPDFでのコスト比較
   - セキュリティ比較表
   - デモ結果のスクリーンショット付き
4. **RunPodセットアップの実行支援**
   - ガイドに従った実際のセットアップ時のトラブルシュート

-----

## 11. 参考リンク

- **GPT-OSS-Swallow-120B:** HuggingFaceで検索（mmnga-o がGGUF提供）
- **RunPod:** https://www.runpod.io/
- **Ollama:** https://ollama.com/
- **Claude Code:** npm `@anthropic-ai/claude-code`
- **NiceGUI:** https://nicegui.io/
- **Codex CLI（将来用）:** npm `@openai/codex`、Issue #8240（リモートOllamaバグ）

-----

*作成日: 2026-02-21*  
*このドキュメントは `docs/RUNPOD_SETUP_GUIDE_SWALLOW_120B.md` と併せて使用してください*  
*用途: 将来構想（To-Be）/ 実装計画*
