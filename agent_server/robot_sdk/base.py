"""Base (mobile platform) control — TidyBot-compatible API backed by SimRobot."""

import numpy as np
from ._runtime import get_robot


def move_to_pose(x, y, theta):
    """Move the base to an absolute world-frame pose.

    Args:
        x, y: Target position in metres (world frame).
        theta: Target heading in radians.
    """
    get_robot().move_base_to_pose(x, y, theta)


def move_delta(dx=0.0, dy=0.0, dtheta=0.0, frame="global"):
    """Move the base by a delta from its current pose.

    Args:
        dx, dy: Position delta in metres.
        dtheta: Heading delta in radians.
        frame: Reference frame — "global" (default) or "local" (base-relative).
    """
    robot = get_robot()
    pos, yaw = robot.get_base_pose()
    if frame == "local":
        # Rotate dx, dy from base-local frame to global frame
        cos_y, sin_y = np.cos(yaw), np.sin(yaw)
        global_dx = cos_y * dx - sin_y * dy
        global_dy = sin_y * dx + cos_y * dy
        move_to_pose(pos[0] + global_dx, pos[1] + global_dy, yaw + dtheta)
    elif frame == "global":
        move_to_pose(pos[0] + dx, pos[1] + dy, yaw + dtheta)
    else:
        raise ValueError(f"Unknown frame '{frame}'. Use 'global' or 'local'.")


def forward(distance):
    """Drive the base forward by *distance* metres along its heading."""
    robot = get_robot()
    pos, yaw = robot.get_base_pose()
    dx = distance * np.cos(yaw)
    dy = distance * np.sin(yaw)
    move_to_pose(pos[0] + dx, pos[1] + dy, yaw)


def rotate(angle):
    """Rotate the base in-place by *angle* radians (positive = CCW)."""
    robot = get_robot()
    pos, yaw = robot.get_base_pose()
    move_to_pose(pos[0], pos[1], yaw + angle)


def rotate_degrees(angle):
    """Rotate the base in-place by *angle* degrees (positive = CCW)."""
    rotate(np.radians(angle))


def send_velocity(vx=0.0, vy=0.0, vtheta=0.0):
    """Send velocity commands to the base.

    Not supported in sim (blocking position controller).
    """
    raise NotImplementedError("Base velocity control not supported in sim — use move_delta or forward.")


def get_state():
    """Return a dict with the current base state."""
    robot = get_robot()
    pos, yaw = robot.get_base_pose()
    return {
        "position": pos.tolist(),
        "heading": yaw,
    }


def stop():
    """Send a zero-velocity command (no-op for blocking controller)."""
    pass
