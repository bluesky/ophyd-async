from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ophyd_async.core import DEFAULT_TIMEOUT, SignalRW, T, wait_for_value
from ophyd_async.core.signal import SignalR


class FileWriteMode(str, Enum):
    single = "Single"
    capture = "Capture"
    stream = "Stream"


class ImageMode(str, Enum):
    single = "Single"
    multiple = "Multiple"
    continuous = "Continuous"


class NDAttributeDataType(str, Enum):
    INT = "INT"
    DOUBLE = "DOUBLE"
    STRING = "STRING"


@dataclass
class NDAttributePv:
    name: str  # name of attribute stamped on array, also scientifically useful name
    # when appended to device.name
    signal: SignalR  # caget the pv given by signal.source and attach to each frame
    datatype: Optional[NDAttributeDataType] = (
        None  # An override datatype, otherwise will use native EPICS type
    )
    description: str = ""  # A description that appears in the HDF file as an attribute


@dataclass
class NDAttributeParam:
    name: str  # name of attribute stamped on array, also scientifically useful name
    # when appended to device.name
    param: str  # The parameter string as seen in the INP link of the record
    datatype: NDAttributeDataType  # The datatype of the parameter
    addr: int = 0  # The address as seen in the INP link of the record
    description: str = ""  # A description that appears in the HDF file as an attribute


async def stop_busy_record(
    signal: SignalRW[T],
    value: T,
    timeout: float = DEFAULT_TIMEOUT,
    status_timeout: Optional[float] = None,
) -> None:
    await signal.set(value, wait=False, timeout=status_timeout)
    await wait_for_value(signal, value, timeout=timeout)
