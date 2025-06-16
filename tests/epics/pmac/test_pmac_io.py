from ophyd_async.epics.pmac import (
    PmacAxisIO,
    PmacCoordIO,
    PmacIO,
    PmacTrajectoryIO,  # type: ignore
)


def test_pmac_io():
    """Instantiate a PmacIO object that looks like the P47 training beamline"""

    pmac = PmacIO(
        axis_nums=[1, 2],
        coord_nums=[1, 9],
        prefix="BL47P-MO-BRICK-01",
        name="p47-brick-01",
    )

    assert pmac.name == "p47-brick-01"

    # check coords PVs
    assert pmac.coord[1].defer_moves.source == "ca://BL47P-MO-BRICK-01:CS1:DeferMoves"
    assert (
        pmac.coord[1].cs_axis_setpoint[2].source
        == "ca://BL47P-MO-BRICK-01:CS1:M2:DirectDemand"
    )
    assert (
        pmac.coord[1].cs_axis_setpoint[1].source
        == "ca://BL47P-MO-BRICK-01:CS1:M1:DirectDemand"
    )
    assert (
        pmac.coord[9].cs_axis_setpoint[2].source
        == "ca://BL47P-MO-BRICK-01:CS9:M2:DirectDemand"
    )

    # check axes PVs
    assert pmac.axis[1].cs_axis_letter.source == "ca://BL47P-MO-BRICK-01:M1:CsAxis_RBV"
    assert pmac.axis[1].cs_port.source == "ca://BL47P-MO-BRICK-01:M1:CsPort_RBV"

    # check trajectory scan PVs
    assert (
        pmac.trajectory.points_to_build.source
        == "ca://BL47P-MO-BRICK-01:ProfilePointsToBuild"
    )
    assert pmac.trajectory.build_profile.source == "ca://BL47P-MO-BRICK-01:ProfileBuild"
    assert (
        pmac.trajectory.execute_profile.source
        == "ca://BL47P-MO-BRICK-01:ProfileExecute"
    )


def test_pmac_trajectory_io():
    """Instantiate a PmacTrajectoryIO object with a specific prefix."""

    pmac_trajectory = PmacTrajectoryIO(
        prefix="BL47P-MO-BRICK-01", name="p47-brick-01-trajectory"
    )

    assert pmac_trajectory.name == "p47-brick-01-trajectory"
    assert (
        pmac_trajectory.points_to_build.source
        == "ca://BL47P-MO-BRICK-01:ProfilePointsToBuild"
    )
    assert pmac_trajectory.build_profile.source == "ca://BL47P-MO-BRICK-01:ProfileBuild"
    assert (
        pmac_trajectory.execute_profile.source
        == "ca://BL47P-MO-BRICK-01:ProfileExecute"
    )


def test_pmac_axis_io():
    """Instantiate a PmacAxisIO object with a specific prefix."""

    pmac_axis = PmacAxisIO(prefix="BL47P-MO-BRICK-01:M1", name="p47-brick-01-axis")

    assert pmac_axis.name == "p47-brick-01-axis"
    assert pmac_axis.cs_axis_letter.source == "ca://BL47P-MO-BRICK-01:M1:CsAxis_RBV"
    assert pmac_axis.cs_port.source == "ca://BL47P-MO-BRICK-01:M1:CsPort_RBV"


def test_pmac_coord_io():
    """Instantiate a PmacCoordIO object with a specific prefix."""

    pmac_coord = PmacCoordIO(prefix="BL47P-MO-BRICK-01:CS1", name="p47-brick-01-coord")

    assert pmac_coord.name == "p47-brick-01-coord"
    assert pmac_coord.defer_moves.source == "ca://BL47P-MO-BRICK-01:CS1:DeferMoves"
    assert (
        pmac_coord.cs_axis_setpoint[1].source
        == "ca://BL47P-MO-BRICK-01:CS1:M1:DirectDemand"
    )
