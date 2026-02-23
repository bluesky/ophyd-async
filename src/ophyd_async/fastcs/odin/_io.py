from ophyd_async.core import Device, SignalR, SignalRW, SignalX


class MetaWriterIO(Device):
    """Ophyd-async implementation of a MetaWriter Odin Subdevice."""

    stop: SignalX
    file_prefix: SignalRW[str]
    directory: SignalRW[str]
    acquisition_id: SignalRW[str]
    writing: SignalR[bool]


class FrameProcessorIO(Device):
    """Ophyd-async implementation of a FrameProcessor Odin Subdevice."""

    start_writing: SignalX
    stop_writing: SignalX
    writing: SignalR[bool]
    frames_written: SignalR[int]
    frames: SignalRW[int]
    data_dims_0: SignalRW[int]
    data_dims_1: SignalRW[int]
    data_chunks_0: SignalRW[int]
    data_chunks_1: SignalRW[int]
    data_chunks_2: SignalRW[int]
    file_path: SignalRW[str]
    file_prefix: SignalRW[str]
    data_datatype: SignalRW[str]
    data_compression: SignalRW[str]
    process_frames_per_block: SignalRW[int]


class OdinIO(Device):
    fp: FrameProcessorIO
    mw: MetaWriterIO
