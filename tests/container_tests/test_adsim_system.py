"""System tests driving a real areaDetector IOC.

These are the only tests in the suite that run containers, so the rules they live
by are written down here rather than somewhere more general.

**Paths must mean the same thing on both sides.** The IOC is started by `docker
compose` against the *host's* container engine (see the `bl01t_di_cam_01`
fixture), so every path in a compose file resolves on the host - not here. A
directory handed to the IOC, as `StaticPathProvider` does below, travels over
Channel Access as a plain string and is opened by the IOC in *its own*
filesystem, so it has to resolve to the same directory there as it does here.
pytest's `tmp_path` does not: a devcontainer's /tmp is not the host's /tmp, and
no IOC container mounts /tmp either way, so the IOC reports the directory missing
and refuses to write. Use `shared_tmp_path`, which is mounted into the IOC at the
same absolute path - see tests/compose-shared-tmp.yaml for how, and note it must
keep working both in a devcontainer and on a bare host (CI), which resolve that
path by different means.

**The IOC outlives each test.** It is started once per module, so whatever a test
leaves configured is what the next test finds, however narrowly the device
fixture is scoped - the device object is not the state that persists, the IOC is.
`reset_adsim_to_baseline` puts it back to a known state before every test, which
is what lets these pass in any order.

**These tests only pass in a pytest session of their own**, which is why they
live here rather than under tests/system_tests - see this directory's conftest.
"""

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import ANY, patch

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import pytest
from aioca import purge_channel_caches
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
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    YamlSettingsProvider,
    init_devices,
)
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore import AreaDetector
from ophyd_async.epics.adsimdetector import SimDetector
from ophyd_async.plan_stubs import (
    apply_settings,
    apply_settings_if_different,
    get_current_settings,
    retrieve_settings,
)

TIMEOUT = 60.0  # allow extra time for docker compose

# Applies to every test here, not just the one that used to carry it: they all
# need the IOC, and the IOC needs services that are not set up on Windows.
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"), reason="Services not set up on Windows"
)


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


@pytest.fixture(autouse=True)
def _aioca_cleanup(event_loop):
    """
    Ensure EPICS CA channels/subscriptions are purged while the asyncio loop
    is still alive, so CA callbacks don't target a closed loop.
    """
    yield
    purge_channel_caches()


@pytest.fixture
def adsim(RE: RunEngine, shared_tmp_path: Path) -> AreaDetector:
    prefix = "BL01T"
    provider = StaticPathProvider(StaticFilenameProvider("adsim"), shared_tmp_path)
    with init_devices():
        adsim = SimDetector(
            f"{prefix}-DI-CAM-01:",
            adcore.ADWriterFactory.hdf(provider, writer_suffix="HDF5:"),
            driver_suffix="DET:",
        )

    return adsim


@pytest.fixture(autouse=True)
def reset_adsim_to_baseline(RE: RunEngine, adsim: SimDetector) -> None:
    """Put the detector back to a known state before every test.

    The IOC is shared by the whole module, so its state outlives any one test
    however narrowly the device is scoped: a test that leaves the driver
    configured differently - `test_prepare_is_idempotent_and_sets_exposure_time`
    sets a 0.2s exposure - would otherwise decide what the next test sees. Every
    test starts from the baseline instead, so they pass in any order.
    """
    RE(apply_baseline_settings(adsim))


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
def test_prepare_is_idempotent_and_sets_exposure_time(
    RE: RunEngine, adsim: SimDetector, bl01t_di_cam_01: None
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


@pytest.mark.timeout(TIMEOUT + 15.0)
def test_software_triggering(
    RE: RunEngine, adsim: SimDetector, bl01t_di_cam_01: None, shared_tmp_path: Path
) -> None:
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
                    # The main dataset's source is the file it is written to;
                    # only NDAttributes carry a PV as their source.
                    "source": (
                        f"file://localhost/"
                        f"{shared_tmp_path.as_posix().lstrip('/')}/adsim.h5"
                    ),
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
            uri=f"file://localhost/{shared_tmp_path.as_posix().lstrip('/')}/adsim.h5",
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
