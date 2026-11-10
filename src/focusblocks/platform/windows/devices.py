from __future__ import annotations

CONSENT_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


class RegistryDeviceMonitor:
    """Reads Windows' privacy registry (no device access, so it never disturbs a meeting)."""

    def device_in_use(self, kind: str) -> bool:
        """True if any app is using the 'webcam' or 'microphone' right now."""
        import winreg
        base = rf"{CONSENT_STORE}\{kind}"

        def scan(path: str) -> bool:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                return False
            with key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                    except OSError:
                        return False
                    i += 1
                    sub_path = rf"{path}\{sub}"
                    if sub == "NonPackaged":  # desktop apps live one level deeper
                        if scan(sub_path):
                            return True
                        continue
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_path) as k:
                            stop, _ = winreg.QueryValueEx(k, "LastUsedTimeStop")
                            if stop == 0:  # started and not yet stopped = in use
                                return True
                    except OSError:
                        pass

        try:
            return scan(base)
        except Exception:
            return False
