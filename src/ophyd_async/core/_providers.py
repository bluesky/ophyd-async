from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass
class DirectoryInfo:
    directory_path: str
    filename_prefix: str


class DirectoryProvider(Protocol):
    @abstractmethod
    def __call__(self) -> DirectoryInfo:
        """Get the current directory to write files into"""


class StaticDirectoryProvider(DirectoryProvider):
    def __init__(self, directory_path: str, filename_prefix: str) -> None:
        self._directory_info = DirectoryInfo(directory_path, filename_prefix)

    def __call__(self) -> DirectoryInfo:
        return self._directory_info


class NameProvider(Protocol):
    @abstractmethod
    def __call__(self) -> str:
        """Get the name to be used as a data_key in the descriptor document"""


class ShapeProvider(Protocol):
    @abstractmethod
    async def __call__(self) -> Sequence[int]:
        """Get the shape of the data collection"""
