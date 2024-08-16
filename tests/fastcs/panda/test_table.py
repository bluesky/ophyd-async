import numpy as np
import pytest
from pydantic import ValidationError

from ophyd_async.fastcs.panda import SeqTable, SeqTableRowType, seq_table_row


@pytest.mark.parametrize(
    # factory so that there aren't global errors if seq_table_row() fails
    "rows_arg_factory",
    [
        lambda: None,
        list,
        lambda: [seq_table_row(), seq_table_row()],
        lambda: np.array([seq_table_row(), seq_table_row()]),
    ],
)
def test_seq_table_initialization_allowed_args(rows_arg_factory):
    rows_arg = rows_arg_factory()
    seq_table = SeqTable() if rows_arg is None else SeqTable(rows_arg)
    assert isinstance(seq_table.root, np.ndarray)
    assert len(seq_table.root) == (0 if rows_arg is None else len(rows_arg))


def test_seq_table_validation_errors():
    with pytest.raises(
        ValueError, match="Cannot construct a SeqTable, some rows are not arrays."
    ):
        SeqTable([seq_table_row().tolist()])
    with pytest.raises(ValidationError, match="Length 4098 not in range."):
        SeqTable([seq_table_row() for _ in range(4098)])
    with pytest.raises(
        ValidationError,
        match="Cannot construct a SeqTable, some rows have incorrect types.",
    ):
        SeqTable([seq_table_row(), np.array([1, 2, 3]), seq_table_row()])
    with pytest.raises(
        ValidationError,
        match="Cannot construct a SeqTable, some rows have incorrect types.",
    ):
        SeqTable(
            [
                seq_table_row(),
                np.array(range(len(seq_table_row().tolist()))),
                seq_table_row(),
            ]
        )


def test_seq_table_pva_conversion():
    expected_pva_dict = {
        "repeats": np.array([1, 2, 3, 4], dtype=np.int32),
        "trigger": np.array(
            ["Immediate", "Immediate", "BITC=0", "Immediate"], dtype="U14"
        ),
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
    expected_numpy_table = np.array(
        [
            (1, "Immediate", 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
            (2, "Immediate", 2, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0),
            (3, "BITC=0", 3, 1, 1, 1, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1),
            (4, "Immediate", 4, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0),
        ],
        dtype=SeqTableRowType,
    )

    # Can convert from PVA table
    numpy_table_from_pva_dict = SeqTable.convert_from_protocol_datatype(
        expected_pva_dict
    )
    assert np.array_equal(numpy_table_from_pva_dict.root, expected_numpy_table)
    assert (
        numpy_table_from_pva_dict.root.dtype
        == expected_numpy_table.dtype
        == SeqTableRowType
    )

    # Can convert to PVA table
    pva_dict_from_numpy_table = SeqTable(
        expected_numpy_table
    ).convert_to_protocol_datatype()
    for column1, column2 in zip(
        pva_dict_from_numpy_table.values(), expected_pva_dict.values()
    ):
        assert np.array_equal(column1, column2)
        assert column1.dtype == column2.dtype

    # Idempotency
    applied_twice_to_numpy_table = SeqTable.convert_from_protocol_datatype(
        SeqTable(expected_numpy_table).convert_to_protocol_datatype()
    )
    assert np.array_equal(applied_twice_to_numpy_table.root, expected_numpy_table)
    assert (
        applied_twice_to_numpy_table.root.dtype
        == expected_numpy_table.dtype
        == SeqTableRowType
    )

    applied_twice_to_pva_dict = SeqTable(
        SeqTable.convert_from_protocol_datatype(expected_pva_dict).root
    ).convert_to_protocol_datatype()
    for column1, column2 in zip(
        applied_twice_to_pva_dict.values(), expected_pva_dict.values()
    ):
        assert np.array_equal(column1, column2)
        assert column1.dtype == column2.dtype
