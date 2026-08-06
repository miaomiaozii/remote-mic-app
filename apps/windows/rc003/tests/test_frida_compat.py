import hashlib
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ovb_rc003 import frida_compat


class AssetDescriptorTests(unittest.TestCase):
    def test_uses_official_release_url(self):
        self.assertTrue(
            frida_compat.FRIDA_GADGET.url.startswith(
                "https://github.com/frida/frida/releases/download/"
            )
        )

    def test_sha256_is_pinned_and_well_formed(self):
        self.assertEqual(len(frida_compat.FRIDA_GADGET.sha256), 64)
        int(frida_compat.FRIDA_GADGET.sha256, 16)


class VerifyAssetTests(unittest.TestCase):
    def test_false_when_missing(self):
        missing = Path("/nonexistent/frida-gadget.dll.xz")
        self.assertFalse(frida_compat.verify_asset(missing, frida_compat.FRIDA_GADGET))

    def test_false_when_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.bin"
            path.write_bytes(b"not the real gadget")
            self.assertFalse(frida_compat.verify_asset(path, frida_compat.FRIDA_GADGET))

    def test_true_when_hash_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.bin"
            content = b"pretend gadget bytes"
            path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            asset = frida_compat.ThirdPartyAsset(
                name="test",
                version="0",
                url="https://example.invalid/a",
                sha256=digest,
                license_name="x",
                license_url="https://example.invalid/license",
            )
            self.assertTrue(frida_compat.verify_asset(path, asset))


class ReportDecodeTests(unittest.TestCase):
    def test_decodes_verified_hidogatt_buffer(self):
        self.assertEqual(
            frida_compat.decode_rc003_ioctl_output(
                bytes.fromhex("010000f10080008100")
            ),
            bytes.fromhex("f10080008100"),
        )

    def test_rejects_wrong_prefix_or_length(self):
        self.assertIsNone(frida_compat.decode_rc003_ioctl_output(b"\x01\x00\x00"))
        self.assertIsNone(
            frida_compat.decode_rc003_ioctl_output(
                bytes.fromhex("020000f10080008100")
            )
        )

    def test_extracts_nonzero_little_endian_usages(self):
        self.assertEqual(
            frida_compat.payload_usages(bytes.fromhex("f10000008100")),
            {0xF1, 0x81},
        )
        self.assertEqual(frida_compat.payload_usages(b"short"), set())


class ReportTapTests(unittest.TestCase):
    def test_emits_only_edges_for_missing_usages(self):
        reports = []
        tap = frida_compat.RC003HidReportTap(
            lambda report_id, payload: reports.append((report_id, payload)),
            enabled=False,
        )
        tap._handle_ioctl_output(bytes.fromhex("010000f10080008100"))
        tap._handle_ioctl_output(bytes.fromhex("010000f10000000000"))
        self.assertEqual(
            reports,
            [
                (1, bytes.fromhex("80008100f100")),
                (1, bytes.fromhex("f10000000000")),
            ],
        )

    def test_releases_active_usages_when_stopped(self):
        reports = []
        tap = frida_compat.RC003HidReportTap(
            lambda report_id, payload: reports.append((report_id, payload)),
            enabled=False,
        )
        tap._handle_ioctl_output(bytes.fromhex("010000f10000000000"))
        tap._release_active()
        self.assertEqual(reports[-1], (1, b"\x00" * 6))

    def test_missing_gadget_degrades_without_starting(self):
        tap = frida_compat.RC003HidReportTap(
            lambda _report_id, _payload: None,
            archive_path=Path("/nonexistent/frida-gadget.dll.xz"),
            enabled=True,
        )
        self.assertFalse(tap.available)
        self.assertIn("unavailable", tap.status)
        self.assertFalse(tap.start())

    def test_compatibility_name_accepts_custom_verified_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.bin"
            content = b"pretend gadget bytes"
            path.write_bytes(content)
            asset = frida_compat.ThirdPartyAsset(
                name="test",
                version="0",
                url="https://example.invalid/a",
                sha256=hashlib.sha256(content).hexdigest(),
                license_name="x",
                license_url="https://example.invalid/license",
            )
            layer = frida_compat.BackKeyCompatLayer(gadget_path=path, asset=asset)
            self.assertTrue(layer.available)
            self.assertEqual(layer.status, "ready_gadget_verified")

    def test_server_accepts_elevated_gadget_after_local_injection_is_denied(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        reports = []
        received = threading.Event()
        tap = frida_compat.RC003HidReportTap(
            lambda report_id, payload: (reports.append((report_id, payload)), received.set()),
            enabled=False,
            retry_delay=0.5,
        )
        thread = threading.Thread(target=tap._run, daemon=True)
        with mock.patch.object(
            frida_compat.frida_hid_tap_runtime,
            "HID_TAP_PORT",
            port,
        ), mock.patch.object(
            frida_compat.frida_hid_tap_runtime,
            "find_rc003_hidogatt_host_pid",
            return_value=42,
        ), mock.patch.object(
            frida_compat,
            "inject_current_process",
            side_effect=PermissionError("elevation required"),
        ):
            thread.start()
            deadline = time.monotonic() + 2.0
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            while True:
                try:
                    client.connect(("127.0.0.1", port))
                    break
                except ConnectionRefusedError:
                    if time.monotonic() >= deadline:
                        self.fail("tap server did not start")
                    time.sleep(0.01)
            try:
                for message in (
                    {"kind": "ready", "pid": 42},
                    {"kind": "gatt_read", "raw": "010000f10000000000"},
                ):
                    client.sendall((json.dumps(message) + "\n").encode("utf-8"))
                self.assertTrue(received.wait(2.0))
            finally:
                tap.stop_event.set()
                client.close()
                thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertIn((1, bytes.fromhex("f10000000000")), reports)


if __name__ == "__main__":
    unittest.main()
