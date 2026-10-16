"""Tests that need IOCs running in containers.

Separate from tests/system_tests, and run as their own pytest invocation, because
they need a process that has never touched EPICS. They reach their IOC through
the ca-gateway, which needs `EPICS_CA_NAME_SERVERS`, and the EPICS client
libraries read that once, when libca initialises. Importing anything that pulls
in pyepics - `from ophyd.signal import EpicsSignal`, in the epics/core system
tests - initialises libca during *collection*, before any fixture can set it, and
these tests then cannot find their IOC at all.

Sharing a session with those tests breaks these, in either order.
`@pytest.mark.insubprocess` also gives the isolation, by running each marked test
in a pytest session of its own, and is what these tests used to rely on. It costs
an IOC start per test, though: as marked tests they were the two slowest in the
whole system-test job, 44.6s of its 116.8s, against ~15s for both together here,
where one module-scoped IOC serves them. Splitting by invocation buys the same
isolation once per module rather than once per test, so it is what the "Run
container tests" step in .github/workflows/_test.yml does.
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
