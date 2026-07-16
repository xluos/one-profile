---
name: chrome-cdp-manager
description: Prefer a healthy Codex/ChatGPT Chrome extension connection; otherwise recover, reuse, or start a managed Chrome with a persistent profile on CDP port 9222. Use when browser automation needs an existing Chrome tab, login state, a persistent profile, stale-state recovery, or a fallback connection through chrome-devtools or Playwright.
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

Before using `chrome-devtools`, `Playwright`, or similar browser automation tools, use this skill first when the task requires persistent Chrome state, login reuse, or CDP attachment.

If the task only needs a fresh stateless browser session, do not trigger this skill.

## Control surface priority

Prefer the Codex/ChatGPT Chrome extension control path when it is available:

1. Load and follow the Browser skill for Chrome extension control.
2. Establish an extension browser binding and perform a read-only `openTabs()` probe. A successful binding plus a successful tab probe means the extension path is healthy; an installed extension process alone is not sufficient evidence.
3. When healthy, use the extension browser for the task. Do not run the CDP manager or call standalone browser MCP servers.
4. When the extension is unavailable or its communication probe fails, read the Chrome extension troubleshooting guidance once. If the connection still cannot be recovered, continue with the managed CDP fallback below.

Do not switch from a healthy extension path to CDP merely because CDP tools are visible. The CDP path exists as a fallback for extension unavailability and for tasks that explicitly require standalone CDP/MCP behavior.

## State model

The managed state directory is fixed to `~/.agents-profile/main/`.

- Profile directory: `~/.agents-profile/main/chrome-profile/`
- Port file: `~/.agents-profile/main/.cdp-port`
- Session file: `~/.agents-profile/main/session.json`
- Lock dir: `~/.agents-profile/main/.launch.lock`

Treat `session.json` and `.cdp-port` as rebuildable caches, not as the source of truth. The live endpoint on fixed port 9222 plus a Chrome main process whose arguments match both the managed profile and port are authoritative. If either cache is missing, corrupt, or stale, rediscover that live process and rewrite both files.

## Port contract

The CDP address is **fixed to `http://127.0.0.1:9222`**. Keep the responsibilities separate:

- MCP configuration routes `chrome-devtools` and Playwright to the fixed address. For Codex, configure `~/.codex/config.toml` with `chrome-devtools-mcp --browserUrl http://127.0.0.1:9222` and `@playwright/mcp --cdp-endpoint http://127.0.0.1:9222`.
- This skill provisions, rediscovers, and reuses the managed Chrome and profile behind that address.

Do not assume the MCP binding exists just because Chrome is reachable. Before using an MCP client in a new host or after its configuration changes, run `scripts/verify_mcp_cdp_config.py --client <codex|claude|cursor>`. If validation fails, stop and report the missing binding. Do not call the unbound MCP because its default behavior may launch a separate Chrome through `remote-debugging-pipe`.

The skill must guarantee that 9222 is either serving the managed Chrome or is free so it can bind to it. If an unrelated process holds 9222, fail instead of choosing another port; another port would break the configured MCP clients.

## Workflow

1. Probe the Chrome extension path as described above. If it is healthy, use it and stop this workflow.
2. For CDP fallback, identify the current MCP host. Run `scripts/verify_mcp_cdp_config.py --client <host>` before the first MCP browser-tool call in that host or after its configuration changes.
3. Run `scripts/ensure_chrome_cdp.sh` and parse its JSON output.
4. The script first probes cached state. If the caches are unusable, it probes fixed port 9222 and verifies the live Chrome main process against the managed profile and port arguments.
5. If `reused` is `true`, the existing managed Chrome was found and both cache files are normalized. Call the configured MCP tools directly.
6. If `reused` is `false`, a fresh managed Chrome was started on 9222. Call the configured MCP tools after the endpoint becomes ready.
7. If either fallback script exits non-zero, surface the error. Do not use an unbound MCP, `open -a`, a different port, or any path that bypasses the managed profile.

## Rules

- Always use the managed custom profile directory. Do not use the user's default daily-browsing Chrome profile.
- Port is fixed to 9222. Never pick an alternative port.
- Probe cached state first, then probe fixed port 9222 directly before deciding that no reusable endpoint exists.
- Require both a valid Chrome CDP response and a matching Chrome main process before rebuilding state or returning `reused: true`.
- If the stored state is stale but 9222 is free, start a fresh Chrome instance and rewrite the state files.
- Do not delete diagnostic state while the profile is still in use; classify the live process first and report the actual mismatch.
- Prevent duplicate launches with the lock dir.
- Return structured JSON so callers do not parse logs.
- Configure the stable HTTP endpoint at MCP process startup; never hardcode the rotating `webSocketDebuggerUrl` from `session.json`.
- Do not pass `port` / `ws_url` per tool call. If the MCP process started without the fixed endpoint, update its host configuration and restart that MCP process.

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
