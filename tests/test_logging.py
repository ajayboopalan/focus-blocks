import logging

import pytest

from focusblocks.logging_setup import configure_logging


@pytest.fixture
def clean_logger():
    root = logging.getLogger("focusblocks")
    saved = root.handlers[:]
    root.handlers.clear()
    yield root
    for handler in root.handlers:
        handler.close()
    root.handlers[:] = saved


def test_log_file_is_written_without_a_console(clean_logger, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stderr", None)    # like focusblocksw / pythonw
    log_file = tmp_path / "focusblocks.log"
    configure_logging(log_file=log_file)
    logging.getLogger("focusblocks.core.engine").warning("tick failed")
    for handler in clean_logger.handlers:
        handler.flush()
    assert "tick failed" in log_file.read_text(encoding="utf-8")
