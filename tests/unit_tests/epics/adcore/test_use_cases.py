from unittest.mock import ANY

import pytest

from ophyd_async.core import (
    DetectorDataLogic,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adaravis, adcore, adsimdetector
from ophyd_async.epics.core import epics_signal_r
from ophyd_async.testing import assert_configuration, assert_reading


async def test_step_scan_hdf_detector_with_stats_and_temp(
    static_path_provider: StaticPathProvider,
):
    stat = adcore.NDStatsIO("PREFIX:STATS:")
    async with init_devices(mock=True):
        det = adsimdetector.SimDetector(
            "PREFIX:", static_path_provider, plugins={"stats": stat}
        )
        temp = epics_signal_r(float, "SAMP:TEMP:RBV")
    ndattributes = [
        adcore.NDAttributeParam(
            name="det-sum",
            param="TOTAL",
            datatype=adcore.NDAttributeDataType.DOUBLE,
            description="Sum of the array",
        ),
        adcore.NDAttributePv(
            name="sample-temp",
            signal=temp,
            dbrtype=adcore.NDAttributePvDbrType.DBR_DOUBLE,
            description="Temperature of the sample",
        ),
    ]
    set_mock_value(stat.nd_attributes_file, adcore.ndattributes_to_xml(ndattributes))
    writer = det.get_plugin("writer", adcore.NDFileHDF5IO)
    set_mock_value(det.driver.acquire_period, 0.1)
    set_mock_value(det.driver.acquire_time, 0.05)
    set_mock_value(det.driver.array_size_x, 1024)
    set_mock_value(det.driver.array_size_y, 768)

    await det.stage()
    assert await det.driver.wait_for_plugins.get_value() is False
    config_description = await det.describe_configuration()
    assert config_description == {
        "det-driver-acquire_period": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://PREFIX:cam1:AcquirePeriod_RBV",
        },
        "det-driver-acquire_time": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://PREFIX:cam1:AcquireTime_RBV",
        },
    }
    await assert_configuration(
        det,
        {
            "det-driver-acquire_period": {"value": 0.1},
            "det-driver-acquire_time": {"value": 0.05},
        },
    )
    # Check we need to call prepare or trigger before we can describe
    with pytest.raises(RuntimeError, match="Prepare not run"):
        await det.describe()
    # Need to tell it the path is valid
    set_mock_value(writer.file_path_exists, True)
    # When arm is pressed, then make a single frame
    callback_on_mock_put(
        det.driver.acquire, lambda v, wait: set_mock_value(writer.num_captured, 1)
    )
    # Trigger a single frame then describe, get hints and read
    await det.trigger()
    path_info = static_path_provider()
    description = await det.describe()
    uri = f"file://localhost{path_info.directory_path}/{path_info.filename}.h5"
    assert description == {
        "det": {
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
            "shape": [1, 768, 1024],
            "source": uri,
        },
        "det-sum": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "external": "STREAM:",
            "shape": [1],
            "source": uri,
        },
        "sample-temp": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "external": "STREAM:",
            "shape": [1],
            "source": "ca://SAMP:TEMP:RBV",
        },
    }
    assert det.hints == {"fields": ["det"]}
    await assert_reading(det, {})
    docs = [doc async for doc in det.collect_asset_docs()]
    sr = docs[:3]
    sd = docs[3:]
    assert sr == [
        (
            "stream_resource",
            {
                "data_key": "det",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (1, 768, 1024),
                    "dataset": "/entry/data/data",
                },
                "uid": ANY,
                "uri": uri,
            },
        ),
        (
            "stream_resource",
            {
                "data_key": "det-sum",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (16384,),
                    "dataset": "/entry/instrument/NDAttributes/det-sum",
                },
                "uid": ANY,
                "uri": uri,
            },
        ),
        (
            "stream_resource",
            {
                "data_key": "sample-temp",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (16384,),
                    "dataset": "/entry/instrument/NDAttributes/sample-temp",
                },
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
                "indices": {"start": 0, "stop": 1},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[i][1]["uid"],
                "uid": ANY,
            },
        )
        for i in range(3)
    ]
    # Check we can prepare and do a second one
    await det.prepare(TriggerInfo(exposure_timeout=0.01))
    callback_on_mock_put(
        det.driver.acquire, lambda v, wait: set_mock_value(writer.num_captured, 2)
    )
    await det.trigger()
    readings = await det.read()
    assert readings == {}
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 1, "stop": 2},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[i][1]["uid"],
                "uid": ANY,
            },
        )
        for i in range(3)
    ]
    # And if we trigger again without updating num_captured then we timeout
    with pytest.raises(
        TimeoutError, match="Timeout Error while waiting 0.01s to update"
    ):
        await det.trigger()


async def test_step_scan_tiff_detector(
    static_path_provider: StaticPathProvider,
):
    async with init_devices(mock=True):
        det = adsimdetector.SimDetector(
            "PREFIX:", static_path_provider, writer_type=adcore.ADWriterType.TIFF
        )

    writer = det.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(det.driver.array_size_x, 1024)
    set_mock_value(det.driver.array_size_y, 768)

    await det.stage()
    # Need to tell it the path is valid
    set_mock_value(writer.file_path_exists, True)
    # When arm is pressed, then make a single frame
    callback_on_mock_put(
        det.driver.acquire, lambda v, wait: set_mock_value(writer.num_captured, 1)
    )
    # Trigger a single frame then describe and read
    await det.trigger()
    path_info = static_path_provider()
    description = await det.describe()
    uri_dir = f"file://localhost{path_info.directory_path}/"
    assert description == {
        "det": {
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
            "shape": [1, 768, 1024],
            "source": uri_dir,
        },
    }
    assert det.hints == {"fields": ["det"]}
    readings = await det.read()
    assert readings == {}
    docs = [doc async for doc in det.collect_asset_docs()]
    sr = docs[:1]
    sd = docs[1:]
    assert sr == [
        (
            "stream_resource",
            {
                "data_key": "det",
                "mimetype": "multipart/related;type=image/tiff",
                "parameters": {
                    "chunk_shape": (1, 768, 1024),
                    "file_template": "ophyd_async_tests_{:06d}.tiff",
                },
                "uid": ANY,
                "uri": uri_dir,
            },
        ),
    ]
    assert sd == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 1},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[0][1]["uid"],
                "uid": ANY,
            },
        ),
    ]


async def test_flyscan_aravis_detector(static_path_provider: StaticPathProvider):
    async with init_devices(mock=True):
        det = adaravis.AravisDetector("PREFIX:", static_path_provider)

    writer = det.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(det.driver.model, "A funny model")
    set_mock_value(det.driver.acquire_period, 0.1)
    set_mock_value(det.driver.acquire_time, 0.05)
    set_mock_value(det.driver.array_size_x, 1024)
    set_mock_value(det.driver.array_size_y, 768)
    await det.stage()
    # Check the model is in the configuration too
    config_description = await det.describe_configuration()
    assert config_description == {
        "det-driver-acquire_period": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://PREFIX:cam1:AcquirePeriod_RBV",
        },
        "det-driver-acquire_time": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://PREFIX:cam1:AcquireTime_RBV",
        },
        "det-driver-model": {
            "dtype": "string",
            "dtype_numpy": "|S40",
            "shape": [],
            "source": "mock+ca://PREFIX:cam1:Model_RBV",
        },
    }
    await assert_configuration(
        det,
        {
            "det-driver-acquire_period": {"value": 0.1},
            "det-driver-acquire_time": {"value": 0.05},
            "det-driver-model": {"value": "A funny model"},
        },
    )
    # Prepare for N frames
    set_mock_value(writer.file_path_exists, True)
    await det.prepare(TriggerInfo(collections_per_event=3, number_of_events=5))
    # Check it is making 3 collections in each event
    path_info = static_path_provider()
    description = await det.describe()
    uri = f"file://localhost{path_info.directory_path}/{path_info.filename}.h5"
    assert description == {
        "det": {
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
            "shape": [3, 768, 1024],
            "source": uri,
        },
    }
    assert det.hints == {"fields": ["det"]}
    # Kick it off and start it completing
    await det.kickoff()
    status = det.complete()
    # Check it makes nothing
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == []
    # Make 2 and 1/3 events and check they are produced
    set_mock_value(writer.num_captured, 7)
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == [
        (
            "stream_resource",
            {
                "data_key": "det",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (1, 768, 1024),
                    "dataset": "/entry/data/data",
                },
                "uid": ANY,
                "uri": uri,
            },
        ),
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 2},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": ANY,
                "uid": ANY,
            },
        ),
    ]
    assert not status.done
    # Update and check it completes
    set_mock_value(writer.num_captured, 15)
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 2, "stop": 5},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": ANY,
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
        await det.kickoff()
    # But preparing again is ok
    await det.prepare(TriggerInfo(collections_per_event=3, number_of_events=3))
    await det.kickoff()
    # Completing adds indexes to the same resource
    status = det.complete()
    set_mock_value(writer.num_captured, 24)
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 5, "stop": 8},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": ANY,
                "uid": ANY,
            },
        ),
    ]


async def test_2_rois_with_hdf(tmp_path):
    path_provider = StaticPathProvider(
        lambda device_name=None: str(device_name), tmp_path
    )
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    rois: list[adcore.NDROIIO] = []
    hdfs: list[adcore.NDFileHDF5IO] = []
    logics: list[DetectorDataLogic] = []
    for i in range(1, 3):
        roi = adcore.NDROIIO(f"PREFIX:ROI{i}")
        hdf = adcore.NDFileHDF5IO(f"PREFIX:HDF{i}")
        rois.append(roi)
        hdfs.append(hdf)
        logics.append(
            adcore.ADHDFDataLogic(
                description=adcore.NDArrayDescription(
                    shape_signals=(roi.size_y, roi.size_x),
                    data_type_signal=driver.data_type,
                ),
                path_provider=path_provider,
                driver=driver,
                writer=hdf,
                datakey_suffix=f"-roi{i}",
            )
        )
    async with init_devices(mock=True):
        det = adcore.AreaDetector(
            driver,
            arm_logic=adcore.ADArmLogic(driver),
            writer_type=None,
            plugins={
                "hdf1": hdfs[0],
                "hdf2": hdfs[1],
                "roi1": rois[0],
                "roi2": rois[1],
            },
        )
        det.add_logics(*logics)
    await det.stage()

    # When arm is pressed, then make a single frame on each HDF
    def publish_captured(v, wait):
        for hdf in hdfs:
            set_mock_value(hdf.num_captured, 1)

    callback_on_mock_put(det.driver.acquire, publish_captured)
    # Setup the size of the rois and say the directory exists
    set_mock_value(rois[0].size_x, 400)
    set_mock_value(rois[0].size_y, 300)
    set_mock_value(rois[1].size_x, 200)
    set_mock_value(rois[1].size_y, 100)
    set_mock_value(hdfs[0].file_path_exists, True)
    set_mock_value(hdfs[1].file_path_exists, True)
    # Trigger a single frame then describe and read
    await det.trigger()
    description = await det.describe()
    path_info = path_provider()
    uri1 = f"file://localhost{path_info.directory_path}/det-hdf1.h5"
    uri2 = f"file://localhost{path_info.directory_path}/det-hdf2.h5"
    assert description == {
        "det-roi1": {
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
            "shape": [1, 300, 400],
            "source": uri1,
        },
        "det-roi2": {
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
            "shape": [1, 100, 200],
            "source": uri2,
        },
    }
    assert det.hints == {"fields": ["det-roi1", "det-roi2"]}
    docs = [doc async for doc in det.collect_asset_docs()]
    sr = docs[0:4:2]
    sd = docs[1:5:2]
    assert sr == [
        (
            "stream_resource",
            {
                "data_key": "det-roi1",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (1, 300, 400),
                    "dataset": "/entry/data/data",
                },
                "uid": ANY,
                "uri": uri1,
            },
        ),
        (
            "stream_resource",
            {
                "data_key": "det-roi2",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (1, 100, 200),
                    "dataset": "/entry/data/data",
                },
                "uid": ANY,
                "uri": uri2,
            },
        ),
    ]
    assert sd == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 1},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[0][1]["uid"],
                "uid": ANY,
            },
        ),
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 1},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": sr[1][1]["uid"],
                "uid": ANY,
            },
        ),
    ]


async def test_simdetector_with_stats_signal():
    stat = adcore.NDStatsIO("PREFIX:STAT:")
    async with init_devices(mock=True):
        det = adsimdetector.SimDetector(
            "PREFIX:", writer_type=None, plugins={"stats": stat}
        )
        det.add_logics(adcore.PluginSignalDataLogic(det.driver, stat.total))
    set_mock_value(stat.total, 1.8)
    await det.stage()
    assert await det.driver.wait_for_plugins.get_value() is False
    await det.trigger()
    assert await det.driver.wait_for_plugins.get_value() is True
    description = await det.describe()
    assert description == {
        "det-stats-total": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://PREFIX:STAT:Total_RBV",
        }
    }
    await assert_reading(det, {"det-stats-total": {"value": 1.8}})
    assert det.hints == {"fields": ["det-stats-total"]}
