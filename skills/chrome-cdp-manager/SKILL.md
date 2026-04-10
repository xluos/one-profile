---
name: chrome-cdp-manager
description: Reuse or start a Chrome instance with a persistent custom profile and an attachable CDP endpoint. Use this whenever the user wants to keep Chrome login state, reuse an existing Chrome automation session, connect to an already opened Chrome via remote debugging, or manage a dedicated Chrome profile for browser automation instead of launching a fresh stateless browser.
---

# Chrome CDP Manager

Use this skill only for Chrome. Do not generalize it to Chromium, Edge, Safari, or a generic browser router unless the user explicitly asks for that expansion.

## Trigger conditions

Use this skill when the user asks for any of the following:

- Reuse an existing Chrome instance instead of launching a new one
- Keep login state across agent runs
- Attach to Chrome through CDP or remote debugging
- Use a persistent Chrome profile for automation
- Recover a stale Chrome CDP session and relaunch it safely

## State model

The managed state directory is fixed to `~/.agents-profile/main/`.

- Profile directory: `~/.agents-profile/main/chrome-profile/`
- Port file: `~/.agents-profile/main/.cdp-port`
- Session file: `~/.agents-profile/main/session.json`
- Lock dir: `~/.agents-profile/main/.launch.lock`

Treat `session.json` as the source of truth. `.cdp-port` is only a fast path for reconnect.

## Workflow

1. Run `scripts/ensure_chrome_cdp.sh`.
2. Parse its JSON output.
3. If `reused` is `true`, attach to the existing Chrome CDP endpoint.
4. If `reused` is `false`, use the newly started Chrome CDP endpoint.
5. Pass `port` or `ws_url` into the browser automation tool that needs Chrome DevTools access.

## Rules

- Always use the managed custom profile directory. Do not use the user's default daily-browsing Chrome profile.
- Probe the stored port before reusing it.
- If the stored port is stale, start a fresh Chrome instance and rewrite the state files.
- Prevent duplicate launches with the lock dir.
- Return structured JSON so callers do not parse logs.

## Output contract

`scripts/ensure_chrome_cdp.sh` must print one JSON object with these keys:

```json
{
  "port": 9222,
  "ws_url": "ws://127.0.0.1:9222/devtools/browser/...",
  "profile_dir": "/Users/example/.agents-profile/main/chrome-profile",
  "reused": true,
  "chrome_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "pid": 12345
}
```

## Troubleshooting

If Chrome fails to start, or the stored state is inconsistent, read `references/troubleshooting.md` before changing the workflow.
