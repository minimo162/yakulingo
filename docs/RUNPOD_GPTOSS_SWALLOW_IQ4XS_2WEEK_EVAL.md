# RunPod GPT-OSS-Swallow-120B (IQ4_XS) 2週間チーム検証ガイド（LM Studio CLI / ヘッドレス版）

## 目的

`mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf` の
`IQ4_XS` 量子化を **2週間でチーム検証** し、複数人利用のローカルAI専用サーバ運用が成立するか判断する。

検証対象クライアントは次の2パターン:
- パターンA: LobeHub Webアプリ（ChatGPTライクなチャット利用）
- パターンB: VSCode拡張（Codex）からの接続利用

このガイドは `LM Studio CLI（lms） + RunPod + Nginx認証` 前提。  
**LM StudioデスクトップGUIは使わない（使えない）想定** で、全手順をCLIで実行する。

## 先に結論（弱点も含む）

- `IQ4_XS` の総サイズは **約61.65GiB**（6分割GGUF合計）で重い。
- `A40 x2` でも同時接続時はKVキャッシュで詰まりやすく、`context-length` と並列数の調整が必須。
- LM Studioは `chat/completions` と `/v1/responses` の両方を提供するが、クライアント互換や実装差で `responses` 側が詰まるケースがある（Codex直結の最大リスク）。
- LM Studio APIはデフォルトで認証不要のため、まずはNginxでトークン認証を前段に置くのが安全。
- 初期運用は **1ノード（A100 80GB x1 か A40 x2）**、拡張は実測（TTFB/tok/s/失敗率）で判断する。

## 運用方針（重要）

- 初期は **1ノード** で開始する。
- **2ノード化は利用者増加時の拡張オプション** とし、最初から常時2台運用しない。
- 拡張判断は実測値（TTFB、tok/s、同時接続時エラー率）で行う。
- 本番採用判定は **2パターン（LobeHub利用 / VSCode Codex接続）両方合格** を必須にする。
- 片系統のみ合格の場合は本番採用せず、「限定運用 + 再検証」に切り替える（詳細は評価基準章）。

## 初日チェックリスト（迷子防止）

初日に必須なのは Step 1〜11 の全量ではなく、次のサブセット。

| 区分 | 必須Step | 目的 | 完了条件 |
|---|---|---|---|
| 起動準備 | Step 1〜5 | Pod作成、LM Studio導入、モデルロード | `/v1/models` に `gpt-oss-swallow-120b-iq4xs` が表示される |
| GPU妥当性 | Step 5-1（A40 x2時は必須） | 2GPU分散有無と1GPU比較 | VRAM分布確認 + 短縮ベンチ比較ログ作成 |
| セキュリティ | Step 6 | Nginx認証プロキシ構築 | 未認証で401、認証付きで2xx |
| 再起動性 | Step 7 | 起動スクリプト/自動化準備 | `start.sh` または systemd で再現起動 |
| APIゲート | Step 8-1 / 8-2 | A/Bパターンの成立性を判定 | `chat` と `responses` の必要ゲートが2xx |
| コールドスタート | Step 9-0 | 朝イチ体感を記録 | `cold_start_ttfb.log` 作成 |
| 性能測定 | Step 9 | P95/成功率/tok/sの基準値取得 | `benchmark_step9_*_summary.log` 作成 |
| 会話継続率 | Step 9-1 / 9-2 | 3ターン継続を自動評価 | `conversation_continuity*_summary.txt` 作成 |

Day2以降で実施:
- Step 10（クライアント本接続）
- Step 11（コストガードレール自動化）
- 2週間の本評価（評価基準章）

## 初日実施フロー（依存関係）

```text
Step 1-5 (Pod+モデル起動)
  -> Step 5-1 (A40 x2時の1GPU比較)
  -> Step 6 (Nginx認証)
  -> Step 7 (再起動/監視)
  -> Step 8-1 (chatゲート) + Step 8-2 (responsesゲート)
       -> Step 8-2 不合格時のみ Step 8-3 (responses->chat 変換) -> Step 8-2再ゲート
  -> Step 9-0 (コールドスタートTTFB記録)
  -> Step 9 (性能計測)
  -> Step 9-1 (会話継続率: chat) / Step 9-2 (会話継続率: responses, 任意)
  -> Step 10 (クライアント接続)
  -> Step 11 (コストガードレール)
```

Go/No-Go（初日）:
- Step 8-1 が不合格: パターンAを保留し、Step 6/7を再点検してから再試験する
- Step 8-2 が不合格: Step 8-3 を適用し、再ゲートで `stream` が通るまで Step 10-B に進まない
- Step 9 で `HTTP成功率 < 98%` または `P95 TTFB > 8s`: 本番採用判定を保留し、並列数/コンテキストを下げて再計測する

現在地確認（迷子防止）:
- APIゲート完了: `/tmp/chat_gate_oneshot.json` `/tmp/resp_gate_stream.txt`
- ベンチ完了: `/workspace/logs/benchmark_step9_*_summary.log`
- 会話継続率完了: `/workspace/logs/conversation_continuity_*_summary.txt`

## スクリプト管理（差分レビュー用）

長いスクリプトは、ドキュメント内インラインに加えて以下へも同内容を配置している。

- `tools/runpod_eval/benchmark_step9.py`
- `tools/runpod_eval/responses_chat_proxy.py`
- `tools/runpod_eval/conversation_continuity_check.py`

更新時の運用ルール:
- スクリプト本体（`tools/runpod_eval/`）を先に更新する
- その後、ドキュメントの `cat > ...` ブロックと差分がないことを確認する

## 枝番ルール（追記時の混乱回避）

- 枝番は `-A`, `-B` を使う（例: `8-2A`）。
- 小数枝番（`8-2.5` など）は今後使わない。

## 検証パターン（2系統）

| パターン | 想定利用者 | 主API | 到達条件 |
|---|---|---|---|
| A: LobeHub Webアプリ（ChatGPTライク） | 非開発者・業務利用者 | `/v1/chat/completions` | Step 8-1 と Step 10-A を満たす |
| B: VSCode拡張（Codex） | 開発者 | `/v1/responses`（必要時はStep 8-3で変換） | Step 8-2 と Step 10-B/10-C を満たす |

注記:
- パターンAは LobeHub（サーバ側でAPIキー保持）を使い、ブラウザからRunPod APIを直接叩かない。
- パターンBは `wire_api` 互換性（特に `stream`）が成否を左右するため、初日にゲート判定する。

## API選定（用途別）

LM Studioは、互換性重視の `/v1/chat/completions` と、独自機能を使える `/v1/responses` の2系統を提供する。  
既存コードの移行容易性と、必要な機能で選ぶ。

| エンドポイント | 向く用途 | 主な機能 |
|---|---|---|
| `/v1/chat/completions` | 既存OpenAIコードを最小改修で移行したい | `messages` 形式、Function Calling（`tools`）、`stream: true` |
| `/v1/responses` | 会話状態をサーバー側で持たせたい/独自機能を使いたい | `previous_response_id`、SSE（`stream: true`）、`reasoning.effort`、Remote MCP（opt-in） |

選定ルール:
1. 既存資産を最小改修で使う場合は `chat/completions` を優先する。
2. サーバー側会話状態管理（`previous_response_id`）や推論深度制御（`reasoning.effort`）が必要なら `responses` を優先する。
3. 本ガイドでは、パターンAは `chat`、パターンBは `responses` を基本とし、Step 8のゲート結果で最終決定する。

## 構成

```text
┌──────────────────────────────────────────────────────────────┐
│  RunPod Pod                                                   │
│                                                              │
│  Nginx認証プロキシ                                            │
│   └─ :11434 (x-api-key / Bearer) → LM Studio :1234          │
│                                                              │
│  LM Studio (lms daemon, localhost:1234)                      │
│   └─ gpt-oss-swallow-120b-iq4xs (identifier)                │
│                                                              │
│  Volume Disk (/workspace, 推奨150〜200GB)                     │
│   ├─ Swallow IQ4_XS GGUF (~61.65GiB)                         │
│   ├─ LM Studio models/cache                                  │
│   └─ ログ / 設定 / 起動スクリプト                             │
└──────────────────────────────────────────────────────────────┘
```

## モデル情報（2026-02-22時点）

| 項目 | 値 |
|---|---|
| モデル | `mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf` |
| 量子化 | `IQ4_XS` |
| GGUF総サイズ | 約 61.65 GiB |
| 参考比較 | `Q4_K_M` は約 81.82 GiB（今回は初期2週間で容量/初回ダウンロード時間を優先し `IQ4_XS` を採用） |
| ライセンス | Apache 2.0（継承） |

## Step 1: RunPodでPodをデプロイ

1. RunPodで `Pods` → `+ Deploy`
2. GPUは `A100 80GB x1` または `A40 x2`
3. テンプレートは `PyTorch`

### 推奨設定

| 設定 | 値 |
|---|---|
| Expose HTTP Ports | `11434` |
| Container Disk | 30 GB |
| Volume Disk | 150〜200 GB |
| Volume Mount Path | `/workspace` |

### インスタンスタイプ方針（On-Demand / Spot）

- **デフォルトは On-Demand 前提** とする（2週間評価の再現性を優先）。
- Spotを使う場合は、Preemption（強制停止）を前提に以下を必須運用にする。
  - 1日1回以上の `benchmark_step9_*_summary.log` 退避
  - Step 11-7 のVolumeスナップショットを週次で実施
  - Preemption復旧後は Step 8-1 / 8-2 のゲートを再実行してから利用再開

### A40 x2 最小構成プロファイル（A100代替）

`A100 80GB x1` が高コストな場合の初期PoC向け。

| 項目 | 推奨値 |
|---|---|
| GPU | `NVIDIA A40 x2 (48GB x2)` |
| 同時接続開始値 | 1（まず1ユーザーで基準計測） |
| `context-length` | `4096` から開始（安定後に `8192` を試す） |
| 目標同時利用 | 2〜3人（短文中心） |
| スケール判断 | TTFB > 8s またはエラー率 > 2% が継続したら増強検討 |

### 通信/TLS前提（重要）

- 公開アクセスは **RunPodのHTTPSプロキシURL** を前提にする。
- Pod内の `127.0.0.1:1234` / `:11434` は平文HTTP。直接外部公開しない。
- RunPod外で流用する場合は、Nginx側でTLS終端（証明書設定）を必須にする。

## Step 2: LM Studio CLI（`lms`）をインストール（GUI不要）

```bash
nvidia-smi
free -h
df -h /workspace
command -v jq >/dev/null 2>&1 || (apt-get update && apt-get install -y jq)

# `curl | bash` を避け、取得後に保存してから実行する
# 注意: 公式が既知の正解ハッシュを提供していない場合、sha256は「記録」と「改ざん差分検知」用途に留まる。
# リスクを許容できない環境では、この手順を使わず社内アーティファクト（正解ハッシュ付き）経由に切り替える。
curl -fsSL https://lmstudio.ai/install.sh -o /tmp/lmstudio-install.sh
CALC_SHA256=$(sha256sum /tmp/lmstudio-install.sh | awk '{print $1}')
echo "install.sh sha256=${CALC_SHA256}"

# 社内で正解ハッシュを配布している場合のみ厳密検証する
EXPECTED_LMS_INSTALL_SHA256="${EXPECTED_LMS_INSTALL_SHA256:-}"
if [ -n "$EXPECTED_LMS_INSTALL_SHA256" ]; then
  echo "${EXPECTED_LMS_INSTALL_SHA256}  /tmp/lmstudio-install.sh" | sha256sum -c -
else
  echo "[WARN] EXPECTED_LMS_INSTALL_SHA256 未設定。厳密照合は未実施（社内配布値がある場合は設定して再実行）。"
fi
sed -n '1,200p' /tmp/lmstudio-install.sh
bash /tmp/lmstudio-install.sh

# パスが通っていない場合
export PATH="$HOME/.lmstudio/bin:$PATH"

lms --help
lms daemon up
```

## Step 3: Swallow IQ4_XS GGUFを取得

```bash
pip install -U huggingface_hub hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1

huggingface-cli download \
  mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf \
  --include "*IQ4_XS*" \
  --local-dir /workspace/models/swallow-120b/

ls -lh /workspace/models/swallow-120b/
```

## Step 4: LM StudioへGGUFを取り込み

```bash
# 先頭シャード（例: ...-00001-of-00006.gguf）を指定
FIRST_GGUF=$(ls /workspace/models/swallow-120b/*IQ4_XS*.gguf | sort | head -1)
echo "FIRST_GGUF=$FIRST_GGUF"

# 既存ファイルを移動せず、シンボリックリンクで取り込み
lms import "$FIRST_GGUF" \
  --user-repo mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf \
  --symbolic-link \
  -y

# 取り込み結果確認
lms ls --json | jq '.[] | {modelKey, path, sizeBytes}'
```

## Step 5: モデルロードとAPIサーバ起動

```bash
# モデル一覧を一時保存してから抽出（失敗時デバッグしやすくする）
LMS_MODELS_JSON=/tmp/lms_models_list.json
lms ls --json > "$LMS_MODELS_JSON"

# モデルキー抽出（IQ4_XSを優先）
MODEL_KEY=$(jq -r '.[] | select((.path|test("GPT-OSS-Swallow-120B-RL-v0.1-gguf"; "i")) and (.path|test("iq4_xs"; "i"))) | .modelKey' "$LMS_MODELS_JSON" | head -1)

if [ -z "$MODEL_KEY" ]; then
  echo "ERROR: IQ4_XSモデルが見つかりません。Step 4 を確認してください。"
  echo "DEBUG: lms ls paths (先頭20件)"
  jq -r '.[].path' "$LMS_MODELS_JSON" | head -20
  exit 1
fi

echo "MODEL_KEY=$MODEL_KEY"

# ランタイムプロファイルを固定（Step 5とstart.shで共通）
# A100: GPU_PROFILE=a100 / A40 x2: GPU_PROFILE=a40x2
GPU_PROFILE=${GPU_PROFILE:-a100}
case "$GPU_PROFILE" in
  a40x2)
    export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0,1}
    CONTEXT_LENGTH=${CONTEXT_LENGTH:-4096}
    ;;
  a100|*)
    CONTEXT_LENGTH=${CONTEXT_LENGTH:-8192}
    ;;
esac
echo "GPU_PROFILE=$GPU_PROFILE CONTEXT_LENGTH=$CONTEXT_LENGTH"

MODEL_ID="gpt-oss-swallow-120b-iq4xs"
lms load "$MODEL_KEY" \
  --identifier "$MODEL_ID" \
  --context-length "$CONTEXT_LENGTH" \
  --gpu max

# サーバ起動（localhost:1234）
if ! lms server status --json --quiet | jq -e '.running == true' >/dev/null 2>&1; then
  nohup lms server start --port 1234 > /workspace/lmstudio-server.log 2>&1 &
fi

# モデルがAPIで見えるまで待機（最大180秒）
READY=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:1234/v1/models >/tmp/lms_models.json 2>/dev/null; then
    if jq -e --arg id "$MODEL_ID" '.data[]? | select(.id == $id)' /tmp/lms_models.json >/dev/null 2>&1; then
      READY=1
      break
    fi
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: モデル $MODEL_ID が /v1/models に現れません（timeout）。"
  exit 1
fi
echo "READY: $MODEL_ID is available on /v1/models"
```

### A40 x2の事前指定（Step 5実行前・永続設定）

```bash
cat > /workspace/runtime.env << 'ENV_EOF'
GPU_PROFILE=a40x2
CUDA_VISIBLE_DEVICES=0,1
CONTEXT_LENGTH=4096
ENV_EOF
chmod 600 /workspace/runtime.env

# このシェルでStep 5を直ちに実行する場合のみ読み込む
set -a
source /workspace/runtime.env
set +a
```

### 5-1: A40 x2 マルチGPU実測チェック（初日必須）

`--gpu max` を指定しても、期待どおりに2枚へ分散されるとは限らない。  
初日に必ず「VRAM分布」と「1GPU比較」を確認する。

```bash
# 1) ロード直後のVRAM分布確認（両GPUが増えているか）
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader

# 2) 短文を10本投げて再確認（推論時の偏りを見る）
for i in $(seq 1 10); do
  curl -sS http://127.0.0.1:1234/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
      "model": "gpt-oss-swallow-120b-iq4xs",
      "messages": [{"role": "user", "content": "10行以内でPythonの入力バリデーション関数を書いて。"}],
      "max_tokens": 256
    }' >/dev/null
done

nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader
```

判定目安:
- GPU0/GPU1 の `memory.used` がどちらも有意に増加している
- 片側のみ増加する場合は、1GPUと2GPUで短縮ベンチを比較して採用可否を決める

```bash
# 単GPU比較（A40 x2 Podで実施）
cat > /workspace/runtime.env << 'ENV_EOF'
GPU_PROFILE=a40x2
CUDA_VISIBLE_DEVICES=0
CONTEXT_LENGTH=4096
ENV_EOF

# `runtime.env` を確実に反映するため、先にLM Studioを停止
export PATH="$HOME/.lmstudio/bin:$PATH"
lms server stop || true
lms daemon down || true

if [ -d /run/systemd/system ] && systemctl is-enabled swallow-lmstudio.service >/dev/null 2>&1; then
  systemctl restart swallow-lmstudio.service
else
  bash /workspace/start.sh
fi

# Step 9を短縮して比較（parallel=1, max_tokens=256, 10本）
```

比較後は2GPU設定に戻す:

```bash
cat > /workspace/runtime.env << 'ENV_EOF'
GPU_PROFILE=a40x2
CUDA_VISIBLE_DEVICES=0,1
CONTEXT_LENGTH=4096
ENV_EOF

# 設定を書き戻しただけでは反映されないため、再起動して2GPU構成へ戻す
if [ -d /run/systemd/system ] && systemctl is-enabled swallow-lmstudio.service >/dev/null 2>&1; then
  systemctl restart swallow-lmstudio.service
else
  bash /workspace/start.sh
fi
```

## Step 6: Nginx認証プロキシ構築

### 6-1: Nginxインストール

```bash
apt-get update

# `auth_request` を使うため、nginx-light ではなく nginx-full/nginx-extras を優先
if apt-cache show nginx-full >/dev/null 2>&1; then
  apt-get install -y nginx-full apache2-utils
elif apt-cache show nginx-extras >/dev/null 2>&1; then
  apt-get install -y nginx-extras apache2-utils
else
  apt-get install -y nginx apache2-utils
fi

# モジュール有無を明示チェック（なければここで停止）
nginx -V 2>&1 | grep -q -- 'http_auth_request_module' || {
  echo "ERROR: ngx_http_auth_request_module が見つかりません。nginx-full/nginx-extras を使用してください。"
  exit 1
}
```

### 6-2: APIトークン作成

```bash
SWALLOW_API_KEY=$(openssl rand -hex 24)
echo "$SWALLOW_API_KEY" > /workspace/.auth_token
chmod 600 /workspace/.auth_token
```

### 6-2A: 社内CIDR allowlist 作成（任意）

デフォルトでは設定しない。
社内ネットワーク/VPN経由のみに制限したい場合だけ作成する。

```bash
cat > /workspace/nginx-allowlist.conf << 'ALLOW_EOF'
# localhost health checks
allow 127.0.0.1;

# TODO: 必ず自社の送信元IP/CIDRに置換する
# 以下はサンプル（RFC 5737。実ネットでは使われない）
allow 203.0.113.10/32;
allow 198.51.100.0/24;

deny all;
ALLOW_EOF
```

### 6-3: Nginx設定（デフォルト: allowlist無効）

```bash
cat > /workspace/nginx-auth-proxy.conf << 'NGINX_EOF'
# `map` は http コンテキストで有効（sites-enabled 経由で http 内に include される）
map $http_x_api_key $auth_from_x_api_key {
    default 0;
    "AUTH_TOKEN_PLACEHOLDER" 1;
}

map $http_authorization $auth_from_bearer {
    default 0;
    "Bearer AUTH_TOKEN_PLACEHOLDER" 1;
}

map "$auth_from_x_api_key:$auth_from_bearer" $auth_status {
    default 401;
    "1:0" 204;
    "0:1" 204;
    "1:1" 204;
}

server {
    listen 11434;

    # /v1/responses と /v1/responses/（および query付き）を同一経路に固定する
    # 完全一致 (`=`) だと末尾スラッシュ付きで別locationに落ちるため使わない
    location ^~ /v1/responses {
        # Optional: 社内CIDR制限を使う場合のみ有効化（location / と同時適用）
        # include /workspace/nginx-allowlist.conf;

        auth_request /_auth_token_check;
        error_page 401 = @auth_failed;

        # デフォルトはLM Studioへ直送。非対応時はStep 8-3で127.0.0.1:18080へ切り替える
        proxy_pass http://127.0.0.1:1234/v1/responses;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_buffering off;
    }

    location / {
        # Optional: 社内CIDR制限を使う場合のみ有効化（/v1/responses 側にも同じincludeを入れる）
        # include /workspace/nginx-allowlist.conf;

        auth_request /_auth_token_check;
        error_page 401 = @auth_failed;

        proxy_pass http://127.0.0.1:1234;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_buffering off;
    }

    location = /_auth_token_check {
        internal;
        return $auth_status;
    }

    location @auth_failed {
        default_type application/json;
        return 401 '{"error":"Unauthorized. x-api-key required."}';
    }
}
NGINX_EOF

AUTH_TOKEN=$(cat /workspace/.auth_token)
# AUTH_TOKEN は openssl rand -hex 由来（[0-9a-f]）で本来エスケープ不要。
# 置換の保険として `\` `|` `&` をエスケープする。
AUTH_TOKEN_ESCAPED=$(printf '%s' "$AUTH_TOKEN" | sed -e 's/[\\|&]/\\&/g')
sed -i "s|AUTH_TOKEN_PLACEHOLDER|$AUTH_TOKEN_ESCAPED|g" /workspace/nginx-auth-proxy.conf
chmod 600 /workspace/nginx-auth-proxy.conf

# 注意: `nginx -T` を実行すると map 内のトークン平文が表示される。
# 共有端末/共有ログに出さない。必要時は必ずマスクして確認する。
# nginx -T 2>/dev/null | sed -E 's/(Bearer )[0-9a-f]+/\\1***MASKED***/g; s/"[0-9a-f]{16,}"/"***MASKED***"/g'

# Optional: allowlistを有効化する場合は2箇所同時に有効化する
# sed -i 's|# include /workspace/nginx-allowlist.conf;|include /workspace/nginx-allowlist.conf;|g' /workspace/nginx-auth-proxy.conf
```

### 6-4: Nginx有効化

```bash
mkdir -p /workspace/backup

ln -sf /workspace/nginx-auth-proxy.conf /etc/nginx/sites-enabled/auth-proxy
if [ -f /etc/nginx/sites-enabled/default ]; then
  cp /etc/nginx/sites-enabled/default /workspace/backup/nginx-default-site.conf
fi
rm -f /etc/nginx/sites-enabled/default
nginx -t && (nginx -s reload 2>/dev/null || nginx)

SWALLOW_API_KEY=$(cat /workspace/.auth_token)

curl -i http://localhost:11434/v1/models
curl http://localhost:11434/v1/models -H "x-api-key: $SWALLOW_API_KEY"
```

ロールバック（Step 6の設定を戻す場合）:

```bash
rm -f /etc/nginx/sites-enabled/auth-proxy
if [ -f /workspace/backup/nginx-default-site.conf ]; then
  ln -sf /workspace/backup/nginx-default-site.conf /etc/nginx/sites-enabled/default
fi
nginx -t && (nginx -s reload 2>/dev/null || nginx)
```

## Step 7: 起動スクリプト（初回のみ作成）

```bash
cat > /workspace/start.sh << 'SCRIPT_EOF'
#!/bin/bash
set -euo pipefail

echo "=== Swallow IQ4_XS (LM Studio) 起動スクリプト ==="

export PATH="$HOME/.lmstudio/bin:$PATH"
mkdir -p /workspace/logs
READY_FILE="/workspace/.lmstudio_ready"
START_FILE="/workspace/.lmstudio_starting"
GRACE_SECONDS=300

rm -f "$READY_FILE"
date +%s > "$START_FILE"

# 固定プロファイル（Step 5 と同じルール）
# 任意で /workspace/runtime.env に上書き値を置く
if [ -f /workspace/runtime.env ]; then
  set -a
  source /workspace/runtime.env
  set +a
fi

export GPU_PROFILE=${GPU_PROFILE:-a100}
case "$GPU_PROFILE" in
  a40x2)
    export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0,1}
    export CONTEXT_LENGTH=${CONTEXT_LENGTH:-4096}
    ;;
  a100|*)
    export CONTEXT_LENGTH=${CONTEXT_LENGTH:-8192}
    ;;
esac

lms daemon up

MODEL_ID="gpt-oss-swallow-120b-iq4xs"
if ! lms ps --json | jq -e --arg id "$MODEL_ID" '.[] | select(.identifier == $id)' >/dev/null 2>&1; then
  LMS_MODELS_JSON=/tmp/lms_models_start.json
  lms ls --json > "$LMS_MODELS_JSON"
  MODEL_KEY=$(jq -r '.[] | select((.path|test("GPT-OSS-Swallow-120B-RL-v0.1-gguf"; "i")) and (.path|test("iq4_xs"; "i"))) | .modelKey' "$LMS_MODELS_JSON" | head -1)
  if [ -z "$MODEL_KEY" ]; then
    echo "ERROR: IQ4_XSモデルが見つかりません。Step 4を再実行してください。"
    echo "DEBUG: lms ls paths (先頭20件)"
    jq -r '.[].path' "$LMS_MODELS_JSON" | head -20
    exit 1
  fi

  lms load "$MODEL_KEY" \
    --identifier "$MODEL_ID" \
    --context-length "$CONTEXT_LENGTH" \
    --gpu max
fi

if ! lms server status --json --quiet | jq -e '.running == true' >/dev/null 2>&1; then
  nohup lms server start --port 1234 > /workspace/logs/lmstudio-server.log 2>&1 &
fi

# モデルがAPIで見えるまで待機（最大180秒）
READY=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:1234/v1/models >/tmp/lms_models_start.json 2>/dev/null; then
    if jq -e --arg id "$MODEL_ID" '.data[]? | select(.id == $id)' /tmp/lms_models_start.json >/dev/null 2>&1; then
      READY=1
      break
    fi
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: モデル $MODEL_ID が /v1/models に現れません（timeout）。"
  exit 1
fi

ln -sf /workspace/nginx-auth-proxy.conf /etc/nginx/sites-enabled/auth-proxy
rm -f /etc/nginx/sites-enabled/default
nginx -t
nginx -s reload 2>/dev/null || nginx

echo "=== 起動完了 ==="
echo "API URL : RunPodの11434 Public URL"
TOKEN_RAW=$(tr -d '\n' < /workspace/.auth_token 2>/dev/null || true)
if [ -z "$TOKEN_RAW" ]; then
  TOKEN_TAIL="<empty>"
  echo "[WARN] /workspace/.auth_token が空です。Step 6-1 を再実行してください。"
else
  TOKEN_TAIL=$(printf '%s' "$TOKEN_RAW" | awk '{ if (length($0) >= 4) print substr($0, length($0)-3); else print $0 }')
fi
echo "API Key : (masked) ****${TOKEN_TAIL}"

# 起動完了フラグ
# 先にREADYを立ててからSTARTを下ろし、両方未作成の瞬間を作らない
touch "$READY_FILE"
rm -f "$START_FILE"

# 最大稼働時間タイマーが有効なら、起動ごとにカウントをリセット
if [ -d /run/systemd/system ] && systemctl is-enabled swallow-max-runtime-stop.timer >/dev/null 2>&1; then
  systemctl restart swallow-max-runtime-stop.timer >/dev/null 2>&1 || true
fi
SCRIPT_EOF

chmod +x /workspace/start.sh
```

### 7-1: 起動自動化（systemdが使える環境のみ）

```bash
if [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/swallow-lmstudio.service << 'UNIT_EOF'
[Unit]
Description=Swallow IQ4_XS Stack (LM Studio + Nginx)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/workspace
ExecStart=/workspace/start.sh
ExecStop=/bin/bash -lc 'export PATH="$HOME/.lmstudio/bin:$PATH"; lms server stop || true; lms daemon down || true'
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT_EOF

  systemctl daemon-reload
  systemctl enable swallow-lmstudio.service
  systemctl start swallow-lmstudio.service
  systemctl status swallow-lmstudio.service --no-pager
else
  echo "systemd非対応環境です。bash /workspace/start.sh を利用してください。"
fi
```

停止:

```bash
systemctl stop swallow-lmstudio.service || true
```

### 7-2: 監視再起動（systemd環境推奨）

`swallow-lmstudio.service` は `oneshot` で起動手順を実行するため、  
`lms server` と `Nginx(:11434) 認証経路` の異常を別途ヘルスチェックで補う。

誤発火を避けるため、再起動は `連続3回失敗` を条件にする（1分間隔タイマー前提で約3分）。  
あわせて `nvidia-smi` と `free -m` を毎分ログ化し、VRAM/RAM/SWAPの閾値超過を早期検知する。

```bash
if [ -d /run/systemd/system ]; then
  mkdir -p /workspace/scripts /workspace/logs

  cat > /workspace/scripts/lmstudio_watchdog.sh << 'WATCHDOG_EOF'
#!/usr/bin/env bash
set -euo pipefail

READY_FILE="/workspace/.lmstudio_ready"
START_FILE="/workspace/.lmstudio_starting"
FAIL_FILE="/workspace/.lmstudio_watchdog_failcount"
AUTH_TOKEN_FILE="/workspace/.auth_token"
GRACE_SECONDS=300
MAX_CONSECUTIVE_FAILS=3
CURL_TIMEOUT_SECONDS=15
VRAM_WARN_PCT=${VRAM_WARN_PCT:-95}
RAM_WARN_PCT=${RAM_WARN_PCT:-90}
SWAP_WARN_MIB=${SWAP_WARN_MIB:-1024}
NOW=$(date +%s)
mkdir -p /workspace

log_resource_state() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    while IFS=',' read -r used total; do
      used=$(echo "$used" | tr -d ' ')
      total=$(echo "$total" | tr -d ' ')
      if [ -n "$used" ] && [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
        vram_pct=$((used * 100 / total))
        echo "[INFO] gpu_vram used=${used}MiB total=${total}MiB pct=${vram_pct}%"
        if [ "$vram_pct" -ge "$VRAM_WARN_PCT" ]; then
          echo "[WARN] gpu_vram high: ${vram_pct}% (threshold=${VRAM_WARN_PCT}%)"
        fi
      fi
    done < <(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null || true)
  fi

  if command -v free >/dev/null 2>&1; then
    MEM_USED=$(free -m | awk '/^Mem:/ {print $3}')
    MEM_TOTAL=$(free -m | awk '/^Mem:/ {print $2}')
    SWAP_USED=$(free -m | awk '/^Swap:/ {print $3}')
    SWAP_TOTAL=$(free -m | awk '/^Swap:/ {print $2}')
    if [ -n "$MEM_USED" ] && [ -n "$MEM_TOTAL" ] && [ "$MEM_TOTAL" -gt 0 ] 2>/dev/null; then
      ram_pct=$((MEM_USED * 100 / MEM_TOTAL))
      echo "[INFO] ram used=${MEM_USED}MiB total=${MEM_TOTAL}MiB pct=${ram_pct}% swap_used=${SWAP_USED:-0}MiB swap_total=${SWAP_TOTAL:-0}MiB"
      if [ "$ram_pct" -ge "$RAM_WARN_PCT" ]; then
        echo "[WARN] ram high: ${ram_pct}% (threshold=${RAM_WARN_PCT}%)"
      fi
    fi
    if [ -n "${SWAP_USED:-}" ] && [ "$SWAP_USED" -ge "$SWAP_WARN_MIB" ] 2>/dev/null; then
      echo "[WARN] swap usage high: ${SWAP_USED}MiB (threshold=${SWAP_WARN_MIB}MiB)"
    fi
  fi
}

log_resource_state

# 起動処理中は再起動を抑止（最大GRACE_SECONDS）
if [ -f "$START_FILE" ]; then
  START_TS=$(cat "$START_FILE" 2>/dev/null || echo 0)
  ELAPSED=$((NOW - START_TS))

  # 起動直後は READY/START が同時に存在しうる。grace期間中は失敗カウントを積まない。
  if [ -f "$READY_FILE" ]; then
    if [ "$ELAPSED" -lt "$GRACE_SECONDS" ]; then
      echo "[INFO] ready+start during grace (${ELAPSED}s/${GRACE_SECONDS}s), skip watchdog"
      exit 0
    fi
    echo "[INFO] stale start marker after grace (${ELAPSED}s), clearing start marker"
    rm -f "$START_FILE"
    echo 0 > "$FAIL_FILE"
    exit 0
  fi

  if [ "$ELAPSED" -lt "$GRACE_SECONDS" ]; then
    echo "[INFO] startup in progress (${ELAPSED}s/${GRACE_SECONDS}s), skip watchdog"
    exit 0
  else
    echo "[WARN] startup marker is stale (${ELAPSED}s), restarting swallow-lmstudio.service"
    systemctl restart swallow-lmstudio.service
    echo 0 > "$FAIL_FILE"
    exit 0
  fi
fi

# 初回起動前（ready未作成）も再起動しない
if [ ! -f "$READY_FILE" ]; then
  echo "[INFO] ready file not found, skip watchdog"
  echo 0 > "$FAIL_FILE"
  exit 0
fi

LMS_OK=0
NGINX_OK=0

if curl -fsS --max-time "$CURL_TIMEOUT_SECONDS" http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
  LMS_OK=1
fi

if [ -r "$AUTH_TOKEN_FILE" ]; then
  AUTH_TOKEN=$(tr -d '\n' < "$AUTH_TOKEN_FILE")
  if [ -n "$AUTH_TOKEN" ] && curl -fsS --max-time "$CURL_TIMEOUT_SECONDS" \
    http://127.0.0.1:11434/v1/models \
    -H "x-api-key: $AUTH_TOKEN" >/dev/null 2>&1; then
    NGINX_OK=1
  fi
fi

if [ "$LMS_OK" -eq 1 ] && [ "$NGINX_OK" -eq 1 ]; then
  echo 0 > "$FAIL_FILE"
  exit 0
fi

if [ "$LMS_OK" -eq 1 ] && [ "$NGINX_OK" -ne 1 ]; then
  echo "[WARN] LM Studioは応答中だが Nginx(:11434) 認証経路が不健康です"
fi

FAIL_COUNT=0
if [ -f "$FAIL_FILE" ]; then
  FAIL_COUNT=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
fi
FAIL_COUNT=$((FAIL_COUNT + 1))
echo "$FAIL_COUNT" > "$FAIL_FILE"

if [ "$FAIL_COUNT" -lt "$MAX_CONSECUTIVE_FAILS" ]; then
  echo "[WARN] health check failed (${FAIL_COUNT}/${MAX_CONSECUTIVE_FAILS}), keep watching"
  exit 0
fi

echo "[WARN] health check failed ${MAX_CONSECUTIVE_FAILS} times, restarting swallow-lmstudio.service"
systemctl restart swallow-lmstudio.service
echo 0 > "$FAIL_FILE"
WATCHDOG_EOF

  chmod +x /workspace/scripts/lmstudio_watchdog.sh

  cat > /etc/systemd/system/swallow-lmstudio-watchdog.service << 'UNIT_EOF'
[Unit]
Description=LM Studio API watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/workspace
ExecStart=/bin/bash -lc '/workspace/scripts/lmstudio_watchdog.sh >> /workspace/logs/lmstudio-watchdog.log 2>&1'
UNIT_EOF

  cat > /etc/systemd/system/swallow-lmstudio-watchdog.timer << 'TIMER_EOF'
[Unit]
Description=Run LM Studio watchdog every minute

[Timer]
OnCalendar=*:0/1
Persistent=true

[Install]
WantedBy=timers.target
TIMER_EOF

  systemctl daemon-reload
  systemctl enable --now swallow-lmstudio-watchdog.timer
  systemctl status swallow-lmstudio-watchdog.timer --no-pager
else
  echo "systemd非対応: 外部監視（Uptime Kuma等）で /v1/models を監視してください。"
fi
```

## Step 8: APIテスト

### 8-0: トークン読込（共通）

```bash
if [ -z "${SWALLOW_API_KEY:-}" ]; then
  if [ -r /workspace/.auth_token ]; then
    export SWALLOW_API_KEY="$(tr -d '\n' < /workspace/.auth_token)"
  else
    export SWALLOW_API_KEY="${SWALLOW_API_KEY:-<Step 6で作成したトークン>}"
  fi
fi
```

### Pod内

```bash
SWALLOW_API_KEY="${SWALLOW_API_KEY:-$(cat /workspace/.auth_token)}"

curl http://localhost:11434/v1/models \
  -H "x-api-key: $SWALLOW_API_KEY"

curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d '{
    "model": "gpt-oss-swallow-120b-iq4xs",
    "messages": [{"role": "user", "content": "Pythonでバリデータを作って。"}],
    "max_tokens": 512
  }'
```

### 自PC

```bash
export SWALLOW_API_KEY="${SWALLOW_API_KEY:-<Step 6で作成したトークン>}"

curl https://{pod-id}-11434.proxy.runpod.net/v1/models \
  -H "x-api-key: $SWALLOW_API_KEY"
```

### 8-1: LobeHub Webアプリ（ChatGPTライク）疎通ゲート（必須）

パターンA（LobeHub利用）を評価するため、`/v1/chat/completions` で  
**単発会話** と **履歴付き会話（2ターン目）** の両方を確認する。

```bash
export SWALLOW_API_KEY="${SWALLOW_API_KEY:-<Step 6で作成したトークン>}"
export BASE_URL="https://{pod-id}-11434.proxy.runpod.net"

# 単発会話
HTTP_CODE_CHAT_ONESHOT=$(curl -sS -o /tmp/chat_gate_oneshot.json -w "%{http_code}" \
  "${BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d '{
    "model": "gpt-oss-swallow-120b-iq4xs",
    "messages": [{"role": "user", "content": "3行で自己紹介してください。"}],
    "max_tokens": 128
  }')
echo "chat_http_oneshot=$HTTP_CODE_CHAT_ONESHOT"
cat /tmp/chat_gate_oneshot.json

# 履歴付き会話（2ターン目）
HTTP_CODE_CHAT_MULTI=$(curl -sS -o /tmp/chat_gate_multi.json -w "%{http_code}" \
  "${BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d '{
    "model": "gpt-oss-swallow-120b-iq4xs",
    "messages": [
      {"role": "user", "content": "Pythonの辞書内包表記を1文で説明して。"},
      {"role": "assistant", "content": "辞書内包表記は、反復処理からキーと値を同時に作って辞書を簡潔に生成する書き方です。"},
      {"role": "user", "content": "では簡単な例を1つ。"}
    ],
    "max_tokens": 128
  }')
echo "chat_http_multi=$HTTP_CODE_CHAT_MULTI"
cat /tmp/chat_gate_multi.json
```

判定:
- `oneshot` / `multi` がともに `200` or `201`: Step 10-A（LobeHub接続）へ進む
- `401/403`: 認証/allowlist設定を見直し（Step 6）
- `5xx` や timeout: `swallow-lmstudio.service` 再起動後に再試験
- `2xx` だが応答本文が空/壊れている: モデルロード状態・Nginx経路・ログ（`/workspace/logs`）を確認

### 8-2: Codex `wire_api=responses` 疎通ゲート（必須）

`wire_api=responses` を使う場合、`/v1/responses` の **non-stream / stream 両方** を先に確認する。  
ここが通らないと Codex直結検証は成立しないため、初日に必ず実施する。

```bash
export SWALLOW_API_KEY="${SWALLOW_API_KEY:-<Step 6で作成したトークン>}"
export BASE_URL="https://{pod-id}-11434.proxy.runpod.net"

# 1) non-streamゲート
HTTP_CODE_NON_STREAM=$(curl -sS -o /tmp/resp_gate_non_stream.json -w "%{http_code}" \
  "${BASE_URL}/v1/responses" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d '{
    "model": "gpt-oss-swallow-120b-iq4xs",
    "input": "疎通確認です。OKだけ返してください。",
    "stream": false,
    "max_output_tokens": 32
  }')

echo "responses_http_non_stream=$HTTP_CODE_NON_STREAM"
cat /tmp/resp_gate_non_stream.json

# 2) streamゲート（SSEが返るか確認）
HTTP_CODE_STREAM=$(curl -sS -N --connect-timeout 10 --max-time 120 -o /tmp/resp_gate_stream.txt -w "%{http_code}" \
  "${BASE_URL}/v1/responses" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d '{
    "model": "gpt-oss-swallow-120b-iq4xs",
    "input": "stream疎通確認です。短く答えてください。",
    "stream": true,
    "max_output_tokens": 32
  }')

echo "responses_http_stream=$HTTP_CODE_STREAM"
head -n 20 /tmp/resp_gate_stream.txt

STREAM_EVENT_OK=0
if grep -Eq 'response\.completed|\[DONE\]' /tmp/resp_gate_stream.txt && \
   grep -Eq 'response\.output_text\.delta|response\.output_text\.done|"delta"' /tmp/resp_gate_stream.txt; then
  STREAM_EVENT_OK=1
fi
echo "responses_stream_event_ok=$STREAM_EVENT_OK"
```

判定:
- `non-stream` と `stream` がともに `200` or `201` かつ `responses_stream_event_ok=1`: Step 10-B（`wire_api="responses"`）へ進む
- `400/404/405/501` が出る: `responses` 互換不足の可能性が高い。Step 8-3 を実施
- `401/403`: 認証/allowlist設定を見直し（Step 6, トラブルシューティング）
- `5xx` や timeout: `swallow-lmstudio.service` 再起動後に再試験し、改善しなければ Step 8-3 へ進む
- `non-stream` は通るが `stream` が失敗、または `responses_stream_event_ok=0`: Step 8-3 を導入し、再度 `stream` ゲートを通してから Step 10-B を使う

### 8-2A: `previous_response_id` 継続確認（任意・状態管理を使う場合）

`responses` の利点（サーバー側会話状態管理）を使う予定がある場合のみ実施する。

```bash
export SWALLOW_API_KEY="${SWALLOW_API_KEY:-<Step 6で作成したトークン>}"
export BASE_URL="${BASE_URL:-https://{pod-id}-11434.proxy.runpod.net}"
MODEL_ID="gpt-oss-swallow-120b-iq4xs"

PAYLOAD1=$(jq -nc --arg model "$MODEL_ID" '{
  model: $model,
  input: "この会話では合言葉を「青い林檎」にしてください。理解したらOKだけ返してください。",
  stream: false,
  max_output_tokens: 64
}')

HTTP_CODE_STATE_1=$(curl -sS -o /tmp/resp_state_1.json -w "%{http_code}" \
  "${BASE_URL}/v1/responses" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d "$PAYLOAD1")

RESP_ID=$(jq -r '.id // empty' /tmp/resp_state_1.json)
echo "responses_http_state_1=$HTTP_CODE_STATE_1 resp_id=${RESP_ID:-<empty>}"
cat /tmp/resp_state_1.json

if [ -n "$RESP_ID" ]; then
  PAYLOAD2=$(jq -nc --arg model "$MODEL_ID" --arg prev "$RESP_ID" '{
    model: $model,
    input: "先ほどの合言葉を1語で答えてください。",
    previous_response_id: $prev,
    stream: false,
    max_output_tokens: 32
  }')

  HTTP_CODE_STATE_2=$(curl -sS -o /tmp/resp_state_2.json -w "%{http_code}" \
    "${BASE_URL}/v1/responses" \
    -H "Content-Type: application/json" \
    -H "x-api-key: $SWALLOW_API_KEY" \
    -d "$PAYLOAD2")

  echo "responses_http_state_2=$HTTP_CODE_STATE_2"
  cat /tmp/resp_state_2.json
fi
```

判定:
- `state_1/state_2` が2xxで、2本目が前ターン制約を保持できる: `previous_response_id` 利用可
- `id` が返らない、または2本目が失敗: 状態管理は使わず、`chat/completions`（毎回履歴送信）かStep 8-3で運用

### 8-3: フォールバック（`responses -> chat/completions` 変換プロキシ）

`/v1/responses` が通らない場合の具体手順。  
以下で `127.0.0.1:18080` に変換プロキシを立て、Nginxの `/v1/responses` だけをそこへルーティングする。

重要:
- この方式では `previous_response_id` によるサーバー側状態管理は実質使えない（毎回 `chat/completions` へ変換するため）。
- `reasoning.effort` や Remote MCP の透過動作は保証しない。
- リポジトリをPodにclone済みなら、`tools/runpod_eval/responses_chat_proxy.py` を `/workspace/scripts/` にコピーして使ってよい。

```bash
export SWALLOW_API_KEY="${SWALLOW_API_KEY:-<Step 6で作成したトークン>}"
export BASE_URL="https://{pod-id}-11434.proxy.runpod.net"

mkdir -p /workspace/scripts /workspace/logs
command -v pip >/dev/null 2>&1 || (apt-get update && apt-get install -y python3-pip)

# 再現性のため依存バージョンを固定（latest追随を避ける）
FASTAPI_VER=0.116.1
UVICORN_VER=0.35.0
HTTPX_VER=0.28.1
pip install \
  "fastapi==${FASTAPI_VER}" \
  "uvicorn[standard]==${UVICORN_VER}" \
  "httpx==${HTTPX_VER}"

cat > /workspace/scripts/responses_chat_proxy.py << 'PY_EOF'
#!/usr/bin/env python3
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

UPSTREAM_BASE_URL = os.getenv("UPSTREAM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-oss-swallow-120b-iq4xs")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "600"))
HTTP_TIMEOUT = httpx.Timeout(REQUEST_TIMEOUT, connect=30.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        app.state.http_client = client
        yield


app = FastAPI(lifespan=lifespan)


def _safe_json_from_response(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except Exception:
        return {"error": {"message": "upstream returned non-json", "raw": response.text[:2000]}}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _extract_text_chunks(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            chunks.extend(_extract_text_chunks(item))
        return chunks
    if isinstance(value, dict):
        dict_chunks: list[str] = []
        value_type = value.get("type")
        if value_type == "input_text" and "text" in value:
            dict_chunks.append(str(value.get("text", "")))
        if isinstance(value.get("content"), str):
            dict_chunks.append(value["content"])
        if isinstance(value.get("content"), (list, dict)):
            dict_chunks.extend(_extract_text_chunks(value["content"]))
        if "text" in value and value_type != "input_text":
            dict_chunks.append(str(value.get("text", "")))
        if "input" in value:
            dict_chunks.extend(_extract_text_chunks(value.get("input")))
        return dict_chunks
    return [str(value)]


def to_input_text(value: Any) -> str:
    return "\n".join([chunk for chunk in _extract_text_chunks(value) if chunk])


def to_chat_messages(input_field: Any, instructions: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if instructions:
        messages.append({"role": "system", "content": str(instructions)})

    if isinstance(input_field, list):
        for item in input_field:
            if isinstance(item, dict) and "role" in item:
                role = str(item.get("role", "user")).lower()
                if role == "developer":
                    role = "system"
                if role not in {"system", "user", "assistant"}:
                    role = "user"
                content = to_input_text(item.get("content", item.get("input", "")))
                if content:
                    messages.append({"role": role, "content": content})
            else:
                text = to_input_text(item)
                if text:
                    messages.append({"role": "user", "content": text})
    else:
        text = to_input_text(input_field)
        if text:
            messages.append({"role": "user", "content": text})

    if not any(m["role"] == "user" for m in messages):
        fallback = to_input_text(input_field)
        if fallback:
            messages.append({"role": "user", "content": fallback})
    return messages


def upstream_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if UPSTREAM_API_KEY:
        headers["x-api-key"] = UPSTREAM_API_KEY
    return headers


def to_chat_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    model = payload.get("model", DEFAULT_MODEL)
    instructions = payload.get("instructions", "")
    messages = to_chat_messages(payload.get("input", ""), str(instructions))
    max_tokens = payload.get("max_output_tokens", payload.get("max_tokens", 512))

    chat_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": bool(payload.get("stream", False)),
    }
    for key in ("temperature", "top_p", "frequency_penalty", "presence_penalty", "stop", "seed"):
        if key in payload:
            chat_payload[key] = payload[key]
    return model, chat_payload


def _sse_line(obj: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@app.get("/v1/models")
async def passthrough_models(request: Request):
    client = get_client(request)
    r = await client.get(
        f"{UPSTREAM_BASE_URL}/models",
        headers=upstream_headers(),
    )
    return JSONResponse(status_code=r.status_code, content=_safe_json_from_response(r))


@app.post("/v1/responses")
async def responses_to_chat(request: Request):
    payload = await request.json()
    model, chat_payload = to_chat_payload(payload)
    stream_requested = bool(chat_payload.get("stream", False))
    client = get_client(request)

    if not stream_requested:
        r = await client.post(
            f"{UPSTREAM_BASE_URL}/chat/completions",
            headers=upstream_headers(),
            json=chat_payload,
        )

        body = _safe_json_from_response(r)
        if r.status_code >= 400:
            return JSONResponse(status_code=r.status_code, content=body)

        choices = body.get("choices", [])
        output_text = ""
        if choices:
            output_text = str(choices[0].get("message", {}).get("content", ""))

        usage = body.get("usage", {})
        response_body = {
            "id": body.get("id", f"resp_{uuid.uuid4().hex}"),
            "object": "response",
            "created_at": body.get("created", int(time.time())),
            "model": body.get("model", model),
            "output_text": output_text,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": output_text}],
                }
            ],
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }
        return JSONResponse(status_code=200, content=response_body)

    upstream = client.build_request(
        "POST",
        f"{UPSTREAM_BASE_URL}/chat/completions",
        headers=upstream_headers(),
        json=chat_payload,
    )
    stream = await client.send(upstream, stream=True)

    if stream.status_code >= 400:
        body = await stream.aread()
        await stream.aclose()
        try:
            parsed = json.loads(body.decode("utf-8", errors="ignore"))
        except Exception:
            parsed = {"error": {"message": "upstream error", "raw": body.decode('utf-8', errors='ignore')[:2000]}}
        return JSONResponse(status_code=stream.status_code, content=parsed)

    response_id = f"resp_{uuid.uuid4().hex}"
    created_at = int(time.time())

    async def event_generator():
        output_parts: list[str] = []
        usage: dict[str, Any] = {}

        yield _sse_line(
            {
                "type": "response.created",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "created_at": created_at,
                    "model": model,
                },
            }
        )

        try:
            async for line in stream.aiter_lines():
                if await request.is_disconnected():
                    break
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                if not isinstance(chunk, dict):
                    continue

                choice0 = (chunk.get("choices") or [{}])[0]
                delta = (choice0.get("delta") or {}).get("content", "")
                if delta:
                    output_parts.append(str(delta))
                    yield _sse_line({"type": "response.output_text.delta", "delta": str(delta)})

                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
        finally:
            await stream.aclose()

        output_text = "".join(output_parts)
        yield _sse_line({"type": "response.output_text.done", "text": output_text})
        yield _sse_line(
            {
                "type": "response.completed",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "created_at": created_at,
                    "model": model,
                    "output_text": output_text,
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": output_text}],
                        }
                    ],
                    "usage": {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                },
            }
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
PY_EOF

cat > /workspace/scripts/responses-chat-proxy.env << 'ENV_EOF'
UPSTREAM_BASE_URL=http://127.0.0.1:1234/v1
UPSTREAM_API_KEY=
DEFAULT_MODEL=gpt-oss-swallow-120b-iq4xs
REQUEST_TIMEOUT=600
ENV_EOF
chmod 600 /workspace/scripts/responses-chat-proxy.env

if [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/swallow-responses-proxy.service << 'UNIT_EOF'
[Unit]
Description=Responses to Chat completion proxy
After=network-online.target swallow-lmstudio.service
Wants=network-online.target swallow-lmstudio.service

[Service]
Type=simple
WorkingDirectory=/workspace/scripts
EnvironmentFile=/workspace/scripts/responses-chat-proxy.env
ExecStart=/usr/bin/env bash -lc 'python3 -m uvicorn responses_chat_proxy:app --host 127.0.0.1 --port 18080'
Restart=always
RestartSec=5
StandardOutput=append:/workspace/logs/responses-proxy.log
StandardError=append:/workspace/logs/responses-proxy.log

[Install]
WantedBy=multi-user.target
UNIT_EOF

  systemctl daemon-reload
  systemctl enable --now swallow-responses-proxy.service
  systemctl status swallow-responses-proxy.service --no-pager
else
  nohup bash -lc 'cd /workspace/scripts && set -a && source /workspace/scripts/responses-chat-proxy.env && set +a && python3 -m uvicorn responses_chat_proxy:app --host 127.0.0.1 --port 18080' \
    >/workspace/logs/responses-proxy.log 2>&1 &
fi

# Nginxの /v1/responses だけを変換プロキシへ向ける
cp /workspace/nginx-auth-proxy.conf /workspace/nginx-auth-proxy.conf.before_step8_3
sed -i 's|proxy_pass http://127.0.0.1:1234/v1/responses;|proxy_pass http://127.0.0.1:18080/v1/responses;|g' /workspace/nginx-auth-proxy.conf
nginx -t && (nginx -s reload 2>/dev/null || nginx)

# 再ゲート（non-stream + stream）
HTTP_CODE_NON_STREAM=$(curl -sS -o /tmp/resp_gate_retry_non_stream.json -w "%{http_code}" \
  "${BASE_URL}/v1/responses" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d '{
    "model": "gpt-oss-swallow-120b-iq4xs",
    "input": "疎通確認です。OKだけ返してください。",
    "stream": false,
    "max_output_tokens": 32
  }')
echo "responses_http_retry_non_stream=$HTTP_CODE_NON_STREAM"
cat /tmp/resp_gate_retry_non_stream.json

HTTP_CODE_STREAM=$(curl -sS -N --connect-timeout 10 --max-time 120 -o /tmp/resp_gate_retry_stream.txt -w "%{http_code}" \
  "${BASE_URL}/v1/responses" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "x-api-key: $SWALLOW_API_KEY" \
  -d '{
    "model": "gpt-oss-swallow-120b-iq4xs",
    "input": "stream再ゲート確認です。短く答えてください。",
    "stream": true,
    "max_output_tokens": 32
  }')
echo "responses_http_retry_stream=$HTTP_CODE_STREAM"
head -n 20 /tmp/resp_gate_retry_stream.txt

STREAM_RETRY_EVENT_OK=0
if grep -Eq 'response\.completed|\[DONE\]' /tmp/resp_gate_retry_stream.txt && \
   grep -Eq 'response\.output_text\.delta|response\.output_text\.done|"delta"' /tmp/resp_gate_retry_stream.txt; then
  STREAM_RETRY_EVENT_OK=1
fi
echo "responses_retry_stream_event_ok=$STREAM_RETRY_EVENT_OK"
```

ロールバック（Step 8-3 適用前に戻す）:

```bash
if [ -d /run/systemd/system ]; then
  systemctl disable --now swallow-responses-proxy.service || true
  rm -f /etc/systemd/system/swallow-responses-proxy.service
  systemctl daemon-reload
else
  pkill -f "uvicorn responses_chat_proxy:app --host 127.0.0.1 --port 18080" || true
fi

if [ -f /workspace/nginx-auth-proxy.conf.before_step8_3 ]; then
  cp /workspace/nginx-auth-proxy.conf.before_step8_3 /workspace/nginx-auth-proxy.conf
else
  sed -i 's|proxy_pass http://127.0.0.1:18080/v1/responses;|proxy_pass http://127.0.0.1:1234/v1/responses;|g' /workspace/nginx-auth-proxy.conf
fi
nginx -t && (nginx -s reload 2>/dev/null || nginx)
```

補足:
- 利用中のCodexバージョンが `wire_api="chat"` を公式サポートしている場合のみ、Step 10-C の `chat` 設定を使ってよい。
- `wire_api="chat"` が不明/非対応なら、この変換プロキシを前提に Step 10-B（`responses`）を使う。
- Step 10-B を使う条件は、再ゲートの `non-stream` と `stream` がともに2xxかつ `responses_retry_stream_event_ok=1` であること。
- `instructions` は `chat/completions` の `system` メッセージにマッピングして欠落を防ぐ。
- ストリーミングはSSEで中継する。`response.output_text.delta` / `response.completed` が流れることを確認する。
- 変換プロキシ経由では `previous_response_id` / `reasoning.effort` / Remote MCP の利用を前提にしない。

## Step 9-0: コールドスタートTTFB記録（初日必須）

ウォームアップ後のP95とは別に、**再起動直後1本目** のTTFBを記録する。  
朝イチ体感の評価に使うため、Step 9 の集計には混ぜない。

```bash
SWALLOW_API_KEY="${SWALLOW_API_KEY:-$(tr -d '\n' < /workspace/.auth_token)}"
BASE_URL_COLD="${BASE_URL_COLD:-http://127.0.0.1:11434}"
MODEL_ID="gpt-oss-swallow-120b-iq4xs"

if [ -d /run/systemd/system ]; then
  systemctl restart swallow-lmstudio.service
else
  bash /workspace/start.sh
fi

# 起動待ち（最大180秒）
for _ in $(seq 1 90); do
  if curl -fsS "${BASE_URL_COLD}/v1/models" -H "x-api-key: ${SWALLOW_API_KEY}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

mkdir -p /workspace/logs
curl -sS -o /tmp/cold_start_response.json \
  -w "time_namelookup=%{time_namelookup} time_connect=%{time_connect} time_starttransfer=%{time_starttransfer} time_total=%{time_total} http=%{http_code}\n" \
  "${BASE_URL_COLD}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${SWALLOW_API_KEY}" \
  -d "{
    \"model\": \"${MODEL_ID}\",
    \"messages\": [{\"role\":\"user\",\"content\":\"コールドスタート計測です。OKだけ返してください。\"}],
    \"max_tokens\": 32
  }" | tee /workspace/logs/cold_start_ttfb.log
```

## Step 9: ベンチ計測（初日必須: 30本 + P95）

評価基準と同じ条件で計測する。  
**重要:** サーバ純性能とE2E体感を混同しないよう、計測先を分ける。

- 短文: `max_tokens=256` を各並列（1/2/3）で30本
- 中長文: `max_tokens=1024` を各並列（1/2/3）で10本
- ウォームアップ: `max_tokens=128` を10本（集計から除外）
- 集計: `HTTP成功率`、`P95 TTFB`、`P95 total`、`tok/s中央値`
- `P95` と `tok/s` の算出対象は **2xx成功リクエストのみ**（失敗は成功率にのみ反映）
- 基準計測（必須）: Pod内LM Studio直結 `http://127.0.0.1:1234`
- ゲートウェイ計測（推奨）: Pod内Nginx経由 `http://127.0.0.1:11434`
- E2E計測（任意）: 公開URL `https://{pod-id}-11434.proxy.runpod.net`
- `tok/s` は `completion_tokens / (total - ttfb)`（デコード区間推定）で計算する。公開URL計測ではRTTを含むため、GPU比較は `BASE_URL_LMS_LOCAL` を一次指標にする
- APIキーは `curl --config <file>` で渡し、プロセス引数への平文露出を避ける
- リポジトリをPodにclone済みなら、`tools/runpod_eval/benchmark_step9.py` を `/workspace/scripts/` にコピーして使ってよい

```bash
export SWALLOW_API_KEY="${SWALLOW_API_KEY:-$(tr -d '\n' < /workspace/.auth_token)}"
export BASE_URL_LMS_LOCAL="http://127.0.0.1:1234"
export BASE_URL_NGINX_LOCAL="http://127.0.0.1:11434"
export BASE_URL_PUBLIC="https://{pod-id}-11434.proxy.runpod.net"
mkdir -p /workspace/scripts /workspace/logs

cat > /workspace/scripts/benchmark_step9.py << 'PY_EOF'
#!/usr/bin/env python3
import argparse
import csv
import json
import math
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

JA_PROMPT = "次の要件を満たすPythonのCSVパーサー用ユニットテストを作成してください。境界値、空行、引用符、文字コード混在を含める。"
EN_PROMPT = "Write Python unit tests for a CSV parser, covering edge cases, quotes, empty rows, and encoding issues."
MODEL_ID = "gpt-oss-swallow-120b-iq4xs"
METRICS_RE = re.compile(r"HTTP=(\d+) TOTAL=([0-9.]+) TTFB=([0-9.]+)")


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, math.ceil(len(ordered) * pct / 100) - 1)
    return ordered[idx]


def make_payload(tokens: int, rid: int) -> dict:
    prompt = JA_PROMPT if rid % 2 == 0 else EN_PROMPT
    return {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": tokens,
    }


def run_one(
    base_url: str,
    api_key: str,
    parallel: int,
    tokens: int,
    rid: int,
    connect_timeout: float,
    max_time: float,
) -> dict:
    payload = make_payload(tokens=tokens, rid=rid)
    with tempfile.NamedTemporaryFile(prefix=f"step9_{parallel}_{tokens}_{rid}_", suffix=".json", delete=False) as tf:
        resp_path = Path(tf.name)
    curl_cfg_path: Path | None = None
    # APIキーをプロセス引数に露出させないため、curl --config を使う
    with tempfile.NamedTemporaryFile(prefix="step9_curl_", suffix=".cfg", delete=False, mode="w", encoding="utf-8") as cf:
        curl_cfg_path = Path(cf.name)
        cf.write('header = "Content-Type: application/json"\n')
        cf.write(f'header = "x-api-key: {api_key}"\n')

    cmd = [
        "curl",
        "-sS",
        "--connect-timeout",
        str(connect_timeout),
        "--max-time",
        str(max_time),
        "--config",
        str(curl_cfg_path),
        f"{base_url}/v1/chat/completions",
    ]
    cmd.extend(
        [
            "-d",
            json.dumps(payload, ensure_ascii=False),
            "-o",
            str(resp_path),
            "-w",
            "HTTP=%{http_code} TOTAL=%{time_total} TTFB=%{time_starttransfer}",
        ]
    )

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    metrics_line = proc.stdout.strip()
    m = METRICS_RE.search(metrics_line)

    http_code = 0
    total = 0.0
    ttfb = 0.0
    if m:
        http_code = int(m.group(1))
        total = float(m.group(2))
        ttfb = float(m.group(3))

    completion_tokens = 0
    try:
        body = json.loads(resp_path.read_text(encoding="utf-8", errors="ignore"))
        completion_tokens = int((body.get("usage") or {}).get("completion_tokens") or 0)
    except Exception:
        completion_tokens = 0
    finally:
        resp_path.unlink(missing_ok=True)
        if curl_cfg_path is not None:
            curl_cfg_path.unlink(missing_ok=True)

    decode_window = max(total - ttfb, 0.0)
    tok_per_sec = (completion_tokens / decode_window) if (completion_tokens > 0 and decode_window > 0) else 0.0

    return {
        "parallel": parallel,
        "tokens": tokens,
        "req_id": rid,
        "http": http_code,
        "total": total,
        "ttfb": ttfb,
        "completion_tokens": completion_tokens,
        "tok_per_sec": tok_per_sec,
        "stderr": proc.stderr.strip(),
    }


def warmup(base_url: str, api_key: str, connect_timeout: float, max_time: float, n: int = 10) -> None:
    for rid in range(1, n + 1):
        _ = run_one(
            base_url,
            api_key,
            parallel=1,
            tokens=128,
            rid=rid,
            connect_timeout=connect_timeout,
            max_time=max_time,
        )


def run_case(
    base_url: str,
    api_key: str,
    parallel: int,
    tokens: int,
    reqs: int,
    connect_timeout: float,
    max_time: float,
) -> list[dict]:
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futures = [
            ex.submit(
                run_one,
                base_url,
                api_key,
                parallel,
                tokens,
                rid,
                connect_timeout,
                max_time,
            )
            for rid in range(1, reqs + 1)
        ]
        for f in as_completed(futures):
            rows.append(f.result())
    rows.sort(key=lambda x: x["req_id"])
    return rows


def summarize(rows: list[dict], parallel: int, tokens: int, reqs: int) -> str:
    target = [r for r in rows if r["parallel"] == parallel and r["tokens"] == tokens]
    ok = [r for r in target if 200 <= r["http"] < 300]
    success_rate = (len(ok) / len(target) * 100) if target else 0.0
    p95_ttfb = percentile([r["ttfb"] for r in ok], 95)
    p95_total = percentile([r["total"] for r in ok], 95)
    tokps_median = percentile([r["tok_per_sec"] for r in ok], 50)
    fail_count = len(target) - len(ok)
    return (
        f"parallel={parallel} tokens={tokens} reqs={reqs} "
        f"success_rate={success_rate:.2f}% ok={len(ok)} fail={fail_count} "
        f"p95_ttfb={(p95_ttfb if p95_ttfb is not None else float('nan')):.3f}s "
        f"p95_total={(p95_total if p95_total is not None else float('nan')):.3f}s "
        f"tokps_median={(tokps_median if tokps_median is not None else float('nan')):.3f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--csv-log", required=True)
    parser.add_argument("--summary-log", required=True)
    parser.add_argument("--short-tokens", type=int, default=256)
    parser.add_argument("--short-reqs", type=int, default=30)
    parser.add_argument("--long-tokens", type=int, default=1024)
    parser.add_argument("--long-reqs", type=int, default=10)
    parser.add_argument("--parallels", default="1,2,3")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--max-time", type=float, default=180.0)
    parser.add_argument("--warmup-reqs", type=int, default=10)
    parser.add_argument("--short-only", action="store_true")
    args = parser.parse_args()

    parallels = [int(x.strip()) for x in args.parallels.split(",") if x.strip()]
    rows: list[dict] = []

    warmup(
        args.base_url,
        args.api_key,
        connect_timeout=args.connect_timeout,
        max_time=args.max_time,
        n=args.warmup_reqs,
    )

    for par in parallels:
        rows.extend(
            run_case(
                args.base_url,
                args.api_key,
                par,
                args.short_tokens,
                args.short_reqs,
                connect_timeout=args.connect_timeout,
                max_time=args.max_time,
            )
        )

    if not args.short_only:
        for par in parallels:
            rows.extend(
                run_case(
                    args.base_url,
                    args.api_key,
                    par,
                    args.long_tokens,
                    args.long_reqs,
                    connect_timeout=args.connect_timeout,
                    max_time=args.max_time,
                )
            )

    csv_path = Path(args.csv_log)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["parallel", "tokens", "req_id", "http", "total", "ttfb", "completion_tokens", "tok_per_sec"])
        for r in rows:
            writer.writerow([
                r["parallel"],
                r["tokens"],
                r["req_id"],
                r["http"],
                f"{r['total']:.6f}",
                f"{r['ttfb']:.6f}",
                r["completion_tokens"],
                f"{r['tok_per_sec']:.6f}",
            ])

    summary_lines = [f"# summary: {datetime.now().isoformat(timespec='seconds')} base_url={args.base_url}"]
    for par in parallels:
        summary_lines.append(summarize(rows, par, args.short_tokens, args.short_reqs))
    if not args.short_only:
        for par in parallels:
            summary_lines.append(summarize(rows, par, args.long_tokens, args.long_reqs))

    summary_path = Path(args.summary_log)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))
    print(f"raw_csv: {csv_path}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
PY_EOF

chmod +x /workspace/scripts/benchmark_step9.py

python3 /workspace/scripts/benchmark_step9.py \
  --base-url "$BASE_URL_LMS_LOCAL" \
  --api-key "$SWALLOW_API_KEY" \
  --csv-log /workspace/logs/benchmark_step9_lms_local.csv \
  --summary-log /workspace/logs/benchmark_step9_lms_local_summary.log

# 推奨: Pod内Nginx経由（認証/プロキシ含む）も別ファイルで取得
python3 /workspace/scripts/benchmark_step9.py \
  --base-url "$BASE_URL_NGINX_LOCAL" \
  --api-key "$SWALLOW_API_KEY" \
  --csv-log /workspace/logs/benchmark_step9_nginx_local.csv \
  --summary-log /workspace/logs/benchmark_step9_nginx_local_summary.log

# 任意: E2E（RunPod公開URL経由）も別ファイルで取得
python3 /workspace/scripts/benchmark_step9.py \
  --base-url "$BASE_URL_PUBLIC" \
  --api-key "$SWALLOW_API_KEY" \
  --csv-log /workspace/logs/benchmark_step9_public.csv \
  --summary-log /workspace/logs/benchmark_step9_public_summary.log
```

A40 x2 の1GPU比較（Step 5-1用）を行う場合:

```bash
python3 /workspace/scripts/benchmark_step9.py \
  --base-url "$BASE_URL_LMS_LOCAL" \
  --api-key "$SWALLOW_API_KEY" \
  --csv-log /workspace/logs/benchmark_step9_short_only.csv \
  --summary-log /workspace/logs/benchmark_step9_short_only_summary.log \
  --short-only \
  --short-reqs 10 \
  --parallels 1
```

## Step 9-1: 会話継続率の自動計測（初日必須）

評価基準で使う「3ターン連続で前ターン制約を維持」を手動で30会話実施するのは負荷が高いため、  
**2ユーザー同時（各15会話）** を模擬した自動判定スクリプトを使う。  
同一スクリプトで `chat/completions`（パターンA）と `responses + previous_response_id`（パターンB）の両方を計測できる。
リポジトリをPodにclone済みなら、`tools/runpod_eval/conversation_continuity_check.py` を `/workspace/scripts/` にコピーして使ってよい。

```bash
export SWALLOW_API_KEY="${SWALLOW_API_KEY:-$(tr -d '\n' < /workspace/.auth_token)}"
export BASE_URL_NGINX_LOCAL="${BASE_URL_NGINX_LOCAL:-http://127.0.0.1:11434}"
export BASE_URL_PUBLIC="${BASE_URL_PUBLIC:-https://{pod-id}-11434.proxy.runpod.net}"

cat > /workspace/scripts/conversation_continuity_check.py << 'PY_EOF'
#!/usr/bin/env python3
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import error, request

MODEL_ID = "gpt-oss-swallow-120b-iq4xs"


def post_json(url: str, api_key: str, payload: dict, timeout: float) -> tuple[int, dict]:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw) if raw else {}
            return int(resp.status), parsed if isinstance(parsed, dict) else {"data": parsed}
    except error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"_raw": raw[:2000]}
        return int(e.code), parsed if isinstance(parsed, dict) else {"data": parsed}
    except Exception as e:
        return 0, {"_error": str(e)}


def extract_chat_text(body: dict) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return str(msg.get("content") or "").strip()


def extract_response_text(body: dict) -> str:
    if isinstance(body.get("output_text"), str) and body.get("output_text"):
        return str(body.get("output_text")).strip()
    output = body.get("output") or []
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = str(content.get("text") or "").strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def run_conversation_chat(base_url: str, api_key: str, timeout: float, conv_id: int, user_id: int) -> dict:
    keyword = f"KEY-{conv_id:03d}-AOIRINGO"
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    messages: list[dict[str, str]] = []

    turn1_user = f"この会話の合言葉は「{keyword}」です。合言葉だけを1語で返してください。"
    messages.append({"role": "user", "content": turn1_user})
    payload1 = {"model": MODEL_ID, "messages": messages, "max_tokens": 64}
    http1, body1 = post_json(url, api_key, payload1, timeout)
    turn1_text = extract_chat_text(body1)
    messages.append({"role": "assistant", "content": turn1_text})

    turn2_user = "もう一度、同じ合言葉だけを返してください。"
    messages.append({"role": "user", "content": turn2_user})
    payload2 = {"model": MODEL_ID, "messages": messages, "max_tokens": 64}
    http2, body2 = post_json(url, api_key, payload2, timeout)
    turn2_text = extract_chat_text(body2)
    messages.append({"role": "assistant", "content": turn2_text})

    turn3_user = "合言葉を含む短い日本語文を1文だけ返してください。"
    messages.append({"role": "user", "content": turn3_user})
    payload3 = {"model": MODEL_ID, "messages": messages, "max_tokens": 64}
    http3, body3 = post_json(url, api_key, payload3, timeout)
    turn3_text = extract_chat_text(body3)

    all_2xx = all(200 <= code < 300 for code in (http1, http2, http3))
    turn2_ok = keyword in turn2_text
    turn3_ok = keyword in turn3_text
    continued = bool(all_2xx and turn2_ok and turn3_ok)

    return {
        "api_mode": "chat",
        "user_id": user_id,
        "conv_id": conv_id,
        "keyword": keyword,
        "http1": http1,
        "http2": http2,
        "http3": http3,
        "state_id_chain_ok": 1,
        "turn2_ok": int(turn2_ok),
        "turn3_ok": int(turn3_ok),
        "continued": int(continued),
        "turn2_text": turn2_text[:200],
        "turn3_text": turn3_text[:200],
    }


def run_conversation_responses(base_url: str, api_key: str, timeout: float, conv_id: int, user_id: int) -> dict:
    keyword = f"KEY-{conv_id:03d}-AOIRINGO"
    url = f"{base_url.rstrip('/')}/v1/responses"

    turn1_payload = {
        "model": MODEL_ID,
        "input": f"この会話の合言葉は「{keyword}」です。合言葉だけを1語で返してください。",
        "stream": False,
        "max_output_tokens": 64,
    }
    http1, body1 = post_json(url, api_key, turn1_payload, timeout)
    turn1_text = extract_response_text(body1)
    resp_id_1 = str(body1.get("id") or "")

    turn2_text = ""
    turn3_text = ""
    http2 = 0
    http3 = 0
    resp_id_2 = ""
    resp_id_3 = ""

    if resp_id_1:
        turn2_payload = {
            "model": MODEL_ID,
            "input": "もう一度、同じ合言葉だけを返してください。",
            "previous_response_id": resp_id_1,
            "stream": False,
            "max_output_tokens": 64,
        }
        http2, body2 = post_json(url, api_key, turn2_payload, timeout)
        turn2_text = extract_response_text(body2)
        resp_id_2 = str(body2.get("id") or "")

        if resp_id_2:
            turn3_payload = {
                "model": MODEL_ID,
                "input": "合言葉を含む短い日本語文を1文だけ返してください。",
                "previous_response_id": resp_id_2,
                "stream": False,
                "max_output_tokens": 64,
            }
            http3, body3 = post_json(url, api_key, turn3_payload, timeout)
            turn3_text = extract_response_text(body3)
            resp_id_3 = str(body3.get("id") or "")

    all_2xx = all(200 <= code < 300 for code in (http1, http2, http3))
    turn2_ok = keyword in turn2_text
    turn3_ok = keyword in turn3_text
    state_id_chain_ok = bool(resp_id_1 and resp_id_2 and resp_id_3)
    continued = bool(all_2xx and state_id_chain_ok and turn2_ok and turn3_ok)

    return {
        "api_mode": "responses",
        "user_id": user_id,
        "conv_id": conv_id,
        "keyword": keyword,
        "http1": http1,
        "http2": http2,
        "http3": http3,
        "state_id_chain_ok": int(state_id_chain_ok),
        "turn2_ok": int(turn2_ok),
        "turn3_ok": int(turn3_ok),
        "continued": int(continued),
        "turn2_text": turn2_text[:200],
        "turn3_text": turn3_text[:200],
        "turn1_id": resp_id_1[:80],
        "turn2_id": resp_id_2[:80],
        "turn3_id": resp_id_3[:80],
        "turn1_text": turn1_text[:200],
    }


def run_conversation(api_mode: str, base_url: str, api_key: str, timeout: float, conv_id: int, user_id: int) -> dict:
    if api_mode == "responses":
        return run_conversation_responses(base_url, api_key, timeout, conv_id, user_id)
    return run_conversation_chat(base_url, api_key, timeout, conv_id, user_id)


def run_user_batch(api_mode: str, base_url: str, api_key: str, timeout: float, user_id: int, conv_start: int, conv_count: int) -> list[dict]:
    rows: list[dict] = []
    for conv_id in range(conv_start, conv_start + conv_count):
        rows.append(run_conversation(api_mode, base_url, api_key, timeout, conv_id, user_id))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--csv-log", required=True)
    parser.add_argument("--summary-log", required=True)
    parser.add_argument("--users", type=int, default=2)
    parser.add_argument("--conversations-per-user", type=int, default=15)
    parser.add_argument("--conversations", type=int, default=0, help="0の場合は users * conversations-per-user")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--api-mode", choices=["chat", "responses"], default="chat")
    args = parser.parse_args()

    if args.users < 1:
        raise ValueError("--users は1以上を指定してください")
    if args.conversations_per_user < 1 and args.conversations <= 0:
        raise ValueError("--conversations-per-user は1以上を指定してください（--conversations指定時を除く）")

    total_conversations = args.conversations if args.conversations > 0 else args.users * args.conversations_per_user
    if total_conversations < 1:
        raise ValueError("総会話数が0です。--conversations または --conversations-per-user を見直してください")

    base = total_conversations // args.users
    extra = total_conversations % args.users
    plans: list[tuple[int, int, int]] = []
    conv_cursor = 1
    for user_id in range(1, args.users + 1):
        conv_count = base + (1 if user_id <= extra else 0)
        plans.append((user_id, conv_cursor, conv_count))
        conv_cursor += conv_count

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.users) as ex:
        futures = [
            ex.submit(run_user_batch, args.api_mode, args.base_url, args.api_key, args.timeout, user_id, conv_start, conv_count)
            for (user_id, conv_start, conv_count) in plans
            if conv_count > 0
        ]
        for f in as_completed(futures):
            rows.extend(f.result())
    rows.sort(key=lambda r: r["conv_id"])

    csv_path = Path(args.csv_log)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["api_mode", "user_id", "conv_id", "keyword", "http1", "http2", "http3", "state_id_chain_ok", "turn2_ok", "turn3_ok", "continued", "turn2_text", "turn3_text"]
        )
        for r in rows:
            writer.writerow(
                [
                    r["api_mode"],
                    r["user_id"],
                    r["conv_id"],
                    r["keyword"],
                    r["http1"],
                    r["http2"],
                    r["http3"],
                    r.get("state_id_chain_ok", 0),
                    r["turn2_ok"],
                    r["turn3_ok"],
                    r["continued"],
                    r["turn2_text"],
                    r["turn3_text"],
                ]
            )

    total = len(rows)
    passed = sum(r["continued"] for r in rows)
    rate = (passed / total * 100) if total else 0.0
    state_chain_ok = sum(r.get("state_id_chain_ok", 0) for r in rows)
    summary = (
        f"api_mode={args.api_mode}\n"
        f"users={args.users}\n"
        f"conversations_per_user_target={args.conversations_per_user}\n"
        f"conversations={total}\n"
        f"continued={passed}\n"
        f"state_id_chain_ok={state_chain_ok}\n"
        f"continuity_rate={rate:.2f}%\n"
        "definition=ユーザー並行実行。3ターン連続2xxかつturn2/turn3で合言葉維持（responsesはresponse_id連鎖も必須）\n"
    )

    summary_path = Path(args.summary_log)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")
    print(summary.strip())
    print(f"raw_csv: {csv_path}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
PY_EOF

chmod +x /workspace/scripts/conversation_continuity_check.py

# パターンA基準値（推奨: Pod内Nginx経由）
python3 /workspace/scripts/conversation_continuity_check.py \
  --base-url "$BASE_URL_NGINX_LOCAL" \
  --api-key "$SWALLOW_API_KEY" \
  --api-mode chat \
  --csv-log /workspace/logs/conversation_continuity_nginx_local.csv \
  --summary-log /workspace/logs/conversation_continuity_summary.txt \
  --users 2 \
  --conversations-per-user 15

# 任意: E2E（公開URL経由）で体感差を確認
python3 /workspace/scripts/conversation_continuity_check.py \
  --base-url "$BASE_URL_PUBLIC" \
  --api-key "$SWALLOW_API_KEY" \
  --api-mode chat \
  --csv-log /workspace/logs/conversation_continuity_public.csv \
  --summary-log /workspace/logs/conversation_continuity_public_summary.txt \
  --users 2 \
  --conversations-per-user 15

# パターンB（responses + previous_response_id）継続率を確認（推奨）
python3 /workspace/scripts/conversation_continuity_check.py \
  --base-url "$BASE_URL_NGINX_LOCAL" \
  --api-key "$SWALLOW_API_KEY" \
  --api-mode responses \
  --csv-log /workspace/logs/conversation_continuity_responses_nginx_local.csv \
  --summary-log /workspace/logs/conversation_continuity_responses_summary.txt \
  --users 2 \
  --conversations-per-user 15
```

## Step 9-2: パターンB会話継続率の扱い（responses運用時は必須）

- Step 10-B を採用する場合、`conversation_continuity_responses_summary.txt` を一次記録にする
- `state_id_chain_ok` が会話数と一致しない場合、`previous_response_id` 連鎖が成立していないため運用不可と判定する

## Step 10: クライアント接続設定（2パターン）

### 10-A: パターンA LobeHub Webアプリ（ChatGPTライク）

Step 8-1（`chat/completions` の oneshot / multi が2xx）を満たしたら、  
LobeHubを OpenAI互換クライアントとして接続する。

前提:
- LobeHubは **RunPodのLM Studio Podとは別ホスト**（社内VM/別Pod/ローカルPC）で動かす。
- このガイドのNginx認証（Step 6）を有効にしていること。

#### 10-A-1: LobeHub用環境変数ファイルを作成

```bash
mkdir -p /opt/lobehub
cat > /opt/lobehub/lobehub.env << 'ENV_EOF'
OPENAI_API_KEY=<Step 6で作成したトークン>
OPENAI_PROXY_URL=https://{pod-id}-11434.proxy.runpod.net/v1
OPENAI_MODEL_LIST=-all,+gpt-oss-swallow-120b-iq4xs
ENV_EOF
chmod 600 /opt/lobehub/lobehub.env
```

#### 10-A-2: LobeHubをDockerで起動

```bash
LOBEHUB_TAG="latest"
docker pull "lobehub/lobe-chat:${LOBEHUB_TAG}"

# pullしたイメージのdigestを固定値として記録（ワークログにも転記）
LOBEHUB_IMAGE_REF=$(docker image inspect --format='{{index .RepoDigests 0}}' "lobehub/lobe-chat:${LOBEHUB_TAG}")
LOBEHUB_DIGEST="${LOBEHUB_IMAGE_REF#lobehub/lobe-chat@}"
echo "LOBEHUB_DIGEST=${LOBEHUB_DIGEST}"

docker run -d \
  --name lobehub \
  --restart unless-stopped \
  -p 3210:3210 \
  --env-file /opt/lobehub/lobehub.env \
  "lobehub/lobe-chat@${LOBEHUB_DIGEST}"

docker ps --filter name=lobehub
curl -sS -I http://127.0.0.1:3210 | head -n 1
```

#### 10-A-3: 初回接続確認（ブラウザ）

1. `http://<LobeHubホスト>:3210` を開く  
2. モデル `gpt-oss-swallow-120b-iq4xs` を選択  
3. 「単発質問」と「履歴付き質問（2ターン以上）」をそれぞれ1回実行  
4. エラー時はLobeHubコンテナログを確認:

```bash
docker logs --tail 200 lobehub
```

#### 10-A-4: 運用上の注意

- ブラウザにRunPod APIキーを直接配らない（LobeHubサーバ側で保持）。
- チーム利用時はLobeHub側にも認証/TLSを前段配置する（社内VPN・リバースプロキシ等）。
- LobeHubの環境変数はバージョンで増減するため、更新時は公式ドキュメントを確認する。

### 10-B: パターンB VSCode拡張（Codex）推奨（`wire_api="responses"`）

Step 8-2（またはStep 8-3再ゲート）で、`non-stream` / `stream` がともに 2xx の場合のみこの設定を使う。  
本採用前に Step 9-2（`--api-mode responses`）で `state_id_chain_ok` が全会話1になることを確認する。

`responses` が向くケース:
- 会話状態を `previous_response_id` でサーバー側管理したい
- `stream`（SSE）や `reasoning.effort` を使いたい

`~/.codex/config.toml`:

```toml
#:schema https://developers.openai.com/codex/config-schema.json

model = "gpt-oss-swallow-120b-iq4xs"
model_provider = "swallow_runpod_lms"

[model_providers.swallow_runpod_lms]
name = "RunPod LM Studio (Swallow IQ4_XS)"
base_url = "https://{pod-id}-11434.proxy.runpod.net/v1"
env_key = "SWALLOW_API_KEY"
wire_api = "responses"
```

### 10-C: パターンB 例外（Codex側が `wire_api="chat"` を公式サポートしている場合のみ）

Step 8-2 が失敗し、かつ利用中のCodex実装が `chat` を正式サポートする場合のみ使用する。

`chat` が向くケース:
- 既存のOpenAI互換実装を最小改修で流用したい
- Function Calling（`tools`）中心の運用を優先したい

```toml
#:schema https://developers.openai.com/codex/config-schema.json

model = "gpt-oss-swallow-120b-iq4xs"
model_provider = "swallow_runpod_lms"

[model_providers.swallow_runpod_lms]
name = "RunPod LM Studio (Swallow IQ4_XS)"
base_url = "https://{pod-id}-11434.proxy.runpod.net/v1"
env_key = "SWALLOW_API_KEY"
wire_api = "chat"
```

運用ルール:
- `wire_api="chat"` のサポート可否が曖昧な場合は使わない
- 判定不能なら Step 8-3 の変換プロキシ経由で `responses` を維持する
- `stream` ゲートに失敗した状態では `wire_api="responses"` を採用しない

Windows (PowerShell):

```powershell
$env:SWALLOW_API_KEY = "<Step 6で作成したトークン>"
[System.Environment]::SetEnvironmentVariable("SWALLOW_API_KEY", "<Step 6で作成したトークン>", "User")
```

注記:
- `User` スコープ保存は「新しく起動したプロセス」に反映される。既存のVSCode/Terminalには即時反映されないため、再起動して読み直す。

## Step 11: コストガードレール設定

この章で、以下を自動化する。

- 月額上限（ソフト警告 + ハード停止）
- RunPod自動停止（最大稼働時間）
- 時間帯運用（平日 09:30-11:30 JST）
- アラート通知（Slack Webhook）

RunPod標準機能だけでは「任意の月額ハード上限」を直接設定できないため、GraphQL APIで代替実装する。

重要（課金集計スコープ）:
- Billing APIはPod単位で厳密分離しにくいため、同一アカウントの他ワークロードが集計に混ざる可能性がある
- 本ガイドでは既定を `BILLING_SCOPE="gpu_only"` とし、GPU課金のみでガードする
- 厳密運用が必要な場合は、Swallow検証専用のRunPodアカウントを使う

### 11-0: `billing.summary.time` の形式確認（初回のみ）

RunPod側仕様が将来変わる可能性があるため、最初に `time` フィールドの形式を確認してから集計を有効化する。

```bash
# 11-1未実施なら一時的に直接指定する
RUNPOD_API_KEY="YOUR_RUNPOD_API_KEY"

# 11-1実施済みならこちらで上書きしてよい
# source /workspace/cost-guardrail.env
curl -sS https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -d '{"query":"query { myself { billing(input:{granularity:DAILY}) { summary { time } } } }"}' \
  | jq -r '.data.myself.billing.summary[:5][]?.time'
```

判定:
- `2026-02-22T00:00:00Z` のようにUTCが明示される: 本ガイドのUTC集計をそのまま使用
- タイムゾーン情報なし/不明形式: 月初1営業日は手動突合（RunPodダッシュボードとの差分確認）を必須化

### 11-1: 閾値ファイル作成

```bash
command -v jq >/dev/null 2>&1 || (apt-get update && apt-get install -y jq)

cat > /workspace/cost-guardrail.env << 'ENV_EOF'
# RunPod APIキー（Settings > API Keys）
RUNPOD_API_KEY="YOUR_RUNPOD_API_KEY"

# 対象Pod ID（RunPod Consoleで確認）
RUNPOD_POD_ID="YOUR_POD_ID"

# 月額上限（USD）
MONTHLY_BUDGET_USD=1200

# 通知閾値（%）
WARN_PCT_1=70
WARN_PCT_2=85
HARD_STOP_PCT=100

# 集計スコープ: gpu_only | total
# - gpu_only: GPU課金のみ（既定。共有アカウント向け）
# - total: billing.summary の全カテゴリ合算（専用アカウント向け）
BILLING_SCOPE="gpu_only"

# 任意: Slack Incoming Webhook
SLACK_WEBHOOK_URL=""
ENV_EOF

chmod 600 /workspace/cost-guardrail.env
```

注記:
- `cost-guardrail.env` には `RUNPOD_API_KEY` が平文で保存される
- 前提として、RunPodのVolume Diskアクセス権（Workspace共有範囲、Podアクセス権、スナップショット運用）を厳格に管理する
- 共有アカウントで他Podを使う場合は `BILLING_SCOPE="gpu_only"` を維持し、`total` は専用アカウント時のみ使う

### 11-2: 監視スクリプト作成（月額集計 + 通知 + 超過停止）

```bash
mkdir -p /workspace/scripts /workspace/logs /workspace/.guardrail

cat > /workspace/scripts/cost_guardrail.sh << 'SCRIPT_EOF'
#!/usr/bin/env bash
set -euo pipefail

source /workspace/cost-guardrail.env

GRAPHQL_URL="https://api.runpod.io/graphql"
# billing.summary.time は 11-0 で形式確認した前提。既定はUTC月で集計。
MONTH_KEY=${MONTH_KEY_OVERRIDE:-$(date -u +%Y-%m)}
STATE_FILE="/workspace/.guardrail/alerts_${MONTH_KEY}.txt"
BILLING_SCOPE=${BILLING_SCOPE:-gpu_only}
case "$BILLING_SCOPE" in
  gpu_only|total) ;;
  *)
    echo "[WARN] BILLING_SCOPE=${BILLING_SCOPE} は不正です。gpu_only へフォールバックします。"
    BILLING_SCOPE="gpu_only"
    ;;
esac
mkdir -p /workspace/.guardrail
touch "$STATE_FILE"

notify_slack() {
  local msg="$1"
  if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
    local payload
    payload=$(jq -Rn --arg text "$msg" '{text:$text}')
    curl -sS -X POST "$SLACK_WEBHOOK_URL" \
      -H "Content-Type: application/json" \
      -d "$payload" >/dev/null || true
  fi
}

emit_once() {
  local key="$1"
  local msg="$2"
  if ! grep -qx "$key" "$STATE_FILE"; then
    echo "$key" >> "$STATE_FILE"
    notify_slack "$msg"
  fi
}

QUERY_PAYLOAD='{
  "query": "query { myself { clientBalance currentSpendPerHr billing(input:{granularity:DAILY}) { summary { time gpuCloudAmount cpuCloudAmount serverlessAmount storageAmount runpodEndpointAmount } } } }"
}'

RAW=$(curl -sS "$GRAPHQL_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -d "$QUERY_PAYLOAD")

if [ "$(echo "$RAW" | jq -r '.errors | length // 0')" != "0" ]; then
  echo "[ERROR] GraphQL error: $(echo "$RAW" | jq -c '.errors')"
  exit 1
fi

SAMPLE_TIME=$(echo "$RAW" | jq -r '.data.myself.billing.summary[0].time // empty')
if [ -n "$SAMPLE_TIME" ] && ! echo "$SAMPLE_TIME" | grep -Eq 'Z$|[+-][0-9]{2}:[0-9]{2}$'; then
  echo "[WARN] billing.summary.time にタイムゾーン情報が見当たりません。UTC仮定で集計中（11-0の手動突合を継続してください）。"
fi

MONTHLY_SPEND=$(echo "$RAW" | jq -r --arg m "$MONTH_KEY" --arg scope "$BILLING_SCOPE" '
  [ (.data.myself.billing.summary // [])[]
    | select((.time // "") | startswith($m))
    | if $scope == "total"
      then ((.gpuCloudAmount // 0) + (.cpuCloudAmount // 0) + (.serverlessAmount // 0) + (.storageAmount // 0) + (.runpodEndpointAmount // 0))
      else (.gpuCloudAmount // 0)
      end
  ] | add // 0
')

CURRENT_SPH=$(echo "$RAW" | jq -r '.data.myself.currentSpendPerHr // 0')
CLIENT_BALANCE=$(echo "$RAW" | jq -r '.data.myself.clientBalance // 0')

PCT=$(awk -v spend="$MONTHLY_SPEND" -v cap="$MONTHLY_BUDGET_USD" 'BEGIN { if (cap > 0) printf "%.2f", (spend / cap) * 100; else print "0" }')

echo "[INFO] month=${MONTH_KEY} scope=${BILLING_SCOPE} spend=${MONTHLY_SPEND}usd cap=${MONTHLY_BUDGET_USD}usd pct=${PCT}% sph=${CURRENT_SPH} balance=${CLIENT_BALANCE}"

cmp_pct() {
  awk -v a="$1" -v b="$2" 'BEGIN { if (a >= b) print 1; else print 0 }'
}

if [ "$(cmp_pct "$PCT" "$WARN_PCT_1")" = "1" ]; then
  emit_once "WARN_${WARN_PCT_1}" "RunPod予算警告: ${PCT}% (${MONTHLY_SPEND}/${MONTHLY_BUDGET_USD} USD), balance=${CLIENT_BALANCE}, spendPerHr=${CURRENT_SPH}"
fi

if [ "$(cmp_pct "$PCT" "$WARN_PCT_2")" = "1" ]; then
  emit_once "WARN_${WARN_PCT_2}" "RunPod予算警告(高): ${PCT}% (${MONTHLY_SPEND}/${MONTHLY_BUDGET_USD} USD), balance=${CLIENT_BALANCE}, spendPerHr=${CURRENT_SPH}"
fi

if [ "$(cmp_pct "$PCT" "$HARD_STOP_PCT")" = "1" ]; then
  if ! grep -qx "HARD_STOP_EXECUTED_${HARD_STOP_PCT}" "$STATE_FILE"; then
    STOP_PAYLOAD=$(printf '{"query":"mutation { podStop(input:{podId:\\"%s\\"}) { id desiredStatus } }"}' "$RUNPOD_POD_ID")
    STOP_RAW=$(curl -sS "$GRAPHQL_URL" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
      -d "$STOP_PAYLOAD")
    STOP_ERROR_COUNT=$(echo "$STOP_RAW" | jq -r '.errors | length // 0')
    STOP_ID=$(echo "$STOP_RAW" | jq -r '.data.podStop.id // empty')
    STOP_STATUS=$(echo "$STOP_RAW" | jq -r '.data.podStop.desiredStatus // empty')
    echo "[INFO] hard_stop_response=$(echo "$STOP_RAW" | jq -c '.')"

    if [ "$STOP_ERROR_COUNT" = "0" ] && [ -n "$STOP_ID" ]; then
      echo "HARD_STOP_EXECUTED_${HARD_STOP_PCT}" >> "$STATE_FILE"
      emit_once "HARD_STOP_${HARD_STOP_PCT}" "RunPod予算上限到達: ${PCT}% (${MONTHLY_SPEND}/${MONTHLY_BUDGET_USD} USD)。Pod ${RUNPOD_POD_ID} を停止しました。 status=${STOP_STATUS}"
    else
      emit_once "HARD_STOP_FAILED_${HARD_STOP_PCT}" "RunPod予算上限到達時のpodStop失敗。再試行継続。pod=${RUNPOD_POD_ID} response=$(echo "$STOP_RAW" | jq -c '.')"
      echo "[ERROR] hard stop failed. podStop not accepted."
    fi
  else
    echo "[INFO] hard stop already executed for threshold ${HARD_STOP_PCT}%"
  fi
fi
SCRIPT_EOF

chmod +x /workspace/scripts/cost_guardrail.sh
```

### 11-3: 15分ごと監視を有効化

systemdが使える環境:

```bash
if [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/swallow-cost-guardrail.service << 'UNIT_EOF'
[Unit]
Description=Swallow Cost Guardrail Check
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/workspace
ExecStart=/bin/bash -lc '/workspace/scripts/cost_guardrail.sh >> /workspace/logs/cost_guardrail.log 2>&1'
UNIT_EOF

  cat > /etc/systemd/system/swallow-cost-guardrail.timer << 'TIMER_EOF'
[Unit]
Description=Run cost guardrail every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
TIMER_EOF

  systemctl daemon-reload
  systemctl enable --now swallow-cost-guardrail.timer
  systemctl status swallow-cost-guardrail.timer --no-pager
else
  echo "systemd非対応: ループ監視に切り替えます"
  nohup bash -lc 'while true; do /workspace/scripts/cost_guardrail.sh >> /workspace/logs/cost_guardrail.log 2>&1; sleep 900; done' \
    >/workspace/logs/cost_guardrail_loop.log 2>&1 &
fi
```

### 11-4: RunPod自動停止（最大稼働時間）

`sleep ... &` 方式はセッション切断で失われるため使わない。  
systemd timerで「起動からN時間後の停止」を予約する。

```bash
source /workspace/cost-guardrail.env
mkdir -p /workspace/scripts /workspace/logs

MAX_RUNTIME_HOURS=${MAX_RUNTIME_HOURS:-2}

cat > /workspace/scripts/pod_stop_once.sh << 'STOP_EOF'
#!/usr/bin/env bash
set -euo pipefail
source /workspace/cost-guardrail.env

GRAPHQL_URL="https://api.runpod.io/graphql"
STOP_PAYLOAD=$(printf '{"query":"mutation { podStop(input:{podId:\\"%s\\"}) { id desiredStatus } }"}' "$RUNPOD_POD_ID")
STOP_RAW=$(curl -sS "$GRAPHQL_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -d "$STOP_PAYLOAD")

ERR_COUNT=$(echo "$STOP_RAW" | jq -r '.errors | length // 0')
STOP_ID=$(echo "$STOP_RAW" | jq -r '.data.podStop.id // empty')
STOP_STATUS=$(echo "$STOP_RAW" | jq -r '.data.podStop.desiredStatus // empty')

if [ "$ERR_COUNT" != "0" ] || [ -z "$STOP_ID" ]; then
  echo "[ERROR] max-runtime stop failed: $(echo "$STOP_RAW" | jq -c '.')"
  exit 1
fi

echo "[INFO] max-runtime stop succeeded: pod=${RUNPOD_POD_ID} status=${STOP_STATUS}"
STOP_EOF

chmod +x /workspace/scripts/pod_stop_once.sh

if [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/swallow-max-runtime-stop.service << 'UNIT_EOF'
[Unit]
Description=Stop RunPod Pod at max runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/workspace
ExecStart=/bin/bash -lc '/workspace/scripts/pod_stop_once.sh >> /workspace/logs/cost_guardrail.log 2>&1'
UNIT_EOF

  cat > /etc/systemd/system/swallow-max-runtime-stop.timer << TIMER_EOF
[Unit]
Description=Stop pod after max runtime

[Timer]
OnActiveSec=${MAX_RUNTIME_HOURS}h
AccuracySec=1min
Unit=swallow-max-runtime-stop.service

[Install]
WantedBy=timers.target
TIMER_EOF

  systemctl daemon-reload
  systemctl enable swallow-max-runtime-stop.timer
  systemctl restart swallow-max-runtime-stop.timer
  systemctl status swallow-max-runtime-stop.timer --no-pager
else
  echo "systemd非対応: 外部スケジューラ（GitHub Actions等）で開始+${MAX_RUNTIME_HOURS}h停止を設定してください。"
fi
```

手動即時停止:

```bash
source /workspace/cost-guardrail.env
STOP_PAYLOAD=$(printf '{"query":"mutation { podStop(input:{podId:\\"%s\\"}) { id desiredStatus } }"}' "$RUNPOD_POD_ID")
curl -sS https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -d "$STOP_PAYLOAD" >/dev/null || true
```

### 11-5: 時間帯運用の停止（平日 11:30 JST）

Pod内で確実に止めるには、外部スケジューラ（GitHub Actions等）からRunPod APIを叩くのが安全。  
以下は GitHub Actions 例（`11:30 JST = 02:30 UTC`）。

`.github/workflows/runpod-window-stop.yml`:

```yaml
name: runpod-window-stop
on:
  schedule:
    - cron: "30 2 * * 1-5" # Mon-Fri 02:30 UTC = 11:30 JST
  workflow_dispatch:

jobs:
  stop-pod:
    runs-on: ubuntu-latest
    steps:
      - name: Stop RunPod Pod
        env:
          RUNPOD_API_KEY: ${{ secrets.RUNPOD_API_KEY }}
          RUNPOD_POD_ID: ${{ secrets.RUNPOD_POD_ID }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: |
          set -euo pipefail
          PAYLOAD=$(printf '{"query":"mutation { podStop(input:{podId:\\"%s\\"}) { id desiredStatus } }"}' "$RUNPOD_POD_ID")
          RESP=$(curl -sS https://api.runpod.io/graphql \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
            -d "$PAYLOAD")
          echo "$RESP"
          ERR_COUNT=$(echo "$RESP" | jq -r '.errors | length // 0')
          STOP_ID=$(echo "$RESP" | jq -r '.data.podStop.id // empty')
          STOP_STATUS=$(echo "$RESP" | jq -r '.data.podStop.desiredStatus // empty')
          if [ "$ERR_COUNT" != "0" ] || [ -z "$STOP_ID" ]; then
            echo "[ERROR] podStop failed: $(echo "$RESP" | jq -c '.')"
            exit 1
          fi
          echo "podStop succeeded: id=${STOP_ID} status=${STOP_STATUS}"
          if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
            MSG=$(echo "$RESP" | jq -c '.')
            PAYLOAD_JSON=$(jq -Rn --arg text "Window stop executed: ${MSG}" '{text:$text}')
            curl -sS -X POST "$SLACK_WEBHOOK_URL" \
              -H "Content-Type: application/json" \
              -d "$PAYLOAD_JSON" >/dev/null || true
          fi
          echo "window-stop workflow completed"
```

### 11-5A: 朝の自動起動（平日 09:30 JST, 任意）

時間帯運用の停止を自動化する場合は、朝の `podResume` もセットで定義する。  
（手動起動前提で運用するなら、このセクションはスキップしてよい）

`.github/workflows/runpod-morning-resume.yml`:

```yaml
name: runpod-morning-resume
on:
  schedule:
    - cron: "30 0 * * 1-5" # Mon-Fri 00:30 UTC = 09:30 JST
  workflow_dispatch:

jobs:
  resume-pod:
    runs-on: ubuntu-latest
    steps:
      - name: Resume RunPod Pod
        env:
          RUNPOD_API_KEY: ${{ secrets.RUNPOD_API_KEY }}
          RUNPOD_POD_ID: ${{ secrets.RUNPOD_POD_ID }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: |
          set -euo pipefail
          PAYLOAD=$(printf '{"query":"mutation { podResume(input:{podId:\\"%s\\"}) { id desiredStatus } }"}' "$RUNPOD_POD_ID")
          RESP=$(curl -sS https://api.runpod.io/graphql \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
            -d "$PAYLOAD")
          echo "$RESP"
          ERR_COUNT=$(echo "$RESP" | jq -r '.errors | length // 0')
          RESUME_ID=$(echo "$RESP" | jq -r '.data.podResume.id // empty')
          RESUME_STATUS=$(echo "$RESP" | jq -r '.data.podResume.desiredStatus // empty')
          if [ "$ERR_COUNT" != "0" ] || [ -z "$RESUME_ID" ]; then
            echo "[ERROR] podResume failed: $(echo "$RESP" | jq -c '.')"
            exit 1
          fi
          echo "podResume succeeded: id=${RESUME_ID} status=${RESUME_STATUS}"
          if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
            MSG=$(echo "$RESP" | jq -c '.')
            PAYLOAD_JSON=$(jq -Rn --arg text "Morning resume executed: ${MSG}" '{text:$text}')
            curl -sS -X POST "$SLACK_WEBHOOK_URL" \
              -H "Content-Type: application/json" \
              -d "$PAYLOAD_JSON" >/dev/null || true
          fi
          echo "morning-resume workflow completed"
```

### 11-6: ログローテーション（必須）

2週間検証でもログ肥大化は起きるため、`/workspace/logs` と手動起動ログのローテーションを先に有効化する。

```bash
apt-get update && apt-get install -y logrotate

cat > /etc/logrotate.d/swallow-runpod << 'ROTATE_EOF'
/workspace/logs/*.log /workspace/lmstudio-server.log {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
ROTATE_EOF

# 設定確認（dry-run）
logrotate -d /etc/logrotate.d/swallow-runpod

# 初回テストローテーション
logrotate -f /etc/logrotate.d/swallow-runpod
```

### 11-7: Volumeスナップショット / バックアップ（推奨）

`IQ4_XS` は約62GiBあり、再ダウンロード時間が長い。  
**初期構築完了直後** と **週次** でVolumeスナップショットを取得する。

最小運用:
1. Step 8 のゲートが通った時点でPodを `Stop`
2. RunPod Consoleの `Volumes` からSnapshotを作成（例: `swallow-base-2026-02-22`）
3. 大きな変更前（Nginx変更、モデル差し替え、依存更新）にも追加でSnapshot

設定ファイルは別途アーカイブしておく:

```bash
mkdir -p /workspace/backups
tar --ignore-failed-read -czf /workspace/backups/swallow-config-$(date +%F).tar.gz \
  /workspace/start.sh \
  /workspace/runtime.env \
  /workspace/nginx-auth-proxy.conf \
  /workspace/scripts \
  /workspace/cost-guardrail.env \
  /workspace/logs/benchmark_step9_*_summary.log
chmod 600 /workspace/backups/swallow-config-*.tar.gz
```

注記:
- `/workspace/.auth_token` は意図的にバックアップ対象から除外する（秘密情報の複製抑止）。
- 復元後は Step 6-2 でトークンを再生成し、関連クライアント側のAPIキーも更新する。

## 日次運用

### 朝（`runpod-morning-resume` を使わない場合）

- 推奨運用時間: **平日 09:30〜11:30 JST**

```bash
if systemctl is-enabled swallow-lmstudio.service >/dev/null 2>&1; then
  systemctl restart swallow-lmstudio.service
else
  bash /workspace/start.sh
fi
```

- パターンA確認: Step 8-1 の oneshot を1本実行（LobeHub向け経路確認）
- パターンB確認: Step 8-2 の non-stream + stream を各1本実行（Codex向け経路確認）
- 朝イチ体感確認: Step 9-0 を1本実行し、`/workspace/logs/cold_start_ttfb.log` を記録

### 退勤前

- `/workspace/logs` を退避
- `runpod-window-stop` を使わない日は RunPodダッシュボードで `Stop`

### 週次（コスト）

- `/workspace/logs/cost_guardrail.log` を確認（閾値到達・停止履歴）
- `MONTHLY_BUDGET_USD` と閾値（`WARN_PCT_*`）を見直し
- `/workspace/logs/lmstudio-watchdog.log` を確認（`gpu_vram` / `ram` / `swap` の閾値超過有無）

## トラブルシューティング

### モデルが見つからない

1. `lms ls --json` で `IQ4_XS` が表示されるか確認
2. Step 4の `lms import` を再実行
3. ファイル名に `IQ4_XS` を含む先頭シャードを指定しているか確認

### OOMになる / 極端に遅い

1. `context-length` を `8192 -> 4096` に下げる
2. 同時接続を1に制限して再計測
3. A40 x2なら短文用途中心で運用し、閾値超過時は2ノード化を検討

### SpotでPreemptionされた

1. RunPod ConsoleでPod状態を確認し、同じVolumeを再アタッチして `Resume`（または再作成）する
2. `bash /workspace/start.sh`（または `systemctl restart swallow-lmstudio.service`）で復旧
3. Step 8-1 / 8-2 のゲート（oneshot + stream）を再実行してから業務利用に戻す
4. Volume破損や紛失時は Step 11-7 の最新Snapshotから復元し、Step 4以降を再実行

### 401 Unauthorized

1. `x-api-key` または `Authorization: Bearer` を付与しているか確認
2. `/workspace/.auth_token` の値と一致しているか確認
3. 更新後に `nginx -t && nginx -s reload` を実行

### 403 Forbidden（IP制限を有効化した場合のみ）

1. `/workspace/nginx-allowlist.conf` のCIDRが正しいか確認
2. 送信元IP（VPN経由含む）がallowlistに含まれるか確認
3. 更新後に `nginx -t && nginx -s reload` を実行

### LobeHubで会話が続かない（文脈が効かない）

1. 2ターン目以降を「同じ会話スレッド」で送っているか確認（毎回New Chatにしていないか）
2. LobeHubを再起動するたびに会話が初期化される運用になっていないか確認
3. Step 8-1 の multiテストが2xxかつ妥当応答になるか再確認

### VSCode Codexが接続できない / 不安定

1. Step 8-2 の `non-stream` / `stream` が両方2xxか確認
2. `stream` 失敗時は Step 8-3 を適用し、再ゲート後に Step 10-B で再設定
3. `~/.codex/config.toml` の `base_url` と `env_key`、環境変数 `SWALLOW_API_KEY` を再確認
4. `wire_api=responses` 運用時は Step 9-2 を再実行し、`state_id_chain_ok` が全会話で1か確認

## 評価基準（2週間）

評価条件（共通）:
- ワークロードは `max_tokens=256` の短文30本 + `max_tokens=1024` の中長文10本。
- 同時利用は `1 -> 2 -> 3` 並列の順で実施。
- パターンA（LobeHub）は、実ブラウザ利用で「新規会話 + 履歴付き会話」を含めて評価する。
- パターンB（VSCode Codex）は、`wire_api` 設定に応じて `responses` または `chat` 経路で評価する。
- 会話継続率の定義は次の通り:
  - 分母: 開始した会話数（本ガイドでは30会話）
  - 分子: 3ターン連続で `2xx` 応答が返り、かつ2ターン目/3ターン目で前ターンの制約（固有名詞・条件）を維持できた会話数
  - 計算式: `会話継続率 = 分子 / 分母`
- パターンAの会話継続率は Step 9-1 の `conversation_continuity_summary.txt` を一次記録として採用する（`--api-mode chat`、手集計はしない）。
- パターンBで `wire_api="responses"` を採用する場合、Step 9-2 の `conversation_continuity_responses_summary.txt` を一次記録として採用する（`--api-mode responses`）。

採用可能判定ルーブリック:
- 事前キャリブレーション: 本採点とは別に4課題（日本語2、英語2）を2名で共同採点し、採点境界を合わせる
- 本採点対象: 20課題（日本語10、英語10）
- 評価者: 開発者2名（キャリブレーション後に独立採点）
- 採点軸（5点満点）:
  - 正確性 0〜2点
  - 指示追従性 0〜2点
  - 可読性/保守性 0〜1点
- 「採用可能」定義: 1課題あたり **4点以上** かつ **重大欠陥なし**
- 最終合格条件: 採用可能率 `>= 70%` かつ 評価者一致率 `>= 80%`
- 一致率が `80%` 未満なら、キャリブレーションメモに基づいて差分レビューして再採点する
- 最終採用条件: **パターンA / パターンB の両方** が下表の合格ラインを満たすこと

| 項目 | 合格ライン |
|---|---|
| パターンA（LobeHub）成立性 | 2ユーザー同時・各15会話（計30会話）で会話継続率 `>= 95%`、UI側の致命的エラー `0` |
| パターンB（VSCode Codex）成立性 | 20タスクで接続失敗 `<= 1件`、途中切断/ハング `0`。`wire_api=responses` 採用時は Step 9-2 で会話継続率 `>= 95%` かつ `state_id_chain_ok=30` |
| 生成品質 | サンプル20課題で「採用可能」判定 70%以上 |
| 応答速度 | `P95 TTFB <= 8秒` かつ `P95 total <= 30秒`。加えて `cold_start_ttfb.log` の初回TTFBが A100で `<= 15秒` / A40 x2で `<= 20秒` |
| 生成スループット | `completion tok/s` の中央値（`BASE_URL_LMS_LOCAL` 計測）: A100で `>= 10`、A40 x2で `>= 6`（暫定） |
| 同時利用 | 3並列 × 30リクエストで `HTTP成功率 >= 98%`、OOM/クラッシュ `0` |
| 安定性 | 5営業日で突発停止 `0`、朝の復旧時間 `<= 10分` |
| セキュリティ | 平文APIキーのログ出力 `0件`、未認証アクセス成功 `0件` |

片系統のみ合格時（AまたはBのみ）の扱い:

| 結果 | 判断 | 次アクション |
|---|---|---|
| Aのみ合格 | 本番採用しない（限定運用） | LobeHubのみ社内限定で暫定利用し、Bは Step 8-3 + Step 10-B 再検証を5営業日以内に実施 |
| Bのみ合格 | 本番採用しない（限定運用） | 開発用途のみ暫定利用し、非開発者向け導線は停止。Aは Step 8-1/Step 10-A を再検証 |
| A/Bとも不合格 | 不採用 | モデル・量子化・構成を見直し（例: `Q4_K_M` または別モデル）してStep 3から再実施 |

注記:
- `tok/s` の合格ラインは初日のStep 9計測結果で再校正する（GPU世代・ドライバ・LM Studio版差分を吸収するため）。
- `tok/s` は `completion_tokens/(total-ttfb)` の推定値。公開URL計測はRTT影響で低めに出るため、合格判定は `benchmark_step9_lms_local_summary.log` を正とする。
- 再校正時は `docs/PHASE1_DAY1_WORKLOG_YYYY-MM-DD.md` に以下を必ず記録し、実行者1名 + 承認者1名で合意する。
  - 使用GPU/ドライバ/LM Studio版
  - 参照した `benchmark_step9_*_summary.log`
  - 更新後のしきい値（A100/A40 x2）
  - 承認日時
- 一度承認したしきい値は2週間評価中は固定し、途中変更時は同ワークログに変更理由を追記する。

## 参考（一次情報）

- モデル: https://huggingface.co/mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf
- HF API（サイズ確認）: https://huggingface.co/api/models/mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf?blobs=true
- LM Studio Developer Docs: https://lmstudio.ai/docs/api
- LM Studio CLI (`lms`): https://lmstudio.ai/docs/cli
- `lms load`: https://lmstudio.ai/docs/cli/local-models/load
- `lms import`: https://lmstudio.ai/docs/cli/local-models/import
- `lms server start`: https://lmstudio.ai/docs/cli/serve/server-start
- Headless startup task: https://lmstudio.ai/docs/developer/core/headless_llmster
- Developer Core index（上記が移動/改名された場合の起点）: https://lmstudio.ai/docs/developer/core
- Authentication: https://lmstudio.ai/docs/developer/core/authentication
- OpenAI互換エンドポイント: https://lmstudio.ai/docs/app/api/endpoints/openai
- Nginx `if` 利用上の注意（If Is Evil）: https://www.nginx.com/resources/wiki/start/topics/depth/ifisevil/
- LobeHub GitHub: https://github.com/lobehub/lobe-chat
- LobeHub 環境変数（Model Provider）: https://lobehub.com/docs/self-hosting/environment-variables/model-provider/
- LobeHub Docker Image: https://hub.docker.com/r/lobehub/lobe-chat
- RunPod Billing: https://docs.runpod.io/references/billing-information
- RunPod GraphQL Manage Pods: https://docs.runpod.io/sdks/graphql/manage-pods
- RunPod GraphQL Spec: https://graphql-spec.runpod.io/

---

*作成日: 2026-02-22*
*最終更新: 2026-02-22*
*用途: GPT-OSS-Swallow-120B IQ4_XS の2週間検証（LM Studio/RunPod）*

