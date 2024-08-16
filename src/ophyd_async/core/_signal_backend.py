from abc import ABC, abstractmethod
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Generic,
    Literal,
    Optional,
    Tuple,
    Type,
)

from ._protocol import DataKey, Reading
from ._utils import DEFAULT_TIMEOUT, ReadingValueCallback, T


class ProtocolDatatypeAbstraction(ABC, Generic[T]):
    @abstractmethod
    def __init__(self):
        """The abstract datatype must be able to be intialized with no arguments."""

    @abstractmethod
    def convert_to_protocol_datatype(self) -> T:
        """
        Convert the abstract datatype to a form which can be sent
        over whichever protocol.

        This output will be used when the device is serialized.
        """

    @classmethod
    @abstractmethod
    def convert_from_protocol_datatype(cls, value: T) -> "ProtocolDatatypeAbstraction":
        """
        Convert the datatype received from the protocol to a
        higher level abstract datatype.
        """


class BackendConverterFactory(ABC):
    """Convert between the signal backend and the signal type"""

    _ALLOWED_TYPES: ClassVar[Tuple[Type]]

    @classmethod
    @abstractmethod
    def datatype_allowed(cls, datatype: Type) -> bool:
        """Check if the datatype is allowed."""

    @classmethod
    @abstractmethod
    def make_converter(self, datatype: Type):
        """Updates the object with callables `to_signal` and `from_signal`."""


class SignalBackend(Generic[T]):
    """A read/write/monitor backend for a Signals"""

    #: Datatype of the signal value
    datatype: Optional[Type[T]] = None

    #: Like ca://PV_PREFIX:SIGNAL
    @abstractmethod
    def source(self, name: str) -> str:
        """Return source of signal. Signals may pass a name to the backend, which can be
        used or discarded."""

    @abstractmethod
    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        """Connect to underlying hardware"""

    @abstractmethod
    async def put(self, value: Optional[T], wait=True, timeout=None):
        """Put a value to the PV, if wait then wait for completion for up to timeout"""

    @abstractmethod
    async def get_datakey(self, source: str) -> DataKey:
        """Metadata like source, dtype, shape, precision, units"""

    @abstractmethod
    async def get_reading(self) -> Reading:
        """The current value, timestamp and severity"""

    @abstractmethod
    async def get_value(self) -> T:
        """The current value"""

    @abstractmethod
    async def get_setpoint(self) -> T:
        """The point that a signal was requested to move to."""

    @abstractmethod
    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
        """Observe changes to the current value, timestamp and severity"""


class _RuntimeSubsetEnumMeta(type):
    def __str__(cls):
        if hasattr(cls, "choices"):
            return f"SubsetEnum{list(cls.choices)}"
        return "SubsetEnum"

    def __getitem__(cls, _choices):
        if isinstance(_choices, str):
            _choices = (_choices,)
        else:
            if not isinstance(_choices, tuple) or not all(
                isinstance(c, str) for c in _choices
            ):
                raise TypeError(
                    "Choices must be a str or a tuple of str, " f"not {type(_choices)}."
                )
            if len(set(_choices)) != len(_choices):
                raise TypeError("Duplicate elements in runtime enum choices.")

        class _RuntimeSubsetEnum(cls):
            choices = _choices

        return _RuntimeSubsetEnum


class RuntimeSubsetEnum(metaclass=_RuntimeSubsetEnumMeta):
    choices: ClassVar[Tuple[str, ...]]

    def __init__(self):
        raise RuntimeError("SubsetEnum cannot be instantiated")


if TYPE_CHECKING:
    SubsetEnum = Literal
else:
    SubsetEnum = RuntimeSubsetEnum
