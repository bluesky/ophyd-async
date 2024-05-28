from abc import abstractmethod
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Dict,
    FrozenSet,
    Generic,
    Literal,
    Optional,
    Type,
)

from bluesky.protocols import DataKey, Reading

from .utils import DEFAULT_TIMEOUT, ReadingValueCallback, T


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


if TYPE_CHECKING:
    RuntimeEnum = Literal
else:

    class _RuntimeEnumMeta(type):
        # Intentionally immutable class variable
        __enum_classes_created: Dict[FrozenSet[str], Type["RuntimeEnum"]] = {}

        def __str__(cls):
            if hasattr(cls, "choices"):
                return f"RuntimeEnum{list(cls.choices)}"
            return "RuntimeEnum"

        def __getitem__(cls, choices):
            if isinstance(choices, str):
                choices = (choices,)
            else:
                if not isinstance(choices, tuple) or not all(
                    isinstance(c, str) for c in choices
                ):
                    raise TypeError(
                        f"Choices must be a str or a tuple of str, not {choices}."
                    )
                if len(set(choices)) != len(choices):
                    raise TypeError("Duplicate elements in runtime enum choices.")

            default_choice_local = choices[0]
            choices_frozenset = frozenset(choices)

            # If the enum has already been created, return it (ignoring order)
            if choices_frozenset in _RuntimeEnumMeta.__enum_classes_created:
                return _RuntimeEnumMeta.__enum_classes_created[choices_frozenset]

            # Create a new enum subclass
            class _RuntimeEnum(cls):
                choices = choices_frozenset
                default_choice = default_choice_local

            _RuntimeEnumMeta.__enum_classes_created[choices_frozenset] = _RuntimeEnum
            return _RuntimeEnum

    class RuntimeEnum(metaclass=_RuntimeEnumMeta):
        choices: ClassVar[FrozenSet[str]]
        default_choice: ClassVar[str]

        def __init__(self):
            raise RuntimeError("RuntimeEnum cannot be instantiated")
