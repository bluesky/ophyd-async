"""FastCS core module for ophyd-async."""

from ophyd_async.core import Device, DeviceConnector
from ophyd_async.epics.core import PviDeviceConnector


def fastcs_connector(
    uri: str, device: Device | None = None, error_hint: str = ""
) -> DeviceConnector:
    """Create devices and connections on pvi device `Device`."""
    # TODO: add Tango support based on uri scheme
    connector = PviDeviceConnector(uri, error_hint)
    if device:
        connector.create_children_from_annotations(device)
    return connector


__all__ = ["fastcs_connector"]
