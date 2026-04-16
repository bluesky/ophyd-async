from ophyd_async.core import (
    Device,
    DeviceVector,
    SignalR,
    SignalRW,
    SignalX,
)


class XspressFrameProcessorIO(Device):
    pass


class XspressFrameProcessorVectorIO(DeviceVector[XspressFrameProcessorIO]):
    """Ophyd-async implementation of a FrameProcessor Odin Subdevice."""

    start_writing: SignalX
    stop_writing: SignalX
    frames_written: SignalR[int]
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


class XspressOdinIO(Device):
    file_path: SignalRW[str]
    file_prefix: SignalRW[str]
    writing: SignalR[bool]
    fp: XspressFrameProcessorVectorIO
