import asyncio

import pytest
from tango.asyncio_executor import set_global_executor


@pytest.fixture
def event_loop():
    """Create a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    """Reset PyTango's cached asyncio executor before every system test, not
    just ones under `tango/`.

    PyTango's asyncio green-mode machinery (`tango.asyncio_executor`) caches
    one *global* executor bound to whichever event loop first asks for one.
    Any earlier test that connected a Tango client leaves that binding
    behind; a later test connecting from a *different* loop (a fresh
    per-test loop, or bluesky's own persistent background loop via
    `call_in_bluesky_event_loop`/the `RE` fixture) reuses the stale
    reference and fails with a raw `TypeError: ... can't be used in 'await'
    expression'` instead of actually connecting - see
    `test_tango_signal_lifecycle.py::test_retrieve_apply_store_settings`'s
    own inline comment for the first time this bit.

    Originally scoped to `tests/system_tests/tango/core/conftest.py` only,
    autoused for just that directory's own Tango-heavy tests. That was
    enough while Tango system tests ran in an isolated CI job/pytest
    session of their own - but `test_tutorials.py` (this directory, a
    sibling of `tango/`) also connects a Tango client
    (`ophyd_async.tango.demo.__main__`, via `call_in_bluesky_event_loop`),
    and once `tests/system_tests/tango` runs in the *same* pytest session
    as the rest of `tests/system_tests` (no longer its own dedicated CI
    job), `tango/core`'s tests collect first alphabetically and leave the
    executor bound to one of their own already-closed per-test loops -
    `test_tutorials.py`'s tango.demo case then fails exactly this way.
    Moved up here so every system test gets a clean executor regardless of
    what ran before it, Tango-touching or not (a no-op, and cheap, for
    tests that never touch Tango at all).
    """
    set_global_executor(None)
