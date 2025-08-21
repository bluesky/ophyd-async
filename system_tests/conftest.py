import pytest
from bluesky.run_engine import RunEngine


@pytest.fixture
def RE():
    RE = RunEngine(call_returns_result=True)
    yield RE
    if RE.state not in ("idle", "panicked"):
        RE.halt()
