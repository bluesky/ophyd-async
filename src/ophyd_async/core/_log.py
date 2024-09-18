import logging
import sys

import colorlog

__all__ = (
    "config_ophyd_async_logging",
    "logger",
    "set_handler",
)

DEFAULT_FORMAT = (
    "%(log_color)s[%(levelname)1.1s %(asctime)s.%(msecs)03d "
    "%(module)s:%(lineno)d] %(message)s"
)

DEFAULT_DATE_FORMAT = "%y%m%d %H:%M:%S"

DEFAULT_LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red,bg_white",
}


class ColoredFormatterWithDeviceName(colorlog.ColoredFormatter):
    def format(self, record):
        message = super().format(record)
        if hasattr(record, "ophyd_async_device_name"):
            message = f"[{record.ophyd_async_device_name}]{message}"  # type: ignore
        return message


def _validate_level(level) -> int:
    """Return an int for level comparison."""
    if isinstance(level, int):
        levelno = level
    elif isinstance(level, str):
        levelno = logging.getLevelName(level)
    else:
        raise TypeError(f"Level {level!r} is not an int or str")

    if isinstance(levelno, int):
        return levelno
    else:
        raise ValueError(
            "Your level is illegal, please use "
            "'CRITICAL', 'FATAL', 'ERROR', 'WARNING', 'INFO', or 'DEBUG'."
        )


logger = logging.getLogger("ophyd_async")

current_handler = None  # overwritten below


def config_ophyd_async_logging(
    file=sys.stdout,
    fmt=DEFAULT_FORMAT,
    datefmt=DEFAULT_DATE_FORMAT,
    color=True,
    level="WARNING",
):
    """
    Set a new handler on the ``logging.getLogger('ophyd_async')`` logger.
    If this is called more than once, the handler from the previous invocation
    is removed (if still present) and replaced.

    Parameters
    ----------
    file : object with ``write`` method or filename string
        Default is ``sys.stdout``.
    fmt : Overall logging format
    datefmt : string
        Date format. Default is ``'%H:%M:%S'``.
    color : boolean
        Use ANSI color codes. True by default.
    level : str or int
        Python logging level, given as string or corresponding integer.
        Default is 'WARNING'.

    Returns
    -------
    handler : logging.Handler
        The handler, which has already been added to the 'ophyd_async' logger.

    Examples
    --------
    Log to a file.

        config_ophyd_async_logging(file='/tmp/what_is_happening.txt')

    Include the date along with the time. (The log messages will always include
    microseconds, which are configured separately, not as part of 'datefmt'.)

        config_ophyd_async_logging(datefmt="%Y-%m-%d %H:%M:%S")

    Turn off ANSI color codes.

        config_ophyd_async_logging(color=False)

    Increase verbosity: show level DEBUG or higher.

        config_ophyd_async_logging(level='DEBUG')

    """
    global current_handler

    if isinstance(file, str):
        handler = logging.FileHandler(file)
        formatter = ColoredFormatterWithDeviceName(
            fmt=fmt, datefmt=datefmt, no_color=True
        )
    else:
        handler = colorlog.StreamHandler(file)
        formatter = ColoredFormatterWithDeviceName(
            fmt=fmt, datefmt=datefmt, log_colors=DEFAULT_LOG_COLORS, no_color=color
        )

    levelno = _validate_level(level)
    handler.setFormatter(formatter)
    handler.setLevel(levelno)

    if current_handler in logger.handlers:
        logger.removeHandler(current_handler)
    logger.addHandler(handler)

    current_handler = handler

    if logger.getEffectiveLevel() > levelno:
        logger.setLevel(levelno)
    try:
        return handler
    finally:
        handler.close()


set_handler = config_ophyd_async_logging  # for back-compat
