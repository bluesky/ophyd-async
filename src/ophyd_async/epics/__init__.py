"""EPICS support for Signals, and Devices that use them."""

# Auto-register InstantMotorMock so tests don't need explicit imports
from ophyd_async.epics.testing import InstantMotorMock  # noqa: F401

__all__ = ["InstantMotorMock"]
