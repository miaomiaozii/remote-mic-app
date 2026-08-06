import unittest
from pathlib import Path
from unittest import mock

from ovb_rc003 import frida_hid_tap_injector as injector


class InjectorPrivilegeOrderingTests(unittest.TestCase):
    def test_debug_privilege_is_enabled_before_wudf_name_query(self):
        calls = []
        dll_path = Path("C:/verified/RemoteMicRC003HidTap.dll")

        with mock.patch.object(injector.os, "name", "nt"), mock.patch.object(
            injector, "find_rc003_hidogatt_host_pid", return_value=42
        ), mock.patch.object(
            injector,
            "enable_debug_privilege",
            side_effect=lambda: calls.append("privilege"),
        ), mock.patch.object(
            injector,
            "_target_process_name",
            side_effect=lambda _pid: calls.append("name") or "wudfhost.exe",
        ), mock.patch.object(
            injector, "prepare_secure_runtime", return_value=dll_path
        ), mock.patch.object(
            injector, "sha256_file", return_value=injector.GADGET_DLL_SHA256
        ), mock.patch.object(
            injector,
            "inject_library",
            side_effect=lambda _pid, _path: calls.append("inject"),
        ):
            injector.inject_current_process(42)

        self.assertEqual(calls, ["privilege", "name", "inject"])


if __name__ == "__main__":
    unittest.main()
