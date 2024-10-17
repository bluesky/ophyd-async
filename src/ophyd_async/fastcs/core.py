from ophyd_async.core import Device, DeviceConnector
from ophyd_async.epics.pvi import PviDeviceConnector


def fastcs_connector(device: Device, uri: str) -> DeviceConnector:
    connector = PviDeviceConnector(uri + "PVI")
    connector.create_children_from_annotations(device)
    return connector
