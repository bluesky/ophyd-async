import pytest
from epicscorelibs.ca import dbr
from p4p import Value as P4PValue
from p4p.nt import NTEnum

from ophyd_async.core import RuntimeEnum
from ophyd_async.epics._backend._aioca import make_converter as aioca_make_converter
from ophyd_async.epics._backend._p4p import make_converter as p4p_make_converter
from ophyd_async.epics.signal.signal import epics_signal_rw


async def test_runtime_enum_behaviour():
    rt_enum = RuntimeEnum["A", "B"]

    with pytest.raises(RuntimeError) as exc:
        rt_enum()
    assert str(exc.value) == "RuntimeEnum cannot be instantiated"

    assert issubclass(rt_enum, RuntimeEnum)
    assert issubclass(rt_enum, RuntimeEnum["A", "B"])
    assert issubclass(rt_enum, RuntimeEnum["B", "A"])

    assert str(rt_enum) in ("RuntimeEnum['A', 'B']", "RuntimeEnum['B', 'A']")
    assert str(RuntimeEnum) == "RuntimeEnum"

    with pytest.raises(TypeError) as exc:
        RuntimeEnum["A", "B", "A"]
    assert str(exc.value) == "Duplicate elements in runtime enum choices."


async def test_ca_runtime_enum_converter():
    class EpicsValue:
        def __init__(self):
            self.name = "test"
            self.ok = (True,)
            self.errorcode = 0
            self.datatype = dbr.DBR_ENUM
            self.element_count = 1
            self.severity = 0
            self.status = 0
            self.raw_stamp = (0,)
            self.timestamp = 0
            self.datetime = 0
            self.enums = ["A", "B", "C"]  # More than the runtime enum

    epics_value = EpicsValue()
    rt_enum = RuntimeEnum["A", "B"]
    converter = aioca_make_converter(
        rt_enum, values={"READ_PV": epics_value, "WRITE_PV": epics_value}
    )
    assert converter.choices == {"A": "A", "B": "B", "C": "C"}
    assert rt_enum.choices.issubset(frozenset(converter.choices.keys()))


async def test_pva_runtime_enum_converter():
    enum_type = NTEnum.buildType()
    epics_value = P4PValue(
        enum_type,
        {
            "value.choices": ["A", "B", "C"],
        },
    )
    rt_enum = RuntimeEnum["A", "B"]
    converter = p4p_make_converter(
        rt_enum, values={"READ_PV": epics_value, "WRITE_PV": epics_value}
    )
    assert frozenset(("A", "B")).issubset(frozenset(converter.choices))


async def test_runtime_enum_signal():
    signal_rw_pva = epics_signal_rw(
        RuntimeEnum["A1", "B1"], "ca://RW_PV", name="signal"
    )
    signal_rw_ca = epics_signal_rw(RuntimeEnum["A2", "B2"], "ca://RW_PV", name="signal")
    await signal_rw_pva.connect(mock=True)
    await signal_rw_ca.connect(mock=True)
    await signal_rw_pva.get_value() == "A1"
    await signal_rw_ca.get_value() == "A2"
    await signal_rw_pva.set("B1")
    await signal_rw_ca.set("B2")
    await signal_rw_pva.get_value() == "B1"
    await signal_rw_ca.get_value() == "B2"

    # Will accept string values even if they're not in the runtime enum
    await signal_rw_pva.set("C1")
    await signal_rw_ca.set("C2")
