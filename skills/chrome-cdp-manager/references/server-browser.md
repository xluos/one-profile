# Server Browser: Xpra-only UI escalation

Read this reference when Chrome must run persistently on a machine without a physical display, when a person needs to complete login or MFA remotely, or when extensions must be installed into that browser.

## Managed shape

Run normal headed Chrome on a virtual display rather than relying on true headless mode for human-assisted sessions:

```text
human browser -- HTTP/WS --> standard HTTP gateway :14500
                                      |
                                      v
                         Xpra + password 127.0.0.1:14501
                                      |
                                      v
                            headed Chrome on Xvfb
                                             |
                                  persistent user-data-dir
                                             |
                                  127.0.0.1:9222 CDP
                                      /              \
                         Chrome DevTools MCP    Playwright Bridge
```

The supported server UI is Xpra's HTML5 client. Do not present local-only, SSH-tunnel, VNC, or noVNC modes as user choices. The user receives one directly accessible HTTP URL and a password.
After Xpra is confirmed listening, the helper stops legacy `x11vnc`/`websockify` processes that match the managed display and old 5900/6080 path.

Chrome, its GUI bridge, and its persistent profile must outlive individual agent calls. Let the service supervisor own their lifecycle; MCP clients attach to Chrome instead of launching replacements.

## Provisioning invariants

- Launch Chrome with a dedicated `--user-data-dir`; never reuse a person's default daily profile or copy a whole profile between machines.
- Ensure the server branch has an official system Google Chrome and pass it as `CHROME_BIN`. A user-local `google-chrome` may be a wrapper that forcibly appends headless flags, and Chrome enterprise policy for the Playwright Bridge must target a supported branded browser.
- Inherit a valid `DISPLAY` from Xpra/Xvfb and do not pass `--headless` when a person must see the same browser for QR login, MFA, consent, or extension setup.
- A healthy CDP response from an existing managed `--headless` Chrome is not sufficient for the server GUI branch. Detect headless and headless-Ozone process arguments, preserve its profile, and perform a controlled restart as headed Chrome on the managed Xvfb before checking window geometry or installing the Bridge.
- After Chrome starts and whenever Xpra is ensured, move every visible managed Chrome top-level window to `(0, 0)` and resize it to `100% × 100%` of the virtual display. Verify and return the resulting window geometry so stale profile placement cannot leave a narrow UI.
- Locate the visible top-level window by the managed Chrome main PID first, with Google Chrome and Chromium class names only as fallbacks; Chrome for Testing and branded Chrome do not use the same X11 class.
- Keep CDP on `127.0.0.1:9222` with no external listener.
- Bind Xpra HTTP/WS externally with password authentication on the default port `14500`. This unencrypted transport is allowed only when the detected address is private/RFC1918; refuse to start it on a public address. The server network must remain trusted because page pixels, keystrokes, and session traffic are not TLS-encrypted.
- Keep Xpra's mixed-protocol listener on loopback `14501`. A small Node HTTP/1.1/WebSocket gateway owns external `14500`, normalizes proxy-style request targets, and forwards only to that loopback backend. This avoids Xpra 3.1 misclassifying some browser HTTP requests as native protocol packets.
- Install Xpra from the signed official stable repository, not Debian Bookworm's EOL 3.1.3 package. Pin and verify the official signing-key fingerprint before adding the repository. On veLinux, map to Bookworm only when `ID=velinux`, `VERSION_ID=2`, and either `/etc/debian_version` confirms Debian 12 or both the installed `base-files` major version and an enabled apt suite confirm Bookworm compatibility; do not rewrite `/etc/os-release` to bypass distribution checks.
- Keep the small official Bookworm source definition deterministic inside the helper instead of making initialization depend on GitHub raw-content availability. Continue downloading the signing key from `xpra.org` and reject it unless its full fingerprint matches the pinned official key.
- For Xpra 6.x, declare file authentication on the bound socket (`--bind-tcp=...,auth=file(filename=...)`). The deprecated global `--tcp-auth=file --password-file=...` form starts but leaves the file authenticator without its filename on current 6.x releases.
- Report Chinese-font coverage during read-only detection. During initialization, query fontconfig for a font advertising `lang=zh`; if none exists, install `fonts-noto-cjk`, refresh the font cache, and fail unless a Chinese-capable match is then visible. Do not install the large CJK package when the host already has a suitable fallback font.
- Some managed veLinux images may have an unrelated package stuck in a half-configured state, causing apt to return non-zero after installing the requested browser packages. Preserve that external package state: continue only after `dpkg-query` proves every package requested by this workflow is installed, and return the apt failure as an initialization warning. If any requested package is missing, fail with the apt diagnostics.
- Treat the Xpra URL and password as credentials. Reveal the password only when human access is needed; `detect` must not print it.
- Persist and protect the profile as credentials. Cookies, local storage, IndexedDB, client certificates, and extension state may all be sensitive. Use restrictive filesystem permissions and do not commit, archive, or casually back up the profile.
- Verify the live Chrome main-process arguments and `/json/version`; a responding port or a stale session file alone does not establish ownership.
- When rediscovering Chrome, exclude child processes carrying `--type=...`; renderers may repeat the profile and debugging-port arguments and must never be written as the managed main PID.
- Verify the Node.js engine requirement of the installed MCP versions. If a compatible Node is installed under a user-local prefix, pass that `PATH` explicitly in the MCP host configuration; an interactive shell probe can succeed while the host later launches the same MCP with an older system Node.

Use `scripts/server_browser.py` for the complete lifecycle:

```bash
scripts/server_browser.py detect
scripts/server_browser.py init --apply --show-credential
scripts/server_browser.py ui --ensure --show-credential
scripts/server_browser.py bridge --apply
scripts/server_browser.py configure-codex --apply
scripts/server_browser.py bridge --verify
```

The package bootstrap includes `x11-utils` because the display readiness probe uses `xdpyinfo`; installing Xvfb and xdotool alone does not provide that command.

`detect` is read-only. The other mutating operations require an explicit flag. Every command emits JSON; callers should consume `url`, `password`, and verification fields instead of scraping logs.

## Human login and recovery

Do not wait for the user to request a remote desktop. Automatically call `ui --ensure --show-credential` when any of these blocks the current browser task:

- login, SSO, QR code, MFA, CAPTCHA, consent, or client-certificate UI;
- the expected element cannot be found after the page and controller attachment were re-probed;
- DOM/ARIA state is insufficient to disambiguate what the user sees;
- the user explicitly asks to inspect or take over the server browser.

Then:

1. Return the JSON `url`, `username`, and `password` as a directly clickable handoff. Do not rewrite the HTTP URL to HTTPS.
2. Let the user operate the same headed Chrome; do not start a second browser or profile.
3. Complete SSO, QR login, MFA, consent, or certificate prompts.
4. The user may close the Xpra tab after clearing the blocker; this must not terminate Chrome.
5. Re-probe the CDP endpoint and controller attachment before continuing automation.

Do not export cookies as the default login-transfer mechanism. A persistent profile preserves more of the actual authentication state and avoids spreading reusable credentials.

## Playwright MCP Bridge and token

The server branch carries a checksum-pinned official Bridge CRX for extension `mmlmfjhmonkocbjadbfplnigmagldckm`. It verifies the asset and manifest, safely extracts it under the managed state directory, loads that stable absolute directory with `--load-extension`, restarts only the managed Chrome, and verifies that the extension appears in the live browser. This makes initialization independent of Google Web Store reachability while preserving the extension ID from the signed manifest key. It then:

1. opens the Bridge Status page so the official extension generates its 32-byte URL-safe token;
2. captures that value inside the virtual display and stores it in `~/.agents-profile/main/playwright-mcp-extension-token` with mode `0600`;
3. configures Codex Playwright MCP with `--extension` and `PLAYWRIGHT_MCP_EXTENSION_TOKEN`;
4. starts the configured MCP with the host environment and calls `browser_tabs` before reporting success.

For the currently validated MCP build, extension mode discovers Chrome from its channel default and does not honor the ordinary `--user-data-dir` option. Set `PWTEST_EXTENSION_USER_DATA_DIR` to the managed profile in the MCP environment so its relay opens `connect.html` in the already-running server Chrome. Treat this as a version-sensitive compatibility setting and retain the live `browser_tabs` probe after upgrades.

Do not print the token. The Xpra password is a separate secret and is printed only by `--show-credential`.

## Other extensions

Choose the installation method from the extension source:

- **Chrome Web Store:** use the remote Xpra UI for ordinary one-off installation. The dedicated profile preserves it across restarts.
- **Unpacked extension under development:** build it to a stable absolute directory and load that directory through Chrome's supported unpacked-extension flow. For reproducible service bootstrap, include `--load-extension=/absolute/path` in the supervisor-owned Chrome launch arguments. Reload after every rebuilt artifact before claiming runtime verification.
- **Fleet-managed Web Store extension:** use Chrome enterprise policy only with authorization. The official Playwright Bridge is handled separately by the checksum-pinned bundled asset when `bridge --apply` or full initialization was explicitly requested.
- **Chrome DevTools MCP extension tools:** use them only if the currently installed MCP exposes the needed tool and supports it for the active connection mode. Do not assume an extension operation available for a pipe-launched browser also works through `--browserUrl` attachment; inspect the current official capability or perform a harmless list/probe first.

Do not download and silently install arbitrary CRX files. Verify the source, requested permissions, build output, and target profile before installation. Installing, force-installing, or removing an extension changes browser state and requires the user's authorization.

## Controller routing on the server

- Use Chrome DevTools MCP to explain failures: network details, console errors, JavaScript state, performance, memory, and extension internals.
- Use Playwright Bridge to execute and assert workflows in the persistent Chrome. Its token and extension-origin token must match.
- Use a Playwright-owned isolated browser for cross-browser tests or cases that require full Playwright protocol fidelity; that browser is separate and does not inherit the server Chrome profile.

Never infer that both MCPs share the persistent session merely because both are configured. Verify each MCP startup argument, restart changed MCP processes, and identify the same page/profile before handoff.
Endpoint validation proves routing arguments, not executable health. Launch each configured MCP with the environment the actual host will inherit and complete at least one harmless protocol call before declaring it usable.
