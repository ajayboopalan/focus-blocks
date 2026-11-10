"""Windows adapters. Win32 calls happen inside functions, so importing this package is safe anywhere."""

from focusblocks.platform.windows.desktops import PyvdaDesktopMonitor
from focusblocks.platform.windows.devices import RegistryDeviceMonitor
from focusblocks.platform.windows.hotkey import HotkeyListener, parse_hotkey
from focusblocks.platform.windows.input import Win32InputMonitor
from focusblocks.platform.windows.instance import SingleInstanceLock
from focusblocks.platform.windows.notifier import ToastNotifier
from focusblocks.platform.windows.screenshots import PillowDesktopSnapshotter
from focusblocks.platform.windows.ui_support import WindowsUiPlatform
from focusblocks.platform.windows.windows import Win32WindowMonitor

__all__ = [
    "HotkeyListener",
    "PillowDesktopSnapshotter",
    "PyvdaDesktopMonitor",
    "RegistryDeviceMonitor",
    "SingleInstanceLock",
    "ToastNotifier",
    "Win32InputMonitor",
    "Win32WindowMonitor",
    "WindowsUiPlatform",
    "parse_hotkey",
]
