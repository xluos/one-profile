#!/usr/bin/env bash

set -euo pipefail

find_chrome_binary() {
  local candidates=()

  if [[ -n "${CHROME_BIN:-}" ]]; then
    candidates+=("${CHROME_BIN}")
  fi

  candidates+=(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"
    "/usr/bin/google-chrome"
    "/usr/bin/google-chrome-stable"
    "/usr/bin/chrome"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  if command -v google-chrome >/dev/null 2>&1; then
    command -v google-chrome
    return 0
  fi

  if command -v google-chrome-stable >/dev/null 2>&1; then
    command -v google-chrome-stable
    return 0
  fi

  return 1
}
