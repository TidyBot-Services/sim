"""Arm control — TidyBot-compatible API backed by SimRobot."""

import numpy as np
from ._runtime import get_robot


def move_to_pose(x, y, z, roll=0.0, pitch=0.0, yaw=0.0):
    """Move the end-effector to an absolute world-frame pose.

    Args:
        x, y, z: Target position in metres (world frame).
        roll, pitch, yaw: Target orientation in radians (world frame Euler ZYX).
    """
    import robosuite.utils.transform_utils as T

    target_pos = np.array([x, y, z])
    target_ori = T.euler2mat(np.array([roll, pitch, yaw]))
    get_robot().move_ee_to_pose(target_pos, target_ori)


def move_delta(dx=0.0, dy=0.0, dz=0.0, droll=0.0, dpitch=0.0, dyaw=0.0, frame="world"):
    """Move the end-effector by a delta from its current pose.

    Args:
        dx, dy, dz: Position delta in metres.
        droll, dpitch, dyaw: Orientation delta in radians.
        frame: Reference frame for the delta — "world" (default), "base", or "ee".
    """
    if frame == "world":
        get_robot().move_ee_delta(dx, dy, dz, droll, dpitch, dyaw)
    elif frame == "base":
        robot = get_robot()
        # Rotate position delta from base frame to world frame
        base_transform = robot._get_base_transform()
        R_base = base_transform[:3, :3]
        world_dpos = R_base @ np.array([dx, dy, dz])
        world_dori = R_base @ np.array([droll, dpitch, dyaw])
        robot.move_ee_delta(world_dpos[0], world_dpos[1], world_dpos[2],
                            world_dori[0], world_dori[1], world_dori[2])
    elif frame == "ee":
        robot = get_robot()
        # Rotate position delta from EE frame to world frame
        _, ee_ori = robot.get_ee_pose()
        world_dpos = ee_ori @ np.array([dx, dy, dz])
        world_dori = ee_ori @ np.array([droll, dpitch, dyaw])
        robot.move_ee_delta(world_dpos[0], world_dpos[1], world_dpos[2],
                            world_dori[0], world_dori[1], world_dori[2])
    else:
        raise ValueError(f"Unknown frame '{frame}'. Use 'world', 'base', or 'ee'.")


def move_joints(q):
    """Move the arm to a specific joint configuration (7-DOF).

    Note: In simulation this is approximated by IK to the forward-kinematics
    target pose, since the controller is OSC_POSE.
    """
    raise NotImplementedError("Direct joint control not yet supported in sim — use move_to_pose.")


def go_home():
    """Move the arm to its default home configuration."""
    get_robot().go_home()


def get_state():
    """Return a dict with the current arm state."""
    robot = get_robot()
    return {
        "ee_pos": robot.get_ee_pose()[0].tolist(),
        "ee_ori": robot.get_ee_pose()[1].tolist(),
        "joint_positions": robot.get_arm_joints().tolist(),
    }


def send_joint_velocity(velocities):
    """Send joint velocity commands to the arm.

    Not supported in sim (OSC_POSE controller, no direct velocity control).
    """
    raise NotImplementedError("Joint velocity control not supported in sim — use move_delta or move_to_pose.")


def send_cartesian_velocity(vx=0.0, vy=0.0, vz=0.0, wx=0.0, wy=0.0, wz=0.0, frame="world"):
    """Send Cartesian velocity commands to the end-effector.

    Not supported in sim (blocking position controller).
    """
    raise NotImplementedError("Cartesian velocity control not supported in sim — use move_delta or move_to_pose.")


def stop():
    """Send a zero-velocity command (no-op for blocking controller)."""
    pass
