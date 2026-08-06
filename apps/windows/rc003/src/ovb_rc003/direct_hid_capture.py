"""Loopback-only live preview for HID reports already owned by the bridge.

The RC001/RC003 back usage is consumed inside the HID-over-GATT WUDF host and
therefore never reaches a second Raw Input listener in the settings process.
The bridge publishes only the compact six-byte keyboard report to localhost so
the explicit "detect real key" UI can display the same physical edge.  No
device address, path, name, voice data, or configured action is transmitted or
persisted, and the receiver never executes an action.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Callable


CAPTURE_HOST = "127.0.0.1"
CAPTURE_PORT = 30686
CAPTURE_KIND = "remote_mic_direct_hid_v1"


def publish_report(report_id: int, payload: bytes) -> None:
    """Best-effort publication of one bridge-owned HID report to localhost."""

    if report_id != 1 or len(payload) != 6:
        return
    message = json.dumps(
        {"kind": CAPTURE_KIND, "report_id": report_id, "payload": payload.hex()},
        separators=(",", ":"),
    ).encode("ascii")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as publisher:
            publisher.sendto(message, (CAPTURE_HOST, CAPTURE_PORT))
    except OSError:
        # Detection is optional.  A closed settings window (the normal case)
        # must never disturb button execution in the bridge.
        return


def decode_message(data: bytes) -> tuple[int, bytes] | None:
    """Validate one loopback datagram and return its compact report."""

    try:
        message = json.loads(data.decode("ascii"))
        if message.get("kind") != CAPTURE_KIND:
            return None
        report_id = int(message["report_id"])
        payload = bytes.fromhex(message["payload"])
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        return None
    if report_id != 1 or len(payload) != 6:
        return None
    return report_id, payload


class DirectHidCaptureListener:
    """Receive bridge previews until explicitly stopped by the settings UI."""

    def __init__(self, handler: Callable[[int, bytes], None]) -> None:
        self._handler = handler
        self._stop_event = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            receiver.bind((CAPTURE_HOST, CAPTURE_PORT))
            receiver.settimeout(0.25)
        except Exception:
            receiver.close()
            raise
        self._socket = receiver
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="remote-mic-direct-hid-capture",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        receiver = self._socket
        if receiver is None:
            return
        while not self._stop_event.is_set():
            try:
                data, address = receiver.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if address[0] != CAPTURE_HOST:
                continue
            decoded = decode_message(data)
            if decoded is None:
                continue
            try:
                self._handler(*decoded)
            except Exception:
                # A preview callback must not strand this owned receiver.
                continue

    def stop(self) -> None:
        self._stop_event.set()
        receiver = self._socket
        self._socket = None
        if receiver is not None:
            receiver.close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
            if thread.is_alive():
                raise RuntimeError("direct HID capture listener did not stop")
