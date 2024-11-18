from typing import TypeVar

from ophyd_async.core import PathProvider

from ._core_io import ADBaseIO, NDFileHDFIO, NDFileIO
from ._core_logic import ADBaseDatasetDescriber
from ._core_writer import ADWriter
from ._hdf_writer import ADHDFWriter
from ._tiff_writer import ADTIFFWriter

ADBaseIOT = TypeVar("ADBaseIOT", bound=ADBaseIO)
NDFileIOT = TypeVar("NDFileIOT", bound=NDFileIO)


def _areadetector_driver_and_fileio(
    drv_cls: type[ADBaseIOT],
    fileio_cls: type[NDFileIOT],
    writer_cls: type[ADWriter],
    prefix: str,
    drv_suffix: str,
    fileio_suffix: str,
    path_provider: PathProvider,
) -> tuple[ADBaseIOT, NDFileIOT, ADWriter]:
    drv = drv_cls(prefix + drv_suffix)
    fileio = fileio_cls(prefix + fileio_suffix)

    def get_detector_name() -> str:
        assert drv.parent, "Detector driver hasn't been attached to a detector"
        return drv.parent.name

    writer = writer_cls(
        fileio, path_provider, get_detector_name, ADBaseDatasetDescriber(drv)
    )
    return drv, fileio, writer


def areadetector_driver_and_hdf(
    drv_cls: type[ADBaseIOT],
    prefix: str,
    drv_suffix: str,
    fileio_suffix: str,
    path_provider: PathProvider,
) -> tuple[ADBaseIOT, NDFileHDFIO, ADWriter]:
    return _areadetector_driver_and_fileio(
        drv_cls=drv_cls,
        fileio_cls=NDFileHDFIO,
        writer_cls=ADHDFWriter,
        prefix=prefix,
        drv_suffix=drv_suffix,
        fileio_suffix=fileio_suffix,
        path_provider=path_provider,
    )


def areadetector_driver_and_tiff(
    drv_cls: type[ADBaseIOT],
    prefix: str,
    drv_suffix: str,
    fileio_suffix: str,
    path_provider: PathProvider,
) -> tuple[ADBaseIOT, NDFileIO, ADWriter]:
    return _areadetector_driver_and_fileio(
        drv_cls=drv_cls,
        fileio_cls=NDFileIO,
        writer_cls=ADTIFFWriter,
        prefix=prefix,
        drv_suffix=drv_suffix,
        fileio_suffix=fileio_suffix,
        path_provider=path_provider,
    )
