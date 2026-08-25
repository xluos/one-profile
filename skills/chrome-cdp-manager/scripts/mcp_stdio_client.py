#!/usr/bin/env python3

import argparse
import json
import selectors
import subprocess
import sys
import time
from typing import Any


def _send(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read(process: subprocess.Popen[str], request_id: int, timeout: int) -> dict[str, Any]:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not selector.select(max(0.0, deadline - time.monotonic())):
            break
        line = process.stdout.readline()
        if not line:
            break
        message = json.loads(line)
        if message.get("id") == request_id:
            return message
    raise TimeoutError(f"no MCP response for request {request_id}")


def call_mcp(
    command: list[str],
    calls: list[dict[str, Any]],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 90,
) -> dict[str, Any]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        _send(process, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "chrome-cdp-manager", "version": "1.0"},
            },
        })
        initialized = _read(process, 1, timeout)
        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = _read(process, 2, timeout)
        tools = listed.get("result", {}).get("tools", [])
        tool_names = {tool.get("name") for tool in tools}
        responses = []
        for request_id, call in enumerate(calls, start=3):
            name = call["name"]
            if name not in tool_names:
                raise ValueError(f"MCP tool is unavailable: {name}")
            _send(process, {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": call.get("arguments", {})},
            })
            response = _read(process, request_id, timeout)
            if response.get("result", {}).get("isError"):
                blocks = response.get("result", {}).get("content", [])
                message = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text")
                raise RuntimeError(message or f"MCP tool failed: {name}")
            responses.append({"tool": name, "response": response})
        return {
            "protocol": initialized.get("result", {}).get("protocolVersion"),
            "server": initialized.get("result", {}).get("serverInfo"),
            "tool_count": len(tools),
            "responses": responses,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Call one or more MCP stdio tools.")
    parser.add_argument("--calls", required=True, help="JSON array of tool calls")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("missing MCP command")
    print(json.dumps(call_mcp(args.command, json.loads(args.calls)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
