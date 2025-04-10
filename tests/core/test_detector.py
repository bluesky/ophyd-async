from unittest.mock import AsyncMock, MagicMock

import pytest

from ophyd_async.core import DetectorTrigger, StandardDetector, TriggerInfo
from ophyd_async.core._detector import _ensure_trigger_info_exists  # noqa: PLC2701


@pytest.fixture
def mock_controller() -> MagicMock:
    controller = MagicMock()
    controller.get_deadtime = MagicMock(return_value=0.5)
    controller.get_exposures_per_event = AsyncMock(return_value=1)
    controller.prepare = AsyncMock(return_value={})
    controller.arm = AsyncMock()
    return controller


@pytest.fixture
def mock_writer() -> MagicMock:
    writer = MagicMock()
    writer.open = AsyncMock(return_value={})
    writer.get_indices_written = AsyncMock(return_value=0)
    return writer


@pytest.fixture
def standard_detector(
    mock_controller: MagicMock, mock_writer: MagicMock
) -> StandardDetector:
    return StandardDetector(
        controller=mock_controller,
        writer=mock_writer,
        config_sigs=[],
        name="test_detector",
    )


async def test_prepare_internal_trigger(standard_detector: StandardDetector) -> None:
    trigger_info = TriggerInfo(
        number_of_events=1,
        trigger=DetectorTrigger.INTERNAL,
        deadtime=0,
        livetime=None,
        exposure_timeout=None,
    )
    await standard_detector.prepare(trigger_info)
    assert standard_detector._trigger_info == trigger_info
    assert standard_detector._number_of_events_iter is not None
    assert standard_detector._initial_frame == 0
    assert standard_detector._name == "test_detector"
    standard_detector._writer.open.assert_called_once_with(
        standard_detector._name, trigger_info.exposures_per_event or 1
    )  # type: ignore
    standard_detector._controller.prepare.assert_called_once_with(trigger_info)  # type: ignore


async def test_prepare_external_trigger(standard_detector: StandardDetector) -> None:
    trigger_info = TriggerInfo(
        number_of_events=1,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=1.0,
        livetime=None,
        exposure_timeout=None,
    )
    await standard_detector.prepare(trigger_info)
    assert standard_detector._trigger_info == trigger_info
    assert standard_detector._number_of_events_iter is not None
    assert standard_detector._initial_frame == 0
    standard_detector._writer.open.assert_called_once_with(
        standard_detector.name, trigger_info.exposures_per_event or 1
    )  # type: ignore
    standard_detector._controller.prepare.assert_called_once_with(trigger_info)  # type: ignore
    standard_detector._controller.arm.assert_called_once()  # type: ignore


async def test_prepare_external_trigger_no_deadtime(
    standard_detector: StandardDetector,
) -> None:
    trigger_info = TriggerInfo(
        number_of_events=1,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=0,  # Less than the required 0.5 set in the fixture
        livetime=None,
        exposure_timeout=None,
    )
    with pytest.raises(
        ValueError,
        match=r"Deadtime must be supplied when in externally triggered mode",
    ):
        await standard_detector.prepare(trigger_info)


async def test_prepare_external_trigger_insufficient_deadtime(
    standard_detector: StandardDetector,
) -> None:
    trigger_info = TriggerInfo(
        number_of_events=1,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=0.4,  # Less than the required 0.5 set in the fixture
        livetime=None,
        exposure_timeout=None,
    )
    with pytest.raises(
        ValueError,
        match=r"Detector .* needs at least 0.5s deadtime, but trigger logic provides only",  # noqa: E501
    ):
        await standard_detector.prepare(trigger_info)


def test_ensure_trigger_info_exists_success() -> None:
    trigger_info = TriggerInfo(number_of_events=1)
    assert isinstance(
        _ensure_trigger_info_exists(trigger_info=trigger_info),
        TriggerInfo,
    )


def test_ensure_trigger_info_exists_raises() -> None:
    with pytest.raises(
        RuntimeError, match="Trigger info must be set before calling this method."
    ):
        assert isinstance(
            _ensure_trigger_info_exists(trigger_info=None),
            TriggerInfo,
        )
