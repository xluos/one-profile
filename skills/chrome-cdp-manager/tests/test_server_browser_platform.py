#!/usr/bin/env python3

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import server_browser  # noqa: E402


class XpraPlatformTests(unittest.TestCase):
    def test_headless_chrome_arguments_are_detected(self) -> None:
        self.assertTrue(server_browser.arguments_are_headless(["chrome", "--headless=new"]))
        self.assertTrue(server_browser.arguments_are_headless(["chrome --headless=new --remote-debugging-port=9222"]))
        self.assertTrue(server_browser.arguments_are_headless(["chrome", "--ozone-platform=headless"]))
        self.assertFalse(server_browser.arguments_are_headless(["chrome", "--remote-debugging-port=9222"]))

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

    def test_apt_nonzero_is_warning_when_requested_packages_are_present(self) -> None:
        failed = SimpleNamespace(returncode=100, stdout="dpkg failed\n", stderr="external package error\n")
        with mock.patch.object(server_browser, "run", return_value=failed), mock.patch.object(
            server_browser, "package_installed", return_value=True
        ):
            warning = server_browser.apt_install(["xpra-server", "xpra-html5"])
        self.assertIn("all requested packages are installed", warning)

    def test_apt_nonzero_fails_when_requested_package_is_missing(self) -> None:
        failed = SimpleNamespace(returncode=100, stdout="dpkg failed\n", stderr="external package error\n")
        with mock.patch.object(server_browser, "run", return_value=failed), mock.patch.object(
            server_browser, "package_installed", side_effect=[True, False]
        ):
            with self.assertRaisesRegex(RuntimeError, "xpra-html5"):
                server_browser.apt_install(["xpra-server", "xpra-html5"])


if __name__ == "__main__":
    unittest.main()
