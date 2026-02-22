# RunPod セットアップガイド

## GPT-OSS-Swallow-120B + Ollama + Claude Code（A100 80GB）

-----

## 全体像

```text
┌──────────────────────────────────────────────────────────────┐
│  RunPod A100 80GB Pod                                        │
│  ├── Nginx認証プロキシ                                       │
│  │   ├── :11434 (x-api-key) → Ollama (localhost:11435)       │
│  │   └── :8080  (Basic認証) → NiceGUI (localhost:8081)       │
│  ├── Ollama (localhost:11435)                                │
│  │   ├── gpt-oss-swallow:120b  ← コーディング               │
│  │   └── qwen3:30b-a3b         ← 翻訳（切替）               │
│  └── NiceGUI翻訳アプリ (localhost:8081)                      │
│      Volume Disk (100GB) ← モデル + アプリ + 認証設定        │
└──────────────────────────────────────────────────────────────┘
         ↑                              ↑
   Claude Code (自分のPC)         同僚のブラウザ
   x-api-keyトークンで認証        Basic認証でログイン
```

### モデル構成

|モデル|用途|サイズ|備考|
|---|---|---:|---|
|**GPT-OSS-Swallow-120B-RL** (IQ4_XS)|コーディング・フロー制御|~66GB|日本語最強（MT-Bench 0.916）|
|**Qwen3-30B-A3B**|翻訳|~18GB|同時ロード不可、切替使用|
|gpt-oss:120b (公式)|フォールバック|~66GB|テンプレ問題時の保険|

> ⚠️ GPT-OSS-Swallow は 2026/2/20 リリース。東京科学大学 + 産総研による日本語特化版。  
> 120B以下のオープンLLMで日本語タスク最高性能（クローズドモデル含めMT-Bench最高値）。

-----

## Step 1: RunPodアカウント作成

1. **https://www.runpod.io/** にアクセス
2. 右上の「Sign Up」をクリック
3. メールアドレスとパスワードで登録（Google/GitHubログインも可）
4. メール認証を完了

-----

## Step 2: クレジットを追加

1. ログイン後、左メニューの **「Billing」** をクリック
2. **「Add Credits」** をクリック
3. まず **$25** を入れる（2週間デモ分）
4. クレジットカードまたはPayPalで支払い

### 費用計画（2週間デモ）

|期間|内容|費用|
|---|---|---:|
|Week 1 (5日)|自己検証・アプリ開発（~15h）|$18|
|Week 2 (5日)|同僚向け翻訳アプリ公開（~45h）|$53|
|Storage|100GB Volume × 1ヶ月|$7|
|**合計**||**~$78（¥11,700）**|

> 💡 A100 PCIe 80GB = $1.19/hr。使わない時は必ずStop！

-----

## Step 3: Podをデプロイ

1. 左メニューの **「Pods」** をクリック
2. **「+ Deploy」** ボタンをクリック

### 3-1: GPUを選択

- **「A100」** の **「80 GB」** を選択
- PCIe と SXM がある場合、**PCIe（$1.19/hr）** で十分
- 「Community Cloud」でOK（安い）

### 3-2: テンプレートを選択

- **「PyTorch」** テンプレート（最新版）を選択

### 3-3: ポートとストレージの設定

- **「Customize Deployment」** をクリック

#### Expose HTTP Ports

```text
11434, 8080
```

（11434 = Ollama API、8080 = 翻訳Webアプリ）

#### Environment Variables

|Key|Value|
|---|---|
|`OLLAMA_HOST`|`0.0.0.0`|

#### Container Disk

- **20 GB**（OSとOllama本体用）

#### Volume Disk（永続ストレージ）

- **100 GB** に設定（Swallow GGUF ~66GB + Qwen3 ~18GB + アプリ）
- Volume Mount Path: `/workspace`

> ⚠️ Volume Diskがないと、Pod再起動時にモデルを再ダウンロードする必要があります

### 3-4: デプロイ

- **「Set Overrides」** → **「Deploy On-Demand」** をクリック
- Podの起動を待つ（1-3分程度）

-----

## Step 4: Ollamaをインストール

### 4-1: Web Terminalを開く

1. Podが **「Running」** になったら、Podの名前をクリック
2. **「Connect」** → **「Start Web Terminal」** → **「Connect to Web Terminal」**

### 4-2: Ollamaをインストール

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 4-3: Ollamaをバックグラウンドで起動

```bash
export OLLAMA_HOST=0.0.0.0
export OLLAMA_MODELS=/workspace/ollama_models
export OLLAMA_NUM_PARALLEL=4

ollama serve &

sleep 3
curl http://localhost:11434
# → "Ollama is running" と表示されればOK
```

-----

## Step 5: GPT-OSS-Swallow-120Bをセットアップ

### 5-1: 公式gpt-ossからHarmonyテンプレートを抽出

GPT-OSSはharmonyフォーマットという独自のチャットテンプレートを使います。  
まず公式モデルからテンプレートを取得します。

```bash
# 公式モデルをpull（テンプレート抽出用）
ollama pull gpt-oss:120b

# Modelfile（テンプレート含む）を抽出して保存
ollama show gpt-oss:120b --modelfile > /workspace/official-gptoss-modelfile.txt

# 内容を確認（TEMPLATE行とPARAMETER行をメモ）
cat /workspace/official-gptoss-modelfile.txt
```

> 💡 このファイルにはTEMPLATE、PARAMETER、SYSTEM等の全設定が含まれます

### 5-2: Swallow GGUFをダウンロード

```bash
# huggingface-cli をインストール
pip install huggingface_hub hf_transfer

# HF_HUB_ENABLE_HF_TRANSFERで高速ダウンロード
export HF_HUB_ENABLE_HF_TRANSFER=1

# IQ4_XS（66.2GB、imatrix日本語最適化）をダウンロード
huggingface-cli download \
  mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf \
  --include "*IQ4_XS*" \
  --local-dir /workspace/models/swallow-120b/
```

> ⚠️ ダウンロードに20-40分かかる場合があります。  
> ファイルが分割されている場合（.gguf-split-a, .gguf-split-bなど）、全パートが必要です。

### 5-3: Swallow用Modelfileを作成

```bash
# ダウンロードしたGGUFファイル名を確認
ls -la /workspace/models/swallow-120b/

# GGUFファイルパスを変数に（実際のファイル名に置き換え）
GGUF_PATH=$(ls /workspace/models/swallow-120b/*.gguf | head -1)
echo "GGUF: $GGUF_PATH"
```

Modelfileを作成します。`/workspace/official-gptoss-modelfile.txt` から  
TEMPLATE部分とPARAMETER部分を取り出し、FROMだけSwallowのGGUFに差し替えます：

```bash
cat > /workspace/Modelfile-swallow << 'MODELFILE_EOF'
# GPT-OSS-Swallow-120B-RL-v0.1 (IQ4_XS, imatrix日本語最適化)
# テンプレートは公式gpt-oss:120bから抽出

FROM /workspace/models/swallow-120b/【ここにGGUFファイル名】

# ↓↓↓ 以下を /workspace/official-gptoss-modelfile.txt の内容で置き換え ↓↓↓
# TEMPLATE """..."""
# PARAMETER ...
# SYSTEM ...
# ↑↑↑ テンプレート部分をここにコピペ ↑↑↑

MODELFILE_EOF
```

**具体的な手順：**

1. `/workspace/official-gptoss-modelfile.txt` をテキストエディタで開く
2. `FROM` 行以外の全内容（TEMPLATE、PARAMETER、SYSTEM等）をコピー
3. `/workspace/Modelfile-swallow` の該当部分に貼り付け
4. `FROM` 行を Swallow の GGUF パスに設定

> 💡 vi や nano が使えます：  
> `apt-get install -y nano`  
> `nano /workspace/Modelfile-swallow`

### 5-4: Ollamaにカスタムモデルとして登録

```bash
# Swallowモデルを作成
ollama create gpt-oss-swallow:120b -f /workspace/Modelfile-swallow

# 作成確認
ollama list
# gpt-oss-swallow:120b  が表示されればOK

# 動作テスト（日本語で質問）
ollama run gpt-oss-swallow:120b "連結決算における為替換算調整勘定について簡潔に説明してください"
```

### 5-5: ストレージ節約（オプション）

動作確認後、公式モデルを削除してストレージを節約できます：

```bash
# 公式gpt-oss:120bを削除（Swallowが動作確認済みの場合のみ）
ollama rm gpt-oss:120b

# 確認
ollama list
# gpt-oss-swallow:120b のみ残っていればOK
```

### 5-6: 翻訳用モデル（オプション・Week 2で追加）

```bash
# Qwen3 30B A3B（翻訳用、約18GB）
# ※ Swallowと同時ロードはできない（VRAM不足）
# Ollamaが自動的にモデルを切り替えてロードします
ollama pull qwen3:30b-a3b
```

-----

## Step 6: 動作テスト

### 6-1: ターミナルで直接テスト

```bash
# 日本語理解テスト
ollama run gpt-oss-swallow:120b "PKGファイルから90社分の連結パッケージを集計し、異常値がある会社を特定するPythonスクリプトを書いてください"

# 推論レベル変更テスト（systemプロンプト経由）
ollama run gpt-oss-swallow:120b "Reasoning: high\n\n日本の連結会計基準とIFRSの主な違いを3つ挙げてください"
```

### 6-2: API経由でテスト（外部アクセス確認）

> ⚠️ この時点ではまだ認証なしです。動作確認後、Step 7 で Nginx 認証を設定します。

RunPodのPod詳細画面で、**ポート11434のPublic URL**を確認：

```text
https://{pod-id}-11434.proxy.runpod.net
```

**自分のPCから：**

```bash
# 接続確認
curl https://{pod-id}-11434.proxy.runpod.net

# Chat Completions API テスト
curl https://{pod-id}-11434.proxy.runpod.net/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss-swallow:120b",
    "messages": [
      {"role": "user", "content": "Excelファイルを読み込んで特定列の合計を返すPython関数を書いて"}
    ]
  }'
```

レスポンスが返ってくれば成功！

### 6-3: テンプレートが正しく動作しない場合

もしSwallowモデルの出力がおかしい（文字化け、制御トークンが見える等）場合：

```bash
# フォールバック：公式gpt-oss:120bを再pullして使用
ollama pull gpt-oss:120b

# 公式版でテスト
ollama run gpt-oss:120b "Hello, can you help me write Python code?"
# → 正常に動作するならテンプレートの問題

# Swallowは翻訳WebアプリのみにしてCodingは公式版を使う等の使い分けも可能
```

-----

## Step 7: セキュリティ設定（Nginx認証）

Ollama APIも翻訳アプリもデフォルトで認証がありません。  
URLが漏洩するとGPUを無断利用される（＝課金が膨らむ）リスクがあるため、  
Nginxリバースプロキシで認証を追加します。

### 認証の仕組み

```text
Before（認証なし）:
  外部 → :11434 → Ollama（誰でもアクセス可能）
  外部 → :8080  → NiceGUI（誰でもアクセス可能）

After（Nginx認証）:
  Claude Code → :11434 → Nginx（x-api-key検証）→ Ollama（localhost:11435）
  ブラウザ    → :8080  → Nginx（Basic認証）   → NiceGUI（localhost:8081）
```

> 💡 **ポイント: クライアントに合わせた認証方式**  
> - **Ollama API（Claude Code用）:** `x-api-key` ヘッダー検証。  
>   Claude Code は `ANTHROPIC_API_KEY` を `x-api-key` として自動送信するため追加設定不要。  
> - **翻訳アプリ（ブラウザ用）:** Basic認証。  
>   ブラウザが自動的にユーザー名/パスワードのダイアログを表示する。

### 7-1: Nginxをインストール

```bash
apt-get update && apt-get install -y nginx apache2-utils
# apache2-utils: htpasswd コマンド（Basic認証用）
```

### 7-2: 認証情報を作成

```bash
# --- Ollama API用: x-api-keyトークン ---
export AUTH_TOKEN=$(openssl rand -hex 16)
echo "$AUTH_TOKEN" > /workspace/.auth_token
chmod 600 /workspace/.auth_token
echo "Ollama APIトークン: $AUTH_TOKEN"
echo "（Claude Code の ANTHROPIC_API_KEY に設定します）"

# --- 翻訳アプリ用: Basic認証 ---
# ユーザー名: demo  パスワード: お好みで設定
htpasswd -cb /workspace/.htpasswd demo "ここにパスワード"
chmod 600 /workspace/.htpasswd
echo "翻訳アプリ: ユーザー名 demo / 設定したパスワード"
echo "（同僚にはこのユーザー名とパスワードを共有します）"
```

> 💡 同僚全員で同じユーザー名/パスワードを共有する想定です。  
> ユーザーを追加したい場合: `htpasswd -b /workspace/.htpasswd user2 password2`

### 7-3: Nginx設定ファイルを作成

```bash
cat > /workspace/nginx-auth-proxy.conf << 'NGINX_EOF'
# ==========================================
# Ollama API（port 11434）: x-api-key 認証
# ==========================================
server {
    listen 11434;

    location / {
        # x-api-key ヘッダーでトークン検証
        set $auth_ok 0;
        if ($http_x_api_key = "AUTH_TOKEN_PLACEHOLDER") {
            set $auth_ok 1;
        }
        # Authorization: Bearer でも許可（汎用API互換）
        if ($http_authorization = "Bearer AUTH_TOKEN_PLACEHOLDER") {
            set $auth_ok 1;
        }
        if ($auth_ok = 0) {
            return 401 '{"error": "Unauthorized. x-api-key header required."}';
        }

        proxy_pass http://127.0.0.1:11435;
        proxy_set_header Host $host;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_buffering off;      # ストリーミング対応
    }
}

# ==========================================
# 翻訳Webアプリ（port 8080）: Basic認証
# ==========================================
server {
    listen 8080;

    location / {
        auth_basic "Mazda Finance Translation Demo";
        auth_basic_user_file /workspace/.htpasswd;

        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;

        # WebSocket対応（NiceGUIが使用）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX_EOF

# トークンを設定ファイルに埋め込み
AUTH_TOKEN=$(cat /workspace/.auth_token)
sed -i "s/AUTH_TOKEN_PLACEHOLDER/$AUTH_TOKEN/g" /workspace/nginx-auth-proxy.conf
```

> ⚠️ NiceGUIはWebSocketを使うため、`Upgrade` / `Connection` ヘッダーの転送が必須です。  
> これがないとアプリが正常に動作しません。

### 7-4: 認証の動作テスト

```bash
# Ollamaを内部ポートで起動
export OLLAMA_HOST=127.0.0.1:11435
export OLLAMA_MODELS=/workspace/ollama_models
ollama serve &
sleep 5

# Nginx起動
ln -sf /workspace/nginx-auth-proxy.conf /etc/nginx/sites-enabled/auth-proxy
rm -f /etc/nginx/sites-enabled/default
nginx -t && nginx -s reload 2>/dev/null || nginx

# --- Ollama API テスト ---
# 認証なし → 401
curl -s http://localhost:11434
# → {"error": "Unauthorized. x-api-key header required."}

# 認証あり → 正常
AUTH_TOKEN=$(cat /workspace/.auth_token)
curl -s -H "x-api-key: $AUTH_TOKEN" http://localhost:11434
# → "Ollama is running"

# --- 翻訳アプリ テスト ---
# ※ NiceGUIアプリがまだ無い段階では 502 Bad Gateway が返る（正常）
# Basic認証なし → 401
curl -s http://localhost:8080
# → 401 Authorization Required

# Basic認証あり → 502（アプリ未起動）or 200（アプリ起動済み）
curl -s -u demo:パスワード http://localhost:8080
# → NiceGUIが起動していれば 200 OK
```

### 7-5: NiceGUIアプリの起動ポート

翻訳アプリ開発時、NiceGUIを **ポート8081** で起動する必要があります：

```python
ui.run(host='127.0.0.1', port=8081)
```

-----

## Step 8: Claude Code 接続設定（自分のPC側）

### 8-1: Claude Code をインストール

```bash
# Node.js 18+ が必要（npm経由）
npm install -g @anthropic-ai/claude-code
```

### 8-2: 環境変数を設定

> ⚠️ `ANTHROPIC_API_KEY` には Step 7 で生成した認証トークンを設定してください。  
> この値がNginxの認証に使われるため、**「ollama」等の推測しやすい値は避けてください**。

**Windows（PowerShell）:**

```powershell
$env:ANTHROPIC_BASE_URL = "https://{pod-id}-11434.proxy.runpod.net"
$env:ANTHROPIC_API_KEY = "ここにStep7で生成したトークン"
$env:ANTHROPIC_MODEL = "gpt-oss-swallow:120b"
```

**Windows（コマンドプロンプト）:**

```cmd
set ANTHROPIC_BASE_URL=https://{pod-id}-11434.proxy.runpod.net
set ANTHROPIC_API_KEY=ここにStep7で生成したトークン
set ANTHROPIC_MODEL=gpt-oss-swallow:120b
```

**Mac / Linux:**

```bash
export ANTHROPIC_BASE_URL="https://{pod-id}-11434.proxy.runpod.net"
export ANTHROPIC_API_KEY="ここにStep7で生成したトークン"
export ANTHROPIC_MODEL="gpt-oss-swallow:120b"
```

### 8-3: Claude Codeを起動

```bash
cd /path/to/your/project
claude

# ワンライナーでタスクを指示
claude "このプロジェクトのREADMEを日本語で作成して"

# 公式gpt-ossモデルに切り替えたい場合（フォールバック）
ANTHROPIC_MODEL="gpt-oss:120b" claude
```

### 8-4: 永続化（オプション）

**Windows（ユーザー環境変数に追加）:**

```powershell
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_BASE_URL", "https://{pod-id}-11434.proxy.runpod.net", "User")
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "ここにトークン", "User")
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_MODEL", "gpt-oss-swallow:120b", "User")
```

**Mac / Linux（~/.bashrc または ~/.zshrc に追記）:**

```bash
echo 'export ANTHROPIC_BASE_URL="https://{pod-id}-11434.proxy.runpod.net"' >> ~/.bashrc
echo 'export ANTHROPIC_API_KEY="ここにトークン"' >> ~/.bashrc
echo 'export ANTHROPIC_MODEL="gpt-oss-swallow:120b"' >> ~/.bashrc
source ~/.bashrc
```

### 8-5: VS Code拡張からの利用

Claude Code の VS Code 拡張を使う場合も、同じ環境変数が適用されます。  
VS Code を**ターミナルから**起動すれば環境変数が引き継がれます：

```bash
code /path/to/your/project
```

-----

## Step 9: Podの停止と再開

### 使い終わったら必ず停止！

1. RunPodダッシュボードでPodの **「Stop」** ボタンをクリック
2. 停止中はGPU課金なし（ストレージ課金のみ: $0.07/GB/月 = 100GBで$7/月）

### 再開するとき

1. **「Start」** ボタンをクリック（1-2分で起動）
2. Web Terminalを開いて、起動スクリプトを実行：

```bash
/workspace/start.sh
```

### 起動スクリプト（初回に作成しておく）

```bash
cat > /workspace/start.sh << 'SCRIPT_EOF'
#!/bin/bash
echo "=== RunPod Ollama 起動スクリプト ==="

# Ollamaを内部ポートで起動（外部からは直接アクセス不可）
export OLLAMA_HOST=127.0.0.1:11435
export OLLAMA_MODELS=/workspace/ollama_models
export OLLAMA_NUM_PARALLEL=4

echo "Ollama起動中（内部ポート 11435）..."
ollama serve &
sleep 5

# Nginx認証プロキシ起動（外部:11434 → 内部:11435, 外部:8080 → 内部:8081）
echo "Nginx認証プロキシ起動中..."
ln -sf /workspace/nginx-auth-proxy.conf /etc/nginx/sites-enabled/auth-proxy
rm -f /etc/nginx/sites-enabled/default
nginx -t && (nginx -s reload 2>/dev/null || nginx)

echo ""
echo "=== 利用可能なモデル ==="
OLLAMA_HOST=127.0.0.1:11435 ollama list

echo ""
echo "=== 接続URL ==="
echo "Ollama API: このPodのポート11434のPublic URL（x-api-key認証）"
echo "翻訳アプリ: このPodのポート8080のPublic URL（Basic認証）"
echo ""
echo "Ollamaトークン: $(cat /workspace/.auth_token)"
echo "翻訳アプリ: ユーザー名 demo / 設定したパスワード"
echo ""
echo "All services ready! (Nginx認証プロキシ経由)"
SCRIPT_EOF

chmod +x /workspace/start.sh
```

-----

## トラブルシューティング

### Swallow GGUFファイルが分割されている場合

大きなGGUFは複数ファイルに分割されることがあります：

```bash
ls /workspace/models/swallow-120b/
# *-split-a.gguf, *-split-b.gguf, ... が見える場合

# Modelfileでは最初のパート（-split-a）を指定すればOllamaが自動結合
FROM /workspace/models/swallow-120b/GPT-OSS-Swallow-120B-RL-v0.1-IQ4_XS-split-a.gguf
```

### テンプレートの問題を診断

```bash
# 公式モデルのテンプレート内容を確認
ollama show gpt-oss:120b --modelfile | head -100

# Swallowモデルのテンプレート内容を確認
ollama show gpt-oss-swallow:120b --modelfile | head -100

# 差分を確認
diff <(ollama show gpt-oss:120b --modelfile) \
     <(ollama show gpt-oss-swallow:120b --modelfile)
```

### ポートにアクセスできない場合

```bash
# OllamaがリッスンしているIPを確認
curl http://localhost:11434
# → "Ollama is running" が出ればOK

echo $OLLAMA_HOST
# → 0.0.0.0 であること
```

### メモリ不足エラー

```bash
nvidia-smi
```

- IQ4_XS (66.2GB) でも不足する場合は IQ3_M (66.7GB) を試す
- それでもダメなら Q3_K_M (71.1GB) は使わず Q4_0 (66.2GB) を使用

### Claude Code がリモートOllamaに接続できない場合

```bash
# まずcurlで認証付きアクセスを確認
AUTH_TOKEN=$(cat /workspace/.auth_token)

# 認証なし → 401 が正常
curl -s https://{pod-id}-11434.proxy.runpod.net

# 認証あり → "Ollama is running" が正常
curl -s -H "x-api-key: $AUTH_TOKEN" https://{pod-id}-11434.proxy.runpod.net
```

### Pod再起動後にモデルが消えた

```bash
# Volume Diskの確認
ls /workspace/ollama_models/
ls /workspace/models/swallow-120b/

# OLLAMA_MODELS が正しく設定されているか確認
echo $OLLAMA_MODELS
# → /workspace/ollama_models であること
```

-----

## 費用まとめ

### 2週間デモプラン

|項目|費用|
|---|---:|
|Week 1: 自己検証 A100×15h|$18|
|Week 2: 同僚デモ A100×45h|$53|
|Volume Disk 100GB × 1ヶ月|$7|
|**合計**|**~$78（¥11,700）**|

### 上司への提案ポイント

|比較|月額|年額|
|---|---:|---:|
|RunPod常時利用（9h×22日）|¥35,000|¥420,000|
|**オンプレGPUサーバー（一括）**|—|**¥300,000〜500,000**|

> 💰 オンプレなら**1年で元が取れる**。しかもランニングコストは電気代のみ。

-----

## 実施ロードマップ

### Phase 1: RunPodセットアップ（Day 1-2）

- [ ] RunPodアカウント作成、$25クレジット追加
- [ ] A100 PCIe 80GB Pod デプロイ
- [ ] Ollama インストール
- [ ] 公式 gpt-oss:120b から Harmony テンプレート抽出
- [ ] GPT-OSS-Swallow-120B GGUF ダウンロード
- [ ] Modelfile作成、カスタムモデル登録
- [ ] 動作テスト（ターミナル + API）
- [ ] Nginx認証プロキシ設定、トークン生成

### Phase 2: ツール開発（Day 3-5）

- [ ] 自分のPCから Claude Code → RunPod Ollama 接続テスト
- [ ] NiceGUI翻訳Webアプリ開発・デプロイ（port 8080）
- [ ] コーディングデモシナリオ作成（PKGバッチ処理等）
- [ ] 画面録画環境準備

### Phase 3: 同僚デモ（Week 2）

- [ ] 翻訳アプリURL共有（メール）
- [ ] 使用状況モニタリング、フィードバック収集
- [ ] コーディングデモ画面録画
- [ ] 1-2分ハイライト動画作成

### Phase 4: 上司プレゼン

- [ ] 翻訳アプリ使用実績まとめ
- [ ] コーディングデモ動画
- [ ] コスト比較資料（クラウド vs オンプレ）
- [ ] IT部門GPUサーバー予算申請

-----

## モデル情報

### GPT-OSS-Swallow-120B-RL-v0.1

- **開発**: 東京科学大学 岡崎・横田研究室 + 産総研
- **ベース**: OpenAI gpt-oss-120b
- **手法**: 継続事前学習 + Reasoning SFT + RLVR
- **日本語性能**: 120B以下オープンLLM最高（日本語タスク平均 0.642）
- **MT-Bench**: 0.916（クローズドモデル含め最高値）
- **JamC-QA**: 元モデルから+11.4pt向上
- **ライセンス**: Apache 2.0
- **GGUF提供**: mmnga-o（HuggingFace、imatrix日本語最適化済み）
- **推奨量子化**: IQ4_XS（66.2GB、A100 80GBに余裕で搭載可）

### Harmonyフォーマットについて

GPT-OSSは独自の「harmony」チャットテンプレートを使用します。  
制御トークン: `<|start|>`, `<|end|>`, `<|message|>`, `<|channel|>` 等  
推論出力は `analysis` チャンネル、最終回答は `final` チャンネルに分離されます。  
Ollama公式のgpt-oss:120bにはこのテンプレートが組み込み済みですが、  
カスタムGGUF（Swallow等）の場合は手動でModelfileに設定が必要です。

-----

*作成日: 2026-02-21*  
*用途: 将来構想（To-Be）/ 実装計画*
