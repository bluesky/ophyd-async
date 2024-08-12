import io
import logging
import logging.handlers
from unittest.mock import MagicMock, patch

import pytest

from ophyd_async.core import Device, _log, config_ophyd_async_logging

# Allow this importing of _log for now to test the internal interface
# But this needs resolving.


def test_validate_level():
    assert _log._validate_level("CRITICAL") == 50
    assert _log._validate_level("ERROR") == 40
    assert _log._validate_level("WARNING") == 30
    assert _log._validate_level("INFO") == 20
    assert _log._validate_level("DEBUG") == 10
    assert _log._validate_level("NOTSET") == 0
    assert _log._validate_level(123) == 123
    with pytest.raises(ValueError):
        _log._validate_level("MYSTERY")


def test_default_config_ophyd_async_logging():
    config_ophyd_async_logging()
    assert isinstance(_log.current_handler, logging.StreamHandler)
    assert _log.logger.getEffectiveLevel() <= logging.WARNING


def test_config_ophyd_async_logging_with_file_handler(tmp_path):
    config_ophyd_async_logging(file=tmp_path / "file")
    assert isinstance(_log.current_handler, logging.StreamHandler)
    assert _log.logger.getEffectiveLevel() <= logging.WARNING


def test_config_ophyd_async_logging_removes_extra_handlers():
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
        _log.ColoredFormatterWithDeviceName(
            fmt=_log.DEFAULT_FORMAT, datefmt=_log.DEFAULT_DATE_FORMAT, no_color=True
        )
    )
    _log.logger.addHandler(log_stream)

    device = Device(name="test_device")
    device._log = logging.LoggerAdapter(
        logging.getLogger("ophyd_async.devices"),
        {"ophyd_async_device_name": device.name},
    )
    device._log.warning("here is a warning")
    assert log_buffer.getvalue().startswith("[test_device]")
    assert log_buffer.getvalue().endswith("here is a warning\n")
