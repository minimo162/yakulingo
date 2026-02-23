#!/usr/bin/env bash
set -euo pipefail

# Network Volume(/workspace)前提で、Pod再作成後の復旧を自動化する。

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
LOG_DIR="${LOG_DIR:-${WORKSPACE_DIR}/logs}"
AUTH_TOKEN_FILE="${AUTH_TOKEN_FILE:-${WORKSPACE_DIR}/.auth_token}"
RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-${WORKSPACE_DIR}/runtime.env}"
START_SCRIPT_FILE="${START_SCRIPT_FILE:-${WORKSPACE_DIR}/start.sh}"
NGINX_DIR="${NGINX_DIR:-${WORKSPACE_DIR}/nginx-swallow}"
NGINX_CONF_FILE="${NGINX_CONF_FILE:-${NGINX_DIR}/nginx.conf}"
YAKULINGO_DIR="${YAKULINGO_DIR:-${WORKSPACE_DIR}/yakulingo}"
YAKULINGO_REPO_URL="${YAKULINGO_REPO_URL:-https://github.com/minimo162/yakulingo.git}"
YAKULINGO_REF="${YAKULINGO_REF:-main}"

MODEL_REPO="${MODEL_REPO:-mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf}"
MODEL_SOURCE_DIR="${MODEL_SOURCE_DIR:-${WORKSPACE_DIR}/models/swallow-120b/IQ4_XS}"
MODEL_ID="${MODEL_ID:-gpt-oss-swallow-120b-iq4xs}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-4096}"
GPU_PROFILE="${GPU_PROFILE:-a40x2}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"
LMS_SERVER_PORT="${LMS_SERVER_PORT:-1234}"
SWALLOW_PROXY_PORT="${SWALLOW_PROXY_PORT:-11434}"

AUTO_START="${AUTO_START:-1}"
INSTALL_NODE_TOOLCHAIN="${INSTALL_NODE_TOOLCHAIN:-0}"
SYNC_YAKULINGO="${SYNC_YAKULINGO:-1}"

log() {
  printf '[bootstrap] %s\n' "$*"
}

ensure_base_packages() {
  log "install base packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg jq git nginx-full apache2-utils
}

sync_yakulingo_repo() {
  if [ "${SYNC_YAKULINGO}" != "1" ]; then
    log "skip yakulingo sync (SYNC_YAKULINGO=${SYNC_YAKULINGO})"
    return
  fi

  if [ ! -d "${YAKULINGO_DIR}/.git" ]; then
    log "clone yakulingo repo -> ${YAKULINGO_DIR}"
    rm -rf "${YAKULINGO_DIR}"
    git clone --depth 1 --branch "${YAKULINGO_REF}" "${YAKULINGO_REPO_URL}" "${YAKULINGO_DIR}"
  else
    log "update yakulingo repo (${YAKULINGO_REF})"
    if ! git -C "${YAKULINGO_DIR}" fetch origin "${YAKULINGO_REF}" --depth 1; then
      log "WARN: git fetch failed. keep existing checkout."
      return
    fi
    if ! git -C "${YAKULINGO_DIR}" checkout "${YAKULINGO_REF}"; then
      log "WARN: git checkout ${YAKULINGO_REF} failed. keep existing branch."
      return
    fi
    if ! git -C "${YAKULINGO_DIR}" pull --ff-only origin "${YAKULINGO_REF}"; then
      log "WARN: git pull failed (local changes?). keep existing checkout."
    fi
  fi
}

sync_bootstrap_script_copy() {
  local src="${YAKULINGO_DIR}/tools/runpod_eval/runpod_nv_bootstrap.sh"
  local dst="${WORKSPACE_DIR}/scripts/runpod_nv_bootstrap.sh"
  if [ -f "${src}" ]; then
    mkdir -p "${WORKSPACE_DIR}/scripts"
    cp "${src}" "${dst}"
    chmod +x "${dst}"
    log "synced bootstrap script -> ${dst}"
  fi

  local lobe_src="${YAKULINGO_DIR}/tools/runpod_eval/runpod_lobehub_bootstrap.sh"
  local lobe_dst="${WORKSPACE_DIR}/scripts/runpod_lobehub_bootstrap.sh"
  if [ -f "${lobe_src}" ]; then
    cp "${lobe_src}" "${lobe_dst}"
    chmod +x "${lobe_dst}"
    log "synced lobehub bootstrap script -> ${lobe_dst}"
  fi
}

ensure_node_toolchain() {
  if [ "${INSTALL_NODE_TOOLCHAIN}" != "1" ]; then
    return
  fi
  if command -v node >/dev/null 2>&1 && command -v pnpm >/dev/null 2>&1; then
    log "node/pnpm already installed"
    return
  fi
  log "install node + pnpm"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
  apt-get update
  apt-get install -y nodejs
  corepack enable
  corepack prepare pnpm@10.20.0 --activate
}

ensure_lms() {
  export PATH="$HOME/.lmstudio/bin:$PATH"
  hash -r
  if command -v lms >/dev/null 2>&1; then
    log "lms already installed"
  else
    log "install lm studio cli"
    curl -fsSL https://lmstudio.ai/install.sh -o /tmp/lmstudio-install.sh
    bash /tmp/lmstudio-install.sh --no-modify-path
  fi
  if ! command -v lms >/dev/null 2>&1; then
    log "ERROR: lms command is not available"
    exit 1
  fi
}

ensure_model_files() {
  shopt -s nullglob
  local files=("${MODEL_SOURCE_DIR}"/*.gguf)
  shopt -u nullglob
  if [ "${#files[@]}" -eq 0 ]; then
    log "ERROR: model shards not found in ${MODEL_SOURCE_DIR}"
    exit 1
  fi
}

link_model_shards() {
  local dst_dir="/root/.lmstudio/models/${MODEL_REPO}"
  mkdir -p "${dst_dir}"

  shopt -s nullglob
  local files=("${MODEL_SOURCE_DIR}"/*.gguf)
  shopt -u nullglob
  for f in "${files[@]}"; do
    ln -sfn "${f}" "${dst_dir}/$(basename "${f}")"
  done
  log "linked ${#files[@]} shard(s) to ${dst_dir}"
}

ensure_model_import() {
  local models_json="/tmp/lms_models_bootstrap.json"
  lms daemon up >/dev/null || true
  lms ls --json > "${models_json}"

  if jq -e --arg repo "${MODEL_REPO}" '.[] | select(.path | test($repo; "i"))' "${models_json}" >/dev/null 2>&1; then
    log "model already imported in lms catalog"
    return
  fi

  local first_gguf
  local dst_dir
  local first_name
  local first_link
  first_gguf="$(ls "${MODEL_SOURCE_DIR}"/*.gguf | sort | head -1)"
  dst_dir="/root/.lmstudio/models/${MODEL_REPO}"
  first_name="$(basename "${first_gguf}")"
  first_link="${dst_dir}/${first_name}"

  # 既存リンクがあると lms import --symbolic-link が失敗するため先に掃除する。
  rm -f "${first_link}"
  log "import first shard into lms catalog"
  if ! lms import "${first_gguf}" --user-repo "${MODEL_REPO}" --symbolic-link -y; then
    # 失敗時でもカタログ登録済みなら続行する。
    lms ls --json > "${models_json}"
    if jq -e --arg repo "${MODEL_REPO}" '.[] | select(.path | test($repo; "i"))' "${models_json}" >/dev/null 2>&1; then
      log "import returned non-zero, but model exists in catalog. continue."
    else
      log "ERROR: lms import failed and model not found in catalog"
      exit 1
    fi
  fi
}

ensure_runtime_env() {
  cat > "${RUNTIME_ENV_FILE}" <<EOF
GPU_PROFILE=${GPU_PROFILE}
CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}
CONTEXT_LENGTH=${CONTEXT_LENGTH}
MODEL_ID=${MODEL_ID}
EOF
  chmod 600 "${RUNTIME_ENV_FILE}"
  log "wrote ${RUNTIME_ENV_FILE}"
}

ensure_auth_token() {
  if [ ! -s "${AUTH_TOKEN_FILE}" ]; then
    openssl rand -hex 24 > "${AUTH_TOKEN_FILE}"
    chmod 600 "${AUTH_TOKEN_FILE}"
    log "created ${AUTH_TOKEN_FILE}"
  else
    chmod 600 "${AUTH_TOKEN_FILE}"
  fi
}

write_nginx_conf() {
  local token
  token="$(tr -d '\n' < "${AUTH_TOKEN_FILE}")"

  mkdir -p "${NGINX_DIR}" "${LOG_DIR}"
  cat > "${NGINX_CONF_FILE}" <<EOF
worker_processes 1;
pid ${NGINX_DIR}/nginx.pid;
error_log ${LOG_DIR}/nginx-swallow-error.log info;

events { worker_connections 1024; }

http {
    server {
        listen ${SWALLOW_PROXY_PORT};

        location = /healthz {
            return 200 "ok\\n";
        }

        location ^~ /v1/ {
            set \$auth_ok 0;
            if (\$http_x_api_key = "${token}") { set \$auth_ok 1; }
            if (\$http_authorization = "Bearer ${token}") { set \$auth_ok 1; }
            if (\$auth_ok = 0) { return 401; }

            proxy_pass http://127.0.0.1:${LMS_SERVER_PORT};
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_buffering off;
            proxy_read_timeout 3600;
        }

        location / {
            return 404;
        }
    }
}
EOF
  log "wrote ${NGINX_CONF_FILE}"
}

write_start_script() {
  cat > "${START_SCRIPT_FILE}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.lmstudio/bin:$PATH"

set -a
source /workspace/runtime.env
set +a

lms daemon up >/dev/null || true

LMS_MODELS_JSON=/tmp/lms_models_list.json
lms ls --json > "$LMS_MODELS_JSON"
MODEL_KEY=$(jq -r '.[] | select((.path|test("GPT-OSS-Swallow-120B-RL-v0.1-gguf"; "i")) and (.path|test("iq4_xs"; "i"))) | .modelKey' "$LMS_MODELS_JSON" | head -1)
[ -n "$MODEL_KEY" ] || { echo "ERROR: MODEL_KEY not found"; exit 1; }

if ! lms ps --json | jq -e --arg id "$MODEL_ID" '.[] | select(.identifier == $id)' >/dev/null 2>&1; then
  if ! lms load "$MODEL_KEY" --identifier "$MODEL_ID" --context-length "$CONTEXT_LENGTH" --gpu max; then
    if lms ps --json | jq -e --arg id "$MODEL_ID" '.[] | select(.identifier == $id)' >/dev/null 2>&1; then
      echo "[INFO] model already loaded, continue"
    else
      echo "ERROR: failed to load model: $MODEL_ID"
      exit 1
    fi
  fi
else
  echo "[INFO] model already loaded, skip load"
fi

if ! lms server status --json --quiet | jq -e '.running == true' >/dev/null 2>&1; then
  nohup lms server start --port 1234 > /workspace/lmstudio-server.log 2>&1 &
fi

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
  echo "ERROR: model $MODEL_ID is not ready on /v1/models"
  exit 1
fi

nginx -c /workspace/nginx-swallow/nginx.conf -s quit 2>/dev/null || true
rm -f /workspace/nginx-swallow/nginx.pid
nginx -t -c /workspace/nginx-swallow/nginx.conf
nginx -c /workspace/nginx-swallow/nginx.conf

echo "start.sh done"
EOF
  chmod +x "${START_SCRIPT_FILE}"
  log "wrote ${START_SCRIPT_FILE}"
}

main() {
  ensure_base_packages
  sync_yakulingo_repo
  sync_bootstrap_script_copy
  ensure_node_toolchain
  ensure_lms
  ensure_model_files
  ensure_model_import
  link_model_shards
  ensure_runtime_env
  ensure_auth_token
  write_nginx_conf
  write_start_script

  if [ "${AUTO_START}" = "1" ]; then
    log "start stack"
    bash "${START_SCRIPT_FILE}"
  fi

  log "done"
}

main "$@"
