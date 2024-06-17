from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Sequence, Union


@dataclass
class DirectoryInfo:
    """
    Information about where and how to write a file.

    The bluesky event model splits the URI for a resource into two segments to aid in
    different applications mounting filesystems at different mount points.
    The portion of this path which is relevant only for the writer is the 'root',
    while the path from an agreed upon mutual mounting is the resource_path.
    The resource_dir is used with the filename to construct the resource_path.

    :param root: Path of a root directory, relevant only for the file writer
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
        resource_dir: Optional[Path] = None,
    ) -> None:
        if resource_dir is None:
            resource_dir = Path(".")
        if isinstance(directory_path, str):
            directory_path = Path(directory_path)
        self._directory_info = DirectoryInfo(
            root=directory_path.resolve(),
            resource_dir=resource_dir,
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
