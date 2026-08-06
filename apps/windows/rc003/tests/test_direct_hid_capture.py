import json
import socket
import threading
import time
import unittest
from unittest import mock

from ovb_rc003 import direct_hid_capture


class DirectHidCaptureTests(unittest.TestCase):
    def test_message_round_trip_contains_only_report_metadata(self):
        payload = bytes.fromhex("f10000000000")
        message = json.dumps(
            {
                "kind": direct_hid_capture.CAPTURE_KIND,
                "report_id": 1,
                "payload": payload.hex(),
            }
        ).encode("ascii")
        self.assertEqual(direct_hid_capture.decode_message(message), (1, payload))
        text = message.decode("ascii")
        for forbidden in ("address", "device_path", "voice", "action"):
            self.assertNotIn(forbidden, text)

    def test_malformed_or_wrong_sized_message_is_rejected(self):
        self.assertIsNone(direct_hid_capture.decode_message(b"not-json"))
        self.assertIsNone(
            direct_hid_capture.decode_message(
                b'{"kind":"remote_mic_direct_hid_v1","report_id":1,"payload":"f100"}'
            )
        )

    def test_publish_is_best_effort_when_no_receiver_exists(self):
        failing_socket = mock.MagicMock()
        failing_socket.__enter__.return_value.sendto.side_effect = OSError("closed")
        with mock.patch.object(
            direct_hid_capture.socket, "socket", return_value=failing_socket
        ):
            direct_hid_capture.publish_report(1, bytes.fromhex("f10000000000"))

    def test_listener_receives_one_loopback_report_and_stops(self):
        received = []
        event = threading.Event()
        listener = direct_hid_capture.DirectHidCaptureListener(
            lambda report_id, payload: (received.append((report_id, payload)), event.set())
        )
        listener.start()
        try:
            direct_hid_capture.publish_report(1, bytes.fromhex("f10000000000"))
            self.assertTrue(event.wait(1.0))
        finally:
            listener.stop()
        self.assertEqual(received, [(1, bytes.fromhex("f10000000000"))])


if __name__ == "__main__":
    unittest.main()
