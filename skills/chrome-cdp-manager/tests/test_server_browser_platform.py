#!/usr/bin/env python3

import pathlib
import sys
import unittest
from unittest import mock


SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import server_browser  # noqa: E402


class XpraPlatformTests(unittest.TestCase):
    def test_velinux_without_debian_version_accepts_proven_bookworm_base(self) -> None:
        release = {"ID": "velinux", "VERSION_ID": "2", "VERSION_CODENAME": "lyra"}
        with mock.patch.object(server_browser, "os_release", return_value=release), mock.patch.object(
            server_browser, "debian_bookworm_compatible", return_value=True
        ):
            self.assertEqual(server_browser.xpra_repo_codename(), "bookworm")

    def test_velinux_rejects_unproven_debian_base(self) -> None:
        release = {"ID": "velinux", "VERSION_ID": "2", "VERSION_CODENAME": "lyra"}
        with mock.patch.object(server_browser, "os_release", return_value=release), mock.patch.object(
            server_browser, "debian_bookworm_compatible", return_value=False
        ):
            with self.assertRaises(RuntimeError):
                server_browser.xpra_repo_codename()


if __name__ == "__main__":
    unittest.main()
