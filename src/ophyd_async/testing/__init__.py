"""Utilities for testing devices."""

from typing import Any

# So that bare asserts in _assert.py give a nice pytest traceback - must
# happen before _assert is imported for the first time, hence done ahead of
# the `from ._assert import ...` below. pytest is a real dependency of this
# package now: it's in the "demo" extra (ophyd_async.epics.demo/
# ophyd_async.tango.demo's tutorial __main__s use this package to spin up a
# fake IOC/device servers to demo against - same as real tests), as well as
# every dev/test install, so there's no "must work without pytest" case left
# to guard against here.
from . import __pytest_assert_rewrite  # noqa: F401
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
