import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import ANY, patch

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import pytest
from bluesky.run_engine import RunEngine
from bluesky.utils import MsgGenerator
from event_model.documents import (
    DocumentType,
    Event,
    EventDescriptor,
    RunStart,
    RunStop,
    StreamDatum,
    StreamResource,
)

from ophyd_async.core import (
    StaticPathProvider,
    TriggerInfo,
    YamlSettingsProvider,
    init_devices,
)
from ophyd_async.epics.adsimdetector import SimDetector
from ophyd_async.plan_stubs import (
    apply_settings,
    apply_settings_if_different,
    get_current_settings,
    retrieve_settings,
)

TIMEOUT = 10.0


@pytest.fixture(scope="module", autouse=True)
def with_env():
    with patch.dict(
        os.environ,
        {
            "EPICS_CA_NAME_SERVERS": "127.0.0.1:9064",
            "EPICS_PVA_NAME_SERVERS": "127.0.0.1:9075",
        },
        clear=False,
    ):
        yield


@pytest.fixture
def adsim(RE: RunEngine) -> SimDetector:
    prefix = "BL01T"
    provider = StaticPathProvider(lambda _: "adsim", Path("/tmp"))
    with init_devices():
        adsim = SimDetector(
            f"{prefix}-DI-CAM-01:",
            path_provider=provider,
            drv_suffix="DET:",
            fileio_suffix="HDF5:",
        )

    RE(apply_baseline_settings(adsim))

    return adsim


def apply_baseline_settings(adsim: SimDetector) -> MsgGenerator[None]:
    current_settings = yield from get_current_settings(adsim)
    provider = YamlSettingsProvider(Path(__file__).parent)
    baseline_settings = yield from retrieve_settings(
        provider,
        "baseline",
        adsim,
    )
    yield from apply_settings_if_different(
        baseline_settings,
        apply_plan=apply_settings,
        current_settings=current_settings,
    )


@pytest.mark.timeout(TIMEOUT + 3.0)
@pytest.mark.xfail(reason="https://github.com/bluesky/ophyd-async/issues/998")
def test_prepare_is_idempotent_and_sets_exposure_time(
    RE: RunEngine, adsim: SimDetector
) -> None:
    def prepare_then_count() -> MsgGenerator[None]:
        yield from bps.prepare(
            adsim,
            TriggerInfo(livetime=0.2),
            wait=True,
        )
        yield from bp.count([adsim])

    RE(prepare_then_count())

    actual_exposure_time: float = RE(bps.rd(adsim.driver.acquire_time)).plan_result
    assert actual_exposure_time == 0.2


@pytest.mark.insubprocess
@pytest.mark.skipif(
    sys.platform.startswith("win"), reason="Services not set up on Windows"
)
@pytest.mark.timeout(TIMEOUT + 15.0)
def test_software_triggering(RE: RunEngine, adsim: SimDetector) -> None:
    docs = run_plan_and_get_documents(RE, bp.count([adsim], num=2))
    assert docs == [
        RunStart(
            uid=ANY,
            time=ANY,
            versions=ANY,
            scan_id=ANY,
            plan_type="generator",
            plan_name="count",
            detectors=["adsim"],
            num_points=2,
            num_intervals=1,
            plan_args={
                "detectors": [ANY],
                "num": 2,
                "delay": 0.0,
            },
            hints={
                "dimensions": [
                    (
                        ("time",),
                        "primary",
                    ),
                ],
            },
        ),
        EventDescriptor(
            uid=ANY,
            time=ANY,
            name="primary",
            configuration={
                "adsim": {
                    "data": {
                        "adsim-driver-acquire_period": 0.005,
                        "adsim-driver-acquire_time": 0.1,
                    },
                    "timestamps": {
                        "adsim-driver-acquire_period": ANY,
                        "adsim-driver-acquire_time": ANY,
                    },
                    "data_keys": {
                        "adsim-driver-acquire_period": {
                            "dtype": "number",
                            "shape": [],
                            "dtype_numpy": "<f8",
                            "source": "ca://BL01T-DI-CAM-01:DET:AcquirePeriod_RBV",
                            "units": "",
                            "precision": 3,
                        },
                        "adsim-driver-acquire_time": {
                            "dtype": "number",
                            "shape": [],
                            "dtype_numpy": "<f8",
                            "source": "ca://BL01T-DI-CAM-01:DET:AcquireTime_RBV",
                            "units": "",
                            "precision": 3,
                        },
                    },
                }
            },
            data_keys={
                "adsim": {
                    "source": "ca://BL01T-DI-CAM-01:HDF5:FullFileName_RBV",
                    "shape": [1, 1024, 1024],
                    "dtype": "array",
                    "dtype_numpy": "|i1",
                    "external": "STREAM:",
                    "object_name": "adsim",
                }
            },
            object_keys={"adsim": ["adsim"]},
            run_start=ANY,
            hints={"adsim": {"fields": ["adsim"]}},
        ),
        StreamResource(
            uid=ANY,
            run_start=ANY,
            data_key="adsim",
            mimetype="application/x-hdf5",
            uri="file://localhost/tmp/adsim.h5",
            parameters={
                "dataset": "/entry/data/data",
                "chunk_shape": (1, 1024, 1024),
            },
        ),
        StreamDatum(
            stream_resource=ANY,
            descriptor=ANY,
            uid=ANY,
            seq_nums={"start": 1, "stop": 2},
            indices={"start": 0, "stop": 1},
        ),
        Event(
            uid=ANY,
            time=ANY,
            descriptor=ANY,
            data={},
            timestamps={},
            seq_num=1,
            filled={},
        ),
        StreamDatum(
            stream_resource=ANY,
            descriptor=ANY,
            uid=ANY,
            seq_nums={"start": 2, "stop": 3},
            indices={"start": 1, "stop": 2},
        ),
        Event(
            uid=ANY,
            time=ANY,
            descriptor=ANY,
            data={},
            timestamps={},
            seq_num=2,
            filled={},
        ),
        RunStop(
            run_start=ANY,
            uid=ANY,
            time=ANY,
            exit_status="success",
            reason="",
            num_events={"primary": 2},
        ),
    ]


def run_plan_and_get_documents(
    RE: RunEngine, plan: MsgGenerator[Any]
) -> list[DocumentType]:
    docs = []
    RE(plan, lambda name, doc: docs.append(doc))
    return docs
