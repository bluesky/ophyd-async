from ophyd_async.core import Device, DeviceVector, SignalR, SignalRW, TriggerableCommand

# from ophyd_async.fastcs.odin import FrameProcessorIO


class XspressListFrameProcessorIO(Device):
    """Custom class for List mode as we can't subclass original FrameProcessorIO."""


class XspressFrameProcessorListVectorIO(DeviceVector[XspressListFrameProcessorIO]):
    """Implementation of a XspressFrameProcessor Odin Subdevice."""

    time_frames: SignalRW[int]
    total_frames_written: SignalR[int]
    start_writing: TriggerableCommand
    stop_writing: TriggerableCommand
    writing: SignalR[bool]
    file_path: SignalRW[str]
    file_prefix: SignalRW[str]


class XspressOdinListIO(Device):
    file_path: SignalRW[str]
    file_prefix: SignalRW[str]
    writing: SignalR[bool]
    fp: XspressFrameProcessorListVectorIO
