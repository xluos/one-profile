#!/usr/bin/env python3

import json
import pathlib
import subprocess
import tempfile
import textwrap
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "verify_mcp_cdp_config.py"


class VerifyMcpConfigTest(unittest.TestCase):
    def verify(self, config: str) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "config.toml"
            path.write_text(textwrap.dedent(config))
            result = subprocess.run(
                [str(SCRIPT), "--client", "codex", "--config", str(path)],
                text=True,
                capture_output=True,
            )
        return result.returncode, json.loads(result.stdout)

    def test_accepts_playwright_bridge_with_token_and_managed_profile(self) -> None:
        code, payload = self.verify("""
            [mcp_servers.playwright]
            command = "/opt/playwright-mcp"
            args = ["--extension", "--browser", "chrome"]

            [mcp_servers.playwright.env]
            PLAYWRIGHT_MCP_EXTENSION_TOKEN = "secret"
            PWTEST_EXTENSION_USER_DATA_DIR = "/srv/chrome-profile"
        """)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["servers"]["playwright"]["mode"], "extension")

    def test_rejects_bridge_without_managed_profile_binding(self) -> None:
        code, payload = self.verify("""
            [mcp_servers.playwright]
            command = "/opt/playwright-mcp"
            args = ["--extension"]

            [mcp_servers.playwright.env]
            PLAYWRIGHT_MCP_EXTENSION_TOKEN = "secret"
        """)
        self.assertEqual(code, 1)
        self.assertFalse(payload["servers"]["playwright"]["extension_profile_configured"])

    def test_accepts_fixed_cdp_mode(self) -> None:
        code, payload = self.verify("""
            [mcp_servers.playwright]
            command = "/opt/playwright-mcp"
            args = ["--cdp-endpoint", "http://127.0.0.1:9222"]
        """)
        self.assertEqual(code, 0)
        self.assertEqual(payload["servers"]["playwright"]["mode"], "cdp")


if __name__ == "__main__":
    unittest.main()
