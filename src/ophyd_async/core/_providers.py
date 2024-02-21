from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Sequence, Union


@dataclass
class DirectoryInfo:
    """
    Information about where and how to write a file.


    :param root: Path of a root directory
    :param resource_dir: Directory into which files should be written, relative to root
    :param prefix: Optional filename prefix to add to all files
    :param suffix: Optional filename suffix to add to all files
    """

    root: Path
    resource_dir: Path
    prefix: Optional[str] = ""
    suffix: Optional[str] = ""


class DirectoryProvider(Protocol):
    @abstractmethod
    def __call__(self) -> DirectoryInfo:
        """Get the current directory to write files into"""


class StaticDirectoryProvider(DirectoryProvider):
    def __init__(
        self,
        directory_path: Union[str, Path],
        filename_prefix: str = "",
        filename_suffix: str = "",
    ) -> None:
        if isinstance(directory_path, str):
            directory_path = Path(directory_path)
        self._directory_info = DirectoryInfo(
            root=directory_path,
            resource_dir=Path("."),
            prefix=filename_prefix,
            suffix=filename_suffix,
        )

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
