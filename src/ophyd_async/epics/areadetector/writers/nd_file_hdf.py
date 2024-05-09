from enum import Enum

from ...signal.signal import epics_signal_r, epics_signal_rw, epics_signal_rw_rbv
from ..utils import FileWriteMode
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
        self.position_mode = epics_signal_rw_rbv(bool, prefix + "PositionMode")
        self.compression = epics_signal_rw_rbv(Compression, prefix + "Compression")
        self.num_extra_dims = epics_signal_rw_rbv(int, prefix + "NumExtraDims")
        self.file_path = epics_signal_rw_rbv(str, prefix + "FilePath")
        self.file_name = epics_signal_rw_rbv(str, prefix + "FileName")
        self.file_path_exists = epics_signal_r(bool, prefix + "FilePathExists_RBV")
        self.file_template = epics_signal_rw_rbv(str, prefix + "FileTemplate")
        self.full_file_name = epics_signal_r(str, prefix + "FullFileName_RBV")
        self.file_write_mode = epics_signal_rw_rbv(
            FileWriteMode, prefix + "FileWriteMode"
        )
        self.num_capture = epics_signal_rw_rbv(int, prefix + "NumCapture")
        self.num_captured = epics_signal_r(int, prefix + "NumCaptured_RBV")
        self.swmr_mode = epics_signal_rw_rbv(bool, prefix + "SWMRMode")
        self.lazy_open = epics_signal_rw_rbv(bool, prefix + "LazyOpen")
        self.capture = epics_signal_rw_rbv(bool, prefix + "Capture")
        self.flush_now = epics_signal_rw(bool, prefix + "FlushNow")
        self.array_size0 = epics_signal_r(int, prefix + "ArraySize0_RBV")
        self.array_size1 = epics_signal_r(int, prefix + "ArraySize1_RBV")
        self.xml_file_name = epics_signal_rw_rbv(str, prefix + "XMLFileName")
        super().__init__(prefix, name)
