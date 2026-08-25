# Troubleshooting

## Common failures

### Xpra returns `ERR_INVALID_HTTP_RESPONSE` while curl succeeds

Symptom: the Xpra HTML URL works with a simple local curl, but a user's browser reports `ERR_INVALID_HTTP_RESPONSE`. The Xpra log records `invalid packet format, HTTP GET request` for that browser or its network proxy.

Cause: Xpra 3.1's mixed HTTP/native-protocol listener can misclassify some valid browser or proxy request forms even though simpler origin-form requests work.

Action:

- Do not expose Xpra's mixed-protocol socket directly.
- Keep Xpra on the managed loopback backend `127.0.0.1:14501`.
- Run `xpra_http_gateway.mjs` on external `14500`; it emits standard HTTP/1.1, normalizes absolute-form targets, and forwards WebSocket upgrades only to the loopback Xpra backend.
- Verify an ordinary GET, an absolute-form GET, and an authenticated `ws://` Xpra info request before returning the URL.

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

### MCP endpoint validation passes but the server exits immediately

Symptom: `verify_mcp_cdp_config.py` reports the fixed endpoint correctly, but the MCP process fails before serving tools. A common server case is that an interactive shell uses a user-local Node.js while the MCP host inherits an older system `PATH`.

Action:

- Run the configured MCP command with the exact environment inherited by the host and inspect its version/startup output.
- Compare the active Node.js version with the MCP package's declared engine requirement.
- If Node.js lives under a user-local prefix, add that prefix to the MCP server's configured `PATH`; do not rely on interactive shell initialization.
- Restart the MCP host and complete a harmless protocol call such as listing pages or tabs. Endpoint validation alone does not prove executable health.

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
- If that managed process stays alive but the endpoint never becomes reachable, treat it as a stale managed instance: stop the browser processes for the managed profile, clear stale singleton locks, and relaunch on 9222.
- If no matching process exists and the profile is unused, start a fresh Chrome instance and rewrite state.
- If another Chrome owns the profile without the debugging argument, leave state intact for diagnosis and relaunch that browser deliberately.

### Two agents try to launch at once

Action:

- Use the `.launch.lock` directory as a coarse lock.
- Re-check session state after obtaining the lock. Another agent may have already launched Chrome.
