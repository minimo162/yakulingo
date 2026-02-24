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
MODEL_LOAD_BLOCKING="${MODEL_LOAD_BLOCKING:-0}"
MODEL_READY_MAX_WAIT_SEC="${MODEL_READY_MAX_WAIT_SEC:-180}"
MODEL_READY_POLL_SEC="${MODEL_READY_POLL_SEC:-2}"
MODEL_LOAD_TIMEOUT_SEC="${MODEL_LOAD_TIMEOUT_SEC:-1800}"
MODEL_KEY_RETRY_MAX="${MODEL_KEY_RETRY_MAX:-20}"
MODEL_KEY_RETRY_DELAY_SEC="${MODEL_KEY_RETRY_DELAY_SEC:-3}"
MODEL_KEY_REQUIRED="${MODEL_KEY_REQUIRED:-0}"
ENABLE_PLAYWRIGHT_MCP="${ENABLE_PLAYWRIGHT_MCP:-1}"
PLAYWRIGHT_MCP_HOST="${PLAYWRIGHT_MCP_HOST:-127.0.0.1}"
PLAYWRIGHT_MCP_PORT="${PLAYWRIGHT_MCP_PORT:-8931}"
PLAYWRIGHT_MCP_REQUIRED="${PLAYWRIGHT_MCP_REQUIRED:-0}"

AUTO_START="${AUTO_START:-1}"
INSTALL_NODE_TOOLCHAIN="${INSTALL_NODE_TOOLCHAIN:-0}"
SYNC_YAKULINGO="${SYNC_YAKULINGO:-1}"
SKIP_BASE_PACKAGES="${SKIP_BASE_PACKAGES:-0}"
FAST_START="${FAST_START:-0}"
CLEANUP_WORKSPACE="${CLEANUP_WORKSPACE:-1}"
CLEANUP_LOG_RETENTION_DAYS="${CLEANUP_LOG_RETENTION_DAYS:-7}"
BACKUP_KEEP_COUNT="${BACKUP_KEEP_COUNT:-0}"

log() {
  printf '[bootstrap] %s\n' "$*"
}

prune_backup_dirs() {
  local base_dir="$1"
  local keep_count="$2"
  local -a sorted=()

  mapfile -t sorted < <(ls -1dt "${base_dir}.backup."* 2>/dev/null || true)
  if [ "${#sorted[@]}" -le "${keep_count}" ]; then
    return
  fi

  local idx=0
  local d
  for d in "${sorted[@]}"; do
    idx=$((idx + 1))
    if [ "${idx}" -le "${keep_count}" ]; then
      continue
    fi
    rm -rf "${d}"
    log "cleanup removed backup: ${d}"
  done
}

cleanup_workspace_artifacts() {
  if [ "${CLEANUP_WORKSPACE}" != "1" ]; then
    log "skip workspace cleanup (CLEANUP_WORKSPACE=${CLEANUP_WORKSPACE})"
    return
  fi

  mkdir -p "${LOG_DIR}"
  find "${LOG_DIR}" -maxdepth 1 -type f -name '*.log' -mtime +"${CLEANUP_LOG_RETENTION_DAYS}" -delete 2>/dev/null || true
  rm -rf "${WORKSPACE_DIR}/_yakulingo_bootstrap" "${WORKSPACE_DIR}/.tmp-lobe-chat-ref"
  prune_backup_dirs "${WORKSPACE_DIR}/yakulingo" "${BACKUP_KEEP_COUNT}"
  prune_backup_dirs "${WORKSPACE_DIR}/lobe-chat" "${BACKUP_KEEP_COUNT}"
}

apply_fast_start_defaults() {
  if [ "${FAST_START}" = "1" ]; then
    SKIP_BASE_PACKAGES=1
    SYNC_YAKULINGO=0
    log "FAST_START=1 -> SKIP_BASE_PACKAGES=1 SYNC_YAKULINGO=0"
  fi
}

ensure_base_packages() {
  if [ "${SKIP_BASE_PACKAGES}" = "1" ]; then
    local missing=()
    local cmd
    for cmd in curl jq git nginx; do
      if ! command -v "${cmd}" >/dev/null 2>&1; then
        missing+=("${cmd}")
      fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
      log "skip base package install (SKIP_BASE_PACKAGES=1)"
      return
    fi
    log "SKIP_BASE_PACKAGES=1 but missing commands: ${missing[*]} -> fallback install"
  fi
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
  if [ "${INSTALL_NODE_TOOLCHAIN}" != "1" ] && [ "${ENABLE_PLAYWRIGHT_MCP}" != "1" ]; then
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
MODEL_REPO=${MODEL_REPO}
LMS_SERVER_PORT=${LMS_SERVER_PORT}
MODEL_LOAD_BLOCKING=${MODEL_LOAD_BLOCKING}
MODEL_READY_MAX_WAIT_SEC=${MODEL_READY_MAX_WAIT_SEC}
MODEL_READY_POLL_SEC=${MODEL_READY_POLL_SEC}
MODEL_LOAD_TIMEOUT_SEC=${MODEL_LOAD_TIMEOUT_SEC}
MODEL_KEY_RETRY_MAX=${MODEL_KEY_RETRY_MAX}
MODEL_KEY_RETRY_DELAY_SEC=${MODEL_KEY_RETRY_DELAY_SEC}
MODEL_KEY_REQUIRED=${MODEL_KEY_REQUIRED}
ENABLE_PLAYWRIGHT_MCP=${ENABLE_PLAYWRIGHT_MCP}
PLAYWRIGHT_MCP_HOST=${PLAYWRIGHT_MCP_HOST}
PLAYWRIGHT_MCP_PORT=${PLAYWRIGHT_MCP_PORT}
PLAYWRIGHT_MCP_REQUIRED=${PLAYWRIGHT_MCP_REQUIRED}
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

        location ^~ /mcp/ {
            set \$auth_ok 0;
            if (\$http_x_api_key = "${token}") { set \$auth_ok 1; }
            if (\$http_authorization = "Bearer ${token}") { set \$auth_ok 1; }
            if (\$auth_ok = 0) { return 401; }

            rewrite ^/mcp/(.*)$ /\$1 break;
            proxy_pass http://127.0.0.1:${PLAYWRIGHT_MCP_PORT};
            proxy_http_version 1.1;
            # Playwright MCP validates Host and only accepts localhost:<port>.
            proxy_set_header Host localhost:${PLAYWRIGHT_MCP_PORT};
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_buffering off;
            proxy_read_timeout 3600;
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

LMS_SERVER_PORT="${LMS_SERVER_PORT:-1234}"
MODEL_LOAD_BLOCKING="${MODEL_LOAD_BLOCKING:-0}"
MODEL_READY_MAX_WAIT_SEC="${MODEL_READY_MAX_WAIT_SEC:-180}"
MODEL_READY_POLL_SEC="${MODEL_READY_POLL_SEC:-2}"
MODEL_LOAD_TIMEOUT_SEC="${MODEL_LOAD_TIMEOUT_SEC:-1800}"
MODEL_KEY_RETRY_MAX="${MODEL_KEY_RETRY_MAX:-20}"
MODEL_KEY_RETRY_DELAY_SEC="${MODEL_KEY_RETRY_DELAY_SEC:-3}"
MODEL_KEY_REQUIRED="${MODEL_KEY_REQUIRED:-0}"
ENABLE_PLAYWRIGHT_MCP="${ENABLE_PLAYWRIGHT_MCP:-1}"
PLAYWRIGHT_MCP_HOST="${PLAYWRIGHT_MCP_HOST:-127.0.0.1}"
PLAYWRIGHT_MCP_PORT="${PLAYWRIGHT_MCP_PORT:-8931}"
PLAYWRIGHT_MCP_REQUIRED="${PLAYWRIGHT_MCP_REQUIRED:-0}"
PLAYWRIGHT_MCP_LOG="${PLAYWRIGHT_MCP_LOG:-/workspace/playwright-mcp.log}"
MODEL_REPO="${MODEL_REPO:-mmnga-o/GPT-OSS-Swallow-120B-RL-v0.1-gguf}"
MODEL_LOAD_LOG="${MODEL_LOAD_LOG:-/workspace/lmstudio-model-load.log}"
MODEL_LOAD_STATUS_FILE="${MODEL_LOAD_STATUS_FILE:-/workspace/model-load.status}"

normalize_int() {
  local raw="$1"
  local fallback="$2"
  if [[ "$raw" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "$raw"
  else
    printf '%s\n' "$fallback"
  fi
}

MODEL_LOAD_TIMEOUT_SEC="$(normalize_int "${MODEL_LOAD_TIMEOUT_SEC}" 1800)"
MODEL_KEY_RETRY_MAX="$(normalize_int "${MODEL_KEY_RETRY_MAX}" 20)"
MODEL_KEY_RETRY_DELAY_SEC="$(normalize_int "${MODEL_KEY_RETRY_DELAY_SEC}" 3)"
MODEL_READY_MAX_WAIT_SEC="$(normalize_int "${MODEL_READY_MAX_WAIT_SEC}" 180)"
MODEL_READY_POLL_SEC="$(normalize_int "${MODEL_READY_POLL_SEC}" 2)"
PLAYWRIGHT_MCP_PORT="$(normalize_int "${PLAYWRIGHT_MCP_PORT}" 8931)"

start_playwright_mcp() {
  if [ "${ENABLE_PLAYWRIGHT_MCP}" != "1" ]; then
    return 0
  fi

  if ! command -v npx >/dev/null 2>&1; then
    echo "[WARN] npx is not available. skip Playwright MCP startup."
    if [ "${PLAYWRIGHT_MCP_REQUIRED}" = "1" ]; then
      echo "ERROR: PLAYWRIGHT_MCP_REQUIRED=1 but npx is missing."
      return 1
    fi
    return 0
  fi

  pkill -f '@playwright/mcp' >/dev/null 2>&1 || true
  nohup npx -y @playwright/mcp@latest --host "${PLAYWRIGHT_MCP_HOST}" --port "${PLAYWRIGHT_MCP_PORT}" > "${PLAYWRIGHT_MCP_LOG}" 2>&1 &

  local ready=0
  for _ in $(seq 1 30); do
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PLAYWRIGHT_MCP_PORT}/" || true)"
    if [ "${code}" = "000" ] || [ -z "${code}" ]; then
      code="$(curl -sS -o /dev/null -w '%{http_code}' "http://localhost:${PLAYWRIGHT_MCP_PORT}/" || true)"
    fi
    if [ "${code}" != "000" ] && [ -n "${code}" ]; then
      ready=1
      break
    fi
    sleep 1
  done

  if [ "${ready}" -ne 1 ]; then
    echo "[WARN] Playwright MCP did not become ready on port ${PLAYWRIGHT_MCP_PORT}"
    if [ "${PLAYWRIGHT_MCP_REQUIRED}" = "1" ]; then
      echo "ERROR: PLAYWRIGHT_MCP_REQUIRED=1 and Playwright MCP is not ready."
      return 1
    fi
    return 0
  fi

  echo "[INFO] Playwright MCP started (host=${PLAYWRIGHT_MCP_HOST}, port=${PLAYWRIGHT_MCP_PORT}, log=${PLAYWRIGHT_MCP_LOG})"
  return 0
}

start_playwright_mcp

lms daemon up >/dev/null || true

if ! lms server status --json --quiet | jq -e '.running == true' >/dev/null 2>&1; then
  nohup lms server start --port "${LMS_SERVER_PORT}" > /workspace/lmstudio-server.log 2>&1 &
fi

API_READY=0
for _ in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${LMS_SERVER_PORT}/v1/models" >/tmp/lms_models_api_ready.json 2>/dev/null; then
    API_READY=1
    break
  fi
  sleep 1
done
if [ "${API_READY}" -ne 1 ]; then
  echo "[WARN] LM Studio API is not reachable yet on :${LMS_SERVER_PORT}; continue startup."
fi

nginx -c /workspace/nginx-swallow/nginx.conf -s quit 2>/dev/null || true
rm -f /workspace/nginx-swallow/nginx.pid
nginx -t -c /workspace/nginx-swallow/nginx.conf
nginx -c /workspace/nginx-swallow/nginx.conf

LMS_MODELS_JSON=/tmp/lms_models_list.json
resolve_model_key() {
  local attempts delay try key
  attempts="${MODEL_KEY_RETRY_MAX}"
  delay="${MODEL_KEY_RETRY_DELAY_SEC}"
  key=""

  if [ "${attempts}" -lt 1 ]; then
    attempts=1
  fi
  if [ "${delay}" -lt 1 ]; then
    delay=1
  fi

  for try in $(seq 1 "${attempts}"); do
    if ! lms ls --json > "${LMS_MODELS_JSON}"; then
      echo "[WARN] lms ls failed (try ${try}/${attempts})"
    fi

    key="$(jq -r --arg repo "${MODEL_REPO}" '
      .[]?
      | select((.path | test($repo; "i")) and (.path | test("iq4_xs"; "i")))
      | .modelKey
    ' "${LMS_MODELS_JSON}" | head -1)"
    if [ -z "${key}" ]; then
      key="$(jq -r --arg repo "${MODEL_REPO}" '
        .[]?
        | select(.path | test($repo; "i"))
        | .modelKey
      ' "${LMS_MODELS_JSON}" | head -1)"
    fi
    if [ -n "${key}" ]; then
      printf '%s\n' "${key}"
      return 0
    fi

    if [ "${try}" -lt "${attempts}" ]; then
      sleep "${delay}"
    fi
  done

  return 1
}

MODEL_KEY="$(resolve_model_key || true)"
if [ -z "${MODEL_KEY}" ]; then
  echo "[WARN] MODEL_KEY not found in lms catalog after retries."
  if [ "${MODEL_KEY_REQUIRED}" = "1" ] || [ "${MODEL_LOAD_BLOCKING}" = "1" ]; then
    echo "ERROR: MODEL_KEY is required for current mode."
    exit 1
  fi
fi

load_model_once() {
  if [ -z "${MODEL_KEY}" ]; then
    echo "[WARN] skip model load because MODEL_KEY is empty."
    return 1
  fi

  local load_rc=0
  if command -v timeout >/dev/null 2>&1 && [ "${MODEL_LOAD_TIMEOUT_SEC}" -gt 0 ]; then
    timeout "${MODEL_LOAD_TIMEOUT_SEC}" \
      lms load "${MODEL_KEY}" --identifier "${MODEL_ID}" --context-length "${CONTEXT_LENGTH}" --gpu max || load_rc=$?
  else
    lms load "${MODEL_KEY}" --identifier "${MODEL_ID}" --context-length "${CONTEXT_LENGTH}" --gpu max || load_rc=$?
  fi

  if [ "${load_rc}" -eq 0 ]; then
    return 0
  fi
  if [ "${load_rc}" -eq 124 ]; then
    echo "[WARN] lms load timed out (${MODEL_LOAD_TIMEOUT_SEC}s)."
  fi

  if lms ps --json | jq -e --arg id "$MODEL_ID" '.[] | select(.identifier == $id)' >/dev/null 2>&1; then
    echo "[INFO] model already loaded, continue"
    return 0
  fi

  echo "ERROR: failed to load model: $MODEL_ID"
  return 1
}

if lms ps --json | jq -e --arg id "$MODEL_ID" '.[] | select(.identifier == $id)' >/dev/null 2>&1; then
  echo "[INFO] model already loaded, skip load"
else
  if [ "${MODEL_LOAD_BLOCKING}" = "1" ]; then
    if ! load_model_once; then
      exit 1
    fi
  else
    (
      started_at="$(date --iso-8601=seconds 2>/dev/null || date)"
      echo "start ${started_at}"
      if load_model_once; then
        finished_at="$(date --iso-8601=seconds 2>/dev/null || date)"
        echo "ok ${finished_at}" > "${MODEL_LOAD_STATUS_FILE}"
      else
        finished_at="$(date --iso-8601=seconds 2>/dev/null || date)"
        echo "failed ${finished_at}" > "${MODEL_LOAD_STATUS_FILE}"
      fi
    ) >> "${MODEL_LOAD_LOG}" 2>&1 &
    echo "[INFO] model load started in background (log: ${MODEL_LOAD_LOG})"
  fi
fi

if [ "${MODEL_LOAD_BLOCKING}" = "1" ]; then
  READY=0
  max_wait_loops=1
  if [ "${MODEL_READY_POLL_SEC}" -gt 0 ]; then
    max_wait_loops=$((MODEL_READY_MAX_WAIT_SEC / MODEL_READY_POLL_SEC))
  fi
  if [ "${max_wait_loops}" -lt 1 ]; then
    max_wait_loops=1
  fi
  for _ in $(seq 1 "${max_wait_loops}"); do
    if curl -fsS "http://127.0.0.1:${LMS_SERVER_PORT}/v1/models" >/tmp/lms_models_start.json 2>/dev/null; then
      if jq -e --arg id "$MODEL_ID" '.data[]? | select(.id == $id)' /tmp/lms_models_start.json >/dev/null 2>&1; then
        READY=1
        break
      fi
    fi
    sleep "${MODEL_READY_POLL_SEC}"
  done
  if [ "${READY}" -ne 1 ]; then
    echo "ERROR: model $MODEL_ID is not ready on /v1/models"
    exit 1
  fi
fi

echo "start.sh done (MODEL_LOAD_BLOCKING=${MODEL_LOAD_BLOCKING})"
EOF
  chmod +x "${START_SCRIPT_FILE}"
  log "wrote ${START_SCRIPT_FILE}"
}

main() {
  apply_fast_start_defaults
  cleanup_workspace_artifacts
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
