---
name: chrome-cdp-manager
description: Route persistent Chrome work through a healthy Codex/ChatGPT extension or a managed CDP endpoint, choosing Chrome DevTools MCP for deep diagnosis and Playwright for repeatable flows. Use for existing tabs or login state, stale CDP recovery, remote server Chrome, or human-assisted login through a persistent profile.
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
- Operate a long-lived Chrome on a server and expose its GUI for login, MFA, or extension setup

Before using `chrome-devtools`, `Playwright`, or similar browser automation tools, use this skill first when the task requires persistent Chrome state, login reuse, or CDP attachment.

If the task only needs a fresh stateless browser session, do not trigger this skill.

## Choose the control surface by outcome

Keep access to the right browser state separate from the tool used to finish the task:

- **Codex/ChatGPT Chrome extension:** default for the user's current Chrome, tabs, cookies, SSO, installed extensions, and ordinary page interaction. If its full CDP mode exposes enough console, network, DOM, or performance data for the task, remain on this path.
- **Chrome DevTools MCP:** use when the requested result requires its dedicated debugging surface, such as request/response inspection, performance traces and insights, throttling, memory analysis, Lighthouse, or Chrome-extension debugging. Do not switch merely because the tool is installed.
- **Playwright:** use for repeatable multi-step flows, semantic assertions, route/API mocks, generated regression coverage, or cross-browser behavior. For Chrome login reuse, attach it to the managed endpoint; for fidelity-sensitive or non-Chrome coverage, let Playwright own an isolated browser instead of pretending CDP attachment is equivalent.

Do not let two controllers mutate the same tab concurrently. Finish or pause one controller, identify the target tab and expected state, then hand off. Observation in one tool does not prove that another tool is attached to the same browser.

## Control surface priority

On a local machine with the user's Chrome, prefer the Codex/ChatGPT Chrome extension control path when it is available:

1. Load and follow the Browser skill for Chrome extension control.
2. Establish an extension browser binding and perform a read-only `openTabs()` probe. A successful binding plus a successful tab probe means the extension path is healthy; an installed extension process alone is not sufficient evidence.
3. When healthy and it covers the requested capability, use the extension browser for the task. Do not run the CDP manager or call standalone browser MCP servers.
4. When the task requires a standalone capability listed above, continue with the managed CDP path without declaring the healthy extension broken.
5. When the extension is unavailable or its communication probe fails, read the Chrome extension troubleshooting guidance once. If the connection still cannot be recovered, continue with the managed CDP fallback below.

Do not switch from a healthy extension path to CDP merely because CDP tools are visible. The managed CDP path exists for extension unavailability and for tasks that require the standalone capabilities listed above.

On a server without a usable Codex/ChatGPT extension connection, skip repeated extension recovery and use a long-lived headed Chrome on a virtual display. Read [references/server-browser.md](references/server-browser.md) before detecting or initializing that environment, installing the Playwright MCP Bridge, changing Codex MCP configuration, or exposing Xpra.

## Server branch

Use `scripts/server_browser.py` as the single entrypoint on Linux servers:

1. Run `scripts/ensure_server_browser.py` first. It is read-only by default and returns a unified health result with stable issue codes, checks, and the exact repair command without revealing credentials.
2. If health fails and the user has authorized host repair, run `scripts/ensure_server_browser.py --repair --apply`. It reuses the idempotent initializer, repairs the managed browser environment, then runs the same health contract again. A healthy environment is a no-op: no apt/npm work, Chrome restart, or Bridge reinstall.
3. `server_browser.py detect` remains the detailed read-only inventory. `server_browser.py init --apply` is also idempotent and may be called directly; it installs the Chrome/Xpra system packages, installs `fonts-noto-cjk` only when needed, pins the Chrome LNA compatibility flags, provisions the Playwright Bridge and configures browser MCP bindings. Add `--show-credential` when the current task may need human UI access.
4. For an existing host, use `bridge --apply`, `configure-codex --apply`, and `bridge --verify` to repair and prove the Playwright Bridge path independently.
5. If automation reaches a login, MFA, CAPTCHA, consent, certificate prompt, ambiguous visual state, or repeated element-location failure, automatically run `server_browser.py ui --ensure --show-credential`. Return its `url` and `password` directly to the user; do not ask them to construct an SSH tunnel or choose a local-access mode.
6. The Xpra page shows the same persistent Chrome controlled through CDP/Bridge. After the user clears the blocker, re-probe the target page and continue the original task. Do not launch another browser or profile.

The server entrypoint must resize every visible managed Chrome top-level window to the full virtual-display geometry after Chrome starts or whenever Xpra is ensured. Include the verified display and window dimensions in the JSON result; do not rely on Chrome's previously persisted window placement.

Starting an external GUI changes the host, so do it only within an authorized server-browser workflow. The UI escalation itself should be automatic once that workflow is authorized; do not make the user debug Xpra commands.

## State model

The managed state directory defaults to `~/.agents-profile/main/`; `CHROME_CDP_STATE_DIR` may override it for a deliberate isolated deployment.

- Profile directory: `~/.agents-profile/main/chrome-profile/`
- Port file: `~/.agents-profile/main/.cdp-port`
- Session file: `~/.agents-profile/main/session.json`
- Lock dir: `~/.agents-profile/main/.launch.lock`

Treat `session.json` and `.cdp-port` as rebuildable caches, not as the source of truth. The live endpoint on fixed port 9222 plus a Chrome main process whose arguments match both the managed profile and port are authoritative. If either cache is missing, corrupt, or stale, rediscover that live process and rewrite both files.

## Port contract

The CDP address is **fixed to `http://127.0.0.1:9222`** and must remain loopback-only. Keep the responsibilities separate:

- MCP configuration routes `chrome-devtools` and Playwright to the fixed address. For Codex, configure `~/.codex/config.toml` with `chrome-devtools-mcp --browserUrl http://127.0.0.1:9222` and `@playwright/mcp --cdp-endpoint http://127.0.0.1:9222`.
- This skill provisions, rediscovers, and reuses the managed Chrome and profile behind that address.

Do not assume the MCP binding exists just because Chrome is reachable. Before using an MCP client in a new host or after its configuration changes, run `scripts/verify_mcp_cdp_config.py --client <codex|claude|cursor>`. If validation fails, stop and report the missing binding. Do not call the unbound MCP because its default behavior may launch a separate Chrome through `remote-debugging-pipe`.

The skill must guarantee that 9222 is either serving the managed Chrome or is free so it can bind to it. If an unrelated process holds 9222, fail instead of choosing another port; another port would break the configured MCP clients.

## Script path convention

All `scripts/...` paths in this document are relative to the root directory of this skill, namely the directory that contains this `SKILL.md`. They are not relative to the caller's current working directory or to the repository root. When invoking a script from another directory, resolve the installed skill root first and use its absolute path, for example:

```bash
SKILL_DIR="/path/to/chrome-cdp-manager"
"${SKILL_DIR}/scripts/verify_mcp_cdp_config.py" --client codex
"${SKILL_DIR}/scripts/ensure_chrome_cdp.sh"
```

The repository `README.md` may use `skills/chrome-cdp-manager/...` paths because those examples are relative to the repository root; that convention does not change the skill's runtime path contract.

## Workflow

1. Choose the control surface from the requested outcome. On a local machine, probe the Chrome extension path before selecting a standalone MCP. On a server known not to have the extension path, read the server reference and continue with managed CDP.
2. If the extension is healthy and covers the requested capability, use it and stop this workflow.
3. For a managed CDP controller, identify the current MCP host. Run `scripts/verify_mcp_cdp_config.py --client <host>` before the first MCP browser-tool call in that host or after its configuration changes.
4. Run `scripts/ensure_chrome_cdp.sh` and parse its JSON output.
5. The script first probes cached state. If the caches are unusable, it probes fixed port 9222 and verifies the live Chrome main process against the managed profile and port arguments.
6. If `reused` is `true`, the existing managed Chrome was found, its required LNA/extension launch arguments matched, and both cache files are normalized. Call the configured MCP tools directly.
7. If `reused` is `false`, a fresh managed Chrome was started on 9222. Call the configured MCP tools after the endpoint becomes ready.
8. If either fallback script exits non-zero, surface the error. Do not use an unbound MCP, `open -a`, a different port, or any path that bypasses the managed profile.

## Rules

- Always use the managed custom profile directory. Do not use the user's default daily-browsing Chrome profile.
- Port is fixed to 9222. Never pick an alternative port.
- Bind CDP to loopback only. Xpra may use HTTP/WS with password authentication only on an RFC1918/private server address when the environment cannot accept TLS certificates. Refuse that transport on a public address; never expose an unauthenticated GUI or publish CDP directly.
- Probe cached state first, then probe fixed port 9222 directly before deciding that no reusable endpoint exists.
- Require both a valid Chrome CDP response and a matching Chrome main process before rebuilding state or returning `reused: true`.
- Require the real main process to include `LocalNetworkAccessChecks,PrivateNetworkAccessForNavigations` in `--disable-features`; a responding stale Chrome without them must be controlled-restarted before reuse.
- If the stored state is stale but 9222 is free, start a fresh Chrome instance and rewrite the state files.
- Do not delete diagnostic state while the profile is still in use; classify the live process first and report the actual mismatch.
- Prevent duplicate launches with the lock dir.
- Return structured JSON so callers do not parse logs.
- Use `ensure_server_browser.py --repair --apply` for automatic recovery. Do not build a second repair path: repeated repair must converge through the same idempotent initializer.
- Configure the stable HTTP endpoint at MCP process startup; never hardcode the rotating `webSocketDebuggerUrl` from `session.json`.
- Do not pass `port` / `ws_url` per tool call. If the MCP process started without the fixed endpoint, update its host configuration and restart that MCP process.
- Do not claim Playwright-native fidelity when using `connectOverCDP`; choose an isolated Playwright browser if the requested test depends on features unavailable through CDP.

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
