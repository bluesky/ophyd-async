from functools import reduce

import numpy as np
import pytest
from pydantic import ValidationError

from ophyd_async.fastcs.panda import SeqTable
from ophyd_async.fastcs.panda._table import SeqTrigger


def test_seq_table_converts_lists():
    seq_table_dict_with_lists = {field_name: [] for field_name, _ in SeqTable()}
    # Validation passes
    seq_table = SeqTable(**seq_table_dict_with_lists)
    for field_name, field_value in seq_table:
        if field_name == "trigger":
            assert field_value == []
        else:
            assert np.array_equal(field_value, np.array([], dtype=field_value.dtype))


def test_seq_table_validation_errors():
    with pytest.raises(ValidationError, match="81 validation errors for SeqTable"):
        SeqTable(
            repeats=0,
            trigger="Immediate",
            position=0,
            time1=0,
            outa1=False,
            outb1=False,
            outc1=False,
            outd1=False,
            oute1=False,
            outf1=False,
            time2=0,
            outa2=False,
            outb2=False,
            outc2=False,
            outd2=False,
            oute2=False,
            outf2=False,
        )

    large_seq_table = SeqTable(
        repeats=np.zeros(4095, dtype=np.int32),
        trigger=np.array(["Immediate"] * 4095, dtype="U32"),
        position=np.zeros(4095, dtype=np.int32),
        time1=np.zeros(4095, dtype=np.int32),
        outa1=np.zeros(4095, dtype=np.bool_),
        outb1=np.zeros(4095, dtype=np.bool_),
        outc1=np.zeros(4095, dtype=np.bool_),
        outd1=np.zeros(4095, dtype=np.bool_),
        oute1=np.zeros(4095, dtype=np.bool_),
        outf1=np.zeros(4095, dtype=np.bool_),
        time2=np.zeros(4095, dtype=np.int32),
        outa2=np.zeros(4095, dtype=np.bool_),
        outb2=np.zeros(4095, dtype=np.bool_),
        outc2=np.zeros(4095, dtype=np.bool_),
        outd2=np.zeros(4095, dtype=np.bool_),
        oute2=np.zeros(4095, dtype=np.bool_),
        outf2=np.zeros(4095, dtype=np.bool_),
    )
    with pytest.raises(
        ValidationError,
        match=(
            "1 validation error for SeqTable\n  "
            "Assertion failed, Length 4096 not in range."
        ),
    ):
        large_seq_table + SeqTable.row()
    with pytest.raises(
        ValidationError,
        match="12 validation errors for SeqTable",
    ):
        row_one = SeqTable.row()
        wrong_types = {
            field_name: field_value.astype(np.unicode_)
            for field_name, field_value in row_one
            if isinstance(field_value, np.ndarray)
        }
        SeqTable(**wrong_types)


def test_seq_table_pva_conversion():
    pva_dict = {
        "repeats": np.array([1, 2, 3, 4], dtype=np.int32),
        "trigger": [
            SeqTrigger.IMMEDIATE,
            SeqTrigger.IMMEDIATE,
            SeqTrigger.BITC_0,
            SeqTrigger.IMMEDIATE,
        ],
        "position": np.array([1, 2, 3, 4], dtype=np.int32),
        "time1": np.array([1, 0, 1, 0], dtype=np.int32),
        "outa1": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outb1": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outc1": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outd1": np.array([1, 0, 1, 0], dtype=np.bool_),
        "oute1": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outf1": np.array([1, 0, 1, 0], dtype=np.bool_),
        "time2": np.array([1, 2, 3, 4], dtype=np.int32),
        "outa2": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outb2": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outc2": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outd2": np.array([1, 0, 1, 0], dtype=np.bool_),
        "oute2": np.array([1, 0, 1, 0], dtype=np.bool_),
        "outf2": np.array([1, 0, 1, 0], dtype=np.bool_),
    }
    row_wise_dicts = [
        {
            "repeats": 1,
            "trigger": "Immediate",
            "position": 1,
            "time1": 1,
            "outa1": 1,
            "outb1": 1,
            "outc1": 1,
            "outd1": 1,
            "oute1": 1,
            "outf1": 1,
            "time2": 1,
            "outa2": 1,
            "outb2": 1,
            "outc2": 1,
            "outd2": 1,
            "oute2": 1,
            "outf2": 1,
        },
        {
            "repeats": 2,
            "trigger": "Immediate",
            "position": 2,
            "time1": 0,
            "outa1": 0,
            "outb1": 0,
            "outc1": 0,
            "outd1": 0,
            "oute1": 0,
            "outf1": 0,
            "time2": 2,
            "outa2": 0,
            "outb2": 0,
            "outc2": 0,
            "outd2": 0,
            "oute2": 0,
            "outf2": 0,
        },
        {
            "repeats": 3,
            "trigger": "BITC=0",
            "position": 3,
            "time1": 1,
            "outa1": 1,
            "outb1": 1,
            "outc1": 1,
            "outd1": 1,
            "oute1": 1,
            "outf1": 1,
            "time2": 3,
            "outa2": 1,
            "outb2": 1,
            "outc2": 1,
            "outd2": 1,
            "oute2": 1,
            "outf2": 1,
        },
        {
            "repeats": 4,
            "trigger": "Immediate",
            "position": 4,
            "time1": 0,
            "outa1": 0,
            "outb1": 0,
            "outc1": 0,
            "outd1": 0,
            "oute1": 0,
            "outf1": 0,
            "time2": 4,
            "outa2": 0,
            "outb2": 0,
            "outc2": 0,
            "outd2": 0,
            "oute2": 0,
            "outf2": 0,
        },
    ]

    def _assert_col_equal(column1, column2):
        if isinstance(column1, np.ndarray):
            assert np.array_equal(column1, column2)
            assert column1.dtype == column2.dtype
        else:
            assert column1 == column2
            assert all(isinstance(x, SeqTrigger) for x in column1)
            assert all(isinstance(x, SeqTrigger) for x in column2)

    seq_table_from_pva_dict = SeqTable(**pva_dict)
    for (_, column1), column2 in zip(seq_table_from_pva_dict, pva_dict.values()):
        _assert_col_equal(column1, column2)

    seq_table_from_rows = reduce(
        lambda x, y: x + y,
        [SeqTable.row(**row_kwargs) for row_kwargs in row_wise_dicts],
    )
    for (_, column1), column2 in zip(seq_table_from_rows, pva_dict.values()):
        _assert_col_equal(column1, column2)

    # Idempotency
    applied_twice_to_pva_dict = SeqTable(**pva_dict).model_dump(mode="python")
    for column1, column2 in zip(applied_twice_to_pva_dict.values(), pva_dict.values()):
        _assert_col_equal(column1, column2)


def test_seq_table_takes_trigger_enum_row():
    for trigger in (SeqTrigger.BITA_0, "BITA=0"):
        table = SeqTable.row(trigger=trigger)
        assert table.trigger[0] == SeqTrigger.BITA_0
        table = SeqTable(
            repeats=np.array([1], dtype=np.int32),
            trigger=[trigger],
            position=np.array([1], dtype=np.int32),
            time1=np.array([1], dtype=np.int32),
            outa1=np.array([1], dtype=np.bool_),
            outb1=np.array([1], dtype=np.bool_),
            outc1=np.array([1], dtype=np.bool_),
            outd1=np.array([1], dtype=np.bool_),
            oute1=np.array([1], dtype=np.bool_),
            outf1=np.array([1], dtype=np.bool_),
            time2=np.array([1], dtype=np.int32),
            outa2=np.array([1], dtype=np.bool_),
            outb2=np.array([1], dtype=np.bool_),
            outc2=np.array([1], dtype=np.bool_),
            outd2=np.array([1], dtype=np.bool_),
            oute2=np.array([1], dtype=np.bool_),
            outf2=np.array([1], dtype=np.bool_),
        )
        assert table.trigger[0] == SeqTrigger.BITA_0
