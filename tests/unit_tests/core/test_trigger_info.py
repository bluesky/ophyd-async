import pytest
from pydantic import ValidationError

from ophyd_async.core import DetectorTrigger, TriggerInfo


@pytest.mark.parametrize(
    ["kwargs", "error_msg"],
    [
        (
            {
                "number_of_events": 1,
                "trigger": DetectorTrigger.EXTERNAL_LEVEL,
                "deadtime": 2,
                "livetime": 2,
                "exposure_timeout": "a",
            },
            "Input should be a valid number, unable to parse string as a number "
            "[type=float_parsing, input_value='a', input_type=str]",
        ),
        (
            {
                "number_of_events": 1,
                "trigger": "EXTERNAL_LEVEL",
                "deadtime": 2,
                "livetime": -1,
            },
            "Input should be greater than or equal to 0 "
            "[type=greater_than_equal, input_value=-1, input_type=int]",
        ),
        (
            {
                "number_of_events": 1,
                "trigger": DetectorTrigger.INTERNAL,
                "deadtime": 2,
                "livetime": 1,
                "exposure_timeout": -1,
            },
            "Input should be greater than 0 "
            "[type=greater_than, input_value=-1, input_type=int]",
        ),
        (
            {
                "number_of_events": 1,
                "trigger": "not_in_enum",
                "deadtime": 2,
                "livetime": 1,
                "exposure_timeout": None,
            },
            "Input should be 'INTERNAL', 'EXTERNAL_EDGE' or 'EXTERNAL_LEVEL' "
            "[type=enum, input_value='not_in_enum', input_type=str]",
        ),
        (
            {
                "number_of_events": -100,
            },
            "number_of_events\n  Input should be greater than or "
            "equal to 0 [type=greater_than_equal, input_value=-100, input_type=int]",
        ),
    ],
)
def test_malformed_trigger_info(kwargs, error_msg):
    with pytest.raises(ValidationError) as exc:
        TriggerInfo(**kwargs)
    assert error_msg in str(exc.value)
