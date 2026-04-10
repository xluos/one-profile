# Troubleshooting

## Common failures

### Port is occupied but not Chrome

Symptom: `http://127.0.0.1:<port>/json/version` fails or returns non-JSON.

Action:

- Treat the port as stale.
- Pick another free port.
- Rewrite `.cdp-port` and `session.json` only after the new CDP endpoint is ready.

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
