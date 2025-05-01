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


def vp_angle(v1, v2, v3):
    plane_normal = np.cross(v2, v3)
    return np.arccos(
        np.dot(v1, plane_normal) / (np.linalg.norm(v1) * np.linalg.norm(plane_normal))
    )


def vanglev(v1, v2):
    angle = np.arccos(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
    return angle


def rotmat(u, angle):
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


def rotxyz(v, u, angle):
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


def setEulerTarget(
    xyz,
    r_alpha,
    r_beta,
    r_gamma,
    motor_pos,
):
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
    strategy = "minimum_movement"
    weighting = [6, 5, 4, 3, 2, 1]

    MI = np.identity(3)
    vx = MI[0, :]
    vy = MI[1, :]
    vz = MI[2, :]
    em = (
        rotmat(vx, r_alpha) @ rotmat(vy, r_beta) @ rotmat(vz, r_gamma)
    )  # ZYX convention
    targetmatrix = np.array(
        [
            np.array((em @ np.array([vx]).T).T)[0],
            np.array((em @ np.array([vy]).T).T)[0],
            np.array((em @ np.array([vz]).T).T)[0],
        ]
    )  # To make consisten with Euler in Blender
    tool = np.array(np.array([tool_offset]) @ targetmatrix)[0]
    xyz = np.array(xyz + tool)
    tv1 = list(np.array(np.array([vx]) @ targetmatrix)[0])
    tv2 = list(np.array(np.array([vy]) @ targetmatrix)[0])
    tv3 = list(np.array(np.array([vz]) @ targetmatrix)[0])
    return i_kinematics(
        np.array([xyz, tv1, tv2, tv3]),
        L_vects,
        axis_vects,
        motor_offsets,
        motor_limits,
        strategy,
        motor_pos,
        weighting,
    )


def i_kinematics(
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

    A1 = np.pi / 2 + vp_angle(np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0]))
    A2 = np.pi / 2 - vp_angle(np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0]))
    A1n = 3 / 2.0 * np.pi - vp_angle(
        np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0])
    )
    A2n = vp_angle(np.array(vc1), np.array([1, 0, 0]), np.array([0, 1, 0])) - np.pi / 2
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
                vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 + (vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

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
                vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 - (vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

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
                vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 + (vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

        elif ii == 3 or ii == 7:
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
                vp_angle((L_vects[3, :] + L_vects[2, :]), [1, 0, 0], [0, 1, 0])
            )
            theta1 = -theta1 - (vp_angle(vc1, [1, 0, 0], [0, 1, 0]))

        # -------------------------------------------------------------------------------------------#
        #           theta0 theta1 and theta2 determine position of Lvect origin
        # -------------------------------------------------------------------------------------------#
        vec3 = rotxyz(
            np.array([L_vects[3, :]]),
            np.array([axis_vects[2, :]]),
            theta2 * 180 / np.pi,
        )

        vec3 = rotxyz(vec3, axis_vects[1, :], theta1 * 180 / np.pi)
        vec3 = rotxyz(vec3, axis_vects[0, :], theta0 * 180 / np.pi)

        av3 = rotxyz(
            np.array([axis_vects[4, :]]),
            np.array([axis_vects[2, :]]),
            theta2 * 180 / np.pi,
        )
        av3 = rotxyz(av3, axis_vects[1, :], theta1 * 180 / np.pi)
        av3 = rotxyz(av3, axis_vects[0, :], theta0 * 180 / np.pi)

        if (
            np.abs(np.dot(np.array(av3)[0], v3)) > 0.0001
        ):  # To check that av3 is not already orthoganol to v3
            theta3i = vp_angle(np.array(av3)[0], np.array(v3), np.array(vec3)[0])
            if ii < 4:
                theta3 = vp_angle(np.array(av3)[0], np.array(v3), np.array(vec3)[0])
            elif theta3i > np.pi / 2:
                theta3 = -(vp_angle(np.array(av3)[0], np.array(vec3)[0], np.array(v3)))
        else:
            theta3 = 0

        theta3 = -np.sign(np.dot(np.array(av3)[0], np.array(v3))) * theta3
        vec4 = rotxyz(
            np.array([L_vects[4, :]]),
            np.array([axis_vects[3, :]]),
            theta3 * 180 / np.pi,
        )
        vec4 = rotxyz(vec4, axis_vects[2, :], theta2 * 180 / np.pi)
        vec4 = rotxyz(vec4, axis_vects[1, :], theta1 * 180 / np.pi)
        vec4 = rotxyz(vec4, axis_vects[0, :], theta0 * 180 / np.pi)
        theta4 = vanglev(v3, np.array(vec4)[0])

        vec5 = rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[4, :]]),
            theta4 * 180 / np.pi,
        )
        vec5 = rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)

        theta4_check = np.abs(vanglev(v3, np.array(vec5)[0]) - np.pi / 2)
        if theta4_check > 0.01:
            theta4 = -vanglev(v3, np.array(vec4)[0])

        vec5 = rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[4, :]]),
            theta4 * 180 / np.pi,
        )
        vec5 = rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)
        theta5 = -vanglev(v1, np.array(vec5)[0])

        vec5 = rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[5, :]]),
            theta5 * 180 / np.pi,
        )
        vec5 = rotxyz(vec5, axis_vects[4, :], theta4 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)

        if np.abs(vanglev(v1, np.array(vec5)[0])) > 0.01:
            theta5 = -theta5

        vec5 = rotxyz(
            np.array([L_vects[5, :]]),
            np.array([axis_vects[5, :]]),
            theta5 * 180 / np.pi,
        )
        vec5 = rotxyz(vec5, axis_vects[4, :], theta4 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[3, :], theta3 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[2, :], theta2 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[1, :], theta1 * 180 / np.pi)
        vec5 = rotxyz(vec5, axis_vects[0, :], theta0 * 180 / np.pi)
        if np.abs(vanglev(v1, np.array(vec5)[0])) > 0.01:
            theta5 = vanglev(v1, np.array(vec5)[0]) + np.pi

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
                np.sum, 1, np.abs(valid_solutions - motor_pos)
            )
            best_solution = valid_solutions[np.argmin(comparator)]

        elif strategy == "minimum_movement_weighted":
            comparator = np.apply_along_axis(
                np.sum,
                1,
                np.abs(valid_solutions - motor_pos) * weighting,
            )
            best_solution = valid_solutions[np.argmin(comparator)]

        elif strategy == "comfortable_limits":
            limit_centres = np.mean(motor_limits, 1)
            comparator = np.abs(
                np.apply_along_axis(np.sum, 1, np.abs(limit_centres - valid_solutions))
            )
            best_solution = valid_solutions[np.argmin(comparator)]

    # # final check to make sure the solutions is consistent with the target value
    # forward_check = self.f_kinematics(best_solution)
    # check_target = forward_check - target[0, :]
    # comparator = np.abs(np.apply_along_axis(np.sum, 1, (check_target)))

    # if np.any(comparator < 2.0e-3):
    #     pass
    # else:
    #     best_solution = np.array([np.nan, np.nan, np.nan, np.nan, np.nan, np.nan])
    return best_solution


def rotationMatrixToEuler(R, convention: str):
    """Extract Euler angles (in radians) from a rotation matrix R.

    Parameters:
      R : 3x3 array
          Rotation matrix.
      order : string, either "zyx" or "xyz"
          If "zyx", extract using (approximately) the formulas from your original function:
             alpha = -atan2(R[2,1], R[2,2])
             beta  = -atan2(-R[2,0], sqrt(R[2,1]**2 + R[2,2]**2))
             gamma = -atan2(R[1,0], R[0,0])
          If "xyz", extract using one common set of formulas for that convention:
             phi   = atan2(-R[1,2], R[2,2])
             theta = arcsin(R[0,2])
             psi   = atan2(-R[0,1], R[0,0])

    Returns:
      A tuple of three angles (in radians).
    """
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
            phi = np.arctan2(-R[1, 2], R[2, 2])
            theta = np.arcsin(R[0, 2])
            psi = np.arctan2(-R[0, 1], R[0, 0])
        else:
            phi = np.arctan2(R[2, 1], R[1, 1])
            theta = np.arcsin(R[0, 2])
            psi = 0.0
        return phi, theta, psi
    else:
        raise ValueError(f"Unsupported convention: {convention}. Use 'zyx' or 'xyz'.")


def fk(joints, offset, convention: str = "xyz"):
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

    x, y, z = T06[0, 3], T06[1, 3], T06[2, 3]
    R = T06[:3, :3]
    alpha, beta, gamma = rotationMatrixToEuler(R, convention)

    return x, y, z, np.rad2deg(alpha), np.rad2deg(beta), np.rad2deg(gamma)


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
            [joint_1, joint_2, joint_3, joint_3, joint_5, joint_6], 70
        )
        return CartesianSpace(
            x=x / 1000, y=y / 1000, z=z / 1000, alpha=alpha, beta=beta, gamma=gamma
        )

    def derived_to_raw(  # noqa: D102
        self, *, x: float, y: float, z: float, alpha: float, beta: float, gamma: float
    ) -> JointSpace:
        joints = setEulerTarget([x, y, z], alpha, beta, gamma, [0, 0, 0, 0, 0, 0])

        return JointSpace(
            joint_1=joints[0],
            joint_2=joints[1],
            joint_3=joints[2],
            joint_4=joints[3],
            joint_5=joints[4],
            joint_6=joints[5],
        )


class Meca500(Device, Movable):  # noqa: D101
    def __init__(self, prefix="", name=""):
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
        self.joint_2.set(raw["joint_2"])
        self.joint_3.set(raw["joint_3"])
        self.joint_4.set(raw["joint_4"])
        self.joint_5.set(raw["joint_5"])
        self.joint_6.set(raw["joint_6"])
