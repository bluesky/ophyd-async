from enum import Enum

from ophyd_async.core import Device, DeviceVector
from ophyd_async.epics.signal import (
    epics_signal_r,
    epics_signal_rw_rbv,
    epics_signal_w,
    epics_signal_x,
)


class Writing(str, Enum):
    ON = "ON"
    OFF = "OFF"


class OdinNode(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.writing = epics_signal_r(Writing, f"{prefix}HDF:Writing")

        # Cannot find:
        # FPClearErrors
        # FPErrorState_RBV
        # FPErrorMessage_RBV

        self.connected = epics_signal_r(
            bool, f"{prefix}Connected"
        )  # Assuming this is both FPProcessConnected_RBV and FRProcessConnected_RBV

        # Usually assert that FramesTimedOut_RBV and FramesDropped_RBV are 0
        # , do these exist or do we want to assert something else?

        super().__init__(name)


class Odin(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nodes = DeviceVector({i: OdinNode(f"{prefix}FP{i}:") for i in range(4)})

        self.capture = epics_signal_x(f"{prefix}ConfigHdfWrite")
        self.num_captured = epics_signal_r(int, f"{prefix}FramesWritten")
        self.num_to_capture = epics_signal_w(int, f"{prefix}Frames")

        self.start_timeout = epics_signal_rw_rbv(int, f"{prefix}TimeoutTimerPeriod")

        self.image_height = epics_signal_rw_rbv(int, f"{prefix}DatasetDataDims0")
        self.image_width = epics_signal_rw_rbv(int, f"{prefix}DatasetDataDims1")

        self.num_row_chunks = epics_signal_rw_rbv(int, f"{prefix}DatasetDataChunks1")
        self.num_col_chunks = epics_signal_rw_rbv(int, f"{prefix}DatasetDataChunks2")

        self.file_path = epics_signal_rw_rbv(str, f"{prefix}ConfigHdfFilePath")
        self.file_name = epics_signal_rw_rbv(str, f"{prefix}ConfigHdfFilePrefix")

        self.acquisition_id = epics_signal_rw_rbv(
            str, f"{prefix}ConfigHdfAcquisitionId"
        )

        self.data_type = epics_signal_rw_rbv(str, f"{prefix}DatasetDataDatatype")

        super().__init__(name)
