from enum import Enum
from typing import Type

from ophyd_async.core.signal import SignalR, SignalRW
from ophyd_async.core.utils import T
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw


def ad_rw(datatype: Type[T], prefix: str) -> SignalRW[T]:
    return epics_signal_rw(datatype, prefix + "_RBV", prefix)


def ad_r(datatype: Type[T], prefix: str) -> SignalR[T]:
    return epics_signal_r(datatype, prefix + "_RBV")


class FileWriteMode(str, Enum):
    single = "Single"
    capture = "Capture"
    stream = "Stream"


class ImageMode(Enum):
    single = "Single"
    multiple = "Multiple"
    continuous = "Continuous"
