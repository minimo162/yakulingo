#!/usr/bin/env bash
set -euo pipefail

# Network Volume(/workspace)前提で、LobeHub同居PoCを復旧する。

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
LOG_DIR="${LOG_DIR:-${WORKSPACE_DIR}/logs}"
LOBE_CHAT_DIR="${LOBE_CHAT_DIR:-${WORKSPACE_DIR}/lobe-chat}"
LOBE_CHAT_REPO_URL="${LOBE_CHAT_REPO_URL:-https://github.com/lobehub/lobe-chat.git}"
LOBE_CHAT_REF="${LOBE_CHAT_REF:-main}"

LOBE_ENV_DIR="${LOBE_ENV_DIR:-${WORKSPACE_DIR}/lobehub}"
LOBE_ENV_FILE="${LOBE_ENV_FILE:-${LOBE_ENV_DIR}/lobehub.env}"
LOBE_ENV_LINK="${LOBE_ENV_LINK:-/opt/lobehub/lobehub.env}"
AUTH_TOKEN_FILE="${AUTH_TOKEN_FILE:-${WORKSPACE_DIR}/.auth_token}"

LOBE_PORT="${LOBE_PORT:-3210}"
LOBE_AUTH_PORT="${LOBE_AUTH_PORT:-3211}"
LOBE_AUTH_FILE="${LOBE_AUTH_FILE:-${WORKSPACE_DIR}/nginx-lobehub-auth/.htpasswd}"
LOBE_AUTH_CREDS_FILE="${LOBE_AUTH_CREDS_FILE:-${WORKSPACE_DIR}/lobehub_basic_auth_users.txt}"
LOBE_AUTH_USER_PREFIX="${LOBE_AUTH_USER_PREFIX:-lobeuser}"
LOBE_AUTH_USER_COUNT="${LOBE_AUTH_USER_COUNT:-6}"
LOBE_AUTH_PASSWORD_LENGTH="${LOBE_AUTH_PASSWORD_LENGTH:-20}"
LOBE_AUTH_REALM="${LOBE_AUTH_REALM:-LobeHub Protected}"

OPENAI_PROXY_URL="${OPENAI_PROXY_URL:-http://127.0.0.1:11434/v1}"
OPENAI_MODEL_LIST="${OPENAI_MODEL_LIST:-gpt-oss-swallow-120b-iq4xs}"
APP_URL="${APP_URL:-http://127.0.0.1:${LOBE_PORT}}"

DB_NAME="${DB_NAME:-lobechat}"
DB_USER="${DB_USER:-lobechat}"
DB_PASSWORD_FILE="${DB_PASSWORD_FILE:-${LOBE_ENV_DIR}/.db_password}"
AUTH_SECRET_FILE="${AUTH_SECRET_FILE:-${LOBE_ENV_DIR}/.auth_secret}"
KEY_VAULTS_SECRET_FILE="${KEY_VAULTS_SECRET_FILE:-${LOBE_ENV_DIR}/.key_vaults_secret}"

SKIP_PNPM_INSTALL="${SKIP_PNPM_INSTALL:-0}"
SKIP_BASE_PACKAGES="${SKIP_BASE_PACKAGES:-0}"
SYNC_LOBE_CHAT="${SYNC_LOBE_CHAT:-1}"
FAST_START="${FAST_START:-0}"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-v0.8.1}"
POSTGRES_CLUSTER_VERSION="${POSTGRES_CLUSTER_VERSION:-}"
POSTGRES_CLUSTER_NAME="${POSTGRES_CLUSTER_NAME:-}"
LOBE_RUN_MODE="${LOBE_RUN_MODE:-start}" # start|dev
LOBE_START_LOG_FILE="${LOG_DIR}/lobehub-start.log"
LOBE_DEV_LOG_FILE="${LOG_DIR}/lobehub-dev.log"
LOBE_ACTIVE_LOG_FILE="${LOBE_START_LOG_FILE}"
CLEANUP_WORKSPACE="${CLEANUP_WORKSPACE:-1}"
CLEANUP_LOG_RETENTION_DAYS="${CLEANUP_LOG_RETENTION_DAYS:-7}"
LOBE_CHAT_BACKUP_KEEP_COUNT="${LOBE_CHAT_BACKUP_KEEP_COUNT:-0}"
KEEP_LOBE_CHAT_BACKUP_ON_SYNC_FAIL="${KEEP_LOBE_CHAT_BACKUP_ON_SYNC_FAIL:-0}"

log() {
  printf '[lobehub-bootstrap] %s\n' "$*"
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
  prune_backup_dirs "${WORKSPACE_DIR}/lobe-chat" "${LOBE_CHAT_BACKUP_KEEP_COUNT}"
  prune_backup_dirs "${WORKSPACE_DIR}/yakulingo" "${LOBE_CHAT_BACKUP_KEEP_COUNT}"
}

apply_fast_start_defaults() {
  if [ "${FAST_START}" = "1" ]; then
    SKIP_BASE_PACKAGES=1
    SYNC_LOBE_CHAT=0
    SKIP_PNPM_INSTALL=1
    log "FAST_START=1 -> SKIP_BASE_PACKAGES=1 SYNC_LOBE_CHAT=0 SKIP_PNPM_INSTALL=1"
  fi
}

ensure_base_packages() {
  if [ "${SKIP_BASE_PACKAGES}" = "1" ]; then
    local missing=()
    local cmd
    for cmd in curl jq git nginx htpasswd psql; do
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
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg jq git nginx-full apache2-utils postgresql postgresql-contrib
}

ensure_node_toolchain() {
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

ensure_pnpm_build_policy() {
  log "configure pnpm build policy (global)"
  pnpm config set --global --json onlyBuiltDependencies '["@swc/core","@lobehub/editor","better-sqlite3","esbuild","onnxruntime-node","sharp"]'
  pnpm config set --global --json ignoredBuiltDependencies '["@playwright/browser-chromium","@scarf/scarf","@tree-sitter-grammars/tree-sitter-yaml","core-js","core-js-pure","electron","es5-ext","protobufjs","tree-sitter","tree-sitter-json","unrs-resolver"]'
}

sync_lobe_chat_repo() {
  if [ "${SYNC_LOBE_CHAT}" != "1" ]; then
    log "skip lobe-chat sync (SYNC_LOBE_CHAT=${SYNC_LOBE_CHAT})"
    return
  fi

  local backup
  if [ ! -d "${LOBE_CHAT_DIR}/.git" ]; then
    log "clone lobe-chat repo -> ${LOBE_CHAT_DIR}"
    rm -rf "${LOBE_CHAT_DIR}"
    git clone --depth 1 --branch "${LOBE_CHAT_REF}" "${LOBE_CHAT_REPO_URL}" "${LOBE_CHAT_DIR}"
    return
  fi

  log "update lobe-chat repo (${LOBE_CHAT_REF})"
  if git -C "${LOBE_CHAT_DIR}" fetch origin "${LOBE_CHAT_REF}" --depth 1 &&
    git -C "${LOBE_CHAT_DIR}" checkout "${LOBE_CHAT_REF}" &&
    git -C "${LOBE_CHAT_DIR}" pull --ff-only origin "${LOBE_CHAT_REF}"; then
    return
  fi

  backup="${LOBE_CHAT_DIR}.backup.$(date +%Y%m%d-%H%M%S)"
  if [ "${KEEP_LOBE_CHAT_BACKUP_ON_SYNC_FAIL}" = "1" ]; then
    log "WARN: repo update failed. backup current dir -> ${backup}"
    mv "${LOBE_CHAT_DIR}" "${backup}"
  else
    log "WARN: repo update failed. remove current dir and re-clone (no backup)"
    rm -rf "${LOBE_CHAT_DIR}"
  fi
  git clone --depth 1 --branch "${LOBE_CHAT_REF}" "${LOBE_CHAT_REPO_URL}" "${LOBE_CHAT_DIR}"
}

ensure_postgres_started() {
  if command -v pg_lsclusters >/dev/null 2>&1; then
    local first
    first="$(pg_lsclusters --no-header | awk 'NR==1 {print $1" "$2" "$4}')"
    if [ -z "${first}" ]; then
      log "ERROR: postgres cluster not found"
      exit 1
    fi
    local ver name status
    ver="$(echo "${first}" | awk '{print $1}')"
    name="$(echo "${first}" | awk '{print $2}')"
    status="$(echo "${first}" | awk '{print $3}')"
    POSTGRES_CLUSTER_VERSION="${ver}"
    POSTGRES_CLUSTER_NAME="${name}"
    if [ "${status}" != "online" ]; then
      pg_ctlcluster "${ver}" "${name}" start
    fi
  else
    service postgresql start || true
  fi
}

restart_postgres() {
  if [ -n "${POSTGRES_CLUSTER_VERSION}" ] && [ -n "${POSTGRES_CLUSTER_NAME}" ] && command -v pg_ctlcluster >/dev/null 2>&1; then
    pg_ctlcluster "${POSTGRES_CLUSTER_VERSION}" "${POSTGRES_CLUSTER_NAME}" restart
  else
    service postgresql restart || true
  fi
}

ensure_pgvector_extension() {
  if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_available_extensions WHERE name='vector'" | grep -q 1; then
    log "pgvector already available"
    return
  fi

  local pg_major
  pg_major="${POSTGRES_CLUSTER_VERSION}"
  if [ -z "${pg_major}" ]; then
    pg_major="$(runuser -u postgres -- psql -tAc 'SHOW server_version_num' | cut -c1-2)"
  fi
  if [ -z "${pg_major}" ]; then
    log "ERROR: failed to detect PostgreSQL major version"
    exit 1
  fi

  log "install pgvector for PostgreSQL ${pg_major}"
  if apt-get install -y "postgresql-${pg_major}-pgvector"; then
    log "installed pgvector from apt"
  else
    log "pgvector apt package not found, build from source (${PGVECTOR_VERSION})"
    apt-get install -y build-essential "postgresql-server-dev-${pg_major}" git
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    git clone --depth 1 --branch "${PGVECTOR_VERSION}" https://github.com/pgvector/pgvector.git "${tmp_dir}/pgvector"
    make -C "${tmp_dir}/pgvector"
    make -C "${tmp_dir}/pgvector" install
    rm -rf "${tmp_dir}"
  fi

  restart_postgres
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_available_extensions WHERE name='vector'" | grep -q 1; then
    log "ERROR: pgvector extension is unavailable after install"
    exit 1
  fi
}

ensure_secret_file() {
  local path="$1"
  local generator="$2"
  mkdir -p "$(dirname "$path")"
  if [ ! -s "$path" ]; then
    eval "$generator" > "$path"
    chmod 600 "$path"
  fi
}

ensure_db_and_env() {
  if [ ! -s "${AUTH_TOKEN_FILE}" ]; then
    log "ERROR: auth token not found: ${AUTH_TOKEN_FILE}"
    exit 1
  fi

  ensure_secret_file "${DB_PASSWORD_FILE}" 'openssl rand -hex 16'
  ensure_secret_file "${AUTH_SECRET_FILE}" 'openssl rand -base64 32'
  ensure_secret_file "${KEY_VAULTS_SECRET_FILE}" 'openssl rand -base64 32'

  local db_pass
  local auth_secret
  local key_vaults_secret
  local api_key
  db_pass="$(tr -d '\n' < "${DB_PASSWORD_FILE}")"
  auth_secret="$(tr -d '\n' < "${AUTH_SECRET_FILE}")"
  key_vaults_secret="$(tr -d '\n' < "${KEY_VAULTS_SECRET_FILE}")"
  api_key="$(tr -d '\n' < "${AUTH_TOKEN_FILE}")"

  runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
    runuser -u postgres -- psql -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${db_pass}';"
  runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
    runuser -u postgres -- psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
  runuser -u postgres -- psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null

  local db_url
  db_url="postgresql://${DB_USER}:${db_pass}@127.0.0.1:5432/${DB_NAME}"

  mkdir -p "${LOBE_ENV_DIR}" "$(dirname "${LOBE_ENV_LINK}")"
  cat > "${LOBE_ENV_FILE}" <<EOF
APP_URL=${APP_URL}
AUTH_SECRET=${auth_secret}
KEY_VAULTS_SECRET=${key_vaults_secret}
DATABASE_DRIVER=node
DATABASE_URL=${db_url}
SSRF_ALLOW_PRIVATE_IP_ADDRESS=1
OPENAI_API_KEY=${api_key}
OPENAI_PROXY_URL=${OPENAI_PROXY_URL}
OPENAI_MODEL_LIST=${OPENAI_MODEL_LIST}
EOF
  chmod 600 "${LOBE_ENV_FILE}"
  ln -sfn "${LOBE_ENV_FILE}" "${LOBE_ENV_LINK}"
}

ensure_lobehub_dependencies() {
  if [ "${SKIP_PNPM_INSTALL}" = "1" ]; then
    if [ -d "${LOBE_CHAT_DIR}/node_modules" ]; then
      log "skip pnpm install (SKIP_PNPM_INSTALL=1)"
      return
    fi
    log "SKIP_PNPM_INSTALL=1 but node_modules is missing. run pnpm install."
  fi

  log "run pnpm install (first time may take long)"
  (
    cd "${LOBE_CHAT_DIR}"
    pnpm install
  )
}

run_db_migration() {
  set -a
  # shellcheck disable=SC1090
  source "${LOBE_ENV_FILE}"
  set +a

  (
    cd "${LOBE_CHAT_DIR}"
    MIGRATION_DB=1 pnpm exec tsx ./scripts/migrateServerDB/index.ts
  )
}

ensure_lobehub_build_for_start() {
  if [ "${LOBE_RUN_MODE}" != "start" ]; then
    return
  fi

  if [ -f "${LOBE_CHAT_DIR}/.next/BUILD_ID" ]; then
    log "next build cache found. skip build for next start"
    return
  fi

  log "build lobehub for next start (first time may take long)"
  (
    cd "${LOBE_CHAT_DIR}"
    set -a
    # shellcheck disable=SC1090
    source "${LOBE_ENV_FILE}"
    set +a
    local node_opts="${NODE_OPTIONS:---max-old-space-size=8192}"
    NODE_OPTIONS="${node_opts}" pnpm build
  )
}

start_lobehub_app() {
  mkdir -p "${LOG_DIR}"
  pkill -f "next dev -H 0.0.0.0 -p ${LOBE_PORT}" 2>/dev/null || true
  pkill -f "next start -H 0.0.0.0 -p ${LOBE_PORT}" 2>/dev/null || true

  local launch_cmd max_wait_loops
  if [ "${LOBE_RUN_MODE}" = "start" ]; then
    ensure_lobehub_build_for_start
    launch_cmd="pnpm exec next start -H 0.0.0.0 -p ${LOBE_PORT}"
    LOBE_ACTIVE_LOG_FILE="${LOBE_START_LOG_FILE}"
    max_wait_loops=180
  elif [ "${LOBE_RUN_MODE}" = "dev" ]; then
    launch_cmd="pnpm exec next dev -H 0.0.0.0 -p ${LOBE_PORT} --webpack"
    LOBE_ACTIVE_LOG_FILE="${LOBE_DEV_LOG_FILE}"
    max_wait_loops=300
  else
    log "ERROR: unsupported LOBE_RUN_MODE=${LOBE_RUN_MODE} (allowed: start|dev)"
    exit 1
  fi

  log "launch lobehub mode=${LOBE_RUN_MODE}"
  nohup bash -lc "cd '${LOBE_CHAT_DIR}' && set -a && source '${LOBE_ENV_FILE}' && set +a && ${launch_cmd}" \
    > "${LOBE_ACTIVE_LOG_FILE}" 2>&1 &

  local ready=0
  for _ in $(seq 1 "${max_wait_loops}"); do
    if curl -fsS "http://127.0.0.1:${LOBE_PORT}/" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "${ready}" -ne 1 ]; then
    log "ERROR: lobehub did not become ready on port ${LOBE_PORT}"
    tail -n 120 "${LOBE_ACTIVE_LOG_FILE}" || true
    exit 1
  fi
}

ensure_basic_auth_users() {
  mkdir -p "$(dirname "${LOBE_AUTH_FILE}")"
  if [ -s "${LOBE_AUTH_FILE}" ] && [ -s "${LOBE_AUTH_CREDS_FILE}" ]; then
    log "basic auth users already exist"
    return
  fi

  rm -f "${LOBE_AUTH_FILE}" "${LOBE_AUTH_CREDS_FILE}"
  local i user pass
  for i in $(seq 1 "${LOBE_AUTH_USER_COUNT}"); do
    user="$(printf "%s%02d" "${LOBE_AUTH_USER_PREFIX}" "${i}")"
    pass="$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-"${LOBE_AUTH_PASSWORD_LENGTH}")"
    if [ ! -f "${LOBE_AUTH_FILE}" ]; then
      printf '%s\n' "${pass}" | htpasswd -iBc "${LOBE_AUTH_FILE}" "${user}" >/dev/null
    else
      printf '%s\n' "${pass}" | htpasswd -iB "${LOBE_AUTH_FILE}" "${user}" >/dev/null
    fi
    printf "%s:%s\n" "${user}" "${pass}" >> "${LOBE_AUTH_CREDS_FILE}"
  done
  chmod 600 "${LOBE_AUTH_FILE}" "${LOBE_AUTH_CREDS_FILE}"
}

write_lobehub_auth_nginx() {
  local conf="${WORKSPACE_DIR}/nginx-lobehub-auth/nginx.conf"
  mkdir -p "${WORKSPACE_DIR}/nginx-lobehub-auth" "${LOG_DIR}"
  cat > "${conf}" <<EOF
worker_processes 1;
pid ${WORKSPACE_DIR}/nginx-lobehub-auth/nginx.pid;
error_log ${LOG_DIR}/nginx-lobehub-auth-error.log info;

events { worker_connections 1024; }

http {
    map \$http_upgrade \$connection_upgrade {
        default upgrade;
        ''      close;
    }

    server {
        listen ${LOBE_AUTH_PORT};

        location = /healthz {
            auth_basic off;
            return 200 "ok\\n";
        }

        auth_basic "${LOBE_AUTH_REALM}";
        auth_basic_user_file ${LOBE_AUTH_FILE};

        location / {
            proxy_pass http://127.0.0.1:${LOBE_PORT};
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection \$connection_upgrade;
            proxy_read_timeout 3600;
            proxy_send_timeout 3600;
            proxy_buffering off;
        }
    }
}
EOF
}

start_lobehub_auth_proxy() {
  local conf="${WORKSPACE_DIR}/nginx-lobehub-auth/nginx.conf"
  nginx -c "${conf}" -s quit 2>/dev/null || true
  rm -f "${WORKSPACE_DIR}/nginx-lobehub-auth/nginx.pid"
  nginx -t -c "${conf}"
  nginx -c "${conf}"
}

health_check() {
  local first auth_user auth_pass
  first="$(head -n1 "${LOBE_AUTH_CREDS_FILE}")"
  auth_user="${first%%:*}"
  auth_pass="${first#*:}"

  local app_http noauth_http auth_http ok=0
  for _ in $(seq 1 90); do
    app_http="$(curl -sS -L -o /dev/null -w '%{http_code}' "http://127.0.0.1:${LOBE_PORT}/" || true)"
    noauth_http="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${LOBE_AUTH_PORT}/" || true)"
    auth_http="$(curl -sS -L -u "${auth_user}:${auth_pass}" -o /dev/null -w '%{http_code}' "http://127.0.0.1:${LOBE_AUTH_PORT}/" || true)"

    log "health: ${LOBE_PORT}=${app_http}"
    log "health: ${LOBE_AUTH_PORT} noauth=${noauth_http} auth=${auth_http}"
    if [[ "${app_http}" =~ ^[23][0-9][0-9]$ ]] &&
      [ "${noauth_http}" = "401" ] &&
      [[ "${auth_http}" =~ ^[23][0-9][0-9]$ ]]; then
      ok=1
      break
    fi
    sleep 2
  done

  if [ "${ok}" -ne 1 ]; then
    log "ERROR: unexpected health status for lobehub auth proxy"
    curl -sS "http://127.0.0.1:${LOBE_PORT}/" -o /tmp/lobehub-3210-error.html || true
    log "hint: /tmp/lobehub-3210-error.html and ${LOBE_ACTIVE_LOG_FILE}"
    tail -n 120 "${LOBE_ACTIVE_LOG_FILE}" || true
    exit 1
  fi
}

main() {
  apply_fast_start_defaults
  cleanup_workspace_artifacts
  ensure_base_packages
  ensure_node_toolchain
  ensure_pnpm_build_policy
  sync_lobe_chat_repo
  ensure_postgres_started
  ensure_pgvector_extension
  ensure_db_and_env
  ensure_lobehub_dependencies
  run_db_migration
  start_lobehub_app
  ensure_basic_auth_users
  write_lobehub_auth_nginx
  start_lobehub_auth_proxy
  health_check
  log "done"
}

main "$@"
