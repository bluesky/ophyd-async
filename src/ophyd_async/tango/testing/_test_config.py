from tango import AttrDataFormat, CmdArgType


class TestConfig:
    data_type: CmdArgType
    data_format: AttrDataFormat
    enum_labels: list[str]
