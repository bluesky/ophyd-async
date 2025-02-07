"""Top level API."""

from . import core
from ._version import version

__version__ = version
"""Version number as calculated by https://github.com/pypa/setuptools_scm"""

__all__ = ["__version__", "core"]
