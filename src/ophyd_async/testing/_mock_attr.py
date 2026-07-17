from typing import TypeVar

from ophyd_async.core import Device

MockT = TypeVar("MockT")


def set_mock_attr(device: Device, attr: str, mock: MockT) -> MockT:
    """Override a Device attribute in a test, bypassing the reserved-name check.

    [](#Device) raises `NameError` if you assign to an attribute whose name
    collides with a bluesky protocol method (`set`, `read`, `trigger`, ...), to
    stop a Signal accidentally shadowing a verb. That guard gets in the way of the
    common test pattern of mocking out a verb, so use this to do it explicitly.

    Returns the `mock` it just set, so the override and the assertion can be a
    single expression.

    :param device: The Device to set the attribute on.
    :param attr: The attribute name to override, e.g. `"set"`.
    :param mock: The value to set it to, usually a mock. Returned unchanged.

    :example:
    ```python
    mock_set = set_mock_attr(motor, "set", MagicMock())
    await motor.kickoff()
    mock_set.assert_called_once_with(-3.0)
    ```
    """
    object.__setattr__(device, attr, mock)
    return mock
