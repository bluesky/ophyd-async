from abc import abstractmethod
from typing import Generic, Optional, Type

from bluesky.protocols import Descriptor, Reading

from .utils import DEFAULT_TIMEOUT, R, ReadingValueCallback, W


class SignalBackend(Generic[R, W]):
    """A read/write/monitor backend for a Signals"""

    #: Datatype of the read signal value
    read_datatype: Optional[Type[R]] = None
    #: Datatype of the write signal value
    write_datatype: Optional[Type[W]] = None

    #: Like ca://PV_PREFIX:SIGNAL
    @abstractmethod
    def source(name: str) -> str:
        """Return source of signal. Signals may pass a name to the backend, which can be
        used or discarded."""

    @abstractmethod
    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        """Connect to underlying hardware"""

    @abstractmethod
    async def put(self, value: Optional[W], wait=True, timeout=None):
        """Put a value to the PV, if wait then wait for completion for up to timeout"""

    @abstractmethod
    async def get_descriptor(self, source: str) -> Descriptor:
        """Metadata like source, dtype, shape, precision, units"""

    @abstractmethod
    async def get_reading(self) -> Reading:
        """The current value, timestamp and severity"""

    @abstractmethod
    async def get_value(self) -> R:
        """The current value"""

    @abstractmethod
    async def get_setpoint(self) -> R:
        """The point that a signal was requested to move to."""

    @abstractmethod
    def set_callback(self, callback: Optional[ReadingValueCallback[R]]) -> None:
        """Observe changes to the current value, timestamp and severity"""
