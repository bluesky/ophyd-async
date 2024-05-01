import io
import logging
import logging.handlers

import pytest

from ophyd_async.core import Device, log
from ophyd_async.core.log import DEFAULT_DATE_FORMAT, DEFAULT_FORMAT


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


def test_default_config_ophyd_async_logging():
    log.config_ophyd_async_logging()
    assert isinstance(log.current_handler, logging.StreamHandler)
    assert log.logger.getEffectiveLevel() <= logging.WARNING


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
    device.log.warning("here is a warning")
    assert log_buffer.getvalue().startswith("[test_device]")
    assert log_buffer.getvalue().endswith("here is a warning\n")
