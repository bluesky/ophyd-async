from ophyd_async.core import DatasetDescriber, NameProvider, PathProvider

from ._core_io import NDFileIO
from ._core_writer import ADWriter


class ADTIFFWriter(ADWriter):
    def __init__(
        self,
        fileio: NDFileIO,
        path_provider: PathProvider,
        name_provider: NameProvider,
        dataset_describer: DatasetDescriber,
    ) -> None:
        super().__init__(
            fileio,
            path_provider,
            name_provider,
            dataset_describer,
            ".tiff",
            "multipart/related;type=image/tiff",
        )
        self.tiff = self.fileio
