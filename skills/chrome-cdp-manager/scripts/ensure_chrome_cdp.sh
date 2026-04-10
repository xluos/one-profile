#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/chrome_paths.sh"
source "${SCRIPT_DIR}/choose_port.sh"

STATE_DIR="${CHROME_CDP_STATE_DIR:-$HOME/.agents-profile/main}"
PROFILE_DIR="${CHROME_CDP_PROFILE_DIR:-$STATE_DIR/chrome-profile}"
PORT_FILE="${STATE_DIR}/.cdp-port"
SESSION_FILE="${STATE_DIR}/session.json"
LOCK_DIR="${STATE_DIR}/.launch.lock"
PREFERRED_PORT="${CHROME_CDP_PREFERRED_PORT:-9222}"
STARTUP_TIMEOUT_SECONDS="${CHROME_CDP_STARTUP_TIMEOUT_SECONDS:-15}"
LAUNCH_LOG="${STATE_DIR}/chrome-launch.log"

mkdir -p "${STATE_DIR}" "${PROFILE_DIR}"

cleanup_lock() {
  rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true
}

acquire_lock() {
  local waited=0
  while ! mkdir "${LOCK_DIR}" >/dev/null 2>&1; do
    sleep 0.2
    waited=$((waited + 1))
    if (( waited > 100 )); then
      echo "failed to acquire launch lock" >&2
      return 1
    fi
  done
  trap cleanup_lock EXIT
}

cleanup_stale_state() {
  rm -f "${PORT_FILE}" "${SESSION_FILE}"
}

pid_is_running() {
  local pid="${1:-0}"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  (( pid > 0 )) || return 1
  kill -0 "${pid}" >/dev/null 2>&1
}

profile_in_use() {
  python3 - "${PROFILE_DIR}" <<'PY'
import subprocess
import sys

profile_dir = sys.argv[1]

try:
    output = subprocess.check_output(
        ["ps", "-axww", "-o", "pid=", "-o", "command="],
        text=True,
    )
except Exception:
    sys.exit(1)

matches = []
for line in output.splitlines():
    line = line.strip()
    if not line or profile_dir not in line:
        continue
    parts = line.split(None, 1)
    if len(parts) != 2:
        continue
    pid, command = parts
    if "Chrome" not in command:
        continue
    matches.append(pid)

if matches:
    print("\n".join(matches))
    sys.exit(0)

sys.exit(1)
PY
}

cleanup_profile_singletons() {
  if profile_in_use >/dev/null 2>&1; then
    return 1
  fi

  rm -rf \
    "${PROFILE_DIR}/SingletonLock" \
    "${PROFILE_DIR}/SingletonCookie" \
    "${PROFILE_DIR}/SingletonSocket"
}

read_port_from_state() {
  if [[ -f "${SESSION_FILE}" ]]; then
    python3 - "${SESSION_FILE}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text())
except Exception:
    sys.exit(1)

port = data.get("port")
if isinstance(port, int):
    print(port)
    sys.exit(0)
sys.exit(1)
PY
    return
  fi

  if [[ -f "${PORT_FILE}" ]]; then
    tr -dc '0-9' < "${PORT_FILE}"
    return
  fi

  return 1
}

probe_cdp() {
  local port="$1"
  local response

  response="$(curl --silent --show-error --max-time 1 "http://127.0.0.1:${port}/json/version" || true)"
  if [[ -z "${response}" ]]; then
    return 1
  fi

  python3 - "$response" <<'PY'
import json
import sys

raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    sys.exit(1)

ws_url = data.get("webSocketDebuggerUrl")
browser = data.get("Browser", "")
if not ws_url or "Chrome" not in browser:
    sys.exit(1)

print(json.dumps({"browser": browser, "ws_url": ws_url}))
PY
}

write_state() {
  local port="$1"
  local ws_url="$2"
  local chrome_path="$3"
  local pid="$4"
  python3 - "${SESSION_FILE}" "${port}" "${ws_url}" "${PROFILE_DIR}" "${chrome_path}" "${pid}" <<'PY'
import json
import pathlib
import sys

session_file = pathlib.Path(sys.argv[1])
port = int(sys.argv[2])
ws_url = sys.argv[3]
profile_dir = sys.argv[4]
chrome_path = sys.argv[5]
pid = int(sys.argv[6])

payload = {
    "port": port,
    "ws_url": ws_url,
    "profile_dir": profile_dir,
    "chrome_path": chrome_path,
    "pid": pid,
}
session_file.write_text(json.dumps(payload, indent=2) + "\n")
PY
  printf '%s\n' "${port}" > "${PORT_FILE}"
}

emit_result() {
  local port="$1"
  local ws_url="$2"
  local chrome_path="$3"
  local pid="$4"
  local reused="$5"
  python3 - "$port" "$ws_url" "${PROFILE_DIR}" "$reused" "$chrome_path" "$pid" <<'PY'
import json
import sys

port = int(sys.argv[1])
ws_url = sys.argv[2]
profile_dir = sys.argv[3]
reused = sys.argv[4].lower() == "true"
chrome_path = sys.argv[5]
pid = int(sys.argv[6])

print(json.dumps({
    "port": port,
    "ws_url": ws_url,
    "profile_dir": profile_dir,
    "reused": reused,
    "chrome_path": chrome_path,
    "pid": pid,
}))
PY
}

launch_chrome() {
  local port="$1"
  local chrome_path="$2"

  : > "${LAUNCH_LOG}"
  "${chrome_path}" \
    --remote-debugging-port="${port}" \
    --user-data-dir="${PROFILE_DIR}" \
    --no-first-run \
    --no-default-browser-check \
    >>"${LAUNCH_LOG}" 2>&1 &

  echo $!
}

wait_for_cdp() {
  local port="$1"
  local deadline=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
  local payload

  while (( SECONDS < deadline )); do
    payload="$(probe_cdp "${port}" || true)"
    if [[ -n "${payload}" ]]; then
      printf '%s\n' "${payload}"
      return 0
    fi
    sleep 0.5
  done

  return 1
}

main() {
  local chrome_path
  chrome_path="$(find_chrome_binary)" || {
    echo "chrome binary not found" >&2
    exit 1
  }

  acquire_lock

  local existing_port=""
  local probe_payload=""
  if existing_port="$(read_port_from_state 2>/dev/null || true)"; then
    if [[ -n "${existing_port}" ]]; then
      probe_payload="$(probe_cdp "${existing_port}" || true)"
      if [[ -n "${probe_payload}" ]]; then
        local ws_url
        ws_url="$(python3 - "${probe_payload}" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["ws_url"])
PY
)"
        local pid
        pid="$(python3 - "${SESSION_FILE}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print(0)
    sys.exit(0)
try:
    data = json.loads(path.read_text())
except Exception:
    print(0)
    sys.exit(0)
print(int(data.get("pid") or 0))
PY
)"
        write_state "${existing_port}" "${ws_url}" "${chrome_path}" "${pid:-0}"
        emit_result "${existing_port}" "${ws_url}" "${chrome_path}" "${pid:-0}" true
        return 0
      fi
    fi
  fi

  cleanup_stale_state
  cleanup_profile_singletons >/dev/null 2>&1 || true

  local port
  port="$(choose_free_port "${PREFERRED_PORT}")"

  local pid
  pid="$(launch_chrome "${port}" "${chrome_path}")"

  probe_payload="$(wait_for_cdp "${port}")" || {
    if ! pid_is_running "${pid}"; then
      cleanup_profile_singletons >/dev/null 2>&1 || true
    fi
    echo "chrome cdp did not become ready on port ${port}" >&2
    echo "launch log: ${LAUNCH_LOG}" >&2
    exit 1
  }

  local ws_url
  ws_url="$(python3 - "${probe_payload}" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["ws_url"])
PY
)"

  write_state "${port}" "${ws_url}" "${chrome_path}" "${pid}"
  emit_result "${port}" "${ws_url}" "${chrome_path}" "${pid}" false
}

main "$@"
