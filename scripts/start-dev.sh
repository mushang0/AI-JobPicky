#!/usr/bin/env bash
set -Eeuo pipefail

runtime="${1:-}"
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  printf '启动失败：%s\n' "$*" >&2
  exit 1
}

usage() {
  printf '用法：%s {docker|podman}\n' "$0" >&2
  exit 64
}

[[ "$runtime" == "docker" || "$runtime" == "podman" ]] || usage
cd "$root_dir"

command -v pnpm >/dev/null 2>&1 || fail "找不到 pnpm，请先安装前端依赖管理工具。"
[[ -f "$root_dir/.env" ]] || fail "缺少根目录 .env，请先配置本地运行环境。"
[[ -d "$root_dir/frontend/node_modules" ]] || fail "缺少前端依赖，请先执行 pnpm --dir frontend install。"

if [[ -n "${CONDA_EXE:-}" ]]; then
  conda_bin="$CONDA_EXE"
else
  conda_bin="$(command -v conda || true)"
fi
[[ -n "$conda_bin" ]] || fail "找不到 conda，请先安装并初始化 Miniforge/Conda。"
backend_runner=("$conda_bin" run --no-capture-output -n base)
if command -v uv >/dev/null 2>&1; then
  migration_runner=(uv run)
else
  migration_runner=("${backend_runner[@]}")
fi

if [[ "$runtime" == "docker" ]]; then
  command -v docker >/dev/null 2>&1 || fail "找不到 docker。"
  if docker compose version >/dev/null 2>&1; then
    compose_command=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    compose_command=(docker-compose)
  else
    fail "找不到 Docker Compose。"
  fi
else
  command -v podman >/dev/null 2>&1 || fail "找不到 podman。"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    podman_machine="${PODMAN_MACHINE:-podman-machine-default}"
    podman machine inspect "$podman_machine" >/dev/null 2>&1 || fail \
      "找不到 Podman machine '$podman_machine'，请先执行 podman machine init。"
    podman_state="$(podman machine inspect "$podman_machine" --format '{{.State}}')"
    if [[ "$podman_state" != "running" ]]; then
      podman machine start "$podman_machine"
    fi
  fi
  compose_command=(podman compose)
fi

# 让迁移和后端读取同一份本地配置；不会打印其中的密钥。
set -a
# shellcheck disable=SC1091
source "$root_dir/.env"
set +a

"${compose_command[@]}" up -d db
for attempt in $(seq 1 30); do
  if "${compose_command[@]}" exec -T db pg_isready \
    -U "${POSTGRES_USER:-jobpicky}" \
    -d "${POSTGRES_DB:-jobpicky}" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 30 ]]; then
    fail "数据库在 30 秒内没有通过健康检查。"
  fi
  sleep 1
done

PYTHONPATH="$root_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
  "${migration_runner[@]}" python -m alembic upgrade head

backend_pid=""
frontend_pid=""
cleanup() {
  trap - INT TERM EXIT
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

printf '数据库已启动（%s）\n' "$runtime"
printf '前端：http://127.0.0.1:5173\n'
printf '后端：http://127.0.0.1:8000\n'
printf '按 Ctrl-C 停止前后端，数据库保持运行。\n'

(
  PYTHONPATH="$root_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
    "${backend_runner[@]}" python -m uvicorn \
    jobpicky.main:app \
    --reload \
    --host 127.0.0.1 \
    --port 8000 \
    --env-file "$root_dir/.env"
) &
backend_pid=$!

(
  cd "$root_dir/frontend"
  pnpm dev --host 127.0.0.1 --port 5173
) &
frontend_pid=$!

wait "$backend_pid" "$frontend_pid"
