from unittest.mock import AsyncMock, MagicMock

import pytest

from ophyd_async.core import DetectorTrigger, StandardDetector, TriggerInfo


@pytest.fixture
def mock_controller():
    controller = MagicMock()
    controller.get_deadtime = MagicMock(return_value=0.5)
    controller.prepare = AsyncMock(return_value={})
    controller.arm = AsyncMock()
    return controller


@pytest.fixture
def mock_writer():
    writer = MagicMock()
    writer.open = AsyncMock(return_value={})
    writer.get_indices_written = AsyncMock(return_value=0)
    return writer


@pytest.fixture
def standard_detector(mock_controller, mock_writer):
    return StandardDetector(
        controller=mock_controller,
        writer=mock_writer,
        config_sigs=[],
        name="test_detector",
    )


async def test_prepare_internal_trigger(standard_detector):
    trigger_info = TriggerInfo(
        number_of_triggers=1,
        trigger=DetectorTrigger.INTERNAL,
        deadtime=None,
        livetime=None,
        frame_timeout=None,
    )
    await standard_detector.prepare(trigger_info)
    assert standard_detector._trigger_info == trigger_info
    assert standard_detector._number_of_triggers_iter is not None
    assert standard_detector._initial_frame == 0
    standard_detector.writer.open.assert_called_once_with(trigger_info.multiplier)
    standard_detector.controller.prepare.assert_called_once_with(trigger_info)


async def test_prepare_external_trigger(standard_detector):
    trigger_info = TriggerInfo(
        number_of_triggers=1,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=1.0,
        livetime=None,
        frame_timeout=None,
    )
    await standard_detector.prepare(trigger_info)
    assert standard_detector._trigger_info == trigger_info
    assert standard_detector._number_of_triggers_iter is not None
    assert standard_detector._initial_frame == 0
    standard_detector.writer.open.assert_called_once_with(trigger_info.multiplier)
    standard_detector.controller.prepare.assert_called_once_with(trigger_info)
    standard_detector.controller.arm.assert_called_once()


async def test_prepare_external_trigger_no_deadtime(standard_detector):
    trigger_info = TriggerInfo(
        number_of_triggers=1,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=None,  # Less than the required 0.5 set in the fixture
        livetime=None,
        frame_timeout=None,
    )
    with pytest.raises(
        ValueError,
        match=r"Deadtime must be supplied when in externally triggered mode",
    ):
        await standard_detector.prepare(trigger_info)


async def test_prepare_external_trigger_insufficient_deadtime(standard_detector):
    trigger_info = TriggerInfo(
        number_of_triggers=1,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=0.4,  # Less than the required 0.5 set in the fixture
        livetime=None,
        frame_timeout=None,
    )
    with pytest.raises(
        ValueError,
        match=r"Detector .* needs at least 0.5s deadtime, but trigger logic provides only",
    ):
        await standard_detector.prepare(trigger_info)
