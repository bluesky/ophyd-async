"""Utilities for testing devices."""

from typing import Any

from ._one_of_everything import (
    ExampleEnum,
    ExampleSubsetEnum,
    ExampleSupersetEnum,
    ExampleTable,
    OneOfEverythingDevice,
    ParentOfEverythingDevice,
    float_array_value,
    int_array_value,
)
from ._single_derived import (
    BeamstopPosition,
    Exploder,
    MovableBeamstop,
    ReadOnlyBeamstop,
)
from ._subprocess import ManagedSubprocess, find_free_port, start_subprocess
from ._wait_for_pending import wait_for_pending_wakeups

try:
    # So that bare asserts in _assert.py give a nice pytest traceback - must
    # happen before _assert is imported for the first time, hence guarded and
    # done ahead of the `from ._assert import ...` below. pytest is a
    # dev/test-only dependency of this package (unlike bluesky/event-model,
    # which ophyd_async.core itself always needs regardless), so this - and
    # _assert.py's own `import pytest`s, deferred into just the handful of
    # functions that need it (see its own comment) - is what lets a backend
    # test/demo server script like
    # ophyd_async.tango.testing._tango_device_servers, run from a bare
    # PyTango environment with a plain `pip install ophyd-async`, import this
    # package without pytest installed. The `from ._assert import ...` below
    # is deliberately a real, unconditional, top-level import rather than a
    # lazily-loaded one (as it used to be, via `__getattr__`): sphinx-
    # autodoc2 statically resolves `__all__` by looking only at a module's
    # direct top-level import statements - it doesn't see inside `if`/`try`
    # blocks at all - so a conditional/lazy import here made every assert
    # helper "unknown" to the docs build.
    from . import __pytest_assert_rewrite  # noqa: F401
except ImportError:
    pass

from ._assert import (
    ApproxTable,
    MonitorQueue,
    StatusWatcher,
    approx_value,
    assert_configuration,
    assert_describe_signal,
    assert_emitted,
    assert_has_calls,
    assert_reading,
    assert_value,
    partial_reading,
)

# Back compat - delete before 1.0
_MOVED_TO_CORE = frozenset(
    {
        "callback_on_mock_put",
        "get_mock",
        "get_mock_put",
        "mock_puts_blocked",
        "set_mock_put_proceeds",
        "set_mock_value",
        "set_mock_values",
    }
)


def __getattr__(name: str) -> Any:
    if name in _MOVED_TO_CORE:
        import warnings

        import ophyd_async.core

        warnings.warn(
            DeprecationWarning(
                f"ophyd_async.testing.{name} has moved to ophyd_async.core"
            ),
            stacklevel=2,
        )
        return getattr(ophyd_async.core, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# The order of this list determines the order of the documentation,
# so does not match the alphabetical order of the imports
__all__ = [
    "approx_value",
    # Assert functions
    "assert_value",
    "assert_reading",
    "assert_configuration",
    "assert_describe_signal",
    "assert_emitted",
    "partial_reading",
    # Wait for pending wakeups
    "wait_for_pending_wakeups",
    # Subprocess management for backend test/demo servers
    "ManagedSubprocess",
    "find_free_port",
    "start_subprocess",
    "ExampleEnum",
    "ExampleSubsetEnum",
    "ExampleSupersetEnum",
    "ExampleTable",
    "OneOfEverythingDevice",
    "ParentOfEverythingDevice",
    "MonitorQueue",
    "ApproxTable",
    "StatusWatcher",
    "int_array_value",
    "float_array_value",
    # Derived examples
    "BeamstopPosition",
    "Exploder",
    "MovableBeamstop",
    "ReadOnlyBeamstop",
    "assert_has_calls",
]
