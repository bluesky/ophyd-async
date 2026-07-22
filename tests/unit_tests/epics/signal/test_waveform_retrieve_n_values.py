import asyncio
from typing import Annotated as A

import aioca
import numpy as np
import pytest
import pytest_asyncio

from ophyd_async.core import (
    Array1D,
    DeviceMock,
    SignalRW,
    StandardReadable,
)
from ophyd_async.core import (
    StandardReadableFormat as Format,
)
from ophyd_async.epics.core import EpicsDevice, EpicsOptions, PvSuffix


@pytest_asyncio.fixture
async def epics_server():
    try:
        await asyncio.wait_for(
            aioca.caget("mfp:SR12C:BPM7:signals:tdp_synth:Y"), timeout=5
        )
    except TimeoutError as exc:
        pytest.skip(f"no connection to epics server: {exc}")


class DevCa(StandardReadable, EpicsDevice):
    wf: A[
        SignalRW[Array1D[np.float64]],
        PvSuffix("signals:tdp_synth:Y"),
        Format.UNCACHED_SIGNAL,
    ]


class DevCaFirstElements(StandardReadable, EpicsDevice):
    wf: A[
        SignalRW[Array1D[np.float64]],
        PvSuffix("signals:tdp_synth:Y"),
        Format.UNCACHED_SIGNAL,
        EpicsOptions(element_count=10),
    ]


async def wf_verify_data(dev: StandardReadable, expected_len: int) -> np.ndarray:
    des = await dev.describe()
    assert list(des) == ["test-wf"]

    shape = tuple(des["test-wf"]["shape"])
    assert shape == (expected_len,)

    t_data = await dev.wf.get_value()
    assert len(t_data) == expected_len

    data = await dev.read()
    assert list(data) == ["test-wf"]

    wf_data = data["test-wf"]["value"]
    assert len(wf_data) == shape[0]
    return wf_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_cls,prefix,expected_len",
    [
        (DevCa, "ca://test:", 20),
        (DevCa, "pva://test:", 20),
        # Mock test do not yet work for requests of sub arrays
        # (DevCaFirstElements, "ca://test:", 10),
        # (DevCaFirstElements, "pva://test:", 10),
    ],
)
async def test_waveform_mock(device_cls, prefix, expected_len):
    dev = device_cls(prefix, name="test")
    await dev.connect(mock=DeviceMock())
    await dev.wf.set(np.arange(20, dtype=np.float64))
    data = await wf_verify_data(dev, expected_len=expected_len)
    assert len(data) == expected_len


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_cls,prefix,expected_len",
    [
        (DevCa, "ca://mfp:SR12C:BPM7:", 200),
        (DevCa, "pva://mfp:SR12C:BPM7:", 200),
        (DevCaFirstElements, "ca://mfp:SR12C:BPM7:", 10),
        (DevCaFirstElements, "pva://mfp:SR12C:BPM7:", 10),
    ],
)
async def test_waveform_server(device_cls, prefix, expected_len, epics_server):
    dev = device_cls(prefix, name="test")
    await dev.connect()
    data = await wf_verify_data(dev, expected_len=expected_len)
    assert len(data) == expected_len
