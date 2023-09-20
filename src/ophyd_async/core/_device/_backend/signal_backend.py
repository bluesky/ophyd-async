from abc import abstractmethod
from typing import Generic, Optional, Type

from bluesky.protocols import Descriptor, Reading

from ...utils import ReadingValueCallback, T


class SignalBackend(Generic[T]):
    """A read/write/monitor backend for a Signals"""

    #: Datatype of the signal value
    datatype: Optional[Type[T]] = None

    #: Like ca://PV_PREFIX:SIGNAL
    source: str = ""

    @abstractmethod
    async def connect(self):
        """Connect to underlying hardware"""

    @abstractmethod
    async def put(self, value: Optional[T], wait=True, timeout=None):
        """Put a value to the PV, if wait then wait for completion for up to timeout"""

    @abstractmethod
    async def get_descriptor(self) -> Descriptor:
        """Metadata like source, dtype, shape, precision, units"""

    @abstractmethod
    async def get_reading(self) -> Reading:
        """The current value, timestamp and severity"""

    @abstractmethod
    async def get_value(self) -> T:
        """The current value"""

    @abstractmethod
    async def get_setpoint(self) -> T:
        """The current setpoint"""

    @abstractmethod
    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
        """Observe changes to the current value, timestamp and severity"""
