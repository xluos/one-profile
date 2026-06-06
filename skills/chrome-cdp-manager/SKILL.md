---
name: chrome-cdp-manager
description: Reuse or start a Chrome instance with a persistent custom profile and an attachable CDP endpoint. Use this whenever browser automation needs existing Chrome login state, a persistent profile, or attachment to a managed Chrome session before using browser tools such as chrome-devtools or Playwright.
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

## State model

The managed state directory is fixed to `~/.agents-profile/main/`.

- Profile directory: `~/.agents-profile/main/chrome-profile/`
- Port file: `~/.agents-profile/main/.cdp-port`
- Session file: `~/.agents-profile/main/session.json`
- Lock dir: `~/.agents-profile/main/.launch.lock`

Treat `session.json` as the source of truth. `.cdp-port` is only a fast path for reconnect.

## Port contract

The CDP port is **fixed to 9222**. Downstream MCP servers (`chrome-devtools`, `playwright`) are configured in `~/.claude.json` to attach to `http://127.0.0.1:9222` at server startup, so the skill must guarantee that 9222 is either (a) already serving our managed Chrome, or (b) free so this skill can bind to it. If 9222 is held by an unrelated process, the script fails with a clear error instead of picking a different port — picking another port would silently break the MCPs.

## Workflow

1. Run `scripts/ensure_chrome_cdp.sh`.
2. Parse its JSON output.
3. If `reused` is `true`, the managed Chrome is already running on 9222 — downstream MCP tools (`chrome-devtools`, `playwright`) can be called directly; they will attach to the same instance.
4. If `reused` is `false`, a fresh Chrome was just started on 9222. MCP tool calls after this point attach to it automatically.
5. If the script exits non-zero because 9222 is occupied by a non-managed process, surface the error to the user — do not fall back to `open -a` or any path that bypasses CDP, that silently drops profile isolation.

## Rules

- Always use the managed custom profile directory. Do not use the user's default daily-browsing Chrome profile.
- Port is fixed to 9222. Never pick an alternative port.
- Probe the stored port before reusing it.
- If the stored state is stale but 9222 is free, start a fresh Chrome instance and rewrite the state files.
- Prevent duplicate launches with the lock dir.
- Return structured JSON so callers do not parse logs.
- Do not instruct the agent to pass `port` / `ws_url` into MCP tool calls per invocation — MCP servers bind to 9222 at their own startup time, not per tool call. The skill's only job is to make sure 9222 points to the right Chrome.

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
