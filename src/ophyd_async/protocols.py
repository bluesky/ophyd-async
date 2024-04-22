from abc import abstractmethod
from typing import Dict, Protocol, runtime_checkable

from bluesky.protocols import Descriptor, HasName, Reading


@runtime_checkable
class AsyncReadable(HasName, Protocol):
    @abstractmethod
    async def read(self) -> Dict[str, Reading]:
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
    async def describe(self) -> Dict[str, Descriptor]:
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
class AsyncConfigurable(Protocol):
    @abstractmethod
    async def read_configuration(self) -> Dict[str, Reading]:
        """Same API as ``read`` but for slow-changing fields related to configuration.
        e.g., exposure time. These will typically be read only once per run.
        """
        ...

    @abstractmethod
    async def describe_configuration(self) -> Dict[str, Descriptor]:
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
