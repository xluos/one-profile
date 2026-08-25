#!/usr/bin/env python3

import pathlib
import sys
import unittest
from unittest import mock


SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ensure_server_browser  # noqa: E402


class EnsureServerBrowserTests(unittest.TestCase):
    def test_read_only_check_does_not_repair_unhealthy_environment(self) -> None:
        unhealthy = {"ok": False, "repair_required": True, "issues": [{"code": "cdp_unreachable"}]}
        with mock.patch.object(sys, "argv", ["ensure_server_browser.py"]), mock.patch.object(
            ensure_server_browser.server_browser, "environment_health", return_value=unhealthy
        ), mock.patch.object(ensure_server_browser.server_browser, "initialize") as initialize, mock.patch.object(
            ensure_server_browser, "emit"
        ):
            exit_code = ensure_server_browser.main()
        initialize.assert_not_called()
        self.assertEqual(exit_code, 1)

    def test_repair_requires_explicit_apply(self) -> None:
        unhealthy = {"ok": False, "repair_required": True, "issues": [{"code": "cdp_unreachable"}]}
        with mock.patch.object(sys, "argv", ["ensure_server_browser.py", "--repair"]), mock.patch.object(
            ensure_server_browser.server_browser, "environment_health", return_value=unhealthy
        ), mock.patch.object(ensure_server_browser.server_browser, "initialize") as initialize, mock.patch.object(
            ensure_server_browser, "emit"
        ):
            exit_code = ensure_server_browser.main()
        initialize.assert_not_called()
        self.assertEqual(exit_code, 2)

    def test_repair_is_a_noop_when_environment_is_healthy(self) -> None:
        healthy = {"ok": True, "repair_required": False, "issues": [], "checks": {}}
        with mock.patch.object(
            sys, "argv", ["ensure_server_browser.py", "--repair", "--apply"]
        ), mock.patch.object(
            ensure_server_browser.server_browser, "environment_health", return_value=healthy
        ), mock.patch.object(ensure_server_browser.server_browser, "initialize") as initialize, mock.patch.object(
            ensure_server_browser, "emit"
        ):
            exit_code = ensure_server_browser.main()
        initialize.assert_not_called()
        self.assertEqual(exit_code, 0)

    def test_repair_failure_is_emitted_as_structured_error(self) -> None:
        unhealthy = {"ok": False, "repair_required": True, "issues": [{"code": "cdp_unreachable"}]}
        with mock.patch.object(
            sys, "argv", ["ensure_server_browser.py", "--repair", "--apply"]
        ), mock.patch.object(
            ensure_server_browser.server_browser, "environment_health", return_value=unhealthy
        ), mock.patch.object(
            ensure_server_browser.server_browser, "initialize", side_effect=RuntimeError("repair failed")
        ), mock.patch.object(ensure_server_browser, "emit") as emit:
            exit_code = ensure_server_browser.main()
        self.assertEqual(exit_code, 1)
        self.assertEqual(emit.call_args.args[0]["error"], "repair failed")

    def test_final_health_failure_is_emitted_as_structured_error(self) -> None:
        unhealthy = {"ok": False, "repair_required": True, "issues": [{"code": "cdp_unreachable"}]}
        with mock.patch.object(
            sys, "argv", ["ensure_server_browser.py", "--repair", "--apply"]
        ), mock.patch.object(
            ensure_server_browser.server_browser,
            "environment_health",
            side_effect=[unhealthy, OSError("probe failed")],
        ), mock.patch.object(
            ensure_server_browser.server_browser, "initialize", return_value={"repaired": True}
        ), mock.patch.object(ensure_server_browser, "emit") as emit:
            exit_code = ensure_server_browser.main()
        self.assertEqual(exit_code, 1)
        self.assertTrue(emit.call_args.args[0]["repaired"])
        self.assertIn("final health check failed", emit.call_args.args[0]["error"])


if __name__ == "__main__":
    unittest.main()
