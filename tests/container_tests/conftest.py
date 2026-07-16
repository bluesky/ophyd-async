"""Tests that need IOCs running in containers.

Separate from tests/system_tests, and run as their own pytest invocation, because
they need a process that has never touched EPICS. They reach their IOC through
the ca-gateway, which needs `EPICS_CA_NAME_SERVERS`, and the EPICS client
libraries read that once, when libca initialises. Importing anything that pulls
in pyepics - `from ophyd.signal import EpicsSignal`, in the epics/core system
tests - initialises libca during *collection*, before any fixture can set it, and
these tests then cannot find their IOC at all.

Sharing a session with those tests breaks these, in either order. Running them
under `@pytest.mark.insubprocess` works for these tests but breaks two of the
epics/core ones instead, so the split is by invocation: see the "Run container
tests" step in .github/workflows/_test.yml.
"""

import asyncio

import pytest


@pytest.fixture
def event_loop():
    """Create a fresh event loop for each test.

    Duplicated from tests/system_tests/conftest.py rather than shared: these
    tests deliberately do not sit under that directory, and it is 4 lines.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
