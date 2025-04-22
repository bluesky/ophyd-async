# type: ignore # Eiger will soon be ophyd-async https://github.com/DiamondLightSource/dodal/issues/700
import asyncio
from functools import partial, reduce

from dodal.devices.status import await_value
from event_model import DataKey
from ophyd import Component, EpicsSignal, EpicsSignalRO, EpicsSignalWithRBV
from ophyd.areadetector.plugins import HDF5Plugin_V22
from ophyd.sim import NullStatus
from ophyd.status import StatusBase, SubscriptionStatus

from ophyd_async.core import Device, PathProvider, StrictEnum, set_and_wait_for_value
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw, epics_signal_rw_rbv


class OdinWriting(StrictEnum):
    ON = "ON"
    OFF = "OFF"


class EigerFan(Device):
    def __init__(self, prefix="", name=""):
        self.on = epics_signal_r(int, prefix + "ProcessConnected_RBV")
        self.consumers_connected = epics_signal_r(int, "AllConsumersConnected_RBV")
        self.ready = epics_signal_r(int, prefix + "StateReady_RBV")
        self.zmq_addr = epics_signal_r(str, prefix + "EigerAddress_RBV")
        self.zmq_port = epics_signal_r(str, prefix + "EigerPort_RBV")
        self.state = epics_signal_r(str, prefix + "State_RBV")
        self.frames_sent = epics_signal_r(int, prefix + "FramesSent_RBV")
        self.series = epics_signal_r(int, prefix + "CurrentSeries_RBV")
        self.offset = epics_signal_r(int, prefix + "CurrentOffset_RBV")
        self.forward_stream = epics_signal_rw_rbv(int, prefix + "ForwardStream")
        self.dev_shm_enable = EpicsSignal(int, prefix + "DevShmCache")
        super().__init__(name=name)


class OdinMetaListener(Device):
    def __init__(self, prefix="", name=""):
        self.initialised = epics_signal_r(int, prefix + "ProcessConnected_RBV")
        self.ready = epics_signal_r(int, prefix + "Writing_RBV")
        # file_name should not be set. Set the filewriter file_name and this will be updated in EPICS
        self.file_name = epics_signal_r(str, prefix + "FileName")
        self.stop_writing = epics_signal_rw(int, prefix + "Stop")
        self.active = epics_signal_r(int, prefix + "AcquisitionActive_RBV")
        super().__init__(name=name)


class OdinFileWriter(HDF5Plugin_V22):
    start_timeout = Component(EpicsSignal, "StartTimeout")
    # id should not be set. Set the filewriter file_name and this will be updated in EPICS
    id = Component(EpicsSignalRO, "AcquisitionID_RBV", string=True)
    image_height = Component(EpicsSignalWithRBV, "ImageHeight")
    image_width = Component(EpicsSignalWithRBV, "ImageWidth")
    plugin_type = None


class OdinNode(Device):
    writing = Component(EpicsSignalRO, "Writing_RBV")
    frames_dropped = Component(EpicsSignalRO, "FramesDropped_RBV")
    frames_timed_out = Component(EpicsSignalRO, "FramesTimedOut_RBV")
    error_status = Component(EpicsSignalRO, "FPErrorState_RBV")
    fp_initialised = Component(EpicsSignalRO, "FPProcessConnected_RBV")
    fr_initialised = Component(EpicsSignalRO, "FRProcessConnected_RBV")
    clear_errors = Component(EpicsSignal, "FPClearErrors")
    num_captured = Component(EpicsSignalRO, "NumCaptured_RBV")
    error_message = Component(EpicsSignalRO, "FPErrorMessage_RBV", string=True)


class OdinNodesStatus(Device):
    node_0 = Component(OdinNode, "OD1:")
    node_1 = Component(OdinNode, "OD2:")
    node_2 = Component(OdinNode, "OD3:")
    node_3 = Component(OdinNode, "OD4:")

    @property
    def nodes(self) -> list[OdinNode]:
        return [self.node_0, self.node_1, self.node_2, self.node_3]

    def _check_node_frames_from_attr(
        self, node_get_func, error_message_verb: str
    ) -> tuple[bool, str]:
        nodes_frames_values = [0] * len(self.nodes)
        frames_details = []
        for node_number, node_pv in enumerate(self.nodes):
            node_state = node_get_func(node_pv)
            nodes_frames_values[node_number] = node_state
            if node_state != 0:
                error_message = f"Filewriter {node_number} {error_message_verb} \
                        {nodes_frames_values[node_number]} frames"
                frames_details.append(error_message)
        bad_frames = any(v != 0 for v in nodes_frames_values)
        return bad_frames, "\n".join(frames_details)

    def check_frames_timed_out(self) -> tuple[bool, str]:
        return self._check_node_frames_from_attr(
            lambda node: node.frames_timed_out.get(), "timed out"
        )

    def check_frames_dropped(self) -> tuple[bool, str]:
        return self._check_node_frames_from_attr(
            lambda node: node.frames_dropped.get(), "dropped"
        )

    def wait_for_no_errors(self, timeout) -> dict[SubscriptionStatus, str]:
        errors = {}
        for node_number, node_pv in enumerate(self.nodes):
            errors[await_value(node_pv.error_status, False, timeout)] = (
                f"Filewriter {node_number} is in an error state with error message\
                     - {node_pv.error_message.get()}"
            )

        return errors

    def get_init_state(self, timeout) -> SubscriptionStatus:
        is_initialised = []
        for node_pv in self.nodes:
            is_initialised.append(await_value(node_pv.fr_initialised, True, timeout))
            is_initialised.append(await_value(node_pv.fp_initialised, True, timeout))
        return reduce(lambda x, y: x & y, is_initialised)

    def clear_odin_errors(self):
        clearing_status = NullStatus()
        for node_number, node_pv in enumerate(self.nodes):
            error_message = node_pv.error_message.get()
            if len(error_message) != 0:
                self.log.info(f"Clearing odin errors from node {node_number}")
                clearing_status &= node_pv.clear_errors.set(1)
        clearing_status.wait(10)


class EigerOdin(Device):
    fan = Component(EigerFan, "OD:FAN:")
    file_writer = Component(OdinFileWriter, "OD:")
    meta = Component(OdinMetaListener, "OD:META:")
    nodes = Component(OdinNodesStatus, "")

    def create_finished_status(self) -> StatusBase:
        writing_finished = await_value(self.meta.ready, 0)
        for node_pv in self.nodes.nodes:
            writing_finished &= await_value(node_pv.writing, 0)
        return writing_finished

    def check_and_wait_for_odin_state(self, timeout) -> bool:
        is_initialised, error_message = self.wait_for_odin_initialised(timeout)
        frames_dropped, frames_dropped_details = self.nodes.check_frames_dropped()
        frames_timed_out, frames_timed_out_details = self.nodes.check_frames_timed_out()

        if not is_initialised:
            raise RuntimeError(error_message)
        if frames_dropped:
            self.log.error(f"Frames dropped: {frames_dropped_details}")
        if frames_timed_out:
            self.log.error(f"Frames timed out: {frames_timed_out_details}")

        return is_initialised and not frames_dropped and not frames_timed_out

    def wait_for_odin_initialised(self, timeout) -> tuple[bool, str]:
        errors = self.nodes.wait_for_no_errors(timeout)
        await_true = partial(await_value, expected_value=True, timeout=timeout)
        errors[
            await_value(
                self.fan.consumers_connected, expected_value=True, timeout=timeout
            )
        ] = "EigerFan is not connected"
        errors[await_true(self.fan.on)] = "EigerFan is not initialised"
        errors[await_true(self.meta.initialised)] = "MetaListener is not initialised"
        errors[self.nodes.get_init_state(timeout)] = (
            "One or more filewriters is not initialised"
        )

        error_strings = []

        for error_status, string in errors.items():
            try:
                error_status.wait(timeout=timeout)
            except Exception:
                error_strings.append(string)

        return not error_strings, "\n".join(error_strings)

    def stop(self) -> StatusBase:
        """Stop odin manually."""
        status = self.file_writer.capture.set(0)
        status &= self.meta.stop_writing.set(1)
        return status


class OdinFileWriterMX(Device):  # HDF5Plugin_V22
    def __init__(self, _path_provider: PathProvider, prefix="", name=""):
        self.start_timeout = epics_signal_rw(int, prefix + "StartTimeout")
        # id should not be set. Set the filewriter file_name and this will be updated in EPICS
        self.id = epics_signal_r(int, prefix + "AcquisitionID_RBV")
        self.image_height = epics_signal_rw(int, prefix + "ImageHeight")
        self.image_width = epics_signal_rw_rbv(int, prefix + "ImageWidth")
        self.file_path = epics_signal_rw(str, prefix + "FilePath")
        self.file_name = epics_signal_rw(str, prefix + "FileName")
        self.data_type = epics_signal_rw(str, prefix + "DataType")
        self.num_capture = epics_signal_rw(int, prefix + "NumCapture")
        self.num_captured = epics_signal_rw(int, prefix + "NumCapture_RBV")
        self.capture = epics_signal_rw(OdinWriting, prefix + "Capture")
        self.num_to_capture = epics_signal_rw
        self._path_provider = _path_provider
        super().__init__(name=name)

    async def open(self, name: str, multiplier: int = 1) -> dict[str, DataKey]:
        info = self._path_provider(device_name=name)
        self._exposures_per_event = multiplier
        await asyncio.gather(
            self.file_path.set(str(info.directory_path)),
            self.file_name.set(info.filename),
            self.data_type.set(
                "uint16"
            ),  # TODO: Get from eiger https://github.com/bluesky/ophyd-async/issues/529
            self.num_capture.set(0),
        )

        await self.capture.set(OdinWriting.ON)

        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        data_shape = await asyncio.gather(
            self.image_height.get_value(), self.image_width.get_value()
        )

        return {
            "data": DataKey(
                source=self.file_name.source,
                shape=[self._exposures_per_event, *data_shape],
                dtype="array",
                # TODO: Use correct type based on eiger https://github.com/bluesky/ophyd-async/issues/529
                dtype_numpy="<u2",
                external="STREAM:",
            )
        }

    async def get_indices_written(self) -> int:
        return await self.num_captured.get_value() // self._exposures_per_event

    async def close(self) -> None:
        await set_and_wait_for_value(self.capture, OdinWriting.OFF)
