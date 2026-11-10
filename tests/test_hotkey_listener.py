import sys
import threading

import pytest

from fakes import FakeNotifier

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey")


def test_listener_stops_and_frees_the_hotkey():
    from focusblocks.platform.windows import HotkeyListener

    spec = "ctrl+alt+shift+f11"                      # unlikely to be taken
    notifier = FakeNotifier()
    first = HotkeyListener(spec, lambda: None, notifier)
    thread = threading.Thread(target=first.run, daemon=True)
    thread.start()
    assert first.ready.wait(2)
    first.stop()
    thread.join(2)
    assert not thread.is_alive()

    again = HotkeyListener(spec, lambda: None, notifier)   # the same key can be registered again
    thread = threading.Thread(target=again.run, daemon=True)
    thread.start()
    assert again.ready.wait(2)
    again.stop()
    thread.join(2)
    assert notifier.sent == []
