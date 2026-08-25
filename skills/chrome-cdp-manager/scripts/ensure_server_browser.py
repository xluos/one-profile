#!/usr/bin/env python3

import argparse
import json
import sys
from types import SimpleNamespace

import server_browser


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the managed server browser and optionally repair it through the idempotent initializer."
    )
    parser.add_argument("--repair", action="store_true", help="repair the environment when health checks fail")
    parser.add_argument("--apply", action="store_true", help="authorize host changes; required with --repair")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        before = server_browser.environment_health()
    except Exception as error:
        emit({"checked": False, "repaired": False, "error": str(error)})
        return 1
    if not args.repair:
        emit({"checked": True, "repaired": False, "health": before})
        return 0 if before["ok"] else 1
    if not args.apply:
        emit({
            "checked": True,
            "repaired": False,
            "health": before,
            "error": "repair changes the host; rerun with --repair --apply",
        })
        return 2
    if before["ok"]:
        emit({"checked": True, "repaired": False, "reason": "environment already healthy", "health": before})
        return 0

    try:
        initialization = server_browser.initialize(SimpleNamespace(apply=True, show_credential=False))
    except Exception as error:
        emit({
            "checked": True,
            "repaired": False,
            "issues_before": before["issues"],
            "error": str(error),
        })
        return 1
    try:
        after = server_browser.environment_health()
    except Exception as error:
        emit({
            "checked": True,
            "repaired": initialization.get("repaired", False),
            "issues_before": before["issues"],
            "error": f"repair finished but the final health check failed: {error}",
        })
        return 1
    emit({
        "checked": True,
        "repaired": initialization.get("repaired", False),
        "issues_before": before["issues"],
        "health": after,
    })
    return 0 if after["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
