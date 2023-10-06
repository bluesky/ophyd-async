"""Module which defines abstract classes to work with writers"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, TypeVar, Union

from bluesky.protocols import Descriptor
from event_model import StreamDatum, StreamResource


class DetectorWriter(ABC):
    @abstractmethod
    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        """Open writer and wait for it to be ready for data.

        Args:
            multiplier: Each StreamDatum index corresponds to this many
                written exposures

        Returns:
            Output for ``describe()``
        """

    @abstractmethod
    async def wait_for_index(self, index: int) -> None:
        """Wait until a specific index is ready to be collected"""

    @abstractmethod
    async def get_indices_written(self) -> int:
        """Get the number of indices written"""

    @abstractmethod
    async def reset_index(self) -> None:
        """Reset the index count."""

    @abstractmethod
    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[Union[StreamResource, StreamDatum]]:
        """Create Stream docs up to given number written"""

    @abstractmethod
    async def close(self) -> None:
        """Close writer and wait for it to be finished"""


D = TypeVar("D", bound=DetectorWriter)
