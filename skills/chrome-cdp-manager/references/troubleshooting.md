# Troubleshooting

## Common failures

### Port is occupied but not Chrome

Symptom: `http://127.0.0.1:<port>/json/version` fails or returns non-JSON.

Action:

- Treat the port as stale.
- Free port 9222; do not pick another port because MCP clients use the fixed endpoint.
- Rewrite `.cdp-port` and `session.json` only after the managed endpoint is ready.

### Profile is in use but the state files are missing

Symptom: Chrome is running with `--user-data-dir=<managed-profile>` and `--remote-debugging-port=9222`, and `/json/version` responds, but `session.json` or `.cdp-port` is missing or corrupt.

Cause: the state files are caches and can drift across a Chrome restart, an interrupted write, or a prior failed probe. Their absence does not prove that the CDP endpoint is gone.

Action:

- Run `scripts/ensure_chrome_cdp.sh` again. It probes fixed port 9222, verifies the live Chrome main process arguments, and rebuilds both cache files.
- Do not close the browser or delete profile locks when the live endpoint and process match.
- If recovery still fails, probe `http://127.0.0.1:9222/json/version` and inspect the main Chrome command line separately. This distinguishes a temporarily unresponsive endpoint from a profile opened without the debugging flag.

### An MCP launches another Chrome after reuse succeeds

Symptom: `ensure_chrome_cdp.sh` returns `reused: true`, but another Chrome appears with `--remote-debugging-pipe` and a profile such as `~/.cache/chrome-devtools-mcp/chrome-profile`.

Cause: the MCP process started without the fixed CDP endpoint. Reusing 9222 does not redirect an already misconfigured MCP process.

Action:

- Run `scripts/verify_mcp_cdp_config.py --client <host>`.
- Configure `chrome-devtools-mcp` with `--browserUrl http://127.0.0.1:9222`.
- Configure `@playwright/mcp` with `--cdp-endpoint http://127.0.0.1:9222`.
- Restart the MCP host so existing server processes reload their arguments.
- Stop the pipe-launched Chrome only after confirming it has no work that must be preserved.

### Chrome exits immediately

Common causes:

- The Chrome binary path is wrong.
- The profile directory has stale singleton lock files.
- Another Chrome process is already using the same custom profile.

Action:

- Verify the detected Chrome path.
- Inspect `chrome-launch.log` under the state directory for startup errors.
- Inspect `chrome-profile/` for stale lock files only if Chrome is not running.
- Do not reuse the system default profile.

### Session file exists but endpoint is dead

Action:

- Check whether a Chrome main process still has both the managed profile and `--remote-debugging-port=9222` arguments.
- If it does, wait for the endpoint and let `ensure_chrome_cdp.sh` normalize `session.json` with the current `ws_url` and `pid`.
- If no matching process exists and the profile is unused, start a fresh Chrome instance and rewrite state.
- If another Chrome owns the profile without the debugging argument, leave state intact for diagnosis and relaunch that browser deliberately.

### Two agents try to launch at once

Action:

- Use the `.launch.lock` directory as a coarse lock.
- Re-check session state after obtaining the lock. Another agent may have already launched Chrome.
