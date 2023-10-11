from ophyd_async.panda.tables import table_chunks, frame, build_table
from ophyd_async.panda import SeqTrigger

testframes = (
        (0, 0, 0, 0, 0, 0),
        (0, 0, 1, 1, 0, 0),
        (0, 1, 0, 0, 1, 0),
        (0, 1, 0, 0, 1, 0),
        (0, 0, 1, 0, 1, 0),
        (0, 1, 1, 1, 1, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 1, 1, 1, 1, 1),
        (0, 1, 0, 0, 1, 0),
        (0, 1, 0, 0, 1, 0),
        (0, 1, 0, 0, 1, 0),
        (0, 0, 1, 1, 0, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 1, 1, 0, 0),
        (0, 1, 0, 0, 1, 0),
        (0, 1, 0, 0, 1, 0),
        (0, 1, 0, 0, 1, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
)


def test_frames():
    f = frame(
    repeats = 5,
    trigger = SeqTrigger.BITB_1,
    position = 20,
    time1 = 15,
    outa1 = 1,
    outb1 = 1,
    outc1 = 0,
    outd1 = 0,
    oute1 = 1,
    outf1 = 1,
    time2 = 18,
    outa2 = 0,
    outb2 = 1,
    outc2 = 1,
    outd2 = 1,
    oute2 = 1,
    outf2 = 0,
    )
    assert f.repeats == 5
    assert f.trigger == SeqTrigger.BITB_1
    assert f.position == 20
    assert f.time1 == 15
    assert f.time2 == 18
    assert f.outa1 == f.outb1 == f.oute1 == f.outf1 == f.outb2 == f.outc2 == f.outd2 == f.oute2 == 1
    assert f.outd1 == f.outc1 == f.outa2 == f.outf2 == 0


def test_table_chunks():
    tc = table_chunks(range(100), 12)
    first = next(tc)
    assert len(first) == 13

def test_build_table():
    t = build_table(
        testframes[0],
        (SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE),
        testframes[1],
        testframes[2],
        testframes[3],
        testframes[4],
        testframes[5],
        testframes[6],
        testframes[7],
        testframes[8],
        testframes[9],
        testframes[10],
        testframes[11],
        testframes[12],
        testframes[13],
        testframes[14],
        testframes[15]
    )

    assert (t["repeats"] == testframes[0]).all()
    assert (t["position"] == testframes[1]).all()
    assert (t["time1"] == testframes[2]).all()
    assert (t["outa1"] == testframes[3]).all()
    assert (t["outb1"] == testframes[4]).all()
    assert (t["outc1"] == testframes[5]).all()
    assert (t["outd1"] == testframes[6]).all()
    assert (t["oute1"] == testframes[7]).all()
    assert (t["outf1"] == testframes[8]).all()
    assert (t["time2"] == testframes[9]).all()
    assert (t["outa2"] == testframes[10]).all()
    assert (t["outb2"] == testframes[11]).all()
    assert (t["outc2"] == testframes[12]).all()
    assert (t["outd2"] == testframes[13]).all()
    assert (t["oute2"] == testframes[14]).all()
    assert (t["outf2"] == testframes[15]).all()
    assert (t["trigger"] == (SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE, SeqTrigger.IMMEDIATE)).all()
