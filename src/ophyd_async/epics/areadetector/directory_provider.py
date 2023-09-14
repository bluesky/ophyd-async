import tempfile
from abc import abstractmethod
from pathlib import Path
from typing import Protocol


class DirectoryProvider(Protocol):
    @abstractmethod
    async def get_directory(self) -> Path:
        ...


class TmpDirectoryProvider(DirectoryProvider):
    def __init__(self) -> None:
        self._directory = Path(tempfile.mkdtemp())

    async def get_directory(self) -> Path:
        return self._directory
