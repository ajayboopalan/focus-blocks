import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex")


def test_second_lock_on_same_folder_is_refused(tmp_path):
    from focusblocks.platform.windows import SingleInstanceLock

    first, second = SingleInstanceLock(tmp_path), SingleInstanceLock(tmp_path)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
        second.release()


def test_different_folders_do_not_block_each_other(tmp_path):
    from focusblocks.platform.windows import SingleInstanceLock

    a, b = SingleInstanceLock(tmp_path / "a"), SingleInstanceLock(tmp_path / uuid.uuid4().hex)
    try:
        assert a.acquire() is True
        assert b.acquire() is True
    finally:
        a.release()
        b.release()


def test_lock_is_free_again_after_release(tmp_path):
    from focusblocks.platform.windows import SingleInstanceLock

    first = SingleInstanceLock(tmp_path)
    assert first.acquire() is True
    first.release()
    again = SingleInstanceLock(tmp_path)
    try:
        assert again.acquire() is True
    finally:
        again.release()
