"""Virtual desktops through pyvda."""

from __future__ import annotations

from typing import Any

from focusblocks.platform.windows.com import com_init
from focusblocks.platform.windows.windows import exe_of_pid, window_pid


def _desk_label(d: Any) -> str:
    return (d.name or "").strip() or f"Desktop {d.number}"


class PyvdaDesktopMonitor:
    def current_desktop(self) -> str | None:
        """Name of the current virtual desktop ("Desktop 2" if unnamed); None if pyvda isn't available."""
        try:
            com_init()
            from pyvda import VirtualDesktop
            return _desk_label(VirtualDesktop.current())
        except Exception:
            return None


def list_desktops() -> list[dict[str, Any]]:
    """[{name, number, apps: [exe, ...], current}] for every virtual desktop."""
    try:
        com_init()
        from pyvda import VirtualDesktop, get_apps_by_z_order, get_virtual_desktops
        cur = VirtualDesktop.current().number
        apps: dict[int, list[str]] = {}
        try:
            for view in get_apps_by_z_order(current_desktop=False):
                try:
                    exe = exe_of_pid(window_pid(view.hwnd))
                    lst = apps.setdefault(view.desktop.number, [])
                    if exe and exe not in lst:
                        lst.append(exe)
                except Exception:
                    pass
        except Exception:
            pass
        return [dict(name=_desk_label(d), number=d.number, apps=apps.get(d.number, []),
                     current=d.number == cur) for d in get_virtual_desktops()]
    except Exception:
        return []


def pin_everywhere(win: Any) -> None:
    """Show a Tk window on every virtual desktop."""
    try:
        com_init()
        from pyvda import AppView
        AppView(hwnd=int(win.wm_frame(), 16)).pin()
    except Exception:
        pass
