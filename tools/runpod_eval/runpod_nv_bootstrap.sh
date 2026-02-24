#!/usr/bin/env bash
set -euo pipefail

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

MODEL_ID="${MODEL_ID:-gpt-oss-swallow-120b-iq4xs}"
MODEL_PULL_NAME="${MODEL_PULL_NAME:-${MODEL_ID}}"
MODEL_SOURCE_DIR="${MODEL_SOURCE_DIR:-${WORKSPACE_DIR}/models/swallow-120b/IQ4_XS}"
MODEL_CREATE_FROM_GGUF="${MODEL_CREATE_FROM_GGUF:-1}"
MODEL_PULL_ENABLED="${MODEL_PULL_ENABLED:-1}"
MODEL_PREP_TIMEOUT_SEC="${MODEL_PREP_TIMEOUT_SEC:-5400}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-4096}"
GPU_PROFILE="${GPU_PROFILE:-a40x2}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"

OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11435}"
OLLAMA_MODELS="${OLLAMA_MODELS:-${WORKSPACE_DIR}/ollama_models}"
SWALLOW_PROXY_PORT="${SWALLOW_PROXY_PORT:-11434}"
MODEL_LOAD_BLOCKING="${MODEL_LOAD_BLOCKING:-0}"
MODEL_READY_MAX_WAIT_SEC="${MODEL_READY_MAX_WAIT_SEC:-240}"
MODEL_READY_POLL_SEC="${MODEL_READY_POLL_SEC:-2}"

ENABLE_PLAYWRIGHT_MCP="${ENABLE_PLAYWRIGHT_MCP:-1}"
PLAYWRIGHT_MCP_HOST="${PLAYWRIGHT_MCP_HOST:-127.0.0.1}"
PLAYWRIGHT_MCP_PORT="${PLAYWRIGHT_MCP_PORT:-8931}"
PLAYWRIGHT_MCP_ALLOWED_HOSTS="${PLAYWRIGHT_MCP_ALLOWED_HOSTS:-*}"
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

normalize_int() {
  local raw="$1"
  local fallback="$2"
  if [[ "${raw}" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "${raw}"
  else
    printf '%s\n' "${fallback}"
  fi
}

extract_port_from_host() {
  local host="$1"
  local port="${host##*:}"
  if [[ "${port}" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "${port}"
  else
    printf '11435\n'
  fi
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
    return
  fi

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

ensure_ollama() {
  if command -v ollama >/dev/null 2>&1; then
    log "ollama already installed"
    return
  fi

  log "install ollama"
  curl -fsSL https://ollama.com/install.sh | sh
  if ! command -v ollama >/dev/null 2>&1; then
    log "ERROR: ollama command is not available"
    exit 1
  fi
}

ensure_runtime_env() {
  local ollama_port
  ollama_port="$(extract_port_from_host "${OLLAMA_HOST}")"
  cat > "${RUNTIME_ENV_FILE}" <<EOF
GPU_PROFILE=${GPU_PROFILE}
CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}
CONTEXT_LENGTH=${CONTEXT_LENGTH}
MODEL_ID=${MODEL_ID}
MODEL_PULL_NAME=${MODEL_PULL_NAME}
MODEL_SOURCE_DIR=${MODEL_SOURCE_DIR}
MODEL_CREATE_FROM_GGUF=${MODEL_CREATE_FROM_GGUF}
MODEL_PULL_ENABLED=${MODEL_PULL_ENABLED}
MODEL_PREP_TIMEOUT_SEC=${MODEL_PREP_TIMEOUT_SEC}
MODEL_LOAD_BLOCKING=${MODEL_LOAD_BLOCKING}
MODEL_READY_MAX_WAIT_SEC=${MODEL_READY_MAX_WAIT_SEC}
MODEL_READY_POLL_SEC=${MODEL_READY_POLL_SEC}
OLLAMA_HOST=${OLLAMA_HOST}
OLLAMA_PORT=${ollama_port}
OLLAMA_MODELS=${OLLAMA_MODELS}
ENABLE_PLAYWRIGHT_MCP=${ENABLE_PLAYWRIGHT_MCP}
PLAYWRIGHT_MCP_HOST=${PLAYWRIGHT_MCP_HOST}
PLAYWRIGHT_MCP_PORT=${PLAYWRIGHT_MCP_PORT}
PLAYWRIGHT_MCP_ALLOWED_HOSTS=${PLAYWRIGHT_MCP_ALLOWED_HOSTS}
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
  local ollama_port
  ollama_port="$(extract_port_from_host "${OLLAMA_HOST}")"

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

            proxy_pass http://127.0.0.1:${ollama_port};
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_buffering off;
            proxy_read_timeout 3600;
        }

        location ^~ /api/ {
            set \$auth_ok 0;
            if (\$http_x_api_key = "${token}") { set \$auth_ok 1; }
            if (\$http_authorization = "Bearer ${token}") { set \$auth_ok 1; }
            if (\$auth_ok = 0) { return 401; }

            proxy_pass http://127.0.0.1:${ollama_port};
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_buffering off;
            proxy_read_timeout 3600;
        }

        location = /mcp {
            set \$auth_ok 0;
            if (\$http_x_api_key = "${token}") { set \$auth_ok 1; }
            if (\$http_authorization = "Bearer ${token}") { set \$auth_ok 1; }
            if (\$auth_ok = 0) { return 401; }

            proxy_pass http://127.0.0.1:${PLAYWRIGHT_MCP_PORT}/mcp;
            proxy_http_version 1.1;
            proxy_set_header Host localhost:${PLAYWRIGHT_MCP_PORT};
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_buffering off;
            proxy_read_timeout 3600;
        }

        location ^~ /mcp/ {
            set \$auth_ok 0;
            if (\$http_x_api_key = "${token}") { set \$auth_ok 1; }
            if (\$http_authorization = "Bearer ${token}") { set \$auth_ok 1; }
            if (\$auth_ok = 0) { return 401; }

            proxy_pass http://127.0.0.1:${PLAYWRIGHT_MCP_PORT}/mcp;
            proxy_http_version 1.1;
            proxy_set_header Host localhost:${PLAYWRIGHT_MCP_PORT};
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

set -a
source /workspace/runtime.env
set +a

MODEL_READY_MAX_WAIT_SEC="$( [[ "${MODEL_READY_MAX_WAIT_SEC:-}" =~ ^[0-9]+$ ]] && echo "${MODEL_READY_MAX_WAIT_SEC}" || echo 240 )"
MODEL_READY_POLL_SEC="$( [[ "${MODEL_READY_POLL_SEC:-}" =~ ^[0-9]+$ ]] && echo "${MODEL_READY_POLL_SEC}" || echo 2 )"
MODEL_PREP_TIMEOUT_SEC="$( [[ "${MODEL_PREP_TIMEOUT_SEC:-}" =~ ^[0-9]+$ ]] && echo "${MODEL_PREP_TIMEOUT_SEC}" || echo 5400 )"
PLAYWRIGHT_MCP_PORT="$( [[ "${PLAYWRIGHT_MCP_PORT:-}" =~ ^[0-9]+$ ]] && echo "${PLAYWRIGHT_MCP_PORT}" || echo 8931 )"
OLLAMA_PORT="$( [[ "${OLLAMA_PORT:-}" =~ ^[0-9]+$ ]] && echo "${OLLAMA_PORT}" || echo 11435 )"
OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:${OLLAMA_PORT}}"
OLLAMA_MODELS="${OLLAMA_MODELS:-/workspace/ollama_models}"
MODEL_ID="${MODEL_ID:-gpt-oss-swallow-120b-iq4xs}"
MODEL_PULL_NAME="${MODEL_PULL_NAME:-${MODEL_ID}}"
MODEL_SOURCE_DIR="${MODEL_SOURCE_DIR:-/workspace/models/swallow-120b/IQ4_XS}"
MODEL_CREATE_FROM_GGUF="${MODEL_CREATE_FROM_GGUF:-1}"
MODEL_PULL_ENABLED="${MODEL_PULL_ENABLED:-1}"
PLAYWRIGHT_MCP_LOG="${PLAYWRIGHT_MCP_LOG:-/workspace/playwright-mcp.log}"
OLLAMA_SERVER_LOG="${OLLAMA_SERVER_LOG:-/workspace/ollama-server.log}"
MODEL_PREP_LOG="${MODEL_PREP_LOG:-/workspace/ollama-model-prepare.log}"

export OLLAMA_HOST OLLAMA_MODELS
mkdir -p "${OLLAMA_MODELS}"

start_playwright_mcp() {
  if [ "${ENABLE_PLAYWRIGHT_MCP:-1}" != "1" ]; then
    return 0
  fi
  if ! command -v npx >/dev/null 2>&1; then
    echo "[WARN] npx is not available. skip Playwright MCP startup."
    if [ "${PLAYWRIGHT_MCP_REQUIRED:-0}" = "1" ]; then
      echo "ERROR: PLAYWRIGHT_MCP_REQUIRED=1 but npx is missing."
      return 1
    fi
    return 0
  fi

  pkill -f '@playwright/mcp' >/dev/null 2>&1 || true
  nohup npx -y @playwright/mcp@latest \
    --host "${PLAYWRIGHT_MCP_HOST:-127.0.0.1}" \
    --port "${PLAYWRIGHT_MCP_PORT}" \
    --allowed-hosts "${PLAYWRIGHT_MCP_ALLOWED_HOSTS:-*}" \
    > "${PLAYWRIGHT_MCP_LOG}" 2>&1 &

  local ready=0
  for _ in $(seq 1 30); do
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PLAYWRIGHT_MCP_PORT}/" || true)"
    if [ "${code}" != "000" ] && [ -n "${code}" ]; then
      ready=1
      break
    fi
    sleep 1
  done

  if [ "${ready}" -ne 1 ]; then
    echo "[WARN] Playwright MCP did not become ready on port ${PLAYWRIGHT_MCP_PORT}"
    if [ "${PLAYWRIGHT_MCP_REQUIRED:-0}" = "1" ]; then
      echo "ERROR: PLAYWRIGHT_MCP_REQUIRED=1 and Playwright MCP is not ready."
      return 1
    fi
  else
    echo "[INFO] Playwright MCP started (host=${PLAYWRIGHT_MCP_HOST:-127.0.0.1}, port=${PLAYWRIGHT_MCP_PORT}, log=${PLAYWRIGHT_MCP_LOG})"
  fi
  return 0
}

start_ollama_server() {
  if curl -fsS "http://127.0.0.1:${OLLAMA_PORT}/api/tags" >/tmp/ollama_tags_probe.json 2>/dev/null; then
    return 0
  fi

  nohup env OLLAMA_HOST="${OLLAMA_HOST}" OLLAMA_MODELS="${OLLAMA_MODELS}" ollama serve > "${OLLAMA_SERVER_LOG}" 2>&1 &
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${OLLAMA_PORT}/api/tags" >/tmp/ollama_tags_probe.json 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "ERROR: Ollama server did not become ready on :${OLLAMA_PORT}"
  return 1
}

model_exists() {
  ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fx "${MODEL_ID}" >/dev/null 2>&1
}

prepare_model_from_gguf() {
  if [ "${MODEL_CREATE_FROM_GGUF}" != "1" ]; then
    return 1
  fi
  shopt -s nullglob
  local ggufs=("${MODEL_SOURCE_DIR}"/*.gguf)
  shopt -u nullglob
  if [ "${#ggufs[@]}" -eq 0 ]; then
    return 1
  fi

  local base_gguf="${ggufs[0]}"
  local modelfile="/tmp/ollama-${MODEL_ID}.Modelfile"
  cat > "${modelfile}" <<MODEL_EOF
FROM ${base_gguf}
PARAMETER num_ctx ${CONTEXT_LENGTH:-4096}
MODEL_EOF

  if command -v timeout >/dev/null 2>&1 && [ "${MODEL_PREP_TIMEOUT_SEC}" -gt 0 ]; then
    timeout "${MODEL_PREP_TIMEOUT_SEC}" ollama create "${MODEL_ID}" -f "${modelfile}" >> "${MODEL_PREP_LOG}" 2>&1
  else
    ollama create "${MODEL_ID}" -f "${modelfile}" >> "${MODEL_PREP_LOG}" 2>&1
  fi
  return 0
}

ensure_model_ready() {
  if model_exists; then
    return 0
  fi

  : > "${MODEL_PREP_LOG}"
  if [ "${MODEL_PULL_ENABLED}" = "1" ]; then
    if command -v timeout >/dev/null 2>&1 && [ "${MODEL_PREP_TIMEOUT_SEC}" -gt 0 ]; then
      timeout "${MODEL_PREP_TIMEOUT_SEC}" ollama pull "${MODEL_PULL_NAME}" >> "${MODEL_PREP_LOG}" 2>&1 || true
    else
      ollama pull "${MODEL_PULL_NAME}" >> "${MODEL_PREP_LOG}" 2>&1 || true
    fi
  fi

  if ! model_exists; then
    if ! prepare_model_from_gguf; then
      echo "ERROR: model '${MODEL_ID}' is unavailable (pull/create failed)."
      return 1
    fi
  fi

  model_exists
}

start_playwright_mcp
start_ollama_server
ensure_model_ready

nginx -c /workspace/nginx-swallow/nginx.conf -s quit 2>/dev/null || true
rm -f /workspace/nginx-swallow/nginx.pid
nginx -t -c /workspace/nginx-swallow/nginx.conf
nginx -c /workspace/nginx-swallow/nginx.conf

models_ready=0
for _ in $(seq 1 30); do
  code="$(curl -sS -o /tmp/ollama_models_start.json -w '%{http_code}' "http://127.0.0.1:${OLLAMA_PORT}/v1/models" || true)"
  if [ "${code}" = "200" ]; then
    if jq -e --arg id "${MODEL_ID}" '.data[]? | select(.id == $id)' /tmp/ollama_models_start.json >/dev/null 2>&1; then
      models_ready=1
      break
    fi
  fi
  sleep 1
done
if [ "${models_ready}" -ne 1 ]; then
  echo "ERROR: model '${MODEL_ID}' is not visible on /v1/models"
  exit 1
fi

chat_ready=0
for _ in $(seq 1 20); do
  code="$(
    curl -sS -o /tmp/ollama_chat_probe.json -w '%{http_code}' \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"${MODEL_ID}\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":1,\"temperature\":0}" \
      "http://127.0.0.1:${OLLAMA_PORT}/v1/chat/completions" || true
  )"
  if [ "${code}" = "200" ]; then
    chat_ready=1
    break
  fi
  sleep "${MODEL_READY_POLL_SEC}"
done
if [ "${chat_ready}" -ne 1 ]; then
  echo "ERROR: /v1/chat/completions is not ready for model '${MODEL_ID}'."
  exit 1
fi

echo "start.sh done (MODEL_LOAD_BLOCKING=${MODEL_LOAD_BLOCKING})"
EOF

  chmod +x "${START_SCRIPT_FILE}"
  log "wrote ${START_SCRIPT_FILE}"
}

main() {
  MODEL_PREP_TIMEOUT_SEC="$(normalize_int "${MODEL_PREP_TIMEOUT_SEC}" 5400)"
  MODEL_READY_MAX_WAIT_SEC="$(normalize_int "${MODEL_READY_MAX_WAIT_SEC}" 240)"
  MODEL_READY_POLL_SEC="$(normalize_int "${MODEL_READY_POLL_SEC}" 2)"

  apply_fast_start_defaults
  cleanup_workspace_artifacts
  ensure_base_packages
  sync_yakulingo_repo
  sync_bootstrap_script_copy
  ensure_node_toolchain
  ensure_ollama
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
