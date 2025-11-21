"""Utilities for testing devices."""

from . import __pytest_assert_rewrite  # noqa: F401
from ._assert import (
    ApproxTable,
    MonitorQueue,
    StatusWatcher,
    approx_value,
    assert_configuration,
    assert_describe_signal,
    assert_emitted,
    assert_reading,
    assert_value,
    partial_reading,
)
from ._one_of_everything import (
    ExampleEnum,
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
from ._wait_for_pending import wait_for_pending_wakeups


# Back compat - delete before 1.0
def __getattr__(name):
    import warnings

    import ophyd_async.core

    moved_to_core = {
        "callback_on_mock_put",
        "get_mock",
        "get_mock_put",
        "mock_puts_blocked",
        "set_mock_put_proceeds",
        "set_mock_value",
        "set_mock_values",
    }
    if name in moved_to_core:
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
    "ExampleEnum",
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
]
