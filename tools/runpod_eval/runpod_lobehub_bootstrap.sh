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

log() {
  printf '[lobehub-bootstrap] %s\n' "$*"
}

ensure_base_packages() {
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

sync_lobe_chat_repo() {
  if [ ! -d "${LOBE_CHAT_DIR}/.git" ]; then
    log "clone lobe-chat repo -> ${LOBE_CHAT_DIR}"
    rm -rf "${LOBE_CHAT_DIR}"
    git clone --depth 1 --branch "${LOBE_CHAT_REF}" "${LOBE_CHAT_REPO_URL}" "${LOBE_CHAT_DIR}"
    return
  fi

  log "update lobe-chat repo (${LOBE_CHAT_REF})"
  if ! git -C "${LOBE_CHAT_DIR}" fetch origin "${LOBE_CHAT_REF}" --depth 1; then
    log "WARN: git fetch failed. keep existing checkout."
    return
  fi
  if ! git -C "${LOBE_CHAT_DIR}" checkout "${LOBE_CHAT_REF}"; then
    log "WARN: git checkout failed. keep existing branch."
    return
  fi
  if ! git -C "${LOBE_CHAT_DIR}" pull --ff-only origin "${LOBE_CHAT_REF}"; then
    log "WARN: git pull failed (local changes?). keep existing checkout."
  fi
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
    if [ "${status}" != "online" ]; then
      pg_ctlcluster "${ver}" "${name}" start
    fi
  else
    service postgresql start || true
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
  runuser -u postgres -- psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null 2>&1 || true

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
    log "skip pnpm install (SKIP_PNPM_INSTALL=1)"
    return
  fi

  if [ -d "${LOBE_CHAT_DIR}/node_modules" ]; then
    log "node_modules exists. skip pnpm install"
    return
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

start_lobehub_dev() {
  mkdir -p "${LOG_DIR}"
  pkill -f "next dev -H 0.0.0.0 -p ${LOBE_PORT}" 2>/dev/null || true
  nohup bash -lc "cd '${LOBE_CHAT_DIR}' && set -a && source '${LOBE_ENV_FILE}' && set +a && pnpm exec next dev -H 0.0.0.0 -p ${LOBE_PORT} --webpack" \
    > "${LOG_DIR}/lobehub-dev.log" 2>&1 &

  local ready=0
  for _ in $(seq 1 180); do
    if curl -fsS "http://127.0.0.1:${LOBE_PORT}/" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "${ready}" -ne 1 ]; then
    log "ERROR: lobehub did not become ready on port ${LOBE_PORT}"
    tail -n 80 "${LOG_DIR}/lobehub-dev.log" || true
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
  for i in $(seq -w 1 "${LOBE_AUTH_USER_COUNT}"); do
    user="${LOBE_AUTH_USER_PREFIX}${i}"
    pass="$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-"${LOBE_AUTH_PASSWORD_LENGTH}")"
    if [ "${i}" = "01" ]; then
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

  local noauth_http auth_http
  noauth_http="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${LOBE_AUTH_PORT}/")"
  auth_http="$(curl -sS -L -u "${auth_user}:${auth_pass}" -o /dev/null -w '%{http_code}' "http://127.0.0.1:${LOBE_AUTH_PORT}/")"

  log "health: ${LOBE_PORT}=$(curl -sS -L -o /dev/null -w '%{http_code}' "http://127.0.0.1:${LOBE_PORT}/")"
  log "health: ${LOBE_AUTH_PORT} noauth=${noauth_http} auth=${auth_http}"
  if [ "${noauth_http}" != "401" ] || [ "${auth_http}" != "200" ]; then
    log "ERROR: unexpected health status for lobehub auth proxy"
    exit 1
  fi
}

main() {
  ensure_base_packages
  ensure_node_toolchain
  sync_lobe_chat_repo
  ensure_postgres_started
  ensure_db_and_env
  ensure_lobehub_dependencies
  run_db_migration
  start_lobehub_dev
  ensure_basic_auth_users
  write_lobehub_auth_nginx
  start_lobehub_auth_proxy
  health_check
  log "done"
}

main "$@"

