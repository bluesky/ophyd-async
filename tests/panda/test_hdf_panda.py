from typing import Dict

import pytest
from bluesky import plan_stubs as bps
from bluesky.run_engine import RunEngine

from ophyd_async.core import StaticDirectoryProvider, set_mock_value
from ophyd_async.core.device import Device
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.core.mock_signal_utils import callback_on_mock_put
from ophyd_async.core.signal import SignalR, assert_emitted
from ophyd_async.epics.signal.signal import epics_signal_r
from ophyd_async.panda import HDFPanda, StaticSeqTableTriggerLogic
from ophyd_async.panda.writers._hdf_writer import Capture
from ophyd_async.plan_stubs import (
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
)


@pytest.fixture
async def mock_hdf_panda(tmp_path):
    class CaptureBlock(Device):
        test_capture: SignalR

    directory_provider = StaticDirectoryProvider(str(tmp_path), filename_prefix="test")
    mock_hdf_panda = HDFPanda(
        "HDFPANDA:", directory_provider=directory_provider, name="panda"
    )
    block_a = CaptureBlock(name="block_a")
    block_b = CaptureBlock(name="block_b")
    block_a.test_capture = epics_signal_r(
        Capture, "pva://test_capture_a", name="test_capture_a"
    )
    block_b.test_capture = epics_signal_r(
        Capture, "pva://test_capture_b", name="test_capture_b"
    )

    setattr(mock_hdf_panda, "block_a", block_a)
    setattr(mock_hdf_panda, "block_b", block_b)
    await mock_hdf_panda.connect(mock=True)

    def link_function(value, **kwargs):
        set_mock_value(mock_hdf_panda.pcap.active, value)

    callback_on_mock_put(mock_hdf_panda.pcap.arm, link_function)
    set_mock_value(block_a.test_capture, Capture.Min)
    set_mock_value(block_b.test_capture, Capture.Diff)

    yield mock_hdf_panda


async def test_hdf_panda_passes_blocks_to_controller(mock_hdf_panda: HDFPanda):
    assert hasattr(mock_hdf_panda.controller, "pcap")
    assert mock_hdf_panda.controller.pcap is mock_hdf_panda.pcap


async def test_hdf_panda_hardware_triggered_flyable(
    RE: RunEngine,
    mock_hdf_panda,
):
    docs = {}

    def append_and_print(name, doc):
        if name not in docs:
            docs[name] = []
        docs[name] += [doc]

    RE.subscribe(append_and_print)

    shutter_time = 0.004
    exposure = 1

    trigger_logic = StaticSeqTableTriggerLogic(mock_hdf_panda.seq[1])
    flyer = HardwareTriggeredFlyable(trigger_logic, [], name="flyer")

    def flying_plan():
        yield from bps.stage_all(mock_hdf_panda, flyer)

        yield from prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
            flyer,
            [mock_hdf_panda],
            number_of_frames=1,
            exposure=exposure,
            shutter_time=shutter_time,
        )

        yield from bps.open_run()
        yield from bps.declare_stream(mock_hdf_panda, name="main_stream", collect=True)

        set_mock_value(flyer.trigger_logic.seq.active, 1)

        yield from bps.kickoff(flyer, wait=True)
        yield from bps.kickoff(mock_hdf_panda)

        yield from bps.complete(flyer, wait=False, group="complete")
        yield from bps.complete(mock_hdf_panda, wait=False, group="complete")

        # Manually incremenet the index as if a frame was taken
        set_mock_value(mock_hdf_panda.data.num_captured, 1)
        set_mock_value(flyer.trigger_logic.seq.active, 0)

        done = False
        while not done:
            try:
                yield from bps.wait(group="complete", timeout=0.5)
            except TimeoutError:
                pass
            else:
                done = True
            yield from bps.collect(
                mock_hdf_panda,
                return_payload=False,
                name="main_stream",
            )
        yield from bps.wait(group="complete")
        yield from bps.close_run()

        yield from bps.unstage_all(flyer, mock_hdf_panda)
        yield from bps.wait_for([lambda: mock_hdf_panda.controller.disarm()])

    # fly scan
    RE(flying_plan())

    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=2, stop=1
    )

    # test descriptor
    data_key_names: Dict[str, str] = docs["descriptor"][0]["object_keys"]["panda"]
    assert data_key_names == [
        "panda-block_a-test-Min",
        "panda-block_b-test-Diff",
    ]
    for data_key_name in data_key_names:
        assert (
            docs["descriptor"][0]["data_keys"][data_key_name]["source"]
            == "mock+soft://panda-data-hdf_directory"
        )

    # test stream resources
    for block_letter, stream_resource, data_key_name in zip(
        ("a", "b"), docs["stream_resource"], data_key_names
    ):
        assert stream_resource["data_key"] == data_key_name
        assert stream_resource["spec"] == "AD_HDF5_SWMR_SLICE"
        assert stream_resource["run_start"] == docs["start"][0]["uid"]
        assert stream_resource["resource_kwargs"] == {
            "block": f"block_{block_letter}",
            "multiplier": 1,
            "name": data_key_name,
            "path": f"BLOCK_{block_letter.upper()}-TEST-{data_key_name.split('-')[-1]}",
            "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
        }

    # test stream datum
    for stream_datum in docs["stream_datum"]:
        assert stream_datum["descriptor"] == docs["descriptor"][0]["uid"]
        assert stream_datum["seq_nums"] == {
            "start": 1,
            "stop": 2,
        }
        assert stream_datum["indices"] == {
            "start": 0,
            "stop": 1,
        }
        assert stream_datum["stream_resource"] in [
            sd["uid"].split("/")[0] for sd in docs["stream_datum"]
        ]
