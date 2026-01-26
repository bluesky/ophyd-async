from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import ANY, call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.fastcs.panda import (
    DatasetTable,
    HDFPanda,
    PandaCaptureMode,
    PandaHdf5DatasetType,
)
from ophyd_async.testing import assert_configuration, assert_has_calls

PANDA_DETECTOR_NAME = "mock_panda"

TABLES = [
    DatasetTable(
        name=[],
        dtype=[],
    ),
    DatasetTable(
        name=["x"],
        dtype=[PandaHdf5DatasetType.UINT_32],
    ),
    DatasetTable(
        name=[
            "x",
            "y",
            "y_min",
            "y_max",
        ],
        dtype=[
            PandaHdf5DatasetType.UINT_32,
            PandaHdf5DatasetType.FLOAT_64,
            PandaHdf5DatasetType.FLOAT_64,
            PandaHdf5DatasetType.FLOAT_64,
        ],
    ),
]


@pytest.fixture
async def hdf_panda() -> HDFPanda:
    path_provider = StaticPathProvider(
        StaticFilenameProvider("test-panda"), Path("/tmp")
    )

    async with init_devices(mock=True):
        panda = HDFPanda("HDFPANDA:", path_provider=path_provider)

    def set_active(value: bool, wait: bool = True):
        set_mock_value(panda.pcap.active, value)

    callback_on_mock_put(panda.pcap.arm, set_active)
    set_mock_value(panda.data.directory_exists, True)
    set_mock_value(
        panda.data.datasets,
        DatasetTable(
            name=["x", "y"],
            dtype=[PandaHdf5DatasetType.UINT_32, PandaHdf5DatasetType.FLOAT_64],
        ),
    )

    return panda


@pytest.mark.parametrize("table", TABLES)
async def test_open_returns_correct_descriptors_and_resources(
    hdf_panda: HDFPanda, table: DatasetTable, caplog
):
    set_mock_value(hdf_panda.data.datasets, table)
    with caplog.at_level(logging.WARNING):
        await hdf_panda.prepare(TriggerInfo(trigger=DetectorTrigger.EXTERNAL_LEVEL))
        description = await hdf_panda.describe()

        # Check if empty datasets table leads to warning log message
        if len(table) == 0:
            assert "DATASETS table is empty!" in caplog.text

    uri = "file://localhost/tmp/test-panda.h5"
    for key, entry, expected_key in zip(
        description.keys(), description.values(), table.name, strict=True
    ):
        assert key == expected_key
        assert entry == {
            "source": uri,
            "shape": [1],
            "dtype": "number",
            "dtype_numpy": "<f8",
            "external": "STREAM:",
        }

    set_mock_value(hdf_panda.data.num_captured, 7)
    docs = [doc async for doc in hdf_panda.collect_asset_docs()]
    sr = docs[: len(table)]
    sd = docs[len(table) :]

    # Expect an SR and SD for each row of the table
    assert len(sr) == len(sd) == len(table)

    for i, name in enumerate(table.name):
        assert sr[i] == (
            "stream_resource",
            {
                "data_key": name,
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (1024,),
                    "dataset": f"/{name}",
                },
                "uid": ANY,
                "uri": uri,
            },
        )
        assert sd[i] == (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 7},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[i][1]["uid"],
                "uid": ANY,
            },
        )


async def test_open_sets_correct_signals(hdf_panda: HDFPanda):
    await hdf_panda.prepare(TriggerInfo(trigger=DetectorTrigger.EXTERNAL_LEVEL))
    assert_has_calls(
        hdf_panda,
        [
            call.data.create_directory.put(0, wait=True),
            call.data.flush_period.put(0, wait=True),
            call.data.hdf_directory.put("/tmp", wait=True),
            call.data.hdf_file_name.put("test-panda.h5", wait=True),
            call.data.capture_mode.put(PandaCaptureMode.FOREVER, wait=True),
            call.data.capture.put(True, wait=True),
            call.pcap.arm.put(True, wait=True),
        ],
    )


async def test_close_sets_correct_signals(hdf_panda: HDFPanda):
    await hdf_panda.unstage()
    assert_has_calls(hdf_panda.pcap, [call.arm.put(False, wait=True)])
    assert_has_calls(hdf_panda.data, [call.capture.put(False, wait=True)])


async def test_flyscan_documents(hdf_panda: HDFPanda):
    # Check there are no config sigs
    config_description = await hdf_panda.describe_configuration()
    assert config_description == {}
    await assert_configuration(hdf_panda, {})
    # Prepare for N frames
    await hdf_panda.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
            collections_per_event=3,
            number_of_events=5,
        )
    )
    # Check it is making 3 collections in each event
    description = await hdf_panda.describe()
    uri = "file://localhost/tmp/test-panda.h5"
    assert description == {
        "x": {
            "dtype": "array",
            "dtype_numpy": "<f8",
            "external": "STREAM:",
            "shape": [3],
            "source": uri,
        },
        "y": {
            "dtype": "array",
            "dtype_numpy": "<f8",
            "external": "STREAM:",
            "shape": [3],
            "source": uri,
        },
    }
    assert hdf_panda.hints == {"fields": []}
    # Kick it off and start it completing
    await hdf_panda.kickoff()
    status = hdf_panda.complete()
    # Check it makes nothing
    docs = [doc async for doc in hdf_panda.collect_asset_docs()]
    assert docs == []
    # Make 2 and 1/3 events and check they are produced
    set_mock_value(hdf_panda.data.num_captured, 7)
    docs = [doc async for doc in hdf_panda.collect_asset_docs()]
    sr = docs[:2]
    sd = docs[2:]
    assert sr == [
        (
            "stream_resource",
            {
                "data_key": "x",
                "mimetype": "application/x-hdf5",
                "parameters": {"chunk_shape": (1024,), "dataset": "/x"},
                "uid": ANY,
                "uri": uri,
            },
        ),
        (
            "stream_resource",
            {
                "data_key": "y",
                "mimetype": "application/x-hdf5",
                "parameters": {"chunk_shape": (1024,), "dataset": "/y"},
                "uid": ANY,
                "uri": uri,
            },
        ),
    ]
    assert sd == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 2},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[0][1]["uid"],
                "uid": ANY,
            },
        ),
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 2},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[1][1]["uid"],
                "uid": ANY,
            },
        ),
    ]
    assert not status.done
    # Update and check it completes
    set_mock_value(hdf_panda.data.num_captured, 15)
    set_mock_value(hdf_panda.pcap.active, False)
    docs = [doc async for doc in hdf_panda.collect_asset_docs()]
    assert docs == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 2, "stop": 5},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[0][1]["uid"],
                "uid": ANY,
            },
        ),
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 2, "stop": 5},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[1][1]["uid"],
                "uid": ANY,
            },
        ),
    ]
    assert status.done
    # Check that another kickoff without prepare is not allowed
    with pytest.raises(
        RuntimeError,
        match="Kickoff requested 15:30, but detector was only prepared up to 15",
    ):
        await hdf_panda.kickoff()
    # But preparing again is ok
    await hdf_panda.prepare(
        TriggerInfo(
            collections_per_event=3,
            number_of_events=3,
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
        )
    )
    await hdf_panda.kickoff()
    # Completing adds indexes to the same resource
    status = hdf_panda.complete()
    set_mock_value(hdf_panda.data.num_captured, 24)
    set_mock_value(hdf_panda.pcap.active, False)
    docs = [doc async for doc in hdf_panda.collect_asset_docs()]
    assert docs == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 5, "stop": 8},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[0][1]["uid"],
                "uid": ANY,
            },
        ),
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 5, "stop": 8},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[1][1]["uid"],
                "uid": ANY,
            },
        ),
    ]
    assert status.done


async def test_get_indices_written(hdf_panda: HDFPanda):
    await hdf_panda.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
            collections_per_event=3,
            number_of_events=5,
        )
    )
    set_mock_value(hdf_panda.data.num_captured, 4)
    assert await hdf_panda.get_index() == 1  # 4 // collections_per_event
    set_mock_value(hdf_panda.data.num_captured, 12)
    assert await hdf_panda.get_index() == 4  # 12 // collections_per_event


async def test_oserror_when_hdf_dir_does_not_exist(hdf_panda: HDFPanda):
    set_mock_value(hdf_panda.data.directory_exists, False)
    with pytest.raises(OSError):
        await hdf_panda.prepare(TriggerInfo(trigger=DetectorTrigger.EXTERNAL_LEVEL))


async def test_deadtime(hdf_panda: HDFPanda):
    supported_triggers, deadtime = await hdf_panda.get_trigger_deadtime()
    assert deadtime == 8e-9
    assert supported_triggers == {DetectorTrigger.EXTERNAL_LEVEL}
