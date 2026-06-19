from ophyd_async.core import (
    Device,
    DeviceVector,
    SignalR,
    SignalRW,
    TriggerableCommand,
)


class XspressFrameProcessorIO(Device):
    pass


class XspressFrameProcessorVectorIO(DeviceVector[XspressFrameProcessorIO]):
    """Implementation of a XspressFrameProcessor Odin Subdevice."""

    start_writing: TriggerableCommand
    stop_writing: TriggerableCommand
    frames: SignalRW[int]
    data_dims_0: SignalRW[int]
    data_dims_1: SignalRW[int]
    data_chunks_0: SignalRW[int]
    data_chunks_1: SignalRW[int]
    data_chunks_2: SignalRW[int]
    data_datatype: SignalRW[str]
    data_compression: SignalRW[str]
    process_frames_per_block: SignalRW[int]
    chunks: SignalRW[int]
    total_frames_written: SignalR[int]


class XspressOdinIO(Device):
    file_path: SignalRW[str]
    file_prefix: SignalRW[str]
    writing: SignalR[bool]
    fp: XspressFrameProcessorVectorIO
