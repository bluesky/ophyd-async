from ophyd_async.core import DatasetDescriber, NameProvider, PathProvider

from ._core_io import NDFileIO, NDPluginBaseIO
from ._core_writer import ADWriter


class ADTIFFWriter(ADWriter[NDFileIO]):
    default_suffix: str = "TIFF1:"

    def __init__(
        self,
        prefix,
        path_provider: PathProvider,
        name_provider: NameProvider,
        dataset_describer: DatasetDescriber,
        plugins: dict[str, NDPluginBaseIO] | None = None,
    ) -> None:
        super().__init__(
            prefix,
            path_provider,
            name_provider,
            dataset_describer,
            plugins=plugins,
            file_extension=".tiff",
            mimetype="multipart/related;type=image/tiff",
        )
        self.tiff = self.fileio
