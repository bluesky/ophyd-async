"""Helpful config class for testing."""

from tango import AttrDataFormat, CmdArgType


class TestConfig:
    """Configuration for a test."""

    data_type: CmdArgType
    data_format: AttrDataFormat
    enum_labels: list[str]
