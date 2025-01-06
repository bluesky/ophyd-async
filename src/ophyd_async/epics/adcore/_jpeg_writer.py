from ophyd_async.core import DatasetDescriber, NameProvider, PathProvider

from ._core_io import NDFileIO, NDPluginBaseIO
from ._core_writer import ADWriter


class ADJPEGWriter(ADWriter[NDFileIO]):
    default_suffix: str = "JPEG1:"

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
            file_extension=".jpg",
            mimetype="multipart/related;type=image/jpeg",
        )
        self.jpeg = self.fileio
