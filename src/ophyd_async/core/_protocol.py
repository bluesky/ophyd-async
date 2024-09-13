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

from bluesky.protocols import HasName, Reading
from event_model import DataKey

if TYPE_CHECKING:
    from ._status import AsyncStatus


@runtime_checkable
class AsyncReadable(HasName, Protocol):
    @abstractmethod
    async def read(self) -> dict[str, Reading]:
        """Return an OrderedDict mapping string field name(s) to dictionaries
        of values and timestamps and optional per-point metadata.

        Example return value:

        .. code-block:: python

            OrderedDict(('channel1',
                         {'value': 5, 'timestamp': 1472493713.271991}),
                         ('channel2',
                         {'value': 16, 'timestamp': 1472493713.539238}))
        """
        ...

    @abstractmethod
    async def describe(self) -> dict[str, DataKey]:
        """Return an OrderedDict with exactly the same keys as the ``read``
        method, here mapped to per-scan metadata about each field.

        Example return value:

        .. code-block:: python

            OrderedDict(('channel1',
                         {'source': 'XF23-ID:SOME_PV_NAME',
                          'dtype': 'number',
                          'shape': []}),
                        ('channel2',
                         {'source': 'XF23-ID:SOME_PV_NAME',
                          'dtype': 'number',
                          'shape': []}))
        """
        ...


@runtime_checkable
class AsyncConfigurable(HasName, Protocol):
    @abstractmethod
    async def read_configuration(self) -> dict[str, Reading]:
        """Same API as ``read`` but for slow-changing fields related to configuration.
        e.g., exposure time. These will typically be read only once per run.
        """
        ...

    @abstractmethod
    async def describe_configuration(self) -> dict[str, DataKey]:
        """Same API as ``describe``, but corresponding to the keys in
        ``read_configuration``.
        """
        ...


@runtime_checkable
class AsyncPausable(Protocol):
    @abstractmethod
    async def pause(self) -> None:
        """Perform device-specific work when the RunEngine pauses."""
        ...

    @abstractmethod
    async def resume(self) -> None:
        """Perform device-specific work when the RunEngine resumes after a pause."""
        ...


@runtime_checkable
class AsyncStageable(Protocol):
    @abstractmethod
    def stage(self) -> AsyncStatus:
        """An optional hook for "setting up" the device for acquisition.

        It should return a ``Status`` that is marked done when the device is
        done staging.
        """
        ...

    @abstractmethod
    def unstage(self) -> AsyncStatus:
        """A hook for "cleaning up" the device after acquisition.

        It should return a ``Status`` that is marked done when the device is finished
        unstaging.
        """
        ...


C = TypeVar("C", contravariant=True)


class Watcher(Protocol, Generic[C]):
    @staticmethod
    def __call__(
        *,
        current: C,
        initial: C,
        target: C,
        name: str | None,
        unit: str | None,
        precision: float | None,
        fraction: float | None,
        time_elapsed: float | None,
        time_remaining: float | None,
    ) -> Any: ...
