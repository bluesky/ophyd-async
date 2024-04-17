import asyncio
from typing import Dict, Optional

import pytest
from bluesky import plan_stubs as bps
from bluesky.run_engine import RunEngine

from ophyd_async.core import StaticDirectoryProvider, set_sim_value
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import DetectorControl, DetectorTrigger
from ophyd_async.core.device import Device
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.core.signal import SignalR, wait_for_value
from ophyd_async.core.sim_signal_backend import SimSignalBackend
from ophyd_async.core.utils import DEFAULT_TIMEOUT
from ophyd_async.panda import HDFPanda, PcapBlock
from ophyd_async.panda.trigger import StaticSeqTableTriggerLogic
from ophyd_async.panda.writers.hdf_writer import Capture
from ophyd_async.planstubs.prepare_trigger_and_dets import (
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
)


class MockPandaPcapController(DetectorControl):
    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap

    def get_deadtime(self, exposure: float) -> float:
        return 0.000000008

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.constant_gate,
        exposure: Optional[float] = None,
        timeout=DEFAULT_TIMEOUT,
    ) -> AsyncStatus:
        assert trigger in (
            DetectorTrigger.constant_gate,
            trigger == DetectorTrigger.variable_gate,
        ), (
            f"Receieved trigger {trigger}. Only constant_gate and "
            "variable_gate triggering is supported on the PandA"
        )
        await self.pcap.arm.set(True, wait=True, timeout=timeout)
        await wait_for_value(self.pcap.active, True, timeout=timeout)
        await asyncio.sleep(0.2)
        await self.pcap.arm.set(False, wait=False, timeout=timeout)
        return AsyncStatus(wait_for_value(self.pcap.active, False, timeout=None))

    async def disarm(self, timeout=DEFAULT_TIMEOUT) -> AsyncStatus:
        await self.pcap.arm.set(False, wait=True, timeout=timeout)
        await wait_for_value(self.pcap.active, False, timeout=timeout)
        await asyncio.sleep(0.2)
        set_sim_value(self.pcap.active, True)
        return AsyncStatus(wait_for_value(self.pcap.active, False, timeout=None))


@pytest.fixture
async def sim_hdf_panda(tmp_path):
    class CaptureBlock(Device):
        test_capture: SignalR

    directory_provider = StaticDirectoryProvider(str(tmp_path), filename_prefix="test")
    sim_hdf_panda = HDFPanda(
        "HDFPANDA:", directory_provider=directory_provider, name="panda"
    )
    sim_hdf_panda._controller = MockPandaPcapController(sim_hdf_panda.pcap)
    block_a = CaptureBlock(name="block_a")
    block_b = CaptureBlock(name="block_b")
    block_a.test_capture = SignalR(backend=SimSignalBackend(Capture, source="block_a"))
    block_b.test_capture = SignalR(backend=SimSignalBackend(Capture, source="block_b"))

    setattr(sim_hdf_panda, "block_a", block_a)
    setattr(sim_hdf_panda, "block_b", block_b)
    await sim_hdf_panda.connect(sim=True)
    set_sim_value(block_a.test_capture, Capture.Min)
    set_sim_value(block_b.test_capture, Capture.Diff)

    yield sim_hdf_panda


async def test_hdf_panda_passes_blocks_to_controller(sim_hdf_panda: HDFPanda):
    assert hasattr(sim_hdf_panda.controller, "pcap")
    assert sim_hdf_panda.controller.pcap is sim_hdf_panda.pcap


async def test_hdf_panda_hardware_triggered_flyable(
    RE: RunEngine,
    sim_hdf_panda,
):
    names = []
    docs = []

    def append_and_print(name, doc):
        names.append(name)
        docs.append(doc)

    RE.subscribe(append_and_print)

    shutter_time = 0.004
    exposure = 1

    trigger_logic = StaticSeqTableTriggerLogic(sim_hdf_panda.seq[1])
    flyer = HardwareTriggeredFlyable(trigger_logic, [], name="flyer")

    def flying_plan():
        yield from bps.stage_all(sim_hdf_panda, flyer)

        yield from prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
            flyer,
            [sim_hdf_panda],
            num=1,
            width=exposure,
            deadtime=sim_hdf_panda.controller.get_deadtime(1),
            shutter_time=shutter_time,
        )
        # sim_hdf_panda.controller.disarm.assert_called_once  # type: ignore

        yield from bps.open_run()
        yield from bps.declare_stream(sim_hdf_panda, name="main_stream", collect=True)

        set_sim_value(flyer.trigger_logic.seq.active, 1)

        yield from bps.kickoff(flyer, wait=True)
        yield from bps.kickoff(sim_hdf_panda)

        yield from bps.complete(flyer, wait=False, group="complete")
        yield from bps.complete(sim_hdf_panda, wait=False, group="complete")

        # Manually incremenet the index as if a frame was taken
        set_sim_value(
            sim_hdf_panda.data.num_captured,
            sim_hdf_panda.data.num_captured._backend._value + 1,
        )

        set_sim_value(flyer.trigger_logic.seq.active, 0)

        done = False
        while not done:
            try:
                yield from bps.wait(group="complete", timeout=0.5)
            except TimeoutError:
                pass
            else:
                done = True
            yield from bps.collect(
                sim_hdf_panda,
                return_payload=False,
                name="main_stream",
            )
        yield from bps.wait(group="complete")
        yield from bps.close_run()

        yield from bps.unstage_all(flyer, sim_hdf_panda)
        # assert sim_hdf_panda.controller.disarm.called  # type: ignore

    # fly scan
    RE(flying_plan())

    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_resource",
        "stream_datum",
        "stream_datum",
        "stop",
    ]
    named_docs = dict(
        zip(
            [
                "start",
                "descriptor",
                "stream_resource_a",
                "stream_resource_b",
                "stream_datum_a",
                "stream_datum_b",
                "stop",
            ],
            docs,
        )
    )

    # test descriptor
    data_key_names: Dict[str, str] = named_docs["descriptor"]["object_keys"]["panda"]
    assert data_key_names == [
        "panda-block_a-test-Min",
        "panda-block_b-test-Diff",
    ]
    for data_key_name in data_key_names:
        assert (
            named_docs["descriptor"]["data_keys"][data_key_name]["source"]
            == "sim://hdf_directory"
        )

    # test stream resources
    for block_letter, data_key_name in zip(("a", "b"), data_key_names):
        assert (
            named_docs[f"stream_resource_{block_letter}"]["data_key"] == data_key_name
        )
        assert (
            named_docs[f"stream_resource_{block_letter}"]["spec"]
            == "AD_HDF5_SWMR_SLICE"
        )
        assert (
            named_docs[f"stream_resource_{block_letter}"]["run_start"]
            == named_docs["start"]["uid"]
        )
        assert named_docs[f"stream_resource_{block_letter}"]["resource_kwargs"] == {
            "block": f"block_{block_letter}",
            "multiplier": 1,
            "name": data_key_name,
            "path": f"BLOCK_{block_letter.upper()}-TEST-{data_key_name.split('-')[-1]}",
            "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
        }

    # test stream datum
    for block_letter in ("a", "b"):
        assert (
            named_docs[f"stream_datum_{block_letter}"]["descriptor"]
            == named_docs["descriptor"]["uid"]
        )
        assert named_docs[f"stream_datum_{block_letter}"]["seq_nums"] == {
            "start": 1,
            "stop": 2,
        }
        assert named_docs[f"stream_datum_{block_letter}"]["indices"] == {
            "start": 0,
            "stop": 1,
        }
        assert (
            named_docs[f"stream_datum_{block_letter}"]["stream_resource"]
            == named_docs[f"stream_resource_{block_letter}"]["uid"]
        )
