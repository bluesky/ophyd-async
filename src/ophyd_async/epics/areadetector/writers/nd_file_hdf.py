from enum import Enum

from ...signal.signal import epics_signal_rw
from ..utils import FileWriteMode, ad_r, ad_rw
from .nd_plugin import NDPluginBase


class Compression(str, Enum):
    none = "None"
    nbit = "N-bit"
    szip = "szip"
    zlib = "zlib"
    blosc = "Blosc"
    bslz4 = "BSLZ4"
    lz4 = "LZ4"
    jpeg = "JPEG"


class NDFileHDF(NDPluginBase):
    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.position_mode = ad_rw(bool, prefix + "PositionMode")
        self.compression = ad_rw(Compression, prefix + "Compression")
        self.num_extra_dims = ad_rw(int, prefix + "NumExtraDims")
        self.file_path = ad_rw(str, prefix + "FilePath")
        self.file_name = ad_rw(str, prefix + "FileName")
        self.file_path_exists = ad_r(bool, prefix + "FilePathExists")
        self.file_template = ad_rw(str, prefix + "FileTemplate")
        self.full_file_name = ad_r(str, prefix + "FullFileName")
        self.file_write_mode = ad_rw(FileWriteMode, prefix + "FileWriteMode")
        self.num_capture = ad_rw(int, prefix + "NumCapture")
        self.num_captured = ad_r(int, prefix + "NumCaptured")
        self.swmr_mode = ad_rw(bool, prefix + "SWMRMode")
        self.lazy_open = ad_rw(bool, prefix + "LazyOpen")
        self.capture = ad_rw(bool, prefix + "Capture")
        self.flush_now = epics_signal_rw(bool, prefix + "FlushNow")
        self.array_size0 = ad_r(int, prefix + "ArraySize0")
        self.array_size1 = ad_r(int, prefix + "ArraySize1")
        super().__init__(prefix, name)
