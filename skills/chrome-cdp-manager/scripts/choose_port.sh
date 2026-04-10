#!/usr/bin/env bash

set -euo pipefail

port_is_free() {
  local port="$1"

  if command -v lsof >/dev/null 2>&1; then
    ! lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi

  if command -v nc >/dev/null 2>&1; then
    ! nc -z 127.0.0.1 "${port}" >/dev/null 2>&1
    return
  fi

  python3 - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.2)
try:
    sock.connect(("127.0.0.1", port))
except OSError:
    sys.exit(0)
else:
    sys.exit(1)
finally:
    sock.close()
PY
}

choose_free_port() {
  local preferred="${1:-}"
  local start="${2:-9222}"
  local limit="${3:-100}"
  local port

  if [[ -n "${preferred}" ]] && port_is_free "${preferred}"; then
    printf '%s\n' "${preferred}"
    return 0
  fi

  for ((port = start; port < start + limit; port++)); do
    if port_is_free "${port}"; then
      printf '%s\n' "${port}"
      return 0
    fi
  done

  echo "no free port found" >&2
  return 1
}
