import unittest
from pathlib import Path
from unittest import mock

from ovb_rc003 import frida_hid_tap_elevation as elevation


class ActivationCommandTests(unittest.TestCase):
    def test_frozen_command_reuses_current_executable(self):
        executable, parameters, cwd = elevation.build_activation_command(
            42, frozen=True, executable="C:/RemoteMic/RemoteMicRC003.exe"
        )
        self.assertEqual(executable, "C:/RemoteMic/RemoteMicRC003.exe")
        self.assertEqual(parameters, "--rc003-hid-injector --pid 42")
        self.assertEqual(Path(cwd), Path(executable).parent)

    def test_source_command_dispatches_through_module(self):
        _executable, parameters, _cwd = elevation.build_activation_command(
            42, frozen=False, executable="C:/Python/python.exe"
        )
        self.assertEqual(
            parameters, "-m ovb_rc003 --rc003-hid-injector --pid 42"
        )


class ActivationRequestTests(unittest.TestCase):
    def test_explicit_request_launches_only_discovered_pid(self):
        launched = []
        with mock.patch.object(elevation.os, "name", "nt"):
            pid = elevation.request_hid_tap_activation(
                _find_pid=lambda: 42,
                _launch=lambda executable, parameters, cwd: launched.append(
                    (executable, parameters, cwd)
                )
                or 33,
            )
        self.assertEqual(pid, 42)
        self.assertIn("--pid 42", launched[0][1])

    def test_uac_cancellation_is_neutral_and_specific(self):
        with mock.patch.object(elevation.os, "name", "nt"):
            with self.assertRaises(elevation.HidTapActivationCancelled):
                elevation.request_hid_tap_activation(
                    _find_pid=lambda: 42,
                    _launch=lambda *_args: elevation.SHELL_ACCESS_DENIED,
                )

    def test_missing_hid_service_fails_before_launch(self):
        launch = mock.Mock()
        with mock.patch.object(elevation.os, "name", "nt"):
            with self.assertRaises(elevation.HidTapActivationError):
                elevation.request_hid_tap_activation(
                    _find_pid=lambda: None,
                    _launch=launch,
                )
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
