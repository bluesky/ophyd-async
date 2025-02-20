"""Back compat."""

import warnings

from .core import *  # noqa: F403

warnings.warn(
    DeprecationWarning(
        "Use `ophyd_async.epics.core` instead of `ophyd_async.epics.signal` and `pvi`"
    ),
    stacklevel=2,
)

__all__ = []
