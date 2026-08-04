#!/usr/bin/env bash
set -Eeuo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
machine_name="${PODMAN_MACHINE_NAME:-podman-machine-default}"
db_volume="${JOBPICKY_PODMAN_DB_VOLUME:-ai-jobpicky_db-data}"

fail() {
  printf '启动失败：%s\n' "$*" >&2
  exit 1
}

cd "$root_dir"

command -v podman >/dev/null 2>&1 || fail "找不到 podman，请先安装 Podman。"
command -v uv >/dev/null 2>&1 || fail "找不到 uv，请先安装 uv。"
command -v node >/dev/null 2>&1 || fail "找不到 node，请先安装 Node.js LTS。"
command -v pnpm >/dev/null 2>&1 || fail "找不到 pnpm，请先安装前端依赖管理工具。"
[[ -f "$root_dir/.env" ]] || fail "缺少根目录 .env，请先配置本地运行环境。"
[[ -d "$root_dir/frontend/node_modules" ]] || fail "缺少前端依赖，请先执行 pnpm --dir frontend install。"

if ! podman info >/dev/null 2>&1; then
  podman machine start "$machine_name" >/dev/null 2>&1 || true
  for attempt in $(seq 1 30); do
    podman info >/dev/null 2>&1 && break
    if [[ "$attempt" == 30 ]]; then
      fail "Podman machine 在 30 秒内没有恢复连接。"
    fi
    sleep 1
  done
fi

if podman container exists jobpicky-db 2>/dev/null; then
  db_status="$(podman inspect --format '{{.State.Status}}' jobpicky-db)"
  [[ "$db_status" == "running" ]] || podman start jobpicky-db >/dev/null
else
  podman volume exists "$db_volume" || fail "找不到数据库卷 $db_volume，未创建新的空卷。"
  podman run -d \
    --name jobpicky-db \
    -e POSTGRES_USER=jobpicky \
    -e POSTGRES_PASSWORD=jobpicky \
    -e POSTGRES_DB=jobpicky \
    -p 5432:5432 \
    -v "$db_volume:/var/lib/postgresql/data" \
    --health-cmd='pg_isready -U jobpicky -d jobpicky' \
    --health-interval=2s \
    --health-timeout=3s \
    --health-retries=15 \
    pgvector/pgvector:pg16 >/dev/null
fi

for attempt in $(seq 1 30); do
  if podman exec jobpicky-db pg_isready -U jobpicky -d jobpicky >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 30 ]]; then
    fail "数据库在 30 秒内没有通过健康检查。"
  fi
  sleep 1
done

set -a
# shellcheck disable=SC1091
source "$root_dir/.env"
set +a

PYTHONPATH="$root_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
  uv run python -m alembic upgrade head

backend_pid=""
frontend_pid=""
cleanup() {
  trap - INT TERM EXIT
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

printf '启动后端和前端；请求日志会显示在当前终端。\n'
printf '按 Ctrl-C 停止前后端，数据库保持运行。\n'

(
  exec env PYTHONPATH="$root_dir/src" \
    uv run python -m uvicorn jobpicky.main:app \
    --reload --host 127.0.0.1 --port 8000
) &
backend_pid=$!

(
  cd "$root_dir/frontend"
  exec pnpm dev --host 127.0.0.1 --port 5173
) &
frontend_pid=$!

for attempt in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8000/api/v1/system/health >/dev/null 2>&1 && break
  if [[ "$attempt" == 20 ]]; then
    fail "后端在 20 秒内没有启动。"
  fi
  sleep 1
done

for attempt in $(seq 1 20); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5173/)" == "200" ]] && break
  if [[ "$attempt" == 20 ]]; then
    fail "前端在 20 秒内没有启动。"
  fi
  sleep 1
done

printf 'Podman、数据库、后端和前端已启动。\n'
printf '前端：http://127.0.0.1:5173\n'
printf '后端：http://127.0.0.1:8000\n'
printf 'API 文档：http://127.0.0.1:8000/docs\n'

wait "$backend_pid" "$frontend_pid"
