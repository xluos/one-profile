#!/usr/bin/env python3

import argparse
import json
import pathlib
import sys
import tomllib
from typing import Any


FIXED_ENDPOINT = "http://127.0.0.1:9222"
SERVER_RULES = {
    "chrome-devtools": ("--browserUrl", "--browser-url"),
    "playwright": ("--cdp-endpoint",),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that browser MCP servers connect to the managed Chrome CDP endpoint."
    )
    parser.add_argument("--client", required=True, choices=("codex", "claude", "cursor"))
    parser.add_argument("--config", type=pathlib.Path)
    return parser.parse_args()


def default_config(client: str) -> pathlib.Path:
    home = pathlib.Path.home()
    return {
        "codex": home / ".codex" / "config.toml",
        "claude": home / ".claude.json",
        "cursor": home / ".cursor" / "mcp.json",
    }[client]


def load_servers(client: str, config_path: pathlib.Path) -> dict[str, Any]:
    if client == "codex":
        with config_path.open("rb") as config_file:
            payload = tomllib.load(config_file)
        servers = payload.get("mcp_servers", {})
    else:
        payload = json.loads(config_path.read_text())
        servers = payload.get("mcpServers", {})

    if not isinstance(servers, dict):
        raise ValueError("MCP server configuration is not an object")
    return servers


def command_parts(server: Any) -> list[str]:
    if not isinstance(server, dict):
        return []

    command = server.get("command", "")
    args = server.get("args", [])
    parts: list[str] = []
    if isinstance(command, str):
        parts.extend(command.split())
    if isinstance(args, list):
        parts.extend(str(value) for value in args)
    return parts


def has_fixed_endpoint(parts: list[str], flags: tuple[str, ...]) -> bool:
    for index, part in enumerate(parts):
        for flag in flags:
            if part == flag and index + 1 < len(parts) and parts[index + 1] == FIXED_ENDPOINT:
                return True
            if part == f"{flag}={FIXED_ENDPOINT}":
                return True
    return False


def main() -> int:
    args = parse_args()
    config_path = args.config or default_config(args.client)
    result: dict[str, Any] = {
        "client": args.client,
        "config_file": str(config_path),
        "endpoint": FIXED_ENDPOINT,
        "servers": {},
        "ok": False,
    }

    try:
        servers = load_servers(args.client, config_path)
    except Exception as error:
        result["error"] = str(error)
        print(json.dumps(result, ensure_ascii=False))
        return 1

    configured_count = 0
    failures = []
    for server_name, flags in SERVER_RULES.items():
        if server_name not in servers:
            result["servers"][server_name] = {"configured": False, "bound": False}
            continue

        configured_count += 1
        parts = command_parts(servers[server_name])
        bound = has_fixed_endpoint(parts, flags)
        result["servers"][server_name] = {
            "configured": True,
            "bound": bound,
            "required_flags": list(flags),
        }
        if not bound:
            failures.append(server_name)

    if configured_count == 0:
        result["error"] = "no supported browser MCP server is configured"
    elif failures:
        result["error"] = f"servers missing the fixed endpoint: {', '.join(failures)}"
    else:
        result["ok"] = True

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
