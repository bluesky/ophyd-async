from collections.abc import Sequence

from ophyd_async.core import (
    Device,
    SignalR,
    SignalRW,
)
from ophyd_async.fastcs.odin import FrameProcessorVectorIO


class XspressFrameProcessorVectorIO(FrameProcessorVectorIO):
    """Implementation of a XspressFrameProcessor Odin Subdevice."""

    chunks: SignalRW[int]
    total_frames_written: SignalR[int]
    dataset_table: SignalR[Sequence[str]]


class XspressOdinIO(Device):
    file_path: SignalRW[str]
    file_prefix: SignalRW[str]
    writing: SignalR[bool]
    fp: XspressFrameProcessorVectorIO
