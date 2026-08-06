#!/usr/bin/env bash
# Reverse SSH tunnel: expose the local backend (127.0.0.1:8000) on the
# public server's loopback (127.0.0.1:8000), where Nginx proxies /api/*.
#
# Generic on purpose: the server is just an SSH target, so switching to a
# new server only means passing a different argument (and installing the
# local SSH key there with ssh-copy-id).
#
# Usage:
#   scripts/tunnel.sh [user@host]
#   JOBPICKY_TUNNEL_SERVER=root@1.2.3.4 scripts/tunnel.sh
set -u

SERVER="${1:-${JOBPICKY_TUNNEL_SERVER:-root@8.148.245.60}}"
REMOTE_PORT="${JOBPICKY_TUNNEL_REMOTE_PORT:-8000}"
LOCAL_PORT="${JOBPICKY_TUNNEL_LOCAL_PORT:-8000}"

while true; do
  echo "[tunnel] exposing 127.0.0.1:${LOCAL_PORT} on ${SERVER}:127.0.0.1:${REMOTE_PORT}" >&2
  ssh -N \
    -o BatchMode=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R "127.0.0.1:${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}" \
    "$SERVER"
  echo "[tunnel] connection to ${SERVER} lost, retrying in 5s..." >&2
  sleep 5
done
