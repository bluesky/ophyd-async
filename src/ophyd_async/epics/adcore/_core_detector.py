from collections.abc import Sequence
from typing import Generic, TypeVar

from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.core._detector import DetectorControllerT
from ophyd_async.core._signal import SignalR

from ._core_io import ADBaseIO, NDFileHDFIO, NDFileIO, NDPluginBaseIO
from ._core_logic import ADBaseDatasetDescriber
from ._hdf_writer import ADHDFWriter
from ._tiff_writer import ADTIFFWriter

ADBaseIOT = TypeVar("ADBaseIOT", bound=ADBaseIO)
NDFileIOT = TypeVar("NDFileIOT", bound=NDFileIO)
NDPluginBaseIOT = TypeVar("NDPluginBaseIOT", bound=NDPluginBaseIO)


class AreaDetector(
    Generic[ADBaseIOT, NDFileIOT, DetectorControllerT],
    StandardDetector[DetectorControllerT],
):
    def __init__(
        self,
        drv: ADBaseIOT,
        controller: DetectorControllerT,
        fileio: NDFileIOT,
        path_provider: PathProvider,
        plugins: dict[str, NDPluginBaseIO],
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        self.drv = drv
        self.fileio = fileio
        for name, plugin in plugins.items():
            setattr(self, name, plugin)

        def name_provider():
            return self.name

        if isinstance(fileio, NDFileHDFIO):
            writer = ADHDFWriter(
                fileio,
                path_provider,
                name_provider,
                ADBaseDatasetDescriber(drv),
                *plugins.values(),
            )
        else:
            writer = ADTIFFWriter(
                fileio, path_provider, name_provider, ADBaseDatasetDescriber(drv)
            )
        super().__init__(controller, writer, config_sigs, name)

    def get_plugin(
        self, name: str, plugin_type: type[NDPluginBaseIOT] = NDPluginBaseIO
    ) -> NDPluginBaseIOT:
        plugin = getattr(self, name, None)
        if not isinstance(plugin, plugin_type):
            raise TypeError(
                f"Expected {self.name}.{name} to be a {plugin_type}, got {plugin}"
            )
        return plugin
