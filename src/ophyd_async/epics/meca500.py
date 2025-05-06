import asyncio  # noqa: D100
from typing import TypedDict  # noqa: D100

import numpy as np
from bluesky.protocols import Locatable, Location

from ophyd_async.core import (
    DerivedSignalFactory,
    DeviceVector,
    StandardReadable,
    Transform,
    soft_signal_rw,
    wait_for_value,
)
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw


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


def _vp_angle(v1, v2, v3):
    plane_normal = np.cross(v2, v3)
    return np.arccos(
        np.dot(v1, plane_normal) / (np.linalg.norm(v1) * np.linalg.norm(plane_normal))
    )


def _vanglev(v1, v2):
    cos_val = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    cos_val = np.clip(cos_val, -1.0, 1.0)
    return np.arccos(cos_val)


def _comparator_difference(arr, motor_pos, weighting=1):
    return np.sum(np.abs(arr - motor_pos) * weighting)


def _rotmat(u, angle):
    # clockwise rotation
    u = np.array(u) / np.linalg.norm(np.array(u))
    angle_rad = np.deg2rad(angle)
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    e11 = u[0] ** 2 + (1 - u[0] ** 2) * c
    e12 = u[0] * u[1] * (1 - c) - u[2] * s
    e13 = u[0] * u[2] * (1 - c) + u[1] * s
    e21 = u[0] * u[1] * (1 - c) + u[2] * s
    e22 = u[1] ** 2 + (1 - u[1] ** 2) * c
    e23 = u[1] * u[2] * (1 - c) - u[0] * s
    e31 = u[0] * u[2] * (1 - c) - u[1] * s
    e32 = u[1] * u[2] * (1 - c) + u[0] * s
    e33 = u[2] ** 2 + (1 - u[2] ** 2) * c
    rotmat = np.array([[e11, e12, e13], [e21, e22, e23], [e31, e32, e33]])
    return rotmat


def _rotxyz(v, u, angle):
    u = np.array(u) / np.linalg.norm(np.array(u))
    u = np.atleast_2d(u)
    angle_rad = np.deg2rad(angle)
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    e11 = u[0, 0] ** 2 + (1 - u[0, 0] ** 2) * c
    e12 = u[0, 0] * u[0, 1] * (1 - c) - u[0, 2] * s
    e13 = u[0, 0] * u[0, 2] * (1 - c) + u[0, 1] * s
    e21 = u[0, 0] * u[0, 1] * (1 - c) + u[0, 2] * s
    e22 = u[0, 1] ** 2 + (1 - u[0, 1] ** 2) * c
    e23 = u[0, 1] * u[0, 2] * (1 - c) - u[0, 0] * s
    e31 = u[0, 0] * u[0, 2] * (1 - c) - u[0, 1] * s
    e32 = u[0, 1] * u[0, 2] * (1 - c) + u[0, 0] * s
    e33 = u[0, 2] ** 2 + (1 - u[0, 2] ** 2) * c
    rotmat = np.array([[e11, e12, e13], [e21, e22, e23], [e31, e32, e33]])
    return (rotmat @ v.T).T


def _setEulerTarget(
    xyz,
    al_be_gam,
    motor_pos,
):
    # Hard coded kinematic chain for the Meca500. Should be generalizable.
    v0 = np.array([0, 0.0, 0.135])
    v1 = np.array([0, 0.0, 0.135 * 2])
    v2 = np.array([0, 0, 0.34102])
    v3 = np.array([0.03210312, 0, 0.3917102])
    v4 = np.array([0.03210312, 0, 0.3917102 + 0.07])
    v5 = np.array([1, 0, 0])
    v6 = np.array([0, 1, 0])
    v7 = np.array([0, 0, 1])
    L_vects = np.array([v0, (v1 - v0), (v2 - v1), (v3 - v2), (v4 - v3), v5, v6, v7])
    ax3 = v3 - v2
    axis_vects = np.array([[0, 0, 1], [0, 1, 0], [0, 1, 0], ax3, [0, 1, 0], [0, 0, 1]])
    motor_offsets = (0, 0, 57.6525565, 0, 32.347444, 0)
    motor_limits = np.array(
        [[-175, 175], [-70, 90], [-135, 70], [-170, 170], [-115, 115], [-3600, 3600]]
    )
    tool_offset = [0, 0, 0]
    strategy = "minimum_movement_weighted"
    weighting = [6, 5, 4, 3, 2, 1]

    MI = np.identity(3)
    vx = MI[0, :]
    vy = MI[1, :]
    vz = MI[2, :]
    em = (
        _rotmat(vx, al_be_gam[0])
        @ _rotmat(vy, al_be_gam[1])
        @ _rotmat(vz, al_be_gam[2])
    )  # ZYX convention
    targetmatrix = np.array(
        [
            np.array((em @ np.array([vx]).T).T)[0],
            np.array((em @ np.array([vy]).T).T)[0],
            np.array((em @ np.array([vz]).T).T)[0],
        ]
    )  # To make consistent with Euler in Blender
    tool = np.array(np.array([tool_offset]) @ targetmatrix)[0]
    xyz = np.array(xyz + tool)
    tv1 = list(np.array(np.array([vx]) @ targetmatrix)[0])
    tv2 = list(np.array(np.array([vy]) @ targetmatrix)[0])
    tv3 = list(np.array(np.array([vz]) @ targetmatrix)[0])
    return _inverse_kinematics(
        np.array([xyz, tv1, tv2, tv3]),
        L_vects,
        axis_vects,
        motor_offsets,
        motor_limits,
        strategy,
        motor_pos,
        weighting,
    )


def _inverse_kinematics(
    target,
    L_vects,
    axis_vects,
    motor_offsets,
    motor_limits,
    strategy,
    motor_pos,
    weighting,
):
    solutions = np.array([[]] * 6).T
    valid_solutions = np.array([[]] * 6).T
    target = target
    L_vects[np.r_[:3], 0] = 0
    L1 = np.linalg.norm(L_vects[1, :])
    L2 = np.linalg.norm(L_vects[2, :] + L_vects[3, :])
    v0 = target[0, :]
    v1 = target[1, :]
    # v2 = target[2, :]
    v3 = target[3, :]

    vlength = np.linalg.norm(L_vects[4, :])
    vc1 = (v0 - (v3 / np.linalg.norm(v3) * vlength)) - L_vects[
        0, :
    ]  # Calculate the origin of L4

    # -----------------------------------------------------------------------
    #       determine angle addition or subtraction and vector length
    # -----------------------------------------------------------------------

    A1 = np.pi / 2 + _vp_angle(np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0]))
    A2 = np.pi / 2 - _vp_angle(np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0]))
    A1n = 3 / 2.0 * np.pi - _vp_angle(
        np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0])
    )
    A2n = _vp_angle(np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0])) - np.pi / 2
    # -----------------------------------------------------------------------

    b = np.linalg.norm(vc1)
    c = np.linalg.norm([L_vects[0, :][0], L_vects[0, :][1], 0])
    a1 = (b**2 + c**2 - (2 * b * c * np.cos(A1))) ** 0.5  # law of cosines
    a2 = (b**2 + c**2 - (2 * b * c * np.cos(A2))) ** 0.5  # law of cosines
    a1n = (b**2 + c**2 - (2 * b * c * np.cos(A1n))) ** 0.5  # law of cosines
    a2n = (b**2 + c**2 - (2 * b * c * np.cos(A2n))) ** 0.5  # law of cosines
    theta_c_angle_offset1 = np.arccos((c**2 - a1**2 - b**2) / (-2 * a1 * b))
    theta_c_angle_offset2 = np.arccos((c**2 - a2**2 - b**2) / (-2 * a2 * b))
    theta_c_angle_offset1n = np.arccos((c**2 - a1n**2 - b**2) / (-2 * a1n * b))
    theta_c_angle_offset2n = np.arccos((c**2 - a2n**2 - b**2) / (-2 * a2n * b))

    theta0check = np.arctan2(vc1[1], vc1[0])
    num_checks = 8
    keep_index = np.zeros((8, 2))
    for ii in list(range(num_checks)):
        if ii == 0 or ii == 4:
            if vc1[-1] > 0:
                vc1n = a2
                theta_c_angle_offset = theta_c_angle_offset2
            else:
                vc1n = a2n
                theta_c_angle_offset = -theta_c_angle_offset2n

            theta0 = theta0check
            theta1 = (
                np.arccos((L1**2 + vc1n**2 - L2**2) / (2 * L1 * vc1n))
                + theta_c_angle_offset
            )  # law of cosines
            theta2 = np.pi - np.arccos(
                (L1**2 + L2**2 - vc1n**2) / (2 * L1 * L2)
            )  # law of cosines
            theta2 = theta2 - (
                _vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 + (_vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

        elif ii == 1 or ii == 5:
            if vc1[-1] > 0:
                vc1n = a1
                theta_c_angle_offset = theta_c_angle_offset1
            else:
                vc1n = a1n
                theta_c_angle_offset = -theta_c_angle_offset1n

            theta0 = theta0check + np.pi
            theta1 = (
                np.arccos((L1**2 + vc1n**2 - L2**2) / (2 * L1 * vc1n))
                + theta_c_angle_offset
            )  # law of cosines
            theta2 = np.pi - np.arccos(
                (L1**2 + L2**2 - vc1n**2) / (2 * L1 * L2)
            )  # law of cosines
            theta2 = theta2 - (
                _vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 - (_vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

        elif ii == 2 or ii == 6:
            if vc1[-1] > 0:
                vc1n = a2
                theta_c_angle_offset = theta_c_angle_offset2
            else:
                vc1n = a2n
                theta_c_angle_offset = -theta_c_angle_offset2n

            theta0 = theta0check
            theta1 = (
                -np.arccos((L1**2 + vc1n**2 - L2**2) / (2 * L1 * vc1n))
                + theta_c_angle_offset
            )  # law of cosines
            theta2 = -(
                np.pi - np.arccos((L1**2 + L2**2 - vc1n**2) / (2 * L1 * L2))
            )  # law of cosines
            theta2 = theta2 - (
                _vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 + (_vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

        else:
            if vc1[-1] > 0:
                vc1n = a1
                theta_c_angle_offset = theta_c_angle_offset1
            else:
                vc1n = a1n
                theta_c_angle_offset = -theta_c_angle_offset1n

            theta0 = theta0check + np.pi
            theta1 = (
                -np.arccos((L1**2 + vc1n**2 - L2**2) / (2 * L1 * vc1n))
                + theta_c_angle_offset
            )  # law of cosines
            theta2 = -(
                np.pi - np.arccos((L1**2 + L2**2 - vc1n**2) / (2 * L1 * L2))
            )  # law of cosines
            theta2 = theta2 - (
                _vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 - (_vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

        # -------------------------------------------------------------------------------------------#
        #           theta0 theta1 and theta2 determine position of Lvect origin
        # -------------------------------------------------------------------------------------------#
        vec3 = _rotxyz(
            np.array([L_vects[3, :]]),
            np.array([axis_vects[2, :]]),
            theta2 * 180 / np.pi,
        )

        vec3 = _rotxyz(vec3, axis_vects[1, :], theta1 * 180 / np.pi)
        vec3 = _rotxyz(vec3, axis_vects[0, :], theta0 * 180 / np.pi)

        av3 = _rotxyz(
            np.array([axis_vects[4, :]]),
            np.array([axis_vects[2, :]]),
            theta2 * 180 / np.pi,
        )
        av3 = _rotxyz(av3, axis_vects[1, :], theta1 * 180 / np.pi)
        av3 = _rotxyz(av3, axis_vects[0, :], theta0 * 180 / np.pi)

        if (
            np.abs(np.dot(np.array(av3)[0], v3)) > 0.0001
        ):  # To check that av3 is not already orthoganol to v3
            theta3i = _vp_angle(np.array(av3)[0], np.array(v3), np.array(vec3)[0])
            if ii < 4:
                theta3 = _vp_angle(np.array(av3)[0], np.array(v3), np.array(vec3)[0])
            elif theta3i > np.pi / 2:
                theta3 = -(_vp_angle(np.array(av3)[0], np.array(vec3)[0], np.array(v3)))
            else:
                theta3 = 0
        else:
            theta3 = 0

        theta3 = -np.sign(np.dot(np.array(av3)[0], np.array(v3))) * theta3
        vec4 = _rotxyz(
            np.array([L_vects[4, :]]),
            np.array([axis_vects[3, :]]),
            theta3 * 180 / np.pi,
        )
        vec4 = _rotxyz(vec4, axis_vects[2, :], theta2 * 180 / np.pi)
        vec4 = _rotxyz(vec4, axis_vects[1, :], theta1 * 180 / np.pi)
        vec4 = _rotxyz(vec4, axis_vects[0, :], theta0 * 180 / np.pi)
        theta4 = _vanglev(v3, np.array(vec4)[0])

        vec5 = _rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[4, :]]),
            theta4 * 180 / np.pi,
        )
        vec5 = _rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)

        theta4_check = np.abs(_vanglev(v3, np.array(vec5)[0]) - np.pi / 2)
        if theta4_check > 0.01:
            theta4 = -1 * _vanglev(v3, np.array(vec4)[0])

        vec5 = _rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[4, :]]),
            theta4 * 180 / np.pi,
        )
        vec5 = _rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)
        theta5 = -_vanglev(v1, np.array(vec5)[0])

        vec5 = _rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[5, :]]),
            theta5 * 180 / np.pi,
        )
        vec5 = _rotxyz(vec5, axis_vects[4, :], theta4 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)

        if np.abs(_vanglev(v1, np.array(vec5)[0])) > 0.01:
            theta5 = -theta5

        vec5 = _rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[5, :]]),
            theta5 * 180 / np.pi,
        )
        vec5 = _rotxyz(vec5, axis_vects[4, :], theta4 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = _rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)
        if np.abs(_vanglev(v1, np.array(vec5)[0])) > 0.01:
            theta5 = _vanglev(v1, np.array(vec5)[0]) + np.pi

        if np.isnan(theta5):
            theta5 = 0
        # set angular range between -180 and 180
        theta0 = np.mod(theta0 + np.pi, 2 * np.pi) - np.pi
        theta1 = np.mod(theta1 + np.pi, 2 * np.pi) - np.pi
        theta2 = np.mod(theta2 + np.pi, 2 * np.pi) - np.pi
        theta3 = np.mod(theta3 + np.pi, 2 * np.pi) - np.pi
        theta4 = np.mod(theta4 + np.pi, 2 * np.pi) - np.pi
        theta5 = np.mod(theta5 + np.pi, 2 * np.pi) - np.pi
        output = np.array(
            [
                theta0 * 180 / np.pi,
                theta1 * 180 / np.pi,
                theta2 * 180 / np.pi,
                theta3 * 180 / np.pi,
                theta4 * 180 / np.pi,
                theta5 * 180 / np.pi,
            ]
        )

        solutions = np.vstack([solutions, output])

    solutions = solutions - motor_offsets

    # ----------------------------------------------------------------------#
    #      Check all motors are within their respective limits
    # ----------------------------------------------------------------------#

    for iii in list(range(int(num_checks))):
        if np.where(motor_limits.T[0, :] <= solutions[iii, :])[0].shape[0] == 6:
            keep_index[iii, 0] = 1
        if np.where(motor_limits.T[1, :] >= solutions[iii, :])[0].shape[0] == 6:
            keep_index[iii, 1] = 1

    for iii in list(range(num_checks)):
        if keep_index[iii, 0] * keep_index[iii, 1] == 1:
            valid_solutions = np.vstack([valid_solutions, solutions[iii, :]])

    if valid_solutions.shape[0] < 1:
        best_solution = np.array([np.nan, np.nan, np.nan, np.nan, np.nan, np.nan])
    else:
        # ------------------------------------------------------------------#
        #                      Solution strategy
        # -------------------------------------------------------------------

        if strategy == "minimum_movement":
            comparator = np.apply_along_axis(
                _comparator_difference, 1, valid_solutions, motor_pos
            )
            best_solution = valid_solutions[np.argmin(comparator)]

        elif strategy == "minimum_movement_weighted":
            comparator = np.apply_along_axis(
                _comparator_difference, 1, valid_solutions, motor_pos, weighting
            )
            best_solution = valid_solutions[np.argmin(comparator)]

        else:
            limit_centres = np.mean(motor_limits, 1)
            comparator = np.apply_along_axis(
                _comparator_difference, 1, limit_centres, valid_solutions
            )
            best_solution = valid_solutions[np.argmin(comparator)]

    return JointSpace(
        joint_1=best_solution[0],
        joint_2=best_solution[1],
        joint_3=best_solution[2],
        joint_4=best_solution[3],
        joint_5=best_solution[4],
        joint_6=best_solution[5],
    )


def _rotationMatrixToEuler(R, convention: str):
    if convention.lower() == "zyx":
        sy = np.sqrt(R[2, 1] ** 2 + R[2, 2] ** 2)
        singular = sy < 1e-6
        if not singular:
            alpha = -np.arctan2(R[2, 1], R[2, 2])
            beta = -np.arctan2(-R[2, 0], sy)
            gamma = -np.arctan2(R[1, 0], R[0, 0])
        else:
            alpha = np.pi - np.arctan2(R[0, 1], R[0, 2])
            beta = -np.arctan2(-R[2, 0], sy)
            gamma = -np.arctan2(R[1, 0], R[0, 0])
        return alpha, beta, gamma
    elif convention.lower() == "xyz":
        cp = np.sqrt(1 - R[0, 2] ** 2)
        singular = cp < 1e-6
        if not singular:
            alpha = np.arctan2(-R[1, 2], R[2, 2])
            beta = np.arcsin(R[0, 2])
            gamma = np.pi + np.arctan2(-R[0, 1], R[0, 0])
        else:
            alpha = np.arctan2(R[2, 1], R[1, 1])
            beta = np.arcsin(R[0, 2])
            gamma = 0.0
        return alpha, beta, gamma
    else:
        raise ValueError(f"Unsupported convention: {convention}. Use 'zyx' or 'xyz'.")


def _forward_kinematics(joints, offset, convention: str = "xyz"):
    motor_values_in_degrees = np.deg2rad(joints)
    joint_1, joint_2, joint_3, joint_4, joint_5, joint_6 = motor_values_in_degrees

    c1, s1 = np.cos(joint_1), np.sin(joint_1)
    c2, s2 = np.cos(joint_2 - np.pi / 2), np.sin(joint_2 - np.pi / 2)
    c3, s3 = np.cos(joint_3), np.sin(joint_3)
    c4, s4 = np.cos(joint_4), np.sin(joint_4)
    c5, s5 = np.cos(joint_5), np.sin(joint_5)
    c6, s6 = np.cos(joint_6), np.sin(joint_6)

    origin_to_joint_1 = np.array(
        [[c1, -s1, 0, 0], [s1, c1, 0, 0], [0, 0, 1, 135], [0, 0, 0, 1]]
    )
    joint_1_to_2 = np.array(
        [[c2, -s2, 0, 0], [0, 0, 1, 0], [-s2, -c2, 0, 0], [0, 0, 0, 1]]
    )
    joint_2_to_3 = np.array(
        [[c3, -s3, 0, 135], [s3, c3, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    )
    joint_3_to_4 = np.array(
        [[c4, -s4, 0, 38], [0, 0, 1, 120], [-s4, -c4, 0, 0], [0, 0, 0, 1]]
    )
    joint_4_to_5 = np.array(
        [[c5, -s5, 0, 0], [0, 0, -1, 0], [s5, c5, 0, 0], [0, 0, 0, 1]]
    )
    joint_5_to_6 = np.array(
        [[c6, -s6, 0, 0], [0, 0, 1, offset], [-s6, -c6, 0, 0], [0, 0, 0, 1]]
    )

    origin_to_tooltip = (
        origin_to_joint_1
        @ joint_1_to_2
        @ joint_2_to_3
        @ joint_3_to_4
        @ joint_4_to_5
        @ joint_5_to_6
    )

    x, y, z = origin_to_tooltip[0, 3], origin_to_tooltip[1, 3], origin_to_tooltip[2, 3]
    rotation_from_origin_to_tooltip = origin_to_tooltip[:3, :3]

    alpha, beta, gamma = _rotationMatrixToEuler(
        rotation_from_origin_to_tooltip, convention
    )

    return CartesianSpace(
        x=x / 1000,
        y=y / 1000,
        z=z / 1000,
        alpha=np.rad2deg(alpha),
        beta=np.rad2deg(beta),
        gamma=np.rad2deg(gamma),
    )


class RobotTransform(Transform):
    """Transform raw joints values to derived axes, and vice versa."""

    def raw_to_derived(
        self,
        *,
        joint_1: float,
        joint_2: float,
        joint_3: float,
        joint_4: float,
        joint_5: float,
        joint_6: float,
    ) -> CartesianSpace:
        """Transform joints angles to cartesian x, y, z, alpha, beta, and gamma."""
        cartesian_pose = _forward_kinematics(
            [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6], 70, "xyz"
        )
        return cartesian_pose

    def derived_to_raw(
        self,
        *,
        x: float,
        y: float,
        z: float,
        alpha: float,
        beta: float,
        gamma: float,
        joint_1: float,
        joint_2: float,
        joint_3: float,
        joint_4: float,
        joint_5: float,
        joint_6: float,
    ) -> JointSpace:
        """Transform cartesian x, y, z, alpha, beta, and gamma to joint angles."""
        try:
            derived_readings = _setEulerTarget(
                [x, y, z],
                [alpha, beta, gamma],
                [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6],
            )
        except RuntimeWarning as err:
            raise ValueError(
                "Invalid tool-tip pose:"
                f"x={x}, y={y}, z={z}, alpha={alpha}, beta={beta}, gamma={gamma}."
                "Failed to generate joint space pose."
            ) from err

        return derived_readings


class Meca500(StandardReadable, Locatable[CartesianSpace]):
    """Meca500 device that derives x, y, z, alpha, beta, and gamma, from joints."""

    def __init__(self, prefix="", name="") -> None:
        with self.add_children_as_readables():
            self.joints = DeviceVector(
                {
                    i: epics_signal_rw(
                        float, f"{prefix}JOINTS:THETA{i + 1}:SP", name=f"joint_{i + 1}"
                    )
                    for i in range(0, 6)
                }
            )

        self.move_joints_array = epics_signal_rw(
            int, f"{prefix}PREPARE_MOVE_JOINTS_ARRAY.PROC"
        )
        self.busy = epics_signal_rw(str, f"{prefix}ROBOT:STATUS:BUSY")
        self.eom = epics_signal_r(float, f"{prefix}ROBOT:STATUS:EOM")

        self._factory = DerivedSignalFactory(
            RobotTransform,
            self.set,
            joint_1=self.joints[0],
            joint_2=self.joints[1],
            joint_3=self.joints[2],
            joint_4=self.joints[3],
            joint_5=self.joints[4],
            joint_6=self.joints[5],
        )

        self.x = self._factory.derived_signal_rw(float, "x")
        self.y = self._factory.derived_signal_rw(float, "y")
        self.z = self._factory.derived_signal_rw(float, "z")
        self.alpha = self._factory.derived_signal_rw(float, "alpha")
        self.beta = self._factory.derived_signal_rw(float, "beta")
        self.gamma = self._factory.derived_signal_rw(float, "gamma")

        self.x_sp = soft_signal_rw(float, name="x")
        self.y_sp = soft_signal_rw(float, name="y")
        self.z_sp = soft_signal_rw(float, name="z")
        self.alpha_sp = soft_signal_rw(float, name="alpha")
        self.beta_sp = soft_signal_rw(float, name="beta")
        self.gamma_sp = soft_signal_rw(float, name="gamma")

        super().__init__(name=name)

    async def set(self, target_cartesian: CartesianSpace) -> None:  # type: ignore  # noqa: D102
        """Set cartesian position of manipulator."""
        transform = await self._factory.transform()

        await asyncio.gather(
            self.x_sp.set(target_cartesian["x"]),
            self.y_sp.set(target_cartesian["y"]),
            self.z_sp.set(target_cartesian["z"]),
            self.alpha_sp.set(target_cartesian["alpha"]),
            self.beta_sp.set(target_cartesian["beta"]),
            self.gamma_sp.set(target_cartesian["gamma"]),
        )

        values = await asyncio.gather(
            *(self.joints[i].get_value() for i in range(len(self.joints)))
        )

        current_joint_positions = JointSpace(
            **{f"joint_{i + 1}": value for i, value in enumerate(values)}
        )

        raw = transform.derived_to_raw(**target_cartesian, **current_joint_positions)

        self.busy.set("BUSY", wait=True)
        await asyncio.gather(
            *(
                self.joints[i].set(raw[self.joints[i].name])
                for i in range(len(self.joints))
            )
        )
        await self.move_joints_array.set(True)
        await wait_for_value(self.eom, 0.0, timeout=5)

    async def locate(self) -> Location[CartesianSpace]:
        """Return last commanded and current cartesian position of tooltip."""
        virtual_setpoints = CartesianSpace(
            x=await self.x_sp.get_value(),
            y=await self.y_sp.get_value(),
            z=await self.z_sp.get_value(),
            alpha=await self.alpha_sp.get_value(),
            beta=await self.beta_sp.get_value(),
            gamma=await self.gamma_sp.get_value(),
        )

        virtual_readbacks = CartesianSpace(
            x=await self.x.get_value(),
            y=await self.y.get_value(),
            z=await self.z.get_value(),
            alpha=await self.alpha.get_value(),
            beta=await self.beta.get_value(),
            gamma=await self.gamma.get_value(),
        )

        return Location(setpoint=virtual_setpoints, readback=virtual_readbacks)
