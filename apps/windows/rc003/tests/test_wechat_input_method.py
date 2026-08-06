import unittest

from ovb_rc003 import wechat_input_method as wetype


class _FakeNative:
    def __init__(self):
        self.toolbar = 10
        self.voice = 20
        self.toolbar_visible = True
        self.voice_visible = False
        self.owner = wetype.EXPECTED_PROCESS_NAME
        self.clicks = []

    def find_window(self, class_name, title):
        if (class_name, title) == (wetype.TOOLBAR_CLASS, wetype.TOOLBAR_TITLE):
            return self.toolbar
        if (class_name, title) == (
            wetype.VOICE_WINDOW_CLASS,
            wetype.VOICE_WINDOW_TITLE,
        ):
            return self.voice
        return 0

    def is_visible(self, hwnd):
        return self.toolbar_visible if hwnd == self.toolbar else self.voice_visible

    def process_name(self, hwnd):
        return self.owner

    def client_size(self, hwnd):
        return (160, 40)

    def post_left_click(self, hwnd, x, y):
        self.clicks.append((hwnd, x, y))
        self.voice_visible = not self.voice_visible
        return True

    def sleep(self, seconds):
        pass


class WeChatInputMethodVoiceToolbarTests(unittest.TestCase):
    def test_voice_button_is_second_of_five_status_bar_items(self):
        self.assertEqual(wetype.voice_button_point(160, 40), (48, 20))

    def test_opens_and_closes_without_duplicate_clicks(self):
        native = _FakeNative()
        self.assertTrue(wetype.set_voice_panel_active(True, _native=native))
        self.assertTrue(native.voice_visible)
        self.assertEqual(native.clicks, [(10, 48, 20)])

        self.assertTrue(wetype.set_voice_panel_active(True, _native=native))
        self.assertEqual(len(native.clicks), 1)

        self.assertTrue(wetype.set_voice_panel_active(False, _native=native))
        self.assertFalse(native.voice_visible)
        self.assertEqual(len(native.clicks), 2)

    def test_rejects_spoofed_owner_or_hidden_toolbar(self):
        native = _FakeNative()
        native.owner = "not-wetype.exe"
        self.assertFalse(wetype.set_voice_panel_active(True, _native=native))
        self.assertEqual(native.clicks, [])

        native.owner = wetype.EXPECTED_PROCESS_NAME
        native.toolbar_visible = False
        self.assertFalse(wetype.set_voice_panel_active(True, _native=native))
        self.assertEqual(native.clicks, [])


if __name__ == "__main__":
    unittest.main()
