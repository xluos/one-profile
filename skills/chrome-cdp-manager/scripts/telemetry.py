#!/usr/bin/env python3
"""Best-effort telemetry for chrome-cdp-manager scripts."""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ENDPOINT = "https://q4c3ha1x.fn.bytedance.net/script-events"
TRACKING_TOKEN = "7a17acae0e6b59b14d710c44353b36a4e203227bec89c6ea2d3fd0692fd93f3c"
TOOL_VERSION = "1.0.1"


def _output(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=1.2, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _user_id() -> str:
    raw = _output(["bytedcli", "--json", "auth", "userinfo"])
    if raw:
        try:
            data = json.loads(raw).get("data", {})
            if data.get("username"):
                return str(data["username"]).strip()
            if data.get("email"):
                return str(data["email"]).split("@", 1)[0]
            if data.get("name"):
                return str(data["name"]).strip()
        except (TypeError, ValueError):
            pass
    return _output(["git", "config", "--get", "user.email"]) or _output(
        ["git", "config", "--get", "user.name"]
    ) or "unknown"


def _send(event: dict[str, Any]) -> None:
    payload = json.dumps({
        "event_type": event["event_type"],
        "script_key": "chrome-cdp-manager",
        "user_id": _user_id(),
        "properties": {
            "tool_version": TOOL_VERSION,
            "source": "skill_script",
            "machine_name": socket.gethostname(),
            "platform": platform.system().lower(),
            **event.get("properties", {}),
        },
    }).encode("utf-8")
    request = urllib.request.Request(
        os.environ.get("IP_TOOL_TELEMETRY_ENDPOINT", ENDPOINT),
        data=payload,
        headers={"content-type": "application/json", "x-script-tracking-token": TRACKING_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.5):
            pass
    except Exception:
        pass


def track(event_type: str, properties: dict[str, Any] | None = None) -> None:
    if os.environ.get("IP_TOOL_TELEMETRY") == "0" or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    event = json.dumps({"event_type": event_type, "properties": properties or {}})
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--emit", event],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        pass


if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--emit":
    try:
        _send(json.loads(sys.argv[2]))
    except Exception:
        pass
