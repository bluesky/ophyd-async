from typing import TypedDict  # noqa: D100

import numpy as np
from bluesky.protocols import Movable

from ophyd_async.core import DerivedSignalFactory, Device, Transform
from ophyd_async.epics.core import epics_signal_rw


class CartesianSpace(TypedDict):  # noqa: D101
    x: float
    y: float
    z: float
    alpha: float
    beta: float
    gamma: float


class JointSpace(TypedDict):  # noqa: D101
    joint_1: float
    joint_2: float
    joint_3: float
    joint_4: float
    joint_5: float
    joint_6: float


def rotationMatrixToEulerZYX(rmatrix):  # noqa: D103
    sy = np.sqrt(rmatrix[2, 1] ** 2 + rmatrix[2, 2] ** 2)
    singular = sy < 1e-6
    if not singular:
        alpha = -np.arctan2(rmatrix[2, 1], rmatrix[2, 2])
        beta = -np.arctan2(
            -rmatrix[2, 0], np.sqrt(rmatrix[2, 1] ** 2 + rmatrix[2, 2] ** 2)
        )
        gamma = -np.arctan2(rmatrix[1, 0], rmatrix[0, 0])
    else:
        alpha = np.pi - np.arctan2(rmatrix[0, 1], rmatrix[0, 2])
        beta = -np.arctan2(
            -rmatrix[2, 0], np.sqrt(rmatrix[2, 1] ** 2 + rmatrix[2, 2] ** 2)
        )
        gamma = -np.arctan2(rmatrix[1, 0], rmatrix[0, 0])
    return alpha, beta, gamma


def transformation_to_pose(T):
    x, y, z = T[0, 3], T[1, 3], T[2, 3]
    R = T[:3, :3]
    alpha, beta, gamma = rotationMatrixToEulerZYX(R)

    return x, y, z, np.rad2deg(alpha), np.rad2deg(beta), np.rad2deg(gamma)


def fk(joints, offset):
    th = np.deg2rad(joints)
    th1, th2, th3, th4, th5, th6 = th

    c1, s1 = np.cos(th1), np.sin(th1)
    c2, s2 = np.cos(th2 - np.pi / 2), np.sin(th2 - np.pi / 2)
    c3, s3 = np.cos(th3), np.sin(th3)
    c4, s4 = np.cos(th4), np.sin(th4)
    c5, s5 = np.cos(th5), np.sin(th5)
    c6, s6 = np.cos(th6), np.sin(th6)

    T01 = np.array([[c1, -s1, 0, 0], [s1, c1, 0, 0], [0, 0, 1, 135], [0, 0, 0, 1]])
    T12 = np.array([[c2, -s2, 0, 0], [0, 0, 1, 0], [-s2, -c2, 0, 0], [0, 0, 0, 1]])
    T23 = np.array([[c3, -s3, 0, 135], [s3, c3, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    T34 = np.array([[c4, -s4, 0, 38], [0, 0, 1, 120], [-s4, -c4, 0, 0], [0, 0, 0, 1]])
    T45 = np.array([[c5, -s5, 0, 0], [0, 0, -1, 0], [s5, c5, 0, 0], [0, 0, 0, 1]])
    T56 = np.array([[c6, -s6, 0, 0], [0, 0, 1, offset], [-s6, -c6, 0, 0], [0, 0, 0, 1]])

    T06 = T01 @ T12 @ T23 @ T34 @ T45 @ T56

    return transformation_to_pose(T06)


class RobotTransform(Transform):  # noqa: D101
    def raw_to_derived(  # noqa: D102
        self,
        *,
        joint_1: float,
        joint_2: float,
        joint_3: float,
        joint_4: float,
        joint_5: float,
        joint_6: float,
    ) -> CartesianSpace:
        x, y, z, alpha, beta, gamma = fk(
            [joint_1, 10, joint_3, 30, joint_5, joint_6], 70
        )
        return CartesianSpace(x=x, y=y, z=z, alpha=alpha, beta=beta, gamma=gamma)

    def derived_to_raw(  # noqa: D102
        self, *, x: float, y: float, z: float, alpha: float, beta: float, gamma: float
    ) -> JointSpace:
        return JointSpace(
            joint_1=10, joint_2=10, joint_3=10, joint_4=10, joint_5=10, joint_6=10
        )


class Meca500(Device, Movable):  # noqa: D101
    def __init__(self, kinematic_chain, prefix="", name=""):
        self.joint_1 = epics_signal_rw(float, f"{prefix}:THETA1:SP")
        self.joint_2 = epics_signal_rw(float, f"{prefix}:THETA2:SP")
        self.joint_3 = epics_signal_rw(float, f"{prefix}:THETA3:SP")
        self.joint_4 = epics_signal_rw(float, f"{prefix}:THETA4:SP")
        self.joint_5 = epics_signal_rw(float, f"{prefix}:THETA5:SP")
        self.joint_6 = epics_signal_rw(float, f"{prefix}:THETA6:SP")

        self._factory = DerivedSignalFactory(
            RobotTransform,
            self.set,
            joint_1=self.joint_1,
            joint_2=self.joint_2,
            joint_3=self.joint_3,
            joint_4=self.joint_4,
            joint_5=self.joint_5,
            joint_6=self.joint_6,
        )

        self.x = self._factory.derived_signal_rw(float, "x")
        self.y = self._factory.derived_signal_rw(float, "y")
        self.z = self._factory.derived_signal_rw(float, "z")
        self.alpha = self._factory.derived_signal_rw(float, "alpha")
        self.beta = self._factory.derived_signal_rw(float, "beta")
        self.gamma = self._factory.derived_signal_rw(float, "gamma")
        super().__init__(name=name)

    async def set(self, cartesian: CartesianSpace) -> None:  # type: ignore  # noqa: D102
        transform = await self._factory.transform()
        raw = transform.derived_to_raw(**cartesian)
        self.joint_1.set(raw["joint_1"])
