# Troubleshooting

## Common failures

### Port is occupied but not Chrome

Symptom: `http://127.0.0.1:<port>/json/version` fails or returns non-JSON.

Action:

- Treat the port as stale.
- Free port 9222; do not pick another port because MCP clients use the fixed endpoint.
- Rewrite `.cdp-port` and `session.json` only after the managed endpoint is ready.

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

- Ignore the stored state and rewrite it from a fresh launch.
- Start a fresh Chrome instance.
- Normalize `session.json` with the new `port`, `ws_url`, and `pid`.

### Two agents try to launch at once

Action:

- Use the `.launch.lock` directory as a coarse lock.
- Re-check session state after obtaining the lock. Another agent may have already launched Chrome.
