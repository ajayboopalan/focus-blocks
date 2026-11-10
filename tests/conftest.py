import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakes import Harness, make_harness


@pytest.fixture
def h() -> Harness:
    """Engine with short timings: 2-min blocks, 1-min breaks, Work desktop is the work source."""
    return make_harness(block_minutes=2, break_minutes=1, daily_goal=3, abandon_minutes=1,
                        nudge_minutes=1)
