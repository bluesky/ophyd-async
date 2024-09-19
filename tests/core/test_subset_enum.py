import pytest
from epicscorelibs.ca import dbr
from p4p import Value as P4PValue
from p4p.nt import NTEnum

from ophyd_async.core import SubsetEnum
from ophyd_async.epics.signal import epics_signal_rw

# Allow these imports from private modules for tests
from ophyd_async.epics.signal._aioca import make_converter as ca_make_converter
from ophyd_async.epics.signal._p4p import make_converter as pva_make_converter


async def test_runtime_enum_behaviour():
    rt_enum = SubsetEnum["A", "B"]

    with pytest.raises(RuntimeError) as exc:
        rt_enum()
    assert str(exc.value) == "SubsetEnum cannot be instantiated"

    assert issubclass(rt_enum, SubsetEnum)

    # Our metaclass doesn't cache already created runtime enums,
    # so we can't do this
    assert not issubclass(rt_enum, SubsetEnum["A", "B"])
    assert not issubclass(rt_enum, SubsetEnum["B", "A"])
    assert rt_enum is not SubsetEnum["A", "B"]
    assert rt_enum is not SubsetEnum["B", "A"]

    assert str(rt_enum) == "SubsetEnum['A', 'B']"
    assert str(SubsetEnum) == "SubsetEnum"

    with pytest.raises(TypeError) as exc:
        SubsetEnum["A", "B", "A"]
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
    rt_enum = SubsetEnum["A", "B"]
    converter = ca_make_converter(
        rt_enum, values={"READ_PV": epics_value, "WRITE_PV": epics_value}
    )
    assert converter.choices == {"A": "A", "B": "B", "C": "C"}
    assert set(rt_enum.choices).issubset(set(converter.choices.keys()))


async def test_pva_runtime_enum_converter():
    enum_type = NTEnum.buildType()
    epics_value = P4PValue(
        enum_type,
        {
            "value.choices": ["A", "B", "C"],
        },
    )
    rt_enum = SubsetEnum["A", "B"]
    converter = pva_make_converter(
        rt_enum, values={"READ_PV": epics_value, "WRITE_PV": epics_value}
    )
    assert {"A", "B"}.issubset(set(converter.choices))


async def test_runtime_enum_signal():
    signal_rw_pva = epics_signal_rw(SubsetEnum["A1", "B1"], "ca://RW_PV", name="signal")
    signal_rw_ca = epics_signal_rw(SubsetEnum["A2", "B2"], "ca://RW_PV", name="signal")
    await signal_rw_pva.connect(mock=True)
    await signal_rw_ca.connect(mock=True)
    assert await signal_rw_pva.get_value() == "A1"
    assert await signal_rw_ca.get_value() == "A2"
    await signal_rw_pva.set("B1")
    await signal_rw_ca.set("B2")
    assert await signal_rw_pva.get_value() == "B1"
    assert await signal_rw_ca.get_value() == "B2"

    # Will accept string values even if they're not in the runtime enum
    # Though type checking should compain
    await signal_rw_pva.set("C1")  # type: ignore
    await signal_rw_ca.set("C2")  # type: ignore
