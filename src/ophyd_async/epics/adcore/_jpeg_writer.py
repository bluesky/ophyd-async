from ophyd_async.core import DatasetDescriber, PathProvider

from ._core_io import NDArrayBaseIO, NDFilePluginIO
from ._core_writer import ADWriter


class ADJPEGWriter(ADWriter[NDFilePluginIO]):
    default_suffix: str = "JPEG1:"

    def __init__(
        self,
        fileio: NDFilePluginIO,
        path_provider: PathProvider,
        dataset_describer: DatasetDescriber,
        plugins: dict[str, NDArrayBaseIO] | None = None,
    ) -> None:
        super().__init__(
            fileio,
            path_provider,
            dataset_describer,
            plugins=plugins,
            file_extension=".jpg",
            mimetype="multipart/related;type=image/jpeg",
        )
