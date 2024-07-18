import io
import logging
import logging.handlers
from unittest.mock import MagicMock, patch

import pytest

from ophyd_async.core import Device, config_ophyd_async_logging

# Allow this importing of _log for now to test the internal interface
from ophyd_async.core._log import (
    DEFAULT_DATE_FORMAT,
    DEFAULT_FORMAT,
    ColoredFormatterWithDeviceName,
    _validate_level,
    current_handler,
    logger,
)


def test_validate_level():
    assert _validate_level("CRITICAL") == 50
    assert _validate_level("ERROR") == 40
    assert _validate_level("WARNING") == 30
    assert _validate_level("INFO") == 20
    assert _validate_level("DEBUG") == 10
    assert _validate_level("NOTSET") == 0
    assert _validate_level(123) == 123
    with pytest.raises(ValueError):
        _validate_level("MYSTERY")


@patch("ophyd_async.core._log.current_handler")
@patch("ophyd_async.core._log.logging.Logger.addHandler")
def test_default_config_ophyd_async_logging(mock_add_handler, mock_current_handler):
    config_ophyd_async_logging()
    assert isinstance(current_handler, logging.StreamHandler)
    assert logger.getEffectiveLevel() <= logging.WARNING


@patch("ophyd_async.core._log.current_handler")
@patch("ophyd_async.core._log.logging.FileHandler")
@patch("ophyd_async.core._log.logging.Logger.addHandler")
def test_config_ophyd_async_logging_with_file_handler(
    mock_add_handler, mock_file_handler, mock_current_handler
):
    config_ophyd_async_logging(file="file")
    assert isinstance(current_handler, MagicMock)
    assert logger.getEffectiveLevel() <= logging.WARNING


@patch("ophyd_async.core._log.current_handler")
def test_config_ophyd_async_logging_removes_extra_handlers(mock_current_handler):
    # Protect global variable in other pytests
    class FakeLogger:
        def __init__(self):
            self.handlers = []
            self.removeHandler = MagicMock()
            self.setLevel = MagicMock()

        def addHandler(self, handler):
            self.handlers.append(handler)

        def getEffectiveLevel(self):
            return 100000

    fake_logger = FakeLogger()
    with (
        patch("ophyd_async.core._log.logger", fake_logger),
    ):
        config_ophyd_async_logging()
        fake_logger.removeHandler.assert_not_called()
        config_ophyd_async_logging()
        fake_logger.removeHandler.assert_called()


# Full format looks like:
#'[test_device][W 240501 13:28:08.937 test_log:35] here is a warning\n'
def test_logger_adapter_ophyd_async_device():
    log_buffer = io.StringIO()
    log_stream = logging.StreamHandler(stream=log_buffer)
    log_stream.setFormatter(
        ColoredFormatterWithDeviceName(
            fmt=DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT, no_color=True
        )
    )
    logger.addHandler(log_stream)

    device = Device(name="test_device")
    device._log = logging.LoggerAdapter(
        logging.getLogger("ophyd_async.devices"),
        {"ophyd_async_device_name": device.name},
    )
    device._log.warning("here is a warning")
    assert log_buffer.getvalue().startswith("[test_device]")
    assert log_buffer.getvalue().endswith("here is a warning\n")
