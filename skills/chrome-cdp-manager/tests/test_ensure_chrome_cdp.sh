#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENSURE_SCRIPT="${SCRIPT_DIR}/../scripts/ensure_chrome_cdp.sh"
PASSED=0

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "expected file: $1"
}

assert_contains() {
  local value="$1"
  local expected="$2"
  [[ "${value}" == *"${expected}"* ]] || fail "expected '${expected}' in '${value}'"
}

run_case() {
  local name="$1"
  shift
  "$@"
  PASSED=$((PASSED + 1))
  echo "PASS: ${name}"
}

case_missing_state_recovers_live_endpoint() (
  local root
  root="$(mktemp -d)"
  trap 'rm -rf "${root}"' EXIT
  export CHROME_CDP_STATE_DIR="${root}/state"
  export CHROME_CDP_PROFILE_DIR="${root}/profile"
  export CHROME_CDP_STARTUP_TIMEOUT_SECONDS=1
  source "${ENSURE_SCRIPT}"

  acquire_lock() { :; }
  find_chrome_binary() { printf '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n'; }
  find_managed_pid() { [[ "$1" == "9222" ]] && printf '4242\n'; }
  wait_for_cdp() { printf '{"browser":"Chrome/150","ws_url":"ws://127.0.0.1:9222/devtools/browser/recovered"}\n'; }
  profile_in_use() { printf '4242\n'; }

  local output
  output="$(main)"
  assert_contains "${output}" '"reused": true'
  assert_contains "${output}" '"pid": 4242'
  assert_file "${CHROME_CDP_STATE_DIR}/session.json"
  assert_file "${CHROME_CDP_STATE_DIR}/.cdp-port"
  [[ "$(<"${CHROME_CDP_STATE_DIR}/.cdp-port")" == "9222" ]] || fail "port cache was not rebuilt"
)

case_corrupt_session_falls_back_to_port_cache() (
  local root
  root="$(mktemp -d)"
  trap 'rm -rf "${root}"' EXIT
  export CHROME_CDP_STATE_DIR="${root}/state"
  export CHROME_CDP_PROFILE_DIR="${root}/profile"
  mkdir -p "${CHROME_CDP_STATE_DIR}" "${CHROME_CDP_PROFILE_DIR}"
  printf '{broken json\n' > "${CHROME_CDP_STATE_DIR}/session.json"
  printf '9222\n' > "${CHROME_CDP_STATE_DIR}/.cdp-port"
  source "${ENSURE_SCRIPT}"

  acquire_lock() { :; }
  find_chrome_binary() { printf '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n'; }
  find_managed_pid() { printf '5252\n'; }
  probe_cdp() { printf '{"browser":"Chrome/150","ws_url":"ws://127.0.0.1:9222/devtools/browser/port-cache"}\n'; }

  local output
  output="$(main)"
  assert_contains "${output}" '"reused": true'
  assert_contains "$(<"${CHROME_CDP_STATE_DIR}/session.json")" '"pid": 5252'
)

case_transient_probe_uses_ready_wait() (
  local root
  root="$(mktemp -d)"
  trap 'rm -rf "${root}"' EXIT
  export CHROME_CDP_STATE_DIR="${root}/state"
  export CHROME_CDP_PROFILE_DIR="${root}/profile"
  source "${ENSURE_SCRIPT}"

  acquire_lock() { :; }
  find_chrome_binary() { printf '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n'; }
  find_managed_pid() { printf '6262\n'; }
  probe_cdp() { return 1; }
  wait_for_cdp() {
    printf '{"browser":"Chrome/150","ws_url":"ws://127.0.0.1:9222/devtools/browser/after-wait"}\n'
  }

  local output
  output="$(main)"
  assert_contains "${output}" 'after-wait'
  assert_contains "${output}" '"pid": 6262'
)

case_unexpected_profile_owner_preserves_state() (
  local root
  root="$(mktemp -d)"
  trap 'rm -rf "${root}"' EXIT
  export CHROME_CDP_STATE_DIR="${root}/state"
  export CHROME_CDP_PROFILE_DIR="${root}/profile"
  mkdir -p "${CHROME_CDP_STATE_DIR}" "${CHROME_CDP_PROFILE_DIR}"
  printf '{"port":9222,"marker":"preserve-me"}\n' > "${CHROME_CDP_STATE_DIR}/session.json"
  source "${ENSURE_SCRIPT}"

  acquire_lock() { :; }
  find_chrome_binary() { printf '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n'; }
  find_managed_pid() { return 1; }
  profile_in_use() { printf '7373\n'; }

  local error_file="${root}/error.log"
  if (main) >"${root}/output.log" 2>"${error_file}"; then
    fail "unexpected profile owner should fail"
  fi
  assert_contains "$(<"${error_file}")" 'does not match --remote-debugging-port=9222'
  assert_contains "$(<"${CHROME_CDP_STATE_DIR}/session.json")" 'preserve-me'
)

run_case "missing state recovers live endpoint" case_missing_state_recovers_live_endpoint
run_case "corrupt session falls back to port cache" case_corrupt_session_falls_back_to_port_cache
run_case "transient probe waits for ready endpoint" case_transient_probe_uses_ready_wait
run_case "unexpected profile owner preserves state" case_unexpected_profile_owner_preserves_state

echo "${PASSED} tests passed"
