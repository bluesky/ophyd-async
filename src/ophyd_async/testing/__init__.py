"""Utilities for testing devices."""

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    # Only for static analysis (type checkers, ruff's __all__ check, IDE
    # autocomplete) - see _ASSERT_NAMES/__getattr__ below for why these aren't
    # imported for real up here.
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

# Names from _assert.py, imported lazily on first access (see __getattr__ below)
# rather than eagerly here. _assert.py needs `pytest`, a dev/test-only dependency
# of this package (unlike bluesky/event-model, which ophyd_async.core itself
# always needs regardless) - a backend test/demo server script like
# ophyd_async.tango.testing._tango_device_servers, run from a bare PyTango
# environment with a plain `pip install ophyd-async`, only needs the subprocess
# helpers above and shouldn't be forced to have pytest installed just because it
# lives in the same package as pytest-dependent assertion helpers.
_ASSERT_NAMES = frozenset(
    {
        "ApproxTable",
        "MonitorQueue",
        "StatusWatcher",
        "approx_value",
        "assert_configuration",
        "assert_describe_signal",
        "assert_emitted",
        "assert_has_calls",
        "assert_reading",
        "assert_value",
        "partial_reading",
    }
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
    if name in _ASSERT_NAMES:
        import pytest

        # So that bare asserts in _assert.py give a nice pytest traceback - must
        # happen before _assert is imported for the first time, which is why this
        # can't just be an eager `from . import __pytest_assert_rewrite` at the
        # top of this file any more.
        pytest.register_assert_rewrite("ophyd_async.testing._assert")
        from . import _assert

        value = getattr(_assert, name)
        globals()[name] = value  # cache: only pay the above cost once
        return value

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
