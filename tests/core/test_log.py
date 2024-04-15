import io
import logging
import logging.handlers
import sys
from unittest.mock import patch

import colorama
import pytest

from ophyd_async.core import Device, log
from ophyd_async.core.log import _stderr_supports_color


def test_validate_level():
    assert log.validate_level("CRITICAL") == 50
    assert log.validate_level("ERROR") == 40
    assert log.validate_level("WARNING") == 30
    assert log.validate_level("INFO") == 20
    assert log.validate_level("DEBUG") == 10
    assert log.validate_level("NOTSET") == 0
    assert log.validate_level(123) == 123
    with pytest.raises(ValueError):
        log.validate_level("MYSTERY")


def test_default_config_ophyd_async_logging():
    log.config_ophyd_async_logging()
    assert isinstance(log.current_handler, logging.StreamHandler)
    assert log.logger.getEffectiveLevel() <= logging.WARNING


def test_logger_adapter_ophyd_async_device():
    log_buffer = io.StringIO()
    log_stream = logging.StreamHandler(stream=log_buffer)
    log_stream.setFormatter(log.LogFormatter())
    log.logger.addHandler(log_stream)

    device = Device(name="test_device")
    device.log.warning("here is a warning")
    assert log_buffer.getvalue().endswith("[test_device] here is a warning\n")
    assert log_buffer.getvalue().endswith("[test_device] here is a warning\n")
    assert log_buffer.getvalue().endswith("[test_device] here is a warning\n")
    assert log_buffer.getvalue().endswith("[test_device] here is a warning\n")


def test_formatter_with_colour():
    log_buffer = io.StringIO()
    log_stream = logging.StreamHandler(stream=log_buffer)
    with (
        patch("ophyd_async.core.log._stderr_supports_color", return_value=True),
        patch("curses.tigetstr", return_value=bytes(4)),
        patch("curses.tparm", return_value=bytes(4)),
    ):
        log_stream.setFormatter(log.LogFormatter())


def test_formatter_with_colour_no_curses(monkeypatch):
    log_buffer = io.StringIO()
    log_stream = logging.StreamHandler(stream=log_buffer)
    with (
        patch("ophyd_async.core.log._stderr_supports_color", return_value=True),
        patch("curses.tigetstr", return_value=bytes(4)),
        patch("curses.tparm", return_value=bytes(4)),
    ):
        monkeypatch.delitem(sys.modules, "curses", raising=False)
        log_stream.setFormatter(log.LogFormatter())


def test_stderr_supports_color_not_atty():
    with patch("sys.stderr.isatty", return_value=False):
        assert not _stderr_supports_color()


def test_stderr_supports_color_curses_available():
    with patch("sys.stderr.isatty", return_value=True), patch("curses.setupterm"):
        with patch("curses.tigetnum", return_value=8):
            assert _stderr_supports_color()


def test_stderr_supports_color_colorama_available(monkeypatch):
    monkeypatch.delitem(sys.modules, "curses", raising=False)
    with (
        patch("sys.stderr.isatty", return_value=True),
        patch("colorama.initialise"),
    ):
        colorama.initialise.wrapped_stderr = sys.stderr
        assert _stderr_supports_color()


def test_stderr_supports_color_no_curses_no_colorama():
    with (
        patch("sys.stderr.isatty", return_value=True),
        patch("curses.setupterm"),
        patch("colorama.initialise"),
    ):
        assert not _stderr_supports_color()
