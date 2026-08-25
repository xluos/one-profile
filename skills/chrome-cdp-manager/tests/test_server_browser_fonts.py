#!/usr/bin/env python3

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import server_browser  # noqa: E402


class ChineseFontTests(unittest.TestCase):
    def test_detects_fontconfig_match(self) -> None:
        response = SimpleNamespace(
            stdout="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc: Noto Sans CJK SC\n",
        )
        with mock.patch.object(server_browser, "executable", return_value="/usr/bin/fc-list"), mock.patch.object(
            server_browser, "run", return_value=response
        ):
            state = server_browser.chinese_font_state()
        self.assertTrue(state["available"])
        self.assertIn("Noto Sans CJK SC", state["match"])

    def test_existing_chinese_font_skips_install(self) -> None:
        state = {"available": True, "match": "Droid Sans Fallback", "reason": None}
        with mock.patch.object(server_browser, "chinese_font_state", return_value=state), mock.patch.object(
            server_browser, "run"
        ) as run_mock:
            result = server_browser.ensure_chinese_font()
        self.assertFalse(result["installed"])
        run_mock.assert_not_called()

    def test_missing_chinese_font_installs_and_rechecks(self) -> None:
        missing = {"available": False, "match": None, "reason": "missing"}
        present = {"available": True, "match": "Noto Sans CJK SC", "reason": None}
        with mock.patch.object(
            server_browser, "chinese_font_state", side_effect=[missing, present]
        ), mock.patch.object(server_browser, "apt_install", return_value=None) as install_mock, mock.patch.object(
            server_browser, "run"
        ) as run_mock:
            result = server_browser.ensure_chinese_font()
        self.assertTrue(result["installed"])
        install_mock.assert_called_once_with(["fonts-noto-cjk"], no_recommends=True)
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0], ["fc-cache", "-f"])


if __name__ == "__main__":
    unittest.main()
