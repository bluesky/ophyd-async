"""Mock implementations for EPICS motor devices."""

from ophyd_async.core import DeviceMock, default_device_mock_for_class
from ophyd_async.epics.motor import Motor
from ophyd_async.testing import callback_on_mock_put, set_mock_value

__all__ = ["InstantMotorMock"]


@default_device_mock_for_class
class InstantMotorMock(DeviceMock[Motor]):
    """A mock for Motor that instantly moves to the setpoint.

    This example demonstrates how to use the @default_device_mock_for_class
    decorator to automatically inject mock behavior when a Motor is connected
    in mock mode.

    When registered, this mock will automatically be used when connecting
    a Motor with mock=True, eliminating the need for manual callback setup.
    """

    async def connect(self, device: Motor) -> None:
        """Inject instant movement logic into the motor mock.

        This method is called automatically when a Motor is connected in mock mode.
        It sets up sensible default values to prevent errors and configures the
        motor to instantly complete moves when the user_setpoint is written.

        Default values can be overridden per test using set_mock_value.
        """
        # Set sensible defaults to avoid runtime errors
        set_mock_value(device.velocity, 1.0)  # Prevent ZeroDivisionError
        set_mock_value(device.acceleration_time, 0.1)

        # Set generous limits (EPICS treats dial limits of 0,0 as no limit)
        # Use large but not infinite values to avoid unexpected behavior
        set_mock_value(device.low_limit_travel, -10000.0)
        set_mock_value(device.high_limit_travel, 10000.0)

        # Set dial limits to match user limits
        set_mock_value(device.dial_low_limit_travel, -10000.0)
        set_mock_value(device.dial_high_limit_travel, 10000.0)

        # Motor starts in "done" state (not moving)
        set_mock_value(device.motor_done_move, 1)

        # When setpoint is written to, immediately update readback and done flag
        def _instant_move(value, wait):
            set_mock_value(device.motor_done_move, 0)  # Moving
            set_mock_value(device.user_readback, value)  # Arrive instantly
            set_mock_value(device.motor_done_move, 1)  # Done

        callback_on_mock_put(device.user_setpoint, _instant_move)
