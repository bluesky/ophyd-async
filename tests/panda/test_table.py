import numpy as np
import pytest

from ophyd_async.panda.table import seq_table_from_arrays


def test_from_arrays_inconsistent_lengths():
    length = 4
    time2 = np.zeros(length)
    time1 = np.zeros(length + 1)
    with pytest.raises(ValueError, match='time1: has length 5 not 4'):
        seq_table_from_arrays(time2=time2, time1=time1)
    time1 = np.zeros(length - 1)
    with pytest.raises(ValueError, match='time1: has length 3 not 4'):
        seq_table_from_arrays(time2=time2, time1=time1)


def test_from_arrays_no_time():
    with pytest.raises(AssertionError, match='time2 must be provided'):
        seq_table_from_arrays(time2=None)  # type: ignore
    with pytest.raises(TypeError, match='required keyword-only argument: \'time2\''):
        seq_table_from_arrays()  # type: ignore
    time2 = np.zeros(0)
    with pytest.raises(AssertionError, match='Length 0 not in range'):
        seq_table_from_arrays(time2=time2)


def test_from_arrays_too_long():
    time2 = np.zeros(4097)
    with pytest.raises(AssertionError, match='Length 4097 not in range'):
        seq_table_from_arrays(time2=time2)
