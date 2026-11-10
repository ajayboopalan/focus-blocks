from __future__ import annotations

import logging

from focusblocks import APP_NAME

log = logging.getLogger(__name__)


class ToastNotifier:
    """Logs every notification and shows it as a Windows toast."""

    def notify(self, title: str, msg: str) -> None:
        log.info("[%s] %s", title, msg)
        try:
            from winotify import Notification, audio
            n = Notification(app_id=APP_NAME, title=title, msg=msg or " ", duration="short")
            n.set_audio(audio.Default, loop=False)
            n.show()
        except Exception:
            pass
