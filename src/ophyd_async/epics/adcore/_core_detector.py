from typing import Sequence, cast
from ophyd_async.core import StandardDetector
from ophyd_async.core import PathProvider
from ophyd_async.core import SignalR

from bluesky.protocols import HasHints, Hints

from ._core_logic import ADBaseController, ADBaseDatasetDescriber

from ._core_writer import ADWriter

from ._core_writer import ADWriter
from ._core_io import NDFileHDFIO, NDFileIO, ADBaseIO
from ._hdf_writer import ADHDFWriter
from ._tiff_writer import ADTIFFWriter


def get_io_class_for_writer(writer_class: type[ADWriter]):
    writer_to_io_map = {
        ADWriter: NDFileIO,
        ADHDFWriter: NDFileHDFIO,
        ADTIFFWriter: NDFileIO,
    }
    return writer_to_io_map[writer_class]


class AreaDetector(StandardDetector, HasHints):
    _controller: ADBaseController
    _writer: ADWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        writer_class: type[ADWriter]=ADWriter,
        writer_suffix: str="",
        controller_class: type[ADBaseController]=ADBaseController,
        drv_class: type[ADBaseIO]=ADBaseIO,
        drv_suffix:str="cam1:",
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
        **kwargs,
    ):
        self.drv = drv_class(prefix + drv_suffix)
        self._fileio = get_io_class_for_writer(writer_class)(prefix + writer_suffix)

        super().__init__(
            controller_class(self.drv, **kwargs),
            writer_class(
                self._fileio,
                path_provider,
                lambda: self.name,
                ADBaseDatasetDescriber(self.drv),
            ),
            config_sigs=(self.drv.acquire_period, self.drv.acquire_time, *config_sigs),
            name=name,
        )

    @property
    def controller(self) -> ADBaseController:
        return cast(ADBaseController, self._controller)


    @property
    def writer(self) -> ADWriter:
        return cast(ADWriter, self._writer)

    @property
    def hints(self) -> Hints:
        return self._writer.hints