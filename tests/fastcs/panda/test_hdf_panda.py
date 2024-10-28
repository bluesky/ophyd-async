import os
from unittest.mock import ANY

import bluesky.plan_stubs as bps
import numpy as np
import pytest
from bluesky import RunEngine

from ophyd_async.core import (
    Device,
    SignalR,
    StaticFilenameProvider,
    StaticPathProvider,
    callback_on_mock_put,
    set_mock_value,
)
from ophyd_async.core._flyer import StandardFlyer
from ophyd_async.core._signal import assert_emitted
from ophyd_async.fastcs.panda import (
    DatasetTable,
    HDFPanda,
    PandaHdf5DatasetType,
)
from ophyd_async.fastcs.panda._trigger import StaticSeqTableTriggerLogic
from ophyd_async.plan_stubs._fly import (
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
)


@pytest.fixture
async def mock_hdf_panda(tmp_path):
    class CaptureBlock(Device):
        test_capture: SignalR

    fp = StaticFilenameProvider("test-panda")
    dp = StaticPathProvider(fp, tmp_path)

    mock_hdf_panda = HDFPanda("HDFPANDA:", path_provider=dp, name="panda")
    await mock_hdf_panda.connect(mock=True)

    def link_function(value, **kwargs):
        set_mock_value(mock_hdf_panda.pcap.active, value)

    # Mimic directory exists check that happens normally in the PandA IOC
    def check_dir_exits(value, **kwargs):
        if os.path.exists(value):
            set_mock_value(mock_hdf_panda.data.directory_exists, 1)

    callback_on_mock_put(mock_hdf_panda.pcap.arm, link_function)
    callback_on_mock_put(mock_hdf_panda.data.hdf_directory, check_dir_exits)

    set_mock_value(
        mock_hdf_panda.data.datasets,
        DatasetTable(
            name=np.array(
                [
                    "x",
                    "y",
                ]
            ),
            hdf5_type=[
                PandaHdf5DatasetType.UINT_32,
                PandaHdf5DatasetType.FLOAT_64,
            ],
        ),
    )

    yield mock_hdf_panda


async def test_hdf_panda_passes_blocks_to_controller(mock_hdf_panda: HDFPanda):
    assert hasattr(mock_hdf_panda.controller, "pcap")
    assert mock_hdf_panda.controller.pcap is mock_hdf_panda.pcap


async def test_hdf_panda_hardware_triggered_flyable(
    RE: RunEngine,
    mock_hdf_panda,
    tmp_path,
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
    flyer = StandardFlyer(trigger_logic, name="flyer")

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
        yield from bps.kickoff(mock_hdf_panda, wait=True)

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
        # Verify that _completable_frames is reset to 0 after the final complete.
        assert mock_hdf_panda._completable_frames == 0
        yield from bps.unstage_all(flyer, mock_hdf_panda)
        yield from bps.wait_for([lambda: mock_hdf_panda.controller.disarm()])

    # fly scan
    RE(flying_plan())

    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=2, stop=1
    )

    # test descriptor
    data_key_names: dict[str, str] = docs["descriptor"][0]["object_keys"]["panda"]
    assert data_key_names == ["x", "y"]
    for data_key_name in data_key_names:
        assert (
            docs["descriptor"][0]["data_keys"][data_key_name]["source"]
            == "mock+soft://panda-data-hdf_directory"
        )

    # test stream resources
    for dataset_name, stream_resource, data_key_name in zip(
        ("x", "y"), docs["stream_resource"], data_key_names, strict=False
    ):
        assert stream_resource == {
            "run_start": docs["start"][0]["uid"],
            "uid": ANY,
            "data_key": data_key_name,
            "mimetype": "application/x-hdf5",
            "uri": "file://localhost" + str(tmp_path / "test-panda.h5"),
            "parameters": {
                "dataset": f"/{dataset_name}",
                "swmr": False,
                "multiplier": 1,
                "chunk_shape": (1024,),
            },
        }
        assert "test-panda.h5" in stream_resource["uri"]

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
