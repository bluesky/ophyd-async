import atexit
from pathlib import Path
import tango

from ophyd_async.tango.testing import TangoSubprocessDeviceServer
from ._servers import DemoMotorDevice, DemoPointDetectorChannelDevice, DemoMultiChannelDetectorDevice

HERE = Path(__file__).absolute().parent


def start_device_server_subprocess(prefix: str, num_channels: int) -> TangoSubprocessDeviceServer:
    """Start an IOC subprocess for sample stage and sensor.

    :param prefix: The prefix for the IOC PVs.
    :param num_channels: The number of point detector channels to create.
    """
    devices = [
        {
            "class": DemoMotorDevice, "devices": [{"name": f"{prefix}/{suffix}", "properties": {"prop1": 12345}} for suffix in ["X", "Y"]]
        },
        {
            "class": DemoPointDetectorChannelDevice, "devices": [{"name": f"{prefix}/C{channel}", "properties": {"channel": channel}} for channel in range(1, num_channels+1)]
        },
        {
            "class": DemoMultiChannelDetectorDevice, "devices": [{"name": f"{prefix}/DET", "properties": {"channels": num_channels}}]
        }
    ]

    tango_server = TangoSubprocessDeviceServer(devices)
    tango_server.connect()

    channel_locators = []
    for channel in range(1, num_channels+1):
        device_name = f"{prefix}/C{channel}"
        # Now connect the channel devices to the motor devices
        device_proxy = tango.DeviceProxy(tango_server.trls[device_name])
        device_proxy.locator_x = tango_server.trls[f"{prefix}/X"]
        device_proxy.locator_y = tango_server.trls[f"{prefix}/Y"]
        device_proxy.connect_devices()
        channel_locators.append(tango_server.trls[device_name])

    # Connect the Detector device to its individual channels
    device_proxy = tango.DeviceProxy(tango_server.trls[f"{prefix}/DET"])
    device_proxy.locators = channel_locators
    device_proxy.connect_devices()


    # Equivalent of this call ?
#    atexit.register(ioc.stop)

    return tango_server
