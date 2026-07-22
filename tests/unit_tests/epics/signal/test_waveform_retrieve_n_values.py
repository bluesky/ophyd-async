from typing import Annotated as A

import numpy as np
import pytest

from ophyd_async.core import (
    Array1D,
    DeviceMock,
    StandardReadable,
    StandardReadableFormat as Format,
    SignalRW,
)
from ophyd_async.epics.core import EpicsDevice, EpicsOptions, PvSuffix


class DevCa(StandardReadable, EpicsDevice):
    wf: A[
        SignalRW[Array1D[np.float64]],
        PvSuffix("wf"),
        Format.UNCACHED_SIGNAL,
    ]


class DevCaFirstElements(StandardReadable, EpicsDevice):
    wf: A[
        SignalRW[Array1D[np.float64]],
        PvSuffix("wf"),
        Format.UNCACHED_SIGNAL,
        EpicsOptions(element_count=10),
    ]



async def wf_verify_data(dev: StandardReadable, expected_len: int) -> np.ndarray:
    des = await dev.describe()
    assert list(des) == ["test_ca-wf"]

    shape = tuple(des["test_ca-wf"]["shape"])
    assert shape == (expected_len,)

    data = await dev.read()
    assert list(data) == ["test_ca-wf"]

    wf_data = data["test_ca-wf"]["value"]
    assert len(wf_data) == shape[0]
    return wf_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_cls,prefix,expected_len",
    [
        (DevCa, "ca://test:", 20),
        (DevCa, "pva://test:", 20),
        # Mock test do not yet work for subarrays
        # (DevCaFirstElements, "ca://test:", 10),
        # (DevCaFirstElements, "pva://test:", 10),
    ],
)
async def test_waveform(device_cls, prefix, expected_len, epics_server):
    dev = device_cls(prefix, name="test_ca")
    await dev.connect(mock=DeviceMock())
    await dev.wf.set(np.arange(20, dtype=np.float64))
    data = await wf_verify_data(dev, expected_len=expected_len)
    assert len(data) == expected_len

