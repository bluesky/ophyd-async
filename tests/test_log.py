import io
import logging
import logging.handlers
from unittest.mock import MagicMock, patch

import pytest

from ophyd_async import log
from ophyd_async.core import Device
from ophyd_async.log import DEFAULT_DATE_FORMAT, DEFAULT_FORMAT


def test_validate_level():
    assert log._validate_level("CRITICAL") == 50
    assert log._validate_level("ERROR") == 40
    assert log._validate_level("WARNING") == 30
    assert log._validate_level("INFO") == 20
    assert log._validate_level("DEBUG") == 10
    assert log._validate_level("NOTSET") == 0
    assert log._validate_level(123) == 123
    with pytest.raises(ValueError):
        log._validate_level("MYSTERY")


@patch("ophyd_async.log.current_handler")
@patch("ophyd_async.log.logging.Logger.addHandler")
def test_default_config_ophyd_async_logging(mock_add_handler, mock_current_handler):
    log.config_ophyd_async_logging()
    assert isinstance(log.current_handler, logging.StreamHandler)
    assert log.logger.getEffectiveLevel() <= logging.WARNING


@patch("ophyd_async.log.current_handler")
@patch("ophyd_async.log.logging.FileHandler")
@patch("ophyd_async.log.logging.Logger.addHandler")
def test_config_ophyd_async_logging_with_file_handler(
    mock_add_handler, mock_file_handler, mock_current_handler
):
    log.config_ophyd_async_logging(file="file")
    assert isinstance(log.current_handler, MagicMock)
    assert log.logger.getEffectiveLevel() <= logging.WARNING


@patch("ophyd_async.log.current_handler")
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
        patch("ophyd_async.log.logger", fake_logger),
    ):
        log.config_ophyd_async_logging()
        fake_logger.removeHandler.assert_not_called()
        log.config_ophyd_async_logging()
        fake_logger.removeHandler.assert_called()


# Full format looks like:
#'[test_device][W 240501 13:28:08.937 test_log:35] here is a warning\n'
def test_logger_adapter_ophyd_async_device():
    log_buffer = io.StringIO()
    log_stream = logging.StreamHandler(stream=log_buffer)
    log_stream.setFormatter(
        log.ColoredFormatterWithDeviceName(
            fmt=DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT, no_color=True
        )
    )
    log.logger.addHandler(log_stream)

    device = Device(name="test_device")
    device.log = logging.LoggerAdapter(
        logging.getLogger("ophyd_async.devices"),
        {"ophyd_async_device_name": device.name},
    )
    device.log.warning("here is a warning")
    assert log_buffer.getvalue().startswith("[test_device]")
    assert log_buffer.getvalue().endswith("here is a warning\n")
