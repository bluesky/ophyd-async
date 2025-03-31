from __future__ import annotations

from abc import abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Protocol,
    TypeVar,
    runtime_checkable,
)

from bluesky.protocols import HasName, Location, Reading, T_co
from event_model import DataKey

from ._utils import T

if TYPE_CHECKING:
    from ._status import AsyncStatus


@runtime_checkable
class AsyncReadable(HasName, Protocol):
    """Async implementations of the sync [](#bluesky.protocols.Readable)."""

    @abstractmethod
    async def read(self) -> dict[str, Reading]:
        """Return value, timestamp, optional per-point metadata for each field name.

        For example:

            {
                "channel1": {"value": 5, "timestamp": 1472493713.271991},
                "channel2": {"value": 16, "timestamp": 1472493713.539238},
            }
        """

    @abstractmethod
    async def describe(self) -> dict[str, DataKey]:
        """Return per-scan metadata for each field name in `read()`.

        For example:

            {
                "channel1": {"source": "SOME_PV1", "dtype": "number", "shape": []},
                "channel2": {"source": "SOME_PV2", "dtype": "number", "shape": []},
            }
        """


@runtime_checkable
class AsyncConfigurable(HasName, Protocol):
    """Async implementation of the sync [](#bluesky.protocols.Configurable)."""

    @abstractmethod
    async def read_configuration(self) -> dict[str, Reading]:
        """Return value, timestamp, optional per-point metadata for each field name.

        Same API as [](#AsyncReadable.read) but for slow-changing fields related to
        configuration. e.g., exposure time. These will typically be read only
        once per run.
        """

    @abstractmethod
    async def describe_configuration(self) -> dict[str, DataKey]:
        """Return per-scan metadata for each field name in `read_configuration()`."""


@runtime_checkable
class AsyncPausable(Protocol):
    """Async implementation of the sync [](#bluesky.protocols.Pausable)."""

    @abstractmethod
    async def pause(self) -> None:
        """Perform device-specific work when the RunEngine pauses."""

    @abstractmethod
    async def resume(self) -> None:
        """Perform device-specific work when the RunEngine resumes after a pause."""


@runtime_checkable
class AsyncStageable(Protocol):
    """Async implementation of the sync [](#bluesky.protocols.Stageable)."""

    @abstractmethod
    def stage(self) -> AsyncStatus:
        """Set up the device for acquisition.

        :return: An `AsyncStatus` that is marked done when the device is done staging.
        """

    @abstractmethod
    def unstage(self) -> AsyncStatus:
        """Clean up the device after acquisition.

        :return: An `AsyncStatus` that is marked done when the device is done unstaging.
        """


@runtime_checkable
class AsyncMovable(Protocol[T_co]):
    @abstractmethod
    def set(self, value: T_co) -> AsyncStatus:
        """Return a ``Status`` that is marked done when the device is done moving."""


@runtime_checkable
class AsyncLocatable(AsyncMovable[T], Protocol):
    @abstractmethod
    async def locate(self) -> Location[T]:
        """Return the current location of a Device.

        While a ``Readable`` reports many values, a ``Movable`` will have the
        concept of location. This is where the Device currently is, and where it
        was last requested to move to. This protocol formalizes how to get the
        location from a ``Movable``.
        """


C = TypeVar("C", contravariant=True)


class Watcher(Protocol, Generic[C]):
    """Protocol for watching changes in values."""

    def __call__(
        self,
        current: C | None = None,
        initial: C | None = None,
        target: C | None = None,
        name: str | None = None,
        unit: str | None = None,
        precision: int | None = None,
        fraction: float | None = None,
        time_elapsed: float | None = None,
        time_remaining: float | None = None,
    ) -> Any: ...
