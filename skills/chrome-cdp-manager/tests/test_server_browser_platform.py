#!/usr/bin/env python3

import json
import pathlib
import sys
import tempfile
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

    def test_xpra_client_is_an_explicit_system_dependency(self) -> None:
        self.assertIn("xpra-client", server_browser.XPRA_SYSTEM_PACKAGES)

    def test_xpra_client_state_requires_package_and_importable_module(self) -> None:
        imported = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(server_browser.sys, "platform", "linux"), mock.patch.object(
            server_browser, "executable", side_effect=lambda name: f"/usr/bin/{name}"
        ), mock.patch.object(server_browser, "package_installed", return_value=True), mock.patch.object(
            server_browser, "run", return_value=imported
        ):
            state = server_browser.xpra_client_state()
        self.assertTrue(state["package_installed"])
        self.assertTrue(state["module_importable"])

        missing = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'xpra.client'\n",
        )
        with mock.patch.object(server_browser.sys, "platform", "linux"), mock.patch.object(
            server_browser, "executable", side_effect=lambda name: f"/usr/bin/{name}"
        ), mock.patch.object(server_browser, "package_installed", return_value=False), mock.patch.object(
            server_browser, "run", return_value=missing
        ):
            state = server_browser.xpra_client_state()
        self.assertFalse(state["package_installed"])
        self.assertFalse(state["module_importable"])
        self.assertIn("xpra.client", state["error"])

    def test_system_package_bootstrap_reports_new_xpra_client(self) -> None:
        before = {"package_installed": False, "module_importable": False, "error": "missing"}
        after = {"package_installed": True, "module_importable": True, "error": None}
        with mock.patch.object(server_browser.sys, "platform", "linux"), mock.patch.object(
            server_browser, "executable", side_effect=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None
        ), mock.patch.object(server_browser, "xpra_client_state", side_effect=[before, after]), mock.patch.object(
            server_browser, "ensure_xpra_stable_repo", return_value=[]
        ), mock.patch.object(server_browser, "run"), mock.patch.object(
            server_browser, "apt_install", return_value=None
        ) as apt_install, mock.patch.object(
            server_browser, "ensure_chinese_font", return_value={"available": True}
        ), mock.patch.object(
            server_browser, "system_chrome_path", return_value="/usr/bin/google-chrome"
        ):
            result = server_browser.ensure_system_packages()

        self.assertIn("xpra-client", apt_install.call_args.args[0])
        self.assertTrue(result["xpra_client"]["installed"])

    def test_full_initialization_restarts_xpra_after_client_install(self) -> None:
        args = SimpleNamespace(show_credential=False)
        system = {"xpra_client": {"installed": True}}
        with mock.patch.object(server_browser, "ensure_permissions"), mock.patch.object(
            server_browser, "ensure_system_packages", return_value=system
        ), mock.patch.object(server_browser, "ensure_user_tools"), mock.patch.object(
            server_browser, "install_byted_lane_runtime", return_value={}
        ), mock.patch.object(server_browser, "ensure_chrome", return_value={}), mock.patch.object(
            server_browser, "install_bridge", return_value={}
        ), mock.patch.object(server_browser, "configure_codex", return_value={}), mock.patch.object(
            server_browser, "managed_xpra_process", return_value=(1234, ["xpra"])
        ), mock.patch.object(server_browser, "stop_managed_xpra") as stop_xpra, mock.patch.object(
            server_browser, "ensure_xpra", return_value={}
        ), mock.patch.object(server_browser, "verify_bridge", return_value={}), mock.patch.object(
            server_browser, "verify_byted_lane", return_value={}
        ):
            result = server_browser.initialize_full(args)

        stop_xpra.assert_called_once_with()
        self.assertTrue(result["xpra"]["restarted_for_client_install"])

    def test_bundled_bridge_asset_is_valid_and_extractable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory)
            bridge_dir = state_dir / f"playwright-mcp-bridge-{server_browser.BRIDGE_VERSION}"
            with mock.patch.object(server_browser, "STATE_DIR", state_dir), mock.patch.object(
                server_browser, "BRIDGE_DIR", bridge_dir
            ):
                extracted = server_browser.prepare_bridge_extension()
                self.assertEqual(extracted, bridge_dir)
                self.assertTrue(server_browser.bridge_directory_valid(extracted))

    def test_bundled_byted_lane_asset_is_valid_and_extractable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory)
            bundle_root = state_dir / f"byted-lane-bundle-{server_browser.BYTED_LANE_VERSION}"
            with mock.patch.object(server_browser, "STATE_DIR", state_dir), mock.patch.object(
                server_browser, "BYTED_LANE_ROOT", bundle_root
            ):
                extracted = server_browser.prepare_byted_lane_bundle()
                self.assertEqual(extracted, bundle_root)
                self.assertTrue(server_browser.byted_lane_bundle_valid(extracted))

    def test_lna_launch_state_requires_real_main_process_flags(self) -> None:
        required_args = [
            "/usr/bin/google-chrome",
            "--disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessForNavigations",
            "--extension-content-verification=none",
        ]
        with mock.patch.object(server_browser.sys, "platform", "darwin"), mock.patch.object(
            server_browser, "process_arguments", return_value=required_args
        ):
            state = server_browser.managed_chrome_launch_state(1234)
        self.assertTrue(state["matched"])
        self.assertTrue(state["main_process_features_present"])

        with mock.patch.object(server_browser.sys, "platform", "darwin"), mock.patch.object(
            server_browser, "process_arguments", return_value=["/usr/bin/google-chrome"]
        ):
            state = server_browser.managed_chrome_launch_state(1234)
        self.assertFalse(state["matched"])

    def test_lna_launch_state_accepts_combined_proc_cmdline_argument(self) -> None:
        combined = [
            "/usr/bin/google-chrome --disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessForNavigations "
            "--extension-content-verification=none"
        ]
        with mock.patch.object(server_browser.sys, "platform", "darwin"), mock.patch.object(
            server_browser, "process_arguments", return_value=combined
        ):
            state = server_browser.managed_chrome_launch_state(1234)
        self.assertTrue(state["matched"])
        self.assertEqual(state["extension_content_verification"], "none")

    def test_absolute_unpacked_bridge_path_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            profile = root / "profile"
            extension = root / "extension"
            extension.mkdir()
            preferences = profile / "Default" / "Preferences"
            preferences.parent.mkdir(parents=True)
            preferences.write_text(json.dumps({
                "extensions": {"settings": {server_browser.BRIDGE_ID: {
                    "path": str(extension),
                    "manifest": {"name": "Playwright Extension", "version": server_browser.BRIDGE_VERSION},
                    "disable_reasons": [],
                }}}
            }))
            with mock.patch.object(server_browser, "PROFILE_DIR", profile):
                state = server_browser.bridge_profile_state()
        self.assertEqual(state["path"], str(extension))

    def test_empty_bridge_tombstone_is_removed_without_touching_other_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = pathlib.Path(directory) / "profile"
            preferences = profile / "Default" / "Preferences"
            preferences.parent.mkdir(parents=True)
            preferences.write_text(json.dumps({
                "extensions": {"settings": {server_browser.BRIDGE_ID: {}, "other": {"state": 1}}}
            }))
            with mock.patch.object(server_browser, "PROFILE_DIR", profile):
                self.assertTrue(server_browser.clear_bridge_tombstone())
            settings = json.loads(preferences.read_text())["extensions"]["settings"]
        self.assertNotIn(server_browser.BRIDGE_ID, settings)
        self.assertEqual(settings["other"], {"state": 1})

    def test_invalid_bridge_profile_is_removed_without_touching_other_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = pathlib.Path(directory) / "profile"
            preferences = profile / "Default" / "Preferences"
            preferences.parent.mkdir(parents=True)
            preferences.write_text(json.dumps({
                "extensions": {"settings": {
                    server_browser.BRIDGE_ID: {
                        "path": "/missing/bridge",
                        "manifest": {"name": "Playwright Extension", "version": server_browser.BRIDGE_VERSION},
                        "disable_reasons": [1],
                    },
                    "other": {"state": 1},
                }}
            }))
            with mock.patch.object(server_browser, "PROFILE_DIR", profile):
                self.assertTrue(server_browser.clear_bridge_tombstone())
            settings = json.loads(preferences.read_text())["extensions"]["settings"]
        self.assertNotIn(server_browser.BRIDGE_ID, settings)
        self.assertEqual(settings["other"], {"state": 1})

    def test_byted_lane_external_crx_uses_stable_derived_id(self) -> None:
        extension_id = "abcdefghijklmnopabcdefghijklmnop"
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            extension = root / "extension"
            extension.mkdir()
            (extension / "manifest.json").write_text('{"name":"byted-lane","version":"0.1.0"}')
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                if any(value.startswith("--pack-extension=") for value in command):
                    packed_root = pathlib.Path(next(
                        value.split("=", 1)[1] for value in command if value.startswith("--pack-extension=")
                    )).parent
                    (packed_root / "byted-lane.crx").write_bytes(b"crx")
                    (packed_root / "byted-lane.pem").write_text("pem")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(server_browser, "STATE_DIR", root), mock.patch.object(
                server_browser, "BYTED_LANE_EXTENSION", extension
            ), mock.patch.object(server_browser, "BYTED_LANE_CRX", root / "byted-lane.crx"), mock.patch.object(
                server_browser, "BYTED_LANE_PEM", root / "byted-lane.pem"
            ), mock.patch.object(
                server_browser, "BYTED_LANE_EXTENSION_ID_FILE", root / "byted-lane-extension-id"
            ), mock.patch.object(
                server_browser, "BYTED_LANE_EXTERNAL_CRX", pathlib.Path("/opt/google/chrome/extensions/byted-lane.crx")
            ), mock.patch.object(server_browser, "system_chrome_path", return_value="/usr/bin/google-chrome"), mock.patch.object(
                server_browser, "derive_chrome_extension_id", return_value=extension_id
            ), mock.patch.object(server_browser, "run", side_effect=fake_run):
                result = server_browser.install_byted_lane_extension()

        self.assertEqual(result["extension_id"], extension_id)
        self.assertEqual(result["external_config"], f"/opt/google/chrome/extensions/{extension_id}.json")
        self.assertTrue(any(command[-1] == result["external_config"] for command in commands))

    def test_byted_lane_cli_launcher_uses_absolute_bun_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local_bin = pathlib.Path(directory) / "bin"
            local_bin.mkdir()
            cli_entry = pathlib.Path(directory) / "runtime with spaces" / "cli" / "index.ts"
            cli_entry.parent.mkdir(parents=True)
            cli_entry.write_text("// cli")
            with mock.patch.object(server_browser, "LOCAL_BIN", local_bin):
                launcher = server_browser.install_byted_lane_cli_launcher(cli_entry)
            content = launcher.read_text()
        self.assertIn(str(local_bin / "bun"), content)
        self.assertIn("'" + str(cli_entry) + "'", content)
        self.assertIn('"$@"', content)
        self.assertFalse(launcher.is_symlink())

    def test_gateway_process_can_be_reused_after_skill_path_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory)
            (state_dir / "xpra-http-gateway.pid").write_text("4321\n")
            cmdline = (
                b"/home/user/.local/bin/node\0"
                b"/home/user/.agents/skills/chrome-cdp-manager/scripts/xpra_http_gateway.mjs\0"
                b"--listen-port\0"
                b"14500\0"
                b"--backend-port\0"
                b"14501\0"
            )
            original_read_bytes = pathlib.Path.read_bytes

            def fake_read_bytes(path):
                if str(path) == "/proc/4321/cmdline":
                    return cmdline
                return original_read_bytes(path)

            with mock.patch.object(server_browser, "STATE_DIR", state_dir), mock.patch.object(
                pathlib.Path, "read_bytes", fake_read_bytes
            ), mock.patch.object(server_browser, "port_open", return_value=True):
                process = server_browser.managed_gateway_process()
                ready = server_browser.managed_gateway_is_ready()
        self.assertEqual(process[0], 4321)
        self.assertTrue(ready)

    def test_bridge_token_capture_activates_status_page_without_closing_window(self) -> None:
        token = "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory)
            (state_dir / "session.json").write_text('{"pid":2468}')
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                if command[:4] == ["xdotool", "search", "--onlyvisible", "--pid"]:
                    return SimpleNamespace(returncode=0, stdout="99\n", stderr="")
                if command[:2] == ["xdotool", "getwindowname"]:
                    return SimpleNamespace(returncode=0, stdout="Playwright Extension Status\n", stderr="")
                if command[:4] == ["xclip", "-selection", "clipboard", "-o"]:
                    return SimpleNamespace(
                        returncode=0,
                        stdout=f"PLAYWRIGHT_MCP_EXTENSION_TOKEN={token}\n",
                        stderr="",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(server_browser, "STATE_DIR", state_dir), mock.patch.object(
                server_browser, "executable", return_value="/usr/bin/tool"
            ), mock.patch.object(server_browser, "run", side_effect=fake_run), mock.patch.object(
                server_browser.time, "sleep", return_value=None
            ):
                captured = server_browser.capture_bridge_token()

        flattened = [value for command in commands for value in command]
        self.assertEqual(captured, token)
        self.assertIn(f"chrome-extension://{server_browser.BRIDGE_ID}/status.html", flattened)
        self.assertNotIn("ctrl+w", flattened)
        self.assertNotIn("alt+f4", flattened)

    def test_bridge_token_is_redacted_from_probe_output(self) -> None:
        secret = "example-secret-token"
        self.assertEqual(
            server_browser.redact_secret(f"https://example.test/?token={secret}", secret),
            "https://example.test/?token=<redacted>",
        )

    def test_healthy_active_lane_does_not_require_safe_default(self) -> None:
        chrome_state = {
            "matched": True,
            "managed_process_verified": True,
            "network_services": [{"pid": 22, "required_features_present": True}],
        }
        lane_state = {
            "bundle_asset_valid": True,
            "runtime_ready": True,
            "cli_installed": True,
            "systemd_unit_installed": True,
            "extension_id": "abcdefghijklmnopabcdefghijklmnop",
            "daemon": {
                "daemon": {"pid": 33},
                "extension": {
                    "connected": True,
                    "lastAppliedOk": True,
                    "lastAppliedRevision": 7,
                },
                "config": {"revision": 7},
            },
            "config": {
                "lane": {"enabled": True, "headers": {}},
                "environments": [{"env": "ppe_test", "enabled": True}],
                "proxy": {"mode": "direct"},
            },
            "safe_default": False,
            "skills": {"byted-lane": True, "byted-integration-test": True},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            token = root / "playwright-mcp-extension-token"
            token.write_text("token")
            external_config = root / "bridge.json"
            external_config.write_text("{}")
            lane_crx = root / "byted-lane.crx"
            lane_crx.write_bytes(b"crx")
            local_bin = root / "bin"
            local_bin.mkdir()
            (local_bin / "bun").write_text("bun")
            (local_bin / "byted-lane").write_text("cli")

            def fake_run(command, **_kwargs):
                version = server_browser.BUN_VERSION if pathlib.Path(command[0]).name == "bun" else server_browser.BYTED_LANE_VERSION
                return SimpleNamespace(returncode=0, stdout=version + "\n", stderr="")

            with mock.patch.object(server_browser.sys, "platform", "linux"), mock.patch.object(
                server_browser, "STATE_DIR", root
            ), mock.patch.object(server_browser, "LOCAL_BIN", local_bin
            ), mock.patch.object(server_browser, "BRIDGE_EXTERNAL_CONFIG", external_config), mock.patch.object(
                server_browser, "BYTED_LANE_EXTERNAL_CRX", lane_crx
            ), mock.patch.object(server_browser, "system_chrome_path", return_value="/usr/bin/google-chrome"), mock.patch.object(
                server_browser, "managed_chrome_launch_state", return_value=chrome_state
            ), mock.patch.object(server_browser, "port_open", return_value=True), mock.patch.object(
                server_browser, "executable", side_effect=lambda name: f"/usr/bin/{name}"
            ), mock.patch.object(server_browser, "managed_xpra_is_http", return_value=True), mock.patch.object(
                server_browser, "managed_gateway_is_ready", return_value=True
            ), mock.patch.object(
                server_browser,
                "xpra_client_state",
                return_value={"package_installed": True, "module_importable": True, "error": None},
            ) as xpra_client_probe, mock.patch.object(server_browser, "file_mode", return_value="0o600"), mock.patch.object(
                server_browser, "bridge_directory_valid", return_value=True
            ), mock.patch.object(server_browser, "bridge_profile_state", return_value={"version": server_browser.BRIDGE_VERSION}), mock.patch.object(
                server_browser, "run", side_effect=fake_run
            ), mock.patch.object(server_browser, "byted_lane_detect_state", return_value=lane_state), mock.patch.object(
                server_browser, "codex_mcp_detect_state", return_value={"ok": True}
            ):
                health = server_browser.environment_health()
                xpra_client_probe.return_value = {
                    "package_installed": False,
                    "module_importable": False,
                    "error": "ModuleNotFoundError: No module named 'xpra.client'",
                }
                missing_client_health = server_browser.environment_health()

        self.assertTrue(health["ok"])
        self.assertFalse(health["checks"]["byted_lane"]["safe_default"])
        self.assertEqual(health["issues"], [])
        self.assertFalse(missing_client_health["ok"])
        self.assertEqual(
            [item["code"] for item in missing_client_health["issues"]],
            ["xpra_client_unavailable"],
        )

    def test_initialize_is_a_noop_when_environment_is_healthy(self) -> None:
        healthy = {"ok": True, "repair_required": False, "issues": [], "checks": {}}
        args = SimpleNamespace(apply=True, show_credential=False)
        with mock.patch.object(server_browser, "environment_health", return_value=healthy), mock.patch.object(
            server_browser, "initialize_full"
        ) as initialize_full:
            result = server_browser.initialize(args)
        initialize_full.assert_not_called()
        self.assertFalse(result["repaired"])
        self.assertEqual(result["reason"], "environment already healthy")

    def test_health_reports_repairable_core_failures_with_stable_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with mock.patch.object(server_browser.sys, "platform", "linux"), mock.patch.object(
                server_browser, "STATE_DIR", root
            ), mock.patch.object(server_browser, "LOCAL_BIN", root / "bin"), mock.patch.object(
                server_browser, "BRIDGE_EXTERNAL_CONFIG", root / "bridge.json"
            ), mock.patch.object(server_browser, "BYTED_LANE_EXTERNAL_CRX", root / "lane.crx"), mock.patch.object(
                server_browser, "system_chrome_path", return_value=None
            ), mock.patch.object(
                server_browser,
                "managed_chrome_launch_state",
                return_value={"matched": False, "managed_process_verified": True, "network_services": []},
            ), mock.patch.object(server_browser, "port_open", return_value=False), mock.patch.object(
                server_browser, "executable", return_value=None
            ), mock.patch.object(server_browser, "managed_xpra_is_http", return_value=False), mock.patch.object(
                server_browser, "managed_gateway_is_ready", return_value=False
            ), mock.patch.object(
                server_browser,
                "xpra_client_state",
                return_value={"package_installed": False, "module_importable": False, "error": "missing"},
            ), mock.patch.object(server_browser, "file_mode", return_value=None), mock.patch.object(
                server_browser, "bridge_directory_valid", return_value=False
            ), mock.patch.object(server_browser, "bridge_profile_state", return_value=None), mock.patch.object(
                server_browser,
                "byted_lane_detect_state",
                return_value={"daemon": None, "config": None, "skills": {"byted-lane": False}},
            ), mock.patch.object(server_browser, "codex_mcp_detect_state", return_value={"ok": False}):
                health = server_browser.environment_health()

        codes = {item["code"] for item in health["issues"]}
        self.assertFalse(health["ok"])
        self.assertTrue({
            "system_chrome_missing",
            "cdp_unreachable",
            "managed_chrome_invalid",
            "network_service_unready",
            "xpra_unavailable",
            "xpra_client_unavailable",
            "bridge_unavailable",
            "toolchain_unavailable",
            "byted_lane_runtime_unavailable",
            "byted_lane_daemon_unavailable",
            "byted_lane_extension_unavailable",
            "byted_lane_config_invalid",
            "skills_missing",
            "codex_mcp_unavailable",
        } <= codes)

if __name__ == "__main__":
    unittest.main()
