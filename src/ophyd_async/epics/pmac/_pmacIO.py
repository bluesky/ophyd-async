from bluesky.protocols import Flyable, Preparable

from ophyd_async.core import StandardReadable

from ..signal.signal import epics_signal_rw


class Pmac(StandardReadable, Flyable, Preparable):
    """Device that moves a PMAC Motor record"""

    def __init__(self, prefix: str, name="") -> None:
        self.timeArray = epics_signal_rw(str, prefix + ":ProfileTimeArray")
        self.a = epics_signal_rw(str, prefix + ":A")
        self.use_a = epics_signal_rw(bool, prefix + ":A:UseAxis")
        self.a_vel = epics_signal_rw(str, prefix + ":A:Velocities")
        self.b = epics_signal_rw(str, prefix + ":B")
        self.use_b = epics_signal_rw(bool, prefix + ":B:UseAxis")
        self.b_vel = epics_signal_rw(str, prefix + ":B:Velocities")
        self.c = epics_signal_rw(str, prefix + ":C")
        self.use_c = epics_signal_rw(bool, prefix + ":C:UseAxis")
        self.c_vel = epics_signal_rw(str, prefix + ":C:Velocities")
        self.u = epics_signal_rw(str, prefix + ":U")
        self.use_u = epics_signal_rw(bool, prefix + ":U:UseAxis")
        self.u_vel = epics_signal_rw(str, prefix + ":U:Velocities")
        self.v = epics_signal_rw(str, prefix + ":V")
        self.use_v = epics_signal_rw(bool, prefix + ":V:UseAxis")
        self.v_vel = epics_signal_rw(str, prefix + ":V:Velocities")
        self.w = epics_signal_rw(str, prefix + ":W")
        self.use_w = epics_signal_rw(bool, prefix + ":W:UseAxis")
        self.w_vel = epics_signal_rw(str, prefix + ":W:Velocities")
        self.x = epics_signal_rw(str, prefix + ":X")
        self.use_x = epics_signal_rw(bool, prefix + ":X:UseAxis")
        self.x_vel = epics_signal_rw(str, prefix + ":X:Velocities")
        self.y = epics_signal_rw(str, prefix + ":Y")
        self.use_y = epics_signal_rw(bool, prefix + ":Y:UseAxis")
        self.y_vel = epics_signal_rw(str, prefix + ":Y:Velocities")
        self.z = epics_signal_rw(str, prefix + ":Z")
        self.use_z = epics_signal_rw(bool, prefix + ":Z:UseAxis")
        self.z_vel = epics_signal_rw(str, prefix + ":Z:Velocities")
