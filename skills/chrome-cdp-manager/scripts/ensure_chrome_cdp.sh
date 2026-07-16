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

find_managed_pid() {
  local port="$1"
  python3 - "${PROFILE_DIR}" "${port}" <<'PY'
import subprocess
import sys

profile_dir = sys.argv[1]
port = sys.argv[2]

try:
    output = subprocess.check_output(
        ["ps", "-axww", "-o", "pid=", "-o", "command="],
        text=True,
    )
except Exception:
    sys.exit(1)

profile_arg = f"--user-data-dir={profile_dir}"
port_arg = f"--remote-debugging-port={port}"
for line in output.splitlines():
    line = line.strip()
    if not line or "Google Chrome Helper" in line:
        continue
    parts = line.split(None, 1)
    if len(parts) != 2:
        continue
    pid, command = parts
    if profile_arg in command and port_arg in command:
        print(pid)
        sys.exit(0)

sys.exit(1)
PY
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
  local session_port=""
  if [[ -f "${SESSION_FILE}" ]]; then
    session_port="$(python3 - "${SESSION_FILE}" <<'PY' || true
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
)"
    if [[ -n "${session_port}" ]]; then
      printf '%s\n' "${session_port}"
      return 0
    fi
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

  response="$(curl --silent --max-time 1 "http://127.0.0.1:${port}/json/version" || true)"
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
  python3 - "${SESSION_FILE}" "${PORT_FILE}" "${port}" "${ws_url}" "${PROFILE_DIR}" "${chrome_path}" "${pid}" <<'PY'
import json
import os
import pathlib
import sys
import tempfile

session_file = pathlib.Path(sys.argv[1])
port_file = pathlib.Path(sys.argv[2])
port = int(sys.argv[3])
ws_url = sys.argv[4]
profile_dir = sys.argv[5]
chrome_path = sys.argv[6]
pid = int(sys.argv[7])

payload = {
    "port": port,
    "ws_url": ws_url,
    "profile_dir": profile_dir,
    "chrome_path": chrome_path,
    "pid": pid,
}


def atomic_write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(descriptor, "w") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


atomic_write(session_file, json.dumps(payload, indent=2) + "\n")
atomic_write(port_file, f"{port}\n")
PY
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

  if [[ "$(uname)" == "Darwin" && "${chrome_path}" == *"/Contents/MacOS/"* ]]; then
    local app_path="${chrome_path%/Contents/MacOS/*}"
    open -n -a "${app_path}" --args \
      --remote-debugging-port="${port}" \
      --user-data-dir="${PROFILE_DIR}" \
      --no-first-run \
      --no-default-browser-check \
      >>"${LAUNCH_LOG}" 2>&1

    local waited=0
    local found_pid=""
    while (( waited < 40 )); do
      found_pid="$(pgrep -f -- "--user-data-dir=${PROFILE_DIR}" | head -n 1 || true)"
      if [[ -n "${found_pid}" ]]; then
        echo "${found_pid}"
        return 0
      fi
      sleep 0.1
      waited=$((waited + 1))
    done

    echo "0"
    return 0
  fi

  nohup "${chrome_path}" \
    --remote-debugging-port="${port}" \
    --user-data-dir="${PROFILE_DIR}" \
    --no-first-run \
    --no-default-browser-check \
    </dev/null >>"${LAUNCH_LOG}" 2>&1 &

  disown "$!" 2>/dev/null || true
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

reuse_managed_endpoint() {
  local port="$1"
  local chrome_path="$2"
  local wait_for_ready="${3:-false}"
  local managed_pid=""
  local probe_payload=""

  managed_pid="$(find_managed_pid "${port}" 2>/dev/null || true)"
  if [[ -z "${managed_pid}" ]]; then
    return 1
  fi

  if [[ "${wait_for_ready}" == "true" ]]; then
    probe_payload="$(wait_for_cdp "${port}" || true)"
  else
    probe_payload="$(probe_cdp "${port}" || true)"
  fi
  if [[ -z "${probe_payload}" ]]; then
    return 1
  fi

  local ws_url
  ws_url="$(python3 - "${probe_payload}" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["ws_url"])
PY
)"

  write_state "${port}" "${ws_url}" "${chrome_path}" "${managed_pid}"
  emit_result "${port}" "${ws_url}" "${chrome_path}" "${managed_pid}" true
}

main() {
  local chrome_path
  chrome_path="$(find_chrome_binary)" || {
    echo "chrome binary not found" >&2
    exit 1
  }

  acquire_lock

  local existing_port=""
  if existing_port="$(read_port_from_state 2>/dev/null || true)"; then
    if [[ -n "${existing_port}" ]]; then
      if reuse_managed_endpoint "${existing_port}" "${chrome_path}" false; then
        return 0
      fi
    fi
  fi

  # State files are caches. If they are missing, corrupt, or stale, rediscover
  # the fixed endpoint from the live Chrome process before considering launch.
  if reuse_managed_endpoint "${PREFERRED_PORT}" "${chrome_path}" true; then
    return 0
  fi

  local existing_pids
  existing_pids="$(profile_in_use 2>/dev/null || true)"
  if [[ -n "${existing_pids}" ]]; then
    local expected_pid=""
    expected_pid="$(find_managed_pid "${PREFERRED_PORT}" 2>/dev/null || true)"
    if [[ -n "${expected_pid}" ]]; then
      echo "managed Chrome pid ${expected_pid} uses profile ${PROFILE_DIR} and port ${PREFERRED_PORT}, but its CDP endpoint did not become reachable within ${STARTUP_TIMEOUT_SECONDS}s." >&2
      echo "keep the profile open and inspect http://127.0.0.1:${PREFERRED_PORT}/json/version plus ${LAUNCH_LOG}." >&2
    else
      echo "profile ${PROFILE_DIR} is already in use by Chrome (pid: $(echo "${existing_pids}" | tr '\n' ' ')), but that process does not match --remote-debugging-port=${PREFERRED_PORT}." >&2
      echo "close or relaunch that Chrome with the managed arguments before retrying; the state files were left intact for diagnosis." >&2
    fi
    exit 1
  fi

  cleanup_profile_singletons >/dev/null 2>&1 || true

  local port="${PREFERRED_PORT}"
  if ! port_is_free "${port}"; then
    if probe_cdp "${port}" >/dev/null 2>&1; then
      echo "port ${port} is occupied by a different CDP endpoint (not the managed Chrome). Stop that instance or run without this skill." >&2
    else
      echo "port ${port} is occupied by a non-CDP process. Free port ${port} before running this skill." >&2
    fi
    exit 1
  fi

  cleanup_stale_state

  local pid
  pid="$(launch_chrome "${port}" "${chrome_path}")"

  local probe_payload
  probe_payload="$(wait_for_cdp "${port}")" || {
    if ! pid_is_running "${pid}"; then
      cleanup_profile_singletons >/dev/null 2>&1 || true
    fi
    echo "chrome cdp did not become ready on port ${port}" >&2
    echo "launch log: ${LAUNCH_LOG}" >&2
    exit 1
  }

  if ! pid_is_running "${pid}"; then
    pid="$(pgrep -f -- "--user-data-dir=${PROFILE_DIR}" | head -n 1 || true)"
    pid="${pid:-0}"
  fi

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

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
