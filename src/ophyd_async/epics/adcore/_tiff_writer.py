import asyncio
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator, Dict, List, Optional
from xml.etree import ElementTree as ET

from bluesky.protocols import DataKey, Hints, StreamAsset

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorWriter,
    HDFDataset,
    HDFFile,
    NameProvider,
    PathProvider,
    ShapeProvider,
    observe_value,
    set_and_wait_for_value,
    wait_for_value,
)

from ._core_io import NDArrayBaseIO, NDFileHDFIO
from ._core_writer import ADWriter
from ._utils import (
    FileWriteMode,
    convert_ad_dtype_to_np,
    convert_param_dtype_to_np,
    convert_pv_dtype_to_np,
)


class ADHDFWriter(ADWriter):
    def __init__(
        self,
        *args,
    ) -> None:
        super().__init__(*args)
        self.hdf = self.fileio

        self._datasets: List[HDFDataset] = []
        self._file: Optional[HDFFile] = None

    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
        self._file = None
        info = self._path_provider(device_name=self.hdf.name)

        # Set the directory creation depth first, since dir creation callback happens
        # when directory path PV is processed.
        await self.hdf.create_directory.set(info.create_dir_depth)

        await asyncio.gather(
            self.hdf.num_extra_dims.set(0),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            # See https://github.com/bluesky/ophyd-async/issues/122
            self.hdf.file_path.set(str(info.directory_path)),
            self.hdf.file_name.set(info.filename),
            self.hdf.file_template.set("%s/%s.h5"),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
            # Never use custom xml layout file but use the one defined
            # in the source code file NDFileHDF5LayoutXML.cpp
            self.hdf.xml_file_name.set(""),
        )
