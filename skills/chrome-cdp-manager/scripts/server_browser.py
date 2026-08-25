#!/usr/bin/env python3

import argparse
import getpass
import ipaddress
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Any

from mcp_stdio_client import call_mcp


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
STATE_DIR = pathlib.Path(os.environ.get("CHROME_CDP_STATE_DIR", "~/.agents-profile/main")).expanduser()
PROFILE_DIR = pathlib.Path(os.environ.get("CHROME_CDP_PROFILE_DIR", str(STATE_DIR / "chrome-profile"))).expanduser()
DISPLAY = os.environ.get("CHROME_CDP_DISPLAY", ":99")
XPRA_PORT = int(os.environ.get("CHROME_CDP_XPRA_PORT", "14500"))
XPRA_BACKEND_PORT = int(os.environ.get("CHROME_CDP_XPRA_BACKEND_PORT", str(XPRA_PORT + 1)))
LOCAL_BIN = pathlib.Path("~/.local/bin").expanduser()
BRIDGE_ID = "mmlmfjhmonkocbjadbfplnigmagldckm"
BRIDGE_UPDATE_URL = "https://clients2.google.com/service/update2/crx"
XPRA_KEY_URL = "https://xpra.org/xpra.asc"
XPRA_KEY_FINGERPRINT = "B4993B57323148E37977E5D873254CAD17978FAF"
XPRA_BOOKWORM_SOURCE = """Types: deb
URIs: https://xpra.org
Suites: bookworm
Components: main
Signed-By: /usr/share/keyrings/xpra.asc
Architectures: amd64 arm64
"""


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def run(command: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True, env=env)


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    path_parts = [str(LOCAL_BIN), "/usr/local/bin", "/usr/bin", "/bin"]
    env["PATH"] = ":".join(dict.fromkeys(path_parts + env.get("PATH", "").split(":")))
    env["DISPLAY"] = DISPLAY
    return env


def executable(name: str) -> str | None:
    return shutil.which(name, path=command_env()["PATH"])


def version(name: str) -> str | None:
    path = executable(name)
    if not path:
        return None
    result = run([path, "--version"], check=False, env=command_env())
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if text else None


def port_open(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def external_ipv4() -> str:
    result = run(["hostname", "-I"], check=False)
    for value in result.stdout.split():
        if ":" not in value and not value.startswith("127."):
            return value
    return socket.gethostbyname(socket.gethostname())


def private_external_ipv4() -> str:
    address = external_ipv4()
    if not ipaddress.ip_address(address).is_private:
        raise RuntimeError(f"refusing unauthenticated transport on non-private address: {address}")
    return address


def file_mode(path: pathlib.Path) -> str | None:
    return oct(path.stat().st_mode & 0o777) if path.exists() else None


def chinese_font_state() -> dict[str, Any]:
    fc_list = executable("fc-list")
    if not fc_list:
        return {"available": False, "match": None, "reason": "fontconfig is not installed"}
    result = run([fc_list, ":lang=zh", "file", "family"], check=False, env=command_env())
    matches = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {
        "available": bool(matches),
        "match": matches[0] if matches else None,
        "reason": None if matches else "fontconfig found no font advertising Chinese glyph coverage",
    }


def detect() -> dict[str, Any]:
    verify = run(
        [str(SCRIPT_DIR / "verify_mcp_cdp_config.py"), "--client", "codex"],
        check=False,
        env=command_env(),
    )
    try:
        mcp_config = json.loads(verify.stdout)
    except json.JSONDecodeError:
        mcp_config = {"ok": False, "error": verify.stderr.strip() or "invalid verifier output"}
    return {
        "platform": sys.platform,
        "hostname": socket.gethostname(),
        "external_ip": external_ipv4(),
        "display": DISPLAY,
        "programs": {
            name: {"path": executable(name), "version": version(name)}
            for name in ("google-chrome", "xpra", "node", "codex", "chrome-devtools-mcp", "playwright-mcp")
        },
        "ports": {
            "cdp_9222": port_open("127.0.0.1", 9222),
            "xpra_external": port_open("127.0.0.1", XPRA_PORT),
        },
        "xpra_url": f"http://{external_ipv4()}:{XPRA_PORT}/",
        "xpra_transport": "http+ws+password",
        "xpra_username": getpass.getuser(),
        "xpra_backend": f"127.0.0.1:{XPRA_BACKEND_PORT}",
        "xpra_password_file": str(STATE_DIR / "xpra-password"),
        "xpra_password_mode": file_mode(STATE_DIR / "xpra-password"),
        "chinese_font": chinese_font_state(),
        "bridge": {
            "extension_id": BRIDGE_ID,
            "policy_installed": pathlib.Path("/etc/opt/chrome/policies/managed/playwright-mcp-bridge.json").exists(),
            "token_file": str(STATE_DIR / "playwright-mcp-extension-token"),
            "token_present": (STATE_DIR / "playwright-mcp-extension-token").exists(),
            "token_mode": file_mode(STATE_DIR / "playwright-mcp-extension-token"),
        },
        "codex_mcp": mcp_config,
    }


def require_apply(args: argparse.Namespace) -> None:
    if not args.apply:
        raise RuntimeError("this operation changes the host; rerun with --apply after authorization")


def ensure_permissions() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    PROFILE_DIR.chmod(0o700)


def os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in pathlib.Path("/etc/os-release").read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value.strip().strip('"')
    return values


def debian_base_major() -> int | None:
    result = run(["dpkg-query", "-W", "-f=${Version}", "base-files"], check=False)
    match = re.match(r"(\d+)", result.stdout.strip())
    return int(match.group(1)) if match else None


def apt_suite_present(suite: str) -> bool:
    source_files = [pathlib.Path("/etc/apt/sources.list")]
    source_files.extend(pathlib.Path("/etc/apt/sources.list.d").glob("*"))
    deb_line = re.compile(rf"^\s*deb(?:\s+\[[^]]+\])?\s+\S+\s+{re.escape(suite)}(?:\s|$)")
    deb822_suite = re.compile(rf"^\s*Suites:\s+.*\b{re.escape(suite)}\b", re.MULTILINE)
    for path in source_files:
        try:
            content = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if any(deb_line.search(line) for line in content.splitlines()) or deb822_suite.search(content):
            return True
    return False


def debian_bookworm_compatible() -> bool:
    debian_version_path = pathlib.Path("/etc/debian_version")
    if debian_version_path.exists() and debian_version_path.read_text().strip().startswith("12"):
        return True
    return debian_base_major() == 12 and apt_suite_present("bookworm")


def package_installed(name: str) -> bool:
    result = run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", name], check=False)
    return result.returncode == 0 and result.stdout.startswith("ii")


def apt_install(
    packages: list[str], *, verify_packages: list[str] | None = None, no_recommends: bool = False
) -> str | None:
    command = ["sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"]
    if no_recommends:
        command.append("--no-install-recommends")
    command.extend(packages)
    result = run(command, check=False)
    if result.returncode == 0:
        return None
    expected = verify_packages or packages
    missing = [name for name in expected if not package_installed(name)]
    if missing:
        detail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-12:])
        raise RuntimeError(f"apt failed and required packages are missing ({', '.join(missing)}):\n{detail}")
    detail_lines = (result.stdout + result.stderr).strip().splitlines()
    detail = " | ".join(detail_lines[-4:]) if detail_lines else f"exit status {result.returncode}"
    return f"apt returned {result.returncode}, but all requested packages are installed; unrelated dpkg issue preserved: {detail}"


def xpra_repo_codename() -> str:
    release = os_release()
    distro_id = release.get("ID")
    codename = release.get("VERSION_CODENAME")
    if distro_id == "debian" and codename == "bookworm":
        return "bookworm"
    if distro_id == "velinux" and release.get("VERSION_ID") == "2" and debian_bookworm_compatible():
        return "bookworm"
    raise RuntimeError(
        "automatic Xpra stable-repository setup supports Debian 12/Bookworm "
        "and verified veLinux 2 hosts backed by Debian 12 only"
    )


def ensure_xpra_stable_repo() -> list[str]:
    warnings: list[str] = []
    codename = xpra_repo_codename()
    if codename != "bookworm":
        raise RuntimeError(f"unsupported Xpra repository codename: {codename}")
    warning = apt_install(["ca-certificates", "curl", "gnupg"])
    if warning:
        warnings.append(warning)
    with tempfile.TemporaryDirectory(prefix="xpra-repo-") as directory:
        key = pathlib.Path(directory) / "xpra.asc"
        sources = pathlib.Path(directory) / "xpra.sources"
        urllib.request.urlretrieve(XPRA_KEY_URL, key)
        fingerprint_result = run([
            "gpg", "--show-keys", "--with-colons", "--fingerprint", str(key),
        ])
        fingerprints = [
            fields[9]
            for line in fingerprint_result.stdout.splitlines()
            if line.startswith("fpr:") and len(fields := line.split(":")) > 9
        ]
        if XPRA_KEY_FINGERPRINT not in fingerprints:
            raise RuntimeError("the downloaded Xpra repository key fingerprint does not match the pinned official key")
        sources.write_text(XPRA_BOOKWORM_SOURCE)
        source_text = sources.read_text()
        required_source_lines = (
            "URIs: https://xpra.org",
            "Suites: bookworm",
            "Signed-By: /usr/share/keyrings/xpra.asc",
        )
        if not all(line in source_text for line in required_source_lines):
            raise RuntimeError("the downloaded Xpra Bookworm source definition is not the expected official repository")
        run(["sudo", "install", "-m", "0644", str(key), "/usr/share/keyrings/xpra.asc"])
        run(["sudo", "install", "-m", "0644", str(sources), "/etc/apt/sources.list.d/xpra.sources"])
    return warnings


def ensure_chinese_font() -> dict[str, Any]:
    before = chinese_font_state()
    if before["available"]:
        return {"installed": False, **before}
    warning = apt_install(["fonts-noto-cjk"], no_recommends=True)
    run(["fc-cache", "-f"], env=command_env())
    after = chinese_font_state()
    if not after["available"]:
        raise RuntimeError("fonts-noto-cjk was installed, but fontconfig still reports no Chinese font")
    result = {"installed": True, **after}
    if warning:
        result["warning"] = warning
    return result


def ensure_system_packages() -> dict[str, Any]:
    if sys.platform != "linux" or not executable("apt-get"):
        raise RuntimeError("automatic initialization currently supports Debian-family Linux only")
    warnings = ensure_xpra_stable_repo()
    run(["sudo", "apt-get", "update"])
    warning = apt_install([
        "xpra-server", "xpra-x11", "xpra-html5", "xvfb", "openbox", "xdotool", "xclip",
        "curl", "ca-certificates", "openssl", "fontconfig",
    ], no_recommends=True)
    if warning:
        warnings.append(warning)
    chinese_font = ensure_chinese_font()
    if executable("google-chrome"):
        return {"chinese_font": chinese_font, "warnings": warnings}
    with tempfile.TemporaryDirectory(prefix="chrome-install-") as directory:
        package = pathlib.Path(directory) / "google-chrome-stable_current_amd64.deb"
        urllib.request.urlretrieve(
            "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb",
            package,
        )
        warning = apt_install([str(package)], verify_packages=["google-chrome-stable"])
        if warning:
            warnings.append(warning)
    return {"chinese_font": chinese_font, "warnings": warnings}


def ensure_user_tools() -> None:
    LOCAL_BIN.parent.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required to install the user-local Node runtime")
    run([npm, "install", "-g", "--prefix", str(LOCAL_BIN.parent), "n"])
    env = command_env()
    env["N_PREFIX"] = str(LOCAL_BIN.parent)
    run([str(LOCAL_BIN / "n"), "lts"], env=env)
    run([
        str(LOCAL_BIN / "npm"), "install", "-g", "--prefix", str(LOCAL_BIN.parent),
        "@openai/codex@latest", "chrome-devtools-mcp@latest", "@playwright/mcp@latest",
    ], env=command_env())


def ensure_x_display() -> None:
    env = command_env()
    if run(["xdpyinfo"], check=False, env=env).returncode == 0:
        return
    log_dir = STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "xvfb.log").open("ab") as log:
        subprocess.Popen(
            ["Xvfb", DISPLAY, "-screen", "0", "1600x1000x24", "-nolisten", "tcp"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=env,
        )
    for _ in range(100):
        if run(["xdpyinfo"], check=False, env=env).returncode == 0:
            return
        time.sleep(0.1)
    raise RuntimeError(f"X display {DISPLAY} did not become ready")


def window_geometry(window_id: str) -> dict[str, int]:
    result = run(["xdotool", "getwindowgeometry", "--shell", window_id], env=command_env())
    values: dict[str, int] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"X", "Y", "WIDTH", "HEIGHT", "SCREEN"}:
            values[key.lower()] = int(value)
    return values


def maximize_chrome_windows() -> dict[str, Any]:
    if not executable("xdotool"):
        raise RuntimeError("xdotool is required to maximize server Chrome")
    env = command_env()
    display_size = run(["xdotool", "getdisplaygeometry"], env=env).stdout.split()
    if len(display_size) != 2:
        raise RuntimeError("could not determine X display geometry")
    display_width, display_height = (int(value) for value in display_size)
    window_ids: list[str] = []
    for _ in range(50):
        found = run(["xdotool", "search", "--onlyvisible", "--class", "google-chrome"], check=False, env=env)
        window_ids = list(dict.fromkeys(found.stdout.split()))
        if window_ids:
            break
        time.sleep(0.1)
    if not window_ids:
        raise RuntimeError("managed Chrome is ready, but no visible Chrome window was found")
    windows = []
    for window_id in window_ids:
        run(["xdotool", "windowmove", "--sync", window_id, "0", "0"], env=env)
        run(["xdotool", "windowsize", "--sync", window_id, "100%", "100%"], env=env)
        geometry = window_geometry(window_id)
        if geometry.get("width") != display_width or geometry.get("height") != display_height:
            raise RuntimeError(f"Chrome window {window_id} did not fill the virtual display")
        windows.append({"window_id": int(window_id), **geometry})
    return {
        "display": {"width": display_width, "height": display_height},
        "windows": windows,
    }


def ensure_chrome() -> dict[str, Any]:
    ensure_x_display()
    result = run([str(SCRIPT_DIR / "ensure_chrome_cdp.sh")], env=command_env())
    payload = json.loads(result.stdout)
    payload["window_layout"] = maximize_chrome_windows()
    return payload


def stop_managed_chrome() -> None:
    session_file = STATE_DIR / "session.json"
    if not session_file.exists():
        return
    try:
        pid = int(json.loads(session_file.read_text()).get("pid") or 0)
    except (ValueError, json.JSONDecodeError):
        return
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise RuntimeError(f"managed Chrome pid {pid} did not stop cleanly")


def devtools_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    command = [
        str(LOCAL_BIN / "chrome-devtools-mcp"),
        "--browserUrl", "http://127.0.0.1:9222",
        "--categoryExtensions=true",
        "--usageStatistics=false",
    ]
    return call_mcp(command, calls, env=command_env())


def response_text(result: dict[str, Any], index: int = -1) -> str:
    response = result["responses"][index]["response"]
    blocks = response.get("result", {}).get("content", [])
    return "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text")


def write_secret(path: pathlib.Path, value: str, *, trailing_newline: bool = True) -> None:
    path.write_text(value + ("\n" if trailing_newline else ""))
    path.chmod(0o600)


def read_bridge_token() -> str:
    path = STATE_DIR / "playwright-mcp-extension-token"
    if not path.exists() or not path.read_text().strip():
        raise RuntimeError("Playwright MCP Bridge token is missing; run bridge --apply first")
    return path.read_text().strip()


def capture_bridge_token() -> str:
    chrome = executable("google-chrome")
    if not chrome or not executable("xdotool") or not executable("xclip"):
        raise RuntimeError("google-chrome, xdotool, and xclip are required to capture the Bridge token")
    run([
        chrome,
        f"--user-data-dir={PROFILE_DIR}",
        f"chrome-extension://{BRIDGE_ID}/status.html",
    ], check=False, env=command_env())
    env = command_env()
    window_id = ""
    for _ in range(50):
        active = run(["xdotool", "getactivewindow"], check=False, env=env)
        if active.returncode == 0:
            candidate = active.stdout.strip()
            title = run(["xdotool", "getwindowname", candidate], check=False, env=env)
            if "Playwright Extension Status" in title.stdout:
                window_id = candidate
                break
        time.sleep(0.1)
    if not window_id:
        raise RuntimeError("Playwright Extension status page did not become active")
    run([
        "xdotool", "windowactivate", "--sync", window_id,
        "key", "--clearmodifiers", "ctrl+a",
        "key", "--clearmodifiers", "ctrl+c",
    ], env=env)
    time.sleep(0.2)
    clipboard = run(["xclip", "-selection", "clipboard", "-o"], env=env).stdout
    match = re.search(r"PLAYWRIGHT_MCP_EXTENSION_TOKEN=([A-Za-z0-9_-]{32,})", clipboard)
    run(["xdotool", "key", "--clearmodifiers", "ctrl+w"], check=False, env=env)
    if not match:
        raise RuntimeError("Playwright Extension did not expose an authentication token")
    token = match.group(1)
    write_secret(STATE_DIR / "playwright-mcp-extension-token", token)
    return token


def bridge_profile_state() -> dict[str, Any] | None:
    preferences = PROFILE_DIR / "Default" / "Preferences"
    if not preferences.exists():
        return None
    try:
        payload = json.loads(preferences.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    settings = payload.get("extensions", {}).get("settings", {}).get(BRIDGE_ID)
    if not isinstance(settings, dict):
        return None
    manifest = settings.get("manifest", {})
    relative_path = settings.get("path")
    extension_path = PROFILE_DIR / "Default" / "Extensions" / str(relative_path or "")
    if (
        manifest.get("name") != "Playwright Extension"
        or settings.get("disable_reasons")
        or not relative_path
        or not extension_path.exists()
    ):
        return None
    return {
        "version": manifest.get("version"),
        "path": str(extension_path),
        "service_worker_started": bool(settings.get("has_started_service_worker")),
    }


def install_bridge() -> dict[str, Any]:
    ensure_permissions()
    policy = {
        "ExtensionSettings": {
            BRIDGE_ID: {
                "installation_mode": "force_installed",
                "update_url": BRIDGE_UPDATE_URL,
            }
        }
    }
    policy_source = STATE_DIR / "playwright-mcp-bridge-policy.json"
    policy_source.write_text(json.dumps(policy, indent=2) + "\n")
    run(["sudo", "install", "-D", "-m", "0644", str(policy_source), "/etc/opt/chrome/policies/managed/playwright-mcp-bridge.json"])
    stop_managed_chrome()
    chrome = ensure_chrome()
    extension_state = None
    for _ in range(60):
        extension_state = bridge_profile_state()
        if extension_state:
            break
        time.sleep(1)
    if not extension_state:
        raise RuntimeError("Playwright MCP Bridge policy is present, but Chrome did not install the extension")
    capture_bridge_token()
    return {
        "installed": True,
        "extension_id": BRIDGE_ID,
        "extension": extension_state,
        "token_file": str(STATE_DIR / "playwright-mcp-extension-token"),
        "chrome": chrome,
    }


def configure_codex() -> dict[str, Any]:
    codex = str(LOCAL_BIN / "codex")
    token = read_bridge_token()
    mcp_path = command_env()["PATH"]
    for name in ("chrome-devtools", "playwright"):
        run([codex, "mcp", "remove", name], check=False, env=command_env())
    run([
        codex, "mcp", "add", "chrome-devtools",
        "--env", f"PATH={mcp_path}", "--",
        str(LOCAL_BIN / "chrome-devtools-mcp"),
        "--browserUrl", "http://127.0.0.1:9222",
        "--categoryExtensions=true", "--usageStatistics=false",
    ], env=command_env())
    run([
        codex, "mcp", "add", "playwright",
        "--env", f"PATH={mcp_path}",
        "--env", f"DISPLAY={DISPLAY}",
        "--env", f"PLAYWRIGHT_MCP_EXTENSION_TOKEN={token}",
        "--env", f"PWTEST_EXTENSION_USER_DATA_DIR={PROFILE_DIR}", "--",
        str(LOCAL_BIN / "playwright-mcp"),
        "--extension", "--browser", "chrome",
    ], env=command_env())
    config = pathlib.Path("~/.codex/config.toml").expanduser()
    if config.exists():
        config.chmod(0o600)
    verified = run([str(SCRIPT_DIR / "verify_mcp_cdp_config.py"), "--client", "codex"], check=False, env=command_env())
    verified_payload = json.loads(verified.stdout)
    if not verified_payload.get("ok"):
        raise RuntimeError(f"Codex MCP configuration verification failed: {verified_payload.get('error')}")
    return {
        "config_file": str(config),
        "chrome_devtools_bound": "--browserUrl" in config.read_text(),
        "playwright_bridge": "--extension" in config.read_text(),
        "token_configured": "PLAYWRIGHT_MCP_EXTENSION_TOKEN" in config.read_text(),
        "verification": verified_payload,
    }


def ensure_xpra_password() -> pathlib.Path:
    password = STATE_DIR / "xpra-password"
    if not password.exists():
        write_secret(password, secrets.token_urlsafe(18), trailing_newline=False)
    else:
        write_secret(password, password.read_text().strip(), trailing_newline=False)
    return password


def managed_xpra_process() -> tuple[int, list[str]] | None:
    pid_file = STATE_DIR / "xpra.pid"
    try:
        pid = int(pid_file.read_text().strip())
        command = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, OSError, ValueError):
        return None
    arguments = [value.decode(errors="replace") for value in command if value]
    command_text = " ".join(arguments)
    if "xpra" not in command_text or " shadow " not in f" {command_text} " or DISPLAY not in command_text:
        return None
    return pid, arguments


def managed_xpra_is_http() -> bool:
    process = managed_xpra_process()
    if not process:
        return False
    _, arguments = process
    modern_binding = (
        f"--bind-tcp=127.0.0.1:{XPRA_BACKEND_PORT},"
        f"auth=file(filename={STATE_DIR / 'xpra-password'})"
    )
    return modern_binding in " ".join(arguments)


def stop_managed_xpra() -> None:
    process = managed_xpra_process()
    if not process:
        return
    pid, _ = process
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise RuntimeError(f"managed Xpra pid {pid} did not stop cleanly")


def managed_gateway_process() -> tuple[int, list[str]] | None:
    pid_file = STATE_DIR / "xpra-http-gateway.pid"
    try:
        pid = int(pid_file.read_text().strip())
        command = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, OSError, ValueError):
        return None
    arguments = [value.decode(errors="replace") for value in command if value]
    expected_script = str(SCRIPT_DIR / "xpra_http_gateway.mjs")
    if expected_script not in arguments:
        return None
    return pid, arguments


def managed_gateway_is_ready() -> bool:
    process = managed_gateway_process()
    if not process or not port_open("127.0.0.1", XPRA_PORT):
        return False
    _, arguments = process
    return (
        "--listen-port" in arguments
        and str(XPRA_PORT) in arguments
        and "--backend-port" in arguments
        and str(XPRA_BACKEND_PORT) in arguments
    )


def stop_managed_gateway() -> None:
    process = managed_gateway_process()
    if not process:
        return
    pid, _ = process
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise RuntimeError(f"Xpra HTTP gateway pid {pid} did not stop cleanly")


def ensure_http_gateway() -> dict[str, Any]:
    if managed_gateway_is_ready():
        pid, _ = managed_gateway_process() or (0, [])
        return {"pid": pid, "reused": True}
    stop_managed_gateway()
    if port_open("127.0.0.1", XPRA_PORT):
        raise RuntimeError(f"port {XPRA_PORT} is occupied by an unmanaged process")
    log_dir = STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "xpra-http-gateway.log").open("ab")
    process = subprocess.Popen([
        str(LOCAL_BIN / "node"),
        str(SCRIPT_DIR / "xpra_http_gateway.mjs"),
        "--listen-host", "0.0.0.0",
        "--listen-port", str(XPRA_PORT),
        "--backend-host", "127.0.0.1",
        "--backend-port", str(XPRA_BACKEND_PORT),
        "--pid-file", str(STATE_DIR / "xpra-http-gateway.pid"),
    ], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, env=command_env())
    log.close()
    for _ in range(100):
        if port_open("127.0.0.1", XPRA_PORT):
            return {"pid": process.pid, "reused": False}
        if process.poll() is not None:
            raise RuntimeError("Xpra HTTP gateway exited before becoming ready")
        time.sleep(0.1)
    raise RuntimeError("Xpra HTTP gateway did not become ready")


def stop_legacy_gui() -> list[dict[str, Any]]:
    stopped = []
    processes = run(["ps", "-u", str(os.getuid()), "-o", "pid=", "-o", "args="], check=False)
    for line in processes.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid_text, command = fields
        is_managed_x11vnc = "x11vnc" in command and f"-display {DISPLAY}" in command
        is_managed_websockify = (
            "websockify" in command
            and "6080" in command
            and ("localhost:5900" in command or "127.0.0.1:5900" in command)
        )
        if not (is_managed_x11vnc or is_managed_websockify):
            continue
        pid = int(pid_text)
        os.kill(pid, signal.SIGTERM)
        stopped.append({"pid": pid, "program": "x11vnc" if is_managed_x11vnc else "websockify"})
    return stopped


def ensure_xpra(show_credential: bool) -> dict[str, Any]:
    ensure_permissions()
    chrome = ensure_chrome()
    address = private_external_ipv4()
    password = ensure_xpra_password()
    if managed_xpra_process() and not managed_xpra_is_http():
        stop_managed_xpra()
    if not managed_xpra_is_http():
        if port_open("127.0.0.1", XPRA_BACKEND_PORT):
            raise RuntimeError(f"Xpra backend port {XPRA_BACKEND_PORT} is occupied by an unmanaged process")
        log_dir = STATE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "xpra", "shadow", DISPLAY,
            "--daemon=yes",
            (
                f"--bind-tcp=127.0.0.1:{XPRA_BACKEND_PORT},"
                f"auth=file(filename={password})"
            ),
            "--html=on",
            "--mdns=no", "--notifications=no", "--pulseaudio=no",
            f"--pidfile={STATE_DIR / 'xpra.pid'}",
            f"--log-file={log_dir / 'xpra.log'}",
        ]
        run(command, env=command_env())
        for _ in range(100):
            if port_open("127.0.0.1", XPRA_BACKEND_PORT):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Xpra loopback backend did not become ready")
    gateway = ensure_http_gateway()
    legacy_stopped = stop_legacy_gui()
    result = {
        "ready": True,
        "url": f"http://{address}:{XPRA_PORT}/",
        "transport": "http+ws+password",
        "tls": False,
        "network_scope": "private-ip-only",
        "username": getpass.getuser(),
        "gateway": gateway,
        "backend": f"127.0.0.1:{XPRA_BACKEND_PORT}",
        "chrome_window_layout": chrome["window_layout"],
        "password_file": str(password),
        "legacy_gui_stopped": legacy_stopped,
    }
    if show_credential:
        result["password"] = password.read_text().strip()
    return result


def verify_bridge() -> dict[str, Any]:
    token = read_bridge_token()
    env = command_env()
    env["PLAYWRIGHT_MCP_EXTENSION_TOKEN"] = token
    env["PWTEST_EXTENSION_USER_DATA_DIR"] = str(PROFILE_DIR)
    command = [
        str(LOCAL_BIN / "playwright-mcp"),
        "--extension", "--browser", "chrome",
    ]
    result = call_mcp(command, [
        {"name": "browser_tabs", "arguments": {"action": "list"}},
        {"name": "browser_snapshot", "arguments": {}},
    ], env=env, timeout=90)
    return {
        "ok": True,
        "server": result["server"],
        "tabs": response_text(result, 0),
        "snapshot": response_text(result, 1),
    }


def initialize(args: argparse.Namespace) -> dict[str, Any]:
    require_apply(args)
    ensure_permissions()
    system = ensure_system_packages()
    ensure_user_tools()
    ensure_chrome()
    bridge = install_bridge()
    codex = configure_codex()
    xpra = ensure_xpra(args.show_credential)
    bridge_probe = verify_bridge()
    return {
        "initialized": True,
        "system": system,
        "xpra": xpra,
        "bridge": bridge,
        "codex": codex,
        "bridge_probe": bridge_probe,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision and expose the managed server Chrome through authenticated Xpra.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("detect")
    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--apply", action="store_true")
    init_parser.add_argument("--show-credential", action="store_true")
    ui_parser = subparsers.add_parser("ui")
    ui_parser.add_argument("--ensure", action="store_true")
    ui_parser.add_argument("--show-credential", action="store_true")
    bridge_parser = subparsers.add_parser("bridge")
    bridge_parser.add_argument("--apply", action="store_true")
    bridge_parser.add_argument("--verify", action="store_true")
    config_parser = subparsers.add_parser("configure-codex")
    config_parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "detect":
            emit(detect())
        elif args.command == "init":
            emit(initialize(args))
        elif args.command == "ui":
            if not args.ensure:
                raise RuntimeError("ui is mutating; pass --ensure")
            emit(ensure_xpra(args.show_credential))
        elif args.command == "bridge":
            if args.verify:
                emit(verify_bridge())
            else:
                require_apply(args)
                emit(install_bridge())
        elif args.command == "configure-codex":
            require_apply(args)
            emit(configure_codex())
        return 0
    except Exception as error:
        emit({"ok": False, "error": str(error)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
