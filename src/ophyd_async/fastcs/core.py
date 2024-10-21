from ophyd_async.core import Device, DeviceConnector
from ophyd_async.epics.core import PviDeviceConnector


def fastcs_connector(device: Device, uri: str) -> DeviceConnector:
    # TODO: add Tango support based on uri scheme
    connector = PviDeviceConnector(uri, uri + "PVI")
    connector.create_children_from_annotations(device)
    return connector
